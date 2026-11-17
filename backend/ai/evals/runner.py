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
from ..llm import LLMError, get_llm
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
    if llm.is_live:
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
        if llm.is_live:
            sources_text = "\n\n".join(f"[{i}] {r.chunk.content}" for i, r in enumerate(retrieved, start=1))
            try:
                verdict = llm.parse(
                    feature="eval_judge",
                    system=JUDGE_PROMPT,
                    messages=[{"role": "user", "content": f"Question: {case['question']}\n\nSources:\n{sources_text}\n\nAnswer:\n{answer}"}],
                    schema=JudgeVerdict,
                    offline=lambda: JudgeVerdict(correct=False, faithful=False, explanation="offline"),
                    max_tokens=settings.AI["MAX_TOKENS_STRUCTURED"],
                    effort="medium",
                    model=settings.AI["EVAL_JUDGE_MODEL"],
                ).value
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
        "config": {**_base_config(), "questions": len(dataset), "judge_model": settings.AI["EVAL_JUDGE_MODEL"] if llm.is_live else None},
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
    llm = get_llm()

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
        "config": {**_base_config(), "cases": n, "effort": settings.AI["EFFORT_ASSISTANT"]},
        "metrics": {
            "task_success_rate": round(sum(r["pass"] for r in rows) / n, 4),
            "grounding_rate": round(sum(r["grounding_ok"] for r in rows) / n, 4),
            "avg_tool_calls": round(sum(r["tool_calls"] for r in rows) / n, 2),
            "p50_latency_ms": int(median(r["latency_ms"] for r in rows)),
            "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 4) if llm.is_live else 0.0,
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


SUITES = {
    "search": run_search_eval, "parse": run_parse_eval, "rag": run_rag_eval, "agent": run_agent_eval,
    "planner": run_planner_eval, "product_qa": run_product_qa_eval, "visual": run_visual_eval,
}
