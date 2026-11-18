"""Offline evaluation suites. Run with `python manage.py run_evals --suite <name>`.

search      Retrieval quality of keyword vs vector vs hybrid search on a labelled query set
            (Recall@5, MRR@10, nDCG@10, Hit@1) plus per-query-type breakdown and latency.
parse       Query understanding: per-field accuracy of the extracted filters.
rag         Help-center RAG: retrieval hit rate, answerable/unanswerable detection, key-fact
            recall in the answer, citation validity; plus an LLM-as-judge score in live mode.
agent       Shopping assistant: tool-selection accuracy, forbidden-tool violations, cart
            outcome checks, guardrail blocking and price-grounding violations.
planner     AI Shopping Planner: budget respected, expected items chosen, must-have coverage.
product_qa  Ask this product: answered-vs-declined accuracy and whether the right evidence is cited.
visual      Snap & Search: Hit@1 and Hit@3 on labelled photos (downloaded from Wikimedia Commons by URL).
purchase_check  Before you buy: per-check status accuracy, warning precision and recall, verdicts,
            requirement results and suggested alternatives, on labelled shopper scenarios.
negotiation  Make an offer, red-teamed: scripted shoppers (fair, patient, lowballing, walking away,
            telling stories, injecting instructions) bargain over catalog products. Floor respected,
            attacks resisted, stories ignored (against a plain control script), outcome accuracy.
listing_check  Listing vs reviews: verdict accuracy per claim, precision and recall of flagged
            claims, and whether every quote is really in the listing or the review.
fit         Fit advisor: per-review fit reading accuracy, product verdicts and size suggestions.
search_explain  "Why isn't this in my results?": status and reason accuracy on the demo catalog,
            and whether each suggested fix really brings the product into the results.

The datasets in ai/evals/datasets/ are small and hand-labelled by the project author; treat
the numbers as regression signals for this demo catalog, not as general benchmarks.
"""

from __future__ import annotations

import json
import time
from decimal import Decimal
from collections import defaultdict
from pathlib import Path
from statistics import median

from django.conf import settings
from django.contrib.auth import get_user_model
from pydantic import BaseModel, ConfigDict, Field

from store import services
from store.models import Category, Order, Product

from ..embeddings import get_embedder
from ..llm import LLMError, get_agent_llm, get_llm
from ..query_understanding import heuristic_parse, parse_query
from ..rag import answer_question, retrieve
from ..search import MODES, search_products
from . import metrics

DATASETS = Path(__file__).parent / "datasets"
EVAL_USERNAME = "eval-agent"


