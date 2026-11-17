"""Cost estimation and the metrics behind the AI dashboard."""

from __future__ import annotations

from datetime import timedelta
from statistics import quantiles

from django.db.models import Count, Sum
from django.utils import timezone

# USD per million tokens (Anthropic list prices, November 2026). Used for *estimates* on the
# dashboard; the Anthropic Console is the source of truth for billing.
# cache_write = 5-minute cache write; cache_read = cache hit.
PRICING_PER_MTOK = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.10},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int,
                      cache_read_tokens: int = 0, cache_creation_tokens: int = 0) -> float | None:
    prices = PRICING_PER_MTOK.get(model)
    if prices is None:
        return None
    cache_write = prices.get("cache_write", prices["input"] * 1.25)
    cache_read = prices.get("cache_read", prices["input"] * 0.10)
    total = (
        input_tokens * prices["input"]
        + output_tokens * prices["output"]
        + cache_creation_tokens * cache_write
        + cache_read_tokens * cache_read
    ) / 1_000_000
    return round(total, 6)


def _percentile(values: list[int], pct: int) -> int | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return int(quantiles(values, n=100, method="inclusive")[pct - 1])


def dashboard_metrics(days: int = 7) -> dict:
    from .models import EvalRun, GuardrailEvent, LLMCall

    since = timezone.now() - timedelta(days=days)
    calls = LLMCall.objects.filter(created_at__gte=since)

    totals = calls.aggregate(
        calls=Count("id"),
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
        cache_read_tokens=Sum("cache_read_tokens"),
        cache_creation_tokens=Sum("cache_creation_tokens"),
        cost_usd=Sum("cost_usd"),
    )
    totals = {k: (v or 0) for k, v in totals.items()}
    totals["cost_usd"] = float(totals["cost_usd"])
    prompt_tokens = totals["input_tokens"] + totals["cache_read_tokens"] + totals["cache_creation_tokens"]
    totals["cache_hit_rate"] = round(totals["cache_read_tokens"] / prompt_tokens, 4) if prompt_tokens else None
    status_counts = dict(calls.values_list("status").annotate(n=Count("id")))
    totals["error_rate"] = round(status_counts.get("error", 0) / totals["calls"], 4) if totals["calls"] else None
    totals["refusal_rate"] = round(status_counts.get("refusal", 0) / totals["calls"], 4) if totals["calls"] else None
    totals["fallbacks"] = calls.filter(fallback_used=True).count()

    by_feature = []
    for row in calls.values("feature").annotate(
        n=Count("id"), input_tokens=Sum("input_tokens"), output_tokens=Sum("output_tokens"), cost_usd=Sum("cost_usd")
    ).order_by("-n"):
        latencies = list(calls.filter(feature=row["feature"]).values_list("latency_ms", flat=True))
        by_feature.append(
            {
                "feature": row["feature"],
                "calls": row["n"],
                "input_tokens": row["input_tokens"] or 0,
                "output_tokens": row["output_tokens"] or 0,
                "cost_usd": float(row["cost_usd"] or 0),
                "p50_latency_ms": _percentile(latencies, 50),
                "p95_latency_ms": _percentile(latencies, 95),
            }
        )

    guardrails = dict(
        GuardrailEvent.objects.filter(created_at__gte=since).values_list("kind").annotate(n=Count("id"))
    )

    recent = [
        {
            "id": c.id,
            "feature": c.feature,
            "provider": c.provider,
            "model": c.model,
            "status": c.status,
            "input_tokens": c.input_tokens,
            "output_tokens": c.output_tokens,
            "cache_read_tokens": c.cache_read_tokens,
            "latency_ms": c.latency_ms,
            "cost_usd": float(c.cost_usd) if c.cost_usd is not None else None,
            "created_at": c.created_at.isoformat(),
        }
        for c in calls[:25]
    ]

    latest_evals = {}
    for run in EvalRun.objects.all()[:50]:
        latest_evals.setdefault(run.suite, {"created_at": run.created_at.isoformat(), "config": run.config, "metrics": run.metrics})

    return {
        "window_days": days,
        "totals": totals,
        "by_feature": by_feature,
        "guardrail_events": guardrails,
        "recent_calls": recent,
        "latest_evals": latest_evals,
    }
