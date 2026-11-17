"""Information-retrieval metrics with binary relevance."""

from __future__ import annotations

import math
from statistics import mean


def recall_at_k(ranked: list, relevant: set, k: int) -> float:
    if not relevant:
        return 0.0
    return len(relevant & set(ranked[:k])) / len(relevant)


def hit_at_k(ranked: list, relevant: set, k: int) -> float:
    return 1.0 if relevant & set(ranked[:k]) else 0.0


def reciprocal_rank(ranked: list, relevant: set, k: int = 10) -> float:
    for i, item in enumerate(ranked[:k], start=1):
        if item in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list, relevant: set, k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 1) for i, item in enumerate(ranked[:k], start=1) if item in relevant)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def summarize(rows: list[dict], keys: list[str]) -> dict:
    return {key: round(mean(r[key] for r in rows), 4) if rows else None for key in keys}