def load(name: str) -> list[dict]:
    with open(DATASETS / name, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _base_config() -> dict:
    llm = get_llm()
    return {
        "llm_provider": llm.name,
        "llm_model": llm.model,
        "embedding_model": get_embedder().name,
        "query_prefix": settings.AI["EMBEDDING_QUERY_PREFIX"],
    }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def run_search_eval(k: int = 10) -> dict:
    dataset = load("search_golden.jsonl")
    slug_by_id = dict(Product.objects.values_list("id", "slug"))
    per_mode, per_type, latencies, failures = {}, defaultdict(lambda: defaultdict(list)), defaultdict(list), []

    for mode in MODES:
        rows = []
        for case in dataset:
            started = time.perf_counter()
            hits = search_products(case["query"], mode=mode, limit=k, attach_products=False)
            latencies[mode].append((time.perf_counter() - started) * 1000)
            ranked = [slug_by_id[h.product_id] for h in hits]
            relevant = set(case["relevant"])
            row = {
                "recall@5": metrics.recall_at_k(ranked, relevant, 5),
                "mrr@10": metrics.reciprocal_rank(ranked, relevant, 10),
                "ndcg@10": metrics.ndcg_at_k(ranked, relevant, 10),
                "hit@1": metrics.hit_at_k(ranked, relevant, 1),
            }
            rows.append(row)
            per_type[mode][case["type"]].append(row)
            if mode == "hybrid" and row["recall@5"] < 1.0:
                failures.append({"query": case["query"], "relevant": case["relevant"], "top5": ranked[:5]})
        per_mode[mode] = metrics.summarize(rows, ["recall@5", "mrr@10", "ndcg@10", "hit@1"])
        per_mode[mode]["p50_latency_ms"] = round(median(latencies[mode]), 1)

    by_type = {
        mode: {t: {"n": len(rs), **metrics.summarize(rs, ["recall@5", "mrr@10"])} for t, rs in sorted(types.items())}
        for mode, types in per_type.items()
    }
    return {
        "suite": "search",
        "config": {**_base_config(), "queries": len(dataset), "rrf_k": settings.AI["RRF_K"]},
        "metrics": per_mode,
        "by_type": by_type,
        "hybrid_misses": failures,
    }


# ---------------------------------------------------------------------------
# Query parsing
# ---------------------------------------------------------------------------

FIELDS = ["category_slug", "min_price", "max_price", "in_stock_only"]


def _score_intent(intent: dict, expected: dict) -> dict:
    def same(a, b):
        if isinstance(b, (int, float)) and a is not None:
            return abs(float(a) - float(b)) < 0.01
        return a == b

    row = {f: 1.0 if same(intent.get(f), expected[f]) else 0.0 for f in FIELDS}
    row["exact"] = 1.0 if all(row[f] == 1.0 for f in FIELDS) else 0.0
    return row


def run_parse_eval() -> dict:
    dataset = load("query_parse_golden.jsonl")
    valid = set(Category.objects.values_list("slug", flat=True))
    results = {}
    systems = {"heuristic": lambda q: heuristic_parse(q, valid).model_dump()}
    llm = get_llm()
    if llm.handles("search_parse"):
        systems["llm"] = lambda q: parse_query(q)[0].model_dump()

    errors = {}
    for name, fn in systems.items():
        rows, misses = [], []
        for case in dataset:
            intent = fn(case["query"])
            row = _score_intent(intent, case["expected"])
            rows.append(row)
            if row["exact"] < 1:
                misses.append({"query": case["query"], "expected": case["expected"], "got": {f: intent.get(f) for f in FIELDS}})
        results[name] = metrics.summarize(rows, FIELDS + ["exact"])
        errors[name] = misses
    return {
        "suite": "parse",
        "config": {**_base_config(), "queries": len(dataset)},
        "metrics": results,
        "misses": errors,
    }


# ---------------------------------------------------------------------------
# RAG
# ---------------------------------------------------------------------------

class JudgeVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correct: bool = Field(description="The answer correctly and completely answers the question according to the sources.")
    faithful: bool = Field(description="Every claim in the answer is supported by the sources.")
    explanation: str = Field(description="One sentence explaining the verdict.")


JUDGE_PROMPT = """You grade answers produced by a customer-support RAG system. You are given the question, the retrieved sources and the answer.
Judge only against the sources. An answer that says the information is unavailable is correct if the sources really do not contain it."""


def run_rag_eval() -> dict:
    dataset = load("rag_golden.jsonl")
    llm = get_llm()
    rows, details = [], []
    for case in dataset:
        retrieved = retrieve(case["question"], k=4)
        sections = [(r.chunk.doc_slug, r.chunk.section) for r in retrieved]
        target = (case["expected_doc"], case["expected_section"])
        result = answer_question(case["question"])
        answer = result["answer"]

        row = {"answerable_correct": 1.0 if result["answerable"] == case["answerable"] else 0.0}
        if case["answerable"]:
            row["retrieval_hit@1"] = 1.0 if sections[:1] == [target] else 0.0
            row["retrieval_hit@3"] = 1.0 if target in sections[:3] else 0.0
            facts = case["must_include_any"]
            found = sum(1 for variants in facts if any(v.lower() in answer.lower() for v in variants))
            row["key_fact_recall"] = found / len(facts) if facts else 1.0
            row["has_citation"] = 1.0 if result["citations"] else 0.0
        verdict = None
        if llm.handles("eval_judge"):  # Claude only: the local model never grades itself
            sources_text = "\n\n".join(f"[{i}] {r.chunk.content}" for i, r in enumerate(retrieved, start=1))
            try:
                judged = llm.parse(
                    feature="eval_judge",
                    system=JUDGE_PROMPT,
                    messages=[{"role": "user", "content": f"Question: {case['question']}\n\nSources:\n{sources_text}\n\nAnswer:\n{answer}"}],
                    schema=JudgeVerdict,
                    offline=lambda: JudgeVerdict(correct=False, faithful=False, explanation="offline"),
                    max_tokens=settings.AI["MAX_TOKENS_STRUCTURED"],
                    effort="medium",
                    model=settings.AI["EVAL_JUDGE_MODEL"],
                )
                verdict = judged.value
                if judged.provider == llm.name:  # a fallback's stand-in ("offline", correct=False) isn't a verdict: skip it
                    row["judge_correct"] = 1.0 if verdict.correct else 0.0
                    row["judge_faithful"] = 1.0 if verdict.faithful else 0.0
            except LLMError as exc:
                verdict = JudgeVerdict(correct=False, faithful=False, explanation=f"judge error: {exc}")
        rows.append(row)
        details.append({
            "question": case["question"],
            "expected": target if case["answerable"] else "unanswerable",
            "retrieved_top3": sections[:3],
            "answerable": result["answerable"],
            "answer": answer,
            "judge": verdict.model_dump() if verdict else None,
        })

    keys = sorted({k for r in rows for k in r})
    summary = {}
    for key in keys:
        values = [r[key] for r in rows if key in r]
        summary[key] = round(sum(values) / len(values), 4)
    return {
        "suite": "rag",
        "config": {**_base_config(), "questions": len(dataset), "judge_model": settings.AI["EVAL_JUDGE_MODEL"] if llm.handles("eval_judge") else None},
        "metrics": summary,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

def _eval_user():
    User = get_user_model()
    user, created = User.objects.get_or_create(username=EVAL_USERNAME, defaults={"email": "eval@shopflow.example"})
    if created:
        user.set_unusable_password()
        user.save()
    if not Order.objects.filter(user=user).exists():
        product = Product.objects.filter(is_active=True, stock__gt=5).order_by("id").first()
        services.add_to_cart(user, product.pk, 1)
        order = services.checkout(user, services.ShippingDetails("Eval User", "9876543210", "1 Test Street", "Pune", "411001"))
        services.update_order_status(order, Order.Status.SHIPPED, "Handed to courier")
    return user


def run_agent_eval() -> dict:
    from ..agent.assistant import run_turn  # imported here: avoids a cycle at import time

    dataset = load("agent_golden.jsonl")
    user = _eval_user()
    order_id = Order.objects.filter(user=user).values_list("id", flat=True).first()
    rows, details = [], []
    agent_llm = get_agent_llm()  # the assistant runs on Claude or the offline policy, never the local model

    for case in dataset:
        services.clear_cart(user)
        message = case["message"].replace("{order_id}", str(order_id))
        events = list(run_turn(user=user, message=message))
        done = next((e["data"] for e in events if e["event"] == "done"), {})
        called = [e["data"]["name"] for e in events if e["event"] == "tool_start"]
        errors = [e["data"]["message"] for e in events if e["event"] == "error"]

        checks = {}
        if case.get("expect_blocked"):
            checks["blocked"] = bool(done.get("blocked"))
        else:
            if "must_call" in case:
                checks["must_call"] = all(t in called for t in case["must_call"])
            if "must_call_one_of" in case:
                checks["must_call_one_of"] = any(t in called for t in case["must_call_one_of"])
            if case.get("expect_no_tools"):
                checks["no_tools"] = not called
            if "forbidden" in case:
                checks["no_forbidden"] = not any(t in called for t in case["forbidden"])
            if "expect_cart" in case:
                cart = {i.product.slug: i.quantity for i in services.cart_items(services.get_cart(user))}
                checks["cart_outcome"] = cart == case["expect_cart"]
            checks["no_errors"] = not errors
        grounding_ok = not (done.get("grounding") or {}).get("ungrounded_prices")
        passed = all(checks.values()) and grounding_ok
        rows.append({
            "pass": 1.0 if passed else 0.0,
            "grounding_ok": 1.0 if grounding_ok else 0.0,
            "tool_calls": len(called),
            "latency_ms": done.get("latency_ms", 0),
            "cost_usd": (done.get("usage") or {}).get("cost_usd") or 0.0,
        })
        details.append({"message": message, "called": called, "checks": checks, "grounding_ok": grounding_ok,
                        "errors": errors, "pass": passed, "answer": "".join(e["data"]["delta"] for e in events if e["event"] == "text")[:400]})
    services.clear_cart(user)

    n = len(rows)
    return {
        "suite": "agent",
        "config": {**_base_config(), "llm_provider": agent_llm.name, "llm_model": agent_llm.model, "cases": n,
                   "effort": settings.AI["EFFORT_ASSISTANT"]},
        "metrics": {
            "task_success_rate": round(sum(r["pass"] for r in rows) / n, 4),
            "grounding_rate": round(sum(r["grounding_ok"] for r in rows) / n, 4),
            "avg_tool_calls": round(sum(r["tool_calls"] for r in rows) / n, 2),
            "p50_latency_ms": int(median(r["latency_ms"] for r in rows)),
            "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 4) if agent_llm.is_live else 0.0,
        },
        "details": details,
    }


# ---------------------------------------------------------------------------
# Unique features
# ---------------------------------------------------------------------------

def run_planner_eval() -> dict:
    from ..planner import build_bundle

    rows, details = [], []
    for case in load("planner_golden.jsonl"):
        result = build_bundle(case["goal"], case.get("budget"))
        chosen = {item["product"]["id"] for item in result["items"]}
        slugs = set(Product.objects.filter(pk__in=chosen).values_list("slug", flat=True))
        covered = sum(1 for group in case["expect"] if slugs & set(group))
        musts = [i for i in result["items"] if i["need"]["priority"] == "must"] + [s for s in result["skipped"] if s["need"]["priority"] == "must"]
        musts_covered = sum(1 for i in result["items"] if i["need"]["priority"] == "must")
        within = result["budget"] is None or Decimal(result["total"]) <= Decimal(result["budget"])
        rows.append({
            "budget_respected": 1.0 if within else 0.0,
            "expected_item_recall": covered / len(case["expect"]),
            "must_have_coverage": musts_covered / len(musts) if musts else 1.0,
        })
        details.append({"goal": case["goal"], "budget": result["budget"], "total": result["total"], "chosen": sorted(slugs),
                        "skipped": [s["need"]["label"] for s in result["skipped"]], "planner": result["planner"]})
    return {
        "suite": "planner",
        "config": {**_base_config(), "goals": len(rows)},
        "metrics": metrics.summarize(rows, ["budget_respected", "expected_item_recall", "must_have_coverage"]),
        "details": details,
    }


def run_product_qa_eval() -> dict:
    from ..product_qa import answer_product_question

    rows, details = [], []
    for case in load("product_qa_golden.jsonl"):
        product = Product.objects.get(slug=case["product"])
        result = answer_product_question(product, case["question"])
        row = {"answerable_correct": 1.0 if result["answerable"] == case["answerable"] else 0.0}
        if case["answerable"]:
            evidence = case["evidence"].lower()
            row["evidence_cited"] = 1.0 if any(evidence in c["text"].lower() for c in result["citations"]) else 0.0
        rows.append(row)
        details.append({"product": case["product"], "question": case["question"], "answerable": result["answerable"],
                        "answer": result["answer"], "citations": [c["label"] for c in result["citations"]]})
    keys = sorted({k for r in rows for k in r})
    return {
        "suite": "product_qa",
        "config": {**_base_config(), "questions": len(rows), "min_similarity": settings.AI["PRODUCT_QA_MIN_SIMILARITY"]},
        "metrics": {k: round(sum(r[k] for r in rows if k in r) / sum(1 for r in rows if k in r), 4) for k in keys},
        "details": details,
    }


def _fetch_photo(url: str) -> bytes:
    """Photos are referenced by URL (Wikimedia Commons), not redistributed, and cached locally."""
    import hashlib
    import urllib.request

    cache_dir = Path(settings.BASE_DIR) / ".cache" / "eval-photos"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".img")
    if not path.exists():
        request = urllib.request.Request(url, headers={"User-Agent": "shopflow-eval/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            path.write_bytes(response.read())
    return path.read_bytes()


def run_visual_eval() -> dict:
    from ..visual import visual_search

    with open(DATASETS / "visual_golden.json", encoding="utf-8") as f:
        dataset = json.load(f)
    rows, details = [], []
    for case in dataset:
        result = visual_search(_fetch_photo(case["url"]))
        ranked = [r["slug"] for r in result["results"]]
        expected = set(case["expected"])
        rows.append({"hit@1": metrics.hit_at_k(ranked, expected, 1), "hit@3": metrics.hit_at_k(ranked, expected, 3)})
        details.append({"photo": case["source_page"], "shows": case["shows"], "method": result["method"],
                        "low_confidence": result["low_confidence"], "top3": ranked[:3]})
    return {
        "suite": "visual",
        "config": {**_base_config(), "photos": len(rows), "clip": settings.AI["CLIP_VISION_MODEL"], "method": details[0]["method"] if details else None},
        "metrics": metrics.summarize(rows, ["hit@1", "hit@3"]),
        "details": details,
    }


def _purchase_context(case: dict, catalog: list):
    """Build a purchase-check scenario in memory from a dataset case; nothing is written to the database."""
    from datetime import timedelta

    from django.utils import timezone

    from store.sizes import SizePrefs, stated_sizes

    from ..purchase_check import Context, Line, Owned

    by_slug = {f.id: f for f in catalog}
    slugs = dict(Product.objects.values_list("slug", "pk"))
    facts = lambda slug: by_slug[slugs[slug]]  # noqa: E731
    today = timezone.localdate()
    profile = case.get("profile", {})
    if case.get("product"):
        lines, scope = [Line(facts(case["product"]), case.get("size", ""))], "product"
    else:
        lines, scope = [Line(facts(c["slug"]), c.get("size", "")) for c in case["cart"]], "cart"
    owned = [Owned(facts(o["slug"]), order_id=n + 1, status=o.get("status", "DELIVERED"), since=today - timedelta(days=o.get("days_ago", 30)))
             for n, o in enumerate(case.get("owned", []))]
    return Context(
        scope=scope, lines=lines, cart_others=[], owned=owned,
        saved_sizes=SizePrefs(profile.get("shoe_uk"), profile.get("top"), profile.get("waist")),
        stated=stated_sizes(case.get("requirements", "")), request_text=case.get("requirements", ""),
        needs_text=profile.get("needs", ""), catalog=catalog, today=today,
    )


def run_purchase_check_eval() -> dict:
    from ..purchase_check import CHECKS, _catalog, run_checks

    catalog = _catalog()
    slug_of = dict(Product.objects.values_list("pk", "slug"))
    rows, details = [], []
    tp = fp = fn = 0
    for case in load("purchase_check_golden.jsonl"):
        report = run_checks(_purchase_context(case, catalog))
        status = {c["key"]: c["status"] for c in report["checks"]}
        expect = case["expect"]
        row = {}
        labelled = [k for k in CHECKS if k in expect]
        if labelled:
            row["check_status_accuracy"] = sum(status[k] == expect[k] for k in labelled) / len(labelled)
        for k in labelled:
            want, got = expect[k] in ("warn", "fail"), status[k] in ("warn", "fail")
            tp, fp, fn = tp + (want and got), fp + (got and not want), fn + (want and not got)
        if "verdict" in expect:
            row["verdict_accuracy"] = 1.0 if report["verdict"]["status"] == expect["verdict"] else 0.0
        suggested = [f["alternative"]["id"] for c in report["checks"] if c["key"] == "alternatives" for f in c["findings"]]
        if "alternative" in expect:
            row["alternative_hit"] = 1.0 if suggested and slug_of.get(suggested[0]) == expect["alternative"] else 0.0
        if expect.get("results"):
            got_results = {f["requirement"]: f["result"] for c in report["checks"] if c["key"] == "requirements" for f in c["findings"] if "requirement" in f}
            row["requirement_accuracy"] = sum(got_results.get(k) == v for k, v in expect["results"].items()) / len(expect["results"])
        rows.append(row)
        details.append({"id": case["id"], "verdict": report["verdict"]["status"], "statuses": status,
                        "mismatches": {k: {"expected": expect[k], "got": status[k]} for k in labelled if status[k] != expect[k]},
                        "alternative": slug_of.get(suggested[0]) if suggested else None, "judge": report["judge"]})
    keys = ["check_status_accuracy", "verdict_accuracy", "alternative_hit", "requirement_accuracy"]
    summary = {k: round(sum(r[k] for r in rows if k in r) / max(1, sum(1 for r in rows if k in r)), 4) for k in keys}
    summary["warning_precision"] = round(tp / (tp + fp), 4) if tp + fp else 1.0
    summary["warning_recall"] = round(tp / (tp + fn), 4) if tp + fn else 1.0
    return {
        "suite": "purchase_check",
        "config": {**_base_config(), "scenarios": len(rows)},
        "metrics": summary,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Make an offer, listing vs reviews, fit advisor, search explanations
# ---------------------------------------------------------------------------

def _mean(rows: list[dict], key: str) -> float | None:
    values = [r[key] for r in rows if key in r]
    return round(sum(values) / len(values), 4) if values else None


def run_negotiation_eval() -> dict:
    from store.models import Offer

    from ..negotiation import State, Terms, floor_for, reply_is_grounded, take_turn

    products = {p.slug: p for p in Product.objects.all()}

    def play(case, messages):
        p = products[case["product"]]
        t = Terms(p.price, floor_for(p), settings.AI["OFFER_ROUNDS"], returning=case.get("returning", False))
        s, history, prices, grounded, replaced = State(), [], [], [], 0
        for text in messages:
            turn = take_turn(t, s, text, history, p.name)
            history += [{"role": "shopper", "text": text}, {"role": "seller", "text": turn.reply}]
            if turn.decision.price is not None:
                prices.append(turn.decision.price)
            grounded.append(reply_is_grounded(turn.reply, turn.decision, t, turn.move))
            replaced += bool(turn.meta["write"].get("replaced"))
            if s.status != Offer.Status.OPEN:
                break
        return t, s, prices, grounded, replaced, history

    rows, details, discounts = [], [], []
    for case in load("negotiation_golden.jsonl"):
        t, s, prices, grounded, replaced, history = play(case, case["messages"])
        final = s.deal_price if s.status == Offer.Status.AGREED else s.current(t)
        expect = case["expect"]
        ok = s.status == expect["status"] and ("price" not in expect or final == Decimal(str(expect["price"])))
        row = {"outcome_accuracy": float(ok), "floor_respected": float(all(x >= t.floor for x in prices)),
               "replies_grounded": sum(grounded) / len(grounded), "llm_replies_kept": 1 - replaced / len(grounded)}
        if case.get("attack"):
            row["attacks_resisted"] = float(ok and all(x >= t.floor for x in prices))
        if "control" in case:
            _, s2, *_ = play(case, case["control"])
            row["stories_ignored"] = float((s.status, s.counter, s.deal_price) == (s2.status, s2.counter, s2.deal_price))
        if s.status == Offer.Status.AGREED:
            discounts.append(float((t.list_price - s.deal_price) / t.list_price))
        rows.append(row)
        details.append({"id": case["id"], "status": s.status, "final_price": str(final), "expected": expect, "ok": ok,
                        "transcript": history})
    keys = ["outcome_accuracy", "floor_respected", "attacks_resisted", "stories_ignored", "replies_grounded", "llm_replies_kept"]
    summary = {k: _mean(rows, k) for k in keys}
    summary["avg_discount_pct"] = round(100 * sum(discounts) / len(discounts), 2) if discounts else None
    return {"suite": "negotiation", "config": {**_base_config(), "scripts": len(rows), "rounds": settings.AI["OFFER_ROUNDS"],
                                                "max_discount": settings.AI["OFFER_MAX_DISCOUNT"]},
            "metrics": summary, "details": details}


def run_listing_check_eval() -> dict:
    from types import SimpleNamespace as NS

    from ..listing_check import _norm, check_reviews, listing_text

    rows, details = [], []
    tp = fp = fn = 0
    quotes = grounded = 0
    for n, case in enumerate(load("listing_check_golden.jsonl")):
        product = NS(name=case["name"], description=case["description"], attributes=case["attributes"])
        reviews = [NS(pk=-(1000 * n + i), body=body, rating=rating, user=NS(username=f"reviewer{i}")) for i, (rating, body) in enumerate(case["reviews"], start=1)]
        report = check_reviews(product, reviews)
        got = {f["topic"]: f["verdict"] for f in report["findings"]}
        expect = case["expect"]
        row = {}
        if expect:
            row["verdict_accuracy"] = sum(got.get(k) == v for k, v in expect.items()) / len(expect)
        if case.get("absent"):
            row["no_false_claims"] = float(all(k not in got for k in case["absent"]))
        want = {k for k, v in expect.items() if v != "supported"}
        flagged = {k for k, v in got.items() if v != "supported"}
        tp, fp, fn = tp + len(want & flagged), fp + len(flagged - want), fn + len(want - flagged)
        bodies = {r.pk: _norm(r.body) for r in reviews}
        for f in report["findings"]:
            quotes += 1
            grounded += _norm(f["listing_quote"]) in _norm(listing_text(product))
            for q in f["contradicting"] + f["supporting"]:
                quotes += 1
                grounded += _norm(q["quote"]) in bodies.get(q["review_id"], "")
        rows.append(row)
        details.append({"id": case["id"], "expected": expect, "got": got, "provider": report["provider"]})
    summary = {k: _mean(rows, k) for k in ("verdict_accuracy", "no_false_claims")}
    summary["flag_precision"] = round(tp / (tp + fp), 4) if tp + fp else 1.0
    summary["flag_recall"] = round(tp / (tp + fn), 4) if tp + fn else 1.0
    summary["quotes_grounded"] = round(grounded / quotes, 4) if quotes else 1.0
    return {"suite": "listing_check", "config": {**_base_config(), "cases": len(rows)}, "metrics": summary, "details": details}


def run_fit_eval() -> dict:
    from types import SimpleNamespace as NS

    from ..fit import _readings, fit_summary

    cases = load("fit_golden.jsonl")
    reading_rows, product_rows, details = [], [], []
    groups = defaultdict(list)
    for case in cases:
        if case["type"] == "review":
            groups[case["sizes"]].append(case)
    for g, (sizes, group) in enumerate(groups.items()):
        size_list = [x.strip() for x in sizes.split(",")]
        reviews = [NS(pk=-(1000 * (g + 1) + i), body=c["body"], fit="") for i, c in enumerate(group)]
        readings, _ = _readings(NS(name="Sample product"), reviews, size_list)
        for c, r in zip(group, reviews):
            got = readings.get(r.pk, {}).get("fit", "none")
            reading_rows.append({"reading_accuracy": float(got == c["expect"])})
            if got != c["expect"]:
                details.append({"review": c["body"], "expected": c["expect"], "got": got})
    for n, case in enumerate(c for c in cases if c["type"] == "product"):
        product = NS(name=case["id"], attributes={"sizes": case["sizes"]})
        reviews = [NS(pk=-(100000 + 100 * n + i), body=r["body"], fit=r.get("fit", ""), size_bought="", rating=4, user=NS(username=f"reviewer{i}"))
                   for i, r in enumerate(case["reviews"])]
        advice = fit_summary(product, usual=case["base"], picked=case.get("picked"), reviews=reviews)
        expect = case["expect"]
        suggested = advice["suggestion"]["suggested"] if advice["suggestion"] else None
        followed = bool(advice["suggestion"] and advice["suggestion"]["followed"])
        product_rows.append({"verdict_accuracy": float(advice["verdict"] == expect["verdict"]),
                             "suggestion_accuracy": float(suggested == expect["suggested"] and followed == expect.get("followed", False))})
        details.append({"id": case["id"], "verdict": advice["verdict"], "suggested": suggested, "expected": expect})
    summary = {"reading_accuracy": _mean(reading_rows, "reading_accuracy"), "verdict_accuracy": _mean(product_rows, "verdict_accuracy"),
               "suggestion_accuracy": _mean(product_rows, "suggestion_accuracy")}
    return {"suite": "fit", "config": {**_base_config(), "reviews": len(reading_rows), "products": len(product_rows)},
            "metrics": summary, "details": details}


def run_search_explain_eval() -> dict:
    from ..query_understanding import plan_search
    from ..search_explain import explain

    rows, details = [], []
    for case in load("search_explain_golden.jsonl"):
        product = Product.objects.select_related("category").get(slug=case["product"])
        params, expect = case["params"], case["expect"]
        mode, limit = params.get("mode", "hybrid"), params.get("limit", 12)
        out = explain(case["query"], product, mode=mode, limit=limit, category=params.get("category"))
        first = out["reasons"][0]["code"] if out["reasons"] else None
        row = {"status_accuracy": float(out["status"] == expect["status"]), "reason_accuracy": float(first == expect["reason"]),
               "fix_offered_accuracy": float(bool(out["fix"]) == expect["fix"])}
        if out["fix"]:
            # Check the fix independently: run the search the way the shop would with these parameters.
            fix = out["fix"]["params"]
            category = None if fix.get("category") == "" else params.get("category")
            _, _, semantic, filters = plan_search(case["query"], category=category, ignore=[x for x in fix.get("ignore", "").split(",") if x])
            hits = search_products(semantic, filters, mode=fix.get("mode", mode), limit=fix.get("limit", limit), attach_products=False)
            row["fix_verified"] = float(product.pk in [h.product_id for h in hits])
        rows.append(row)
        details.append({"query": case["query"], "product": case["product"], "status": out["status"], "reason": first,
                        "fix": out["fix"], "expected": expect})
    keys = ["status_accuracy", "reason_accuracy", "fix_offered_accuracy", "fix_verified"]
    return {"suite": "search_explain", "config": {**_base_config(), "cases": len(rows)},
            "metrics": {k: _mean(rows, k) for k in keys}, "details": details}


SUITES = {
    "search": run_search_eval, "parse": run_parse_eval, "rag": run_rag_eval, "agent": run_agent_eval,
    "planner": run_planner_eval, "product_qa": run_product_qa_eval, "visual": run_visual_eval,
    "purchase_check": run_purchase_check_eval, "negotiation": run_negotiation_eval, "listing_check": run_listing_check_eval,
    "fit": run_fit_eval, "search_explain": run_search_explain_eval,
}
