import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ai.evals.runner import SUITES
from ai.models import EvalRun

REPORTS = Path(__file__).resolve().parents[2] / "evals" / "reports"


def _lookup(report: dict, path: str):
    node = report["metrics"]
    for part in path.split("."):
        node = node[part]
    return node


class Command(BaseCommand):
    help = ("Run evaluation suites (search, parse, rag, agent, planner, product_qa, visual, purchase_check, negotiation, "
            "listing_check, fit, search_explain) and save reports.")

    def add_arguments(self, parser):
        parser.add_argument("--suite", default="all", choices=["all", *SUITES])
        parser.add_argument("--no-save", action="store_true", help="Do not write reports/ or EvalRun rows.")
        parser.add_argument(
            "--fail-under", action="append", default=[], metavar="SUITE:METRIC=VALUE",
            help="Exit non-zero if a metric is below VALUE, e.g. search:hybrid.recall@5=0.85 (repeatable). Used as a CI gate.",
        )

    def handle(self, *args, **options):
        suites = list(SUITES) if options["suite"] == "all" else [options["suite"]]
        reports = {}
        for name in suites:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n== {name} =="))
            report = SUITES[name]()
            reports[name] = report
            self._print(report)
            if not options["no_save"]:
                REPORTS.mkdir(parents=True, exist_ok=True)
                (REPORTS / f"{name}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
                EvalRun.objects.create(suite=name, config=report["config"], metrics=report["metrics"])

        failures = []
        for rule in options["fail_under"]:
            try:
                target, threshold = rule.split("=")
                suite, path = target.split(":")
                value = _lookup(reports[suite], path)
            except (ValueError, KeyError) as exc:
                raise CommandError(f"Bad --fail-under rule {rule!r}: {exc}")
            if value < float(threshold):
                failures.append(f"{target} = {value} < {threshold}")
        if failures:
            raise CommandError("Eval gate failed: " + "; ".join(failures))

    def _print(self, report):
        self.stdout.write("config: " + json.dumps(report["config"], ensure_ascii=False))
        metrics = report["metrics"]
        if metrics and all(isinstance(v, dict) for v in metrics.values()):
            columns = list(next(iter(metrics.values())).keys())
            self.stdout.write("| system | " + " | ".join(columns) + " |")
            self.stdout.write("|---|" + "---|" * len(columns))
            for system, row in metrics.items():
                self.stdout.write(f"| {system} | " + " | ".join(str(row[c]) for c in columns) + " |")
        else:
            for key, value in metrics.items():
                self.stdout.write(f"  {key}: {value}")
        if "by_type" in report:
            self.stdout.write("recall@5 by query type:")
            for mode, types in report["by_type"].items():
                self.stdout.write(f"  {mode:8} " + ", ".join(f"{t}={v['recall@5']} (n={v['n']})" for t, v in types.items()))
