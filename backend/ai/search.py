"""Hybrid product retrieval: PostgreSQL full-text search + pgvector semantic search,
combined with Reciprocal Rank Fusion (RRF).

Why hybrid: keyword search is precise for exact terms ("JBL", "4K", model names) but misses
paraphrases ("something to keep my coffee hot" vs. "insulated flask"); vector search handles
paraphrases but can blur exact terms. RRF merges the two ranked lists using only ranks
(score_d = sum over lists of 1 / (k + rank_d)), so the two scores never need calibrating.
The retrieval eval (`manage.py run_evals --suite search`) measures all three modes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import TextField
from django.db.models.functions import Cast
from pgvector.django import CosineDistance

from store.models import Product
from store.selectors import annotated_products

from .embeddings import embed_query

MODES = ("keyword", "vector", "hybrid")
CANDIDATES_PER_RETRIEVER = 50

_TERM_RE = re.compile(r"[a-z0-9]+")


@dataclass
class SearchFilters:
    category: str | None = None  # category slug
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    in_stock_only: bool = False

    def apply(self, qs):
        if self.category:
            qs = qs.filter(category__slug=self.category)
        if self.min_price is not None:
            qs = qs.filter(price__gte=self.min_price)
        if self.max_price is not None:
            qs = qs.filter(price__lte=self.max_price)
        if self.in_stock_only:
            qs = qs.filter(stock__gt=0)
        return qs

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "min_price": str(self.min_price) if self.min_price is not None else None,
            "max_price": str(self.max_price) if self.max_price is not None else None,
            "in_stock_only": self.in_stock_only,
        }


@dataclass
class SearchHit:
    product_id: int
    score: float
    keyword_rank: int | None = None
    vector_rank: int | None = None
    similarity: float | None = None
    product: Product | None = field(default=None, repr=False)


def _product_search_vector():
    return (
        SearchVector("name", weight="A", config="english")
        + SearchVector("brand", weight="A", config="english")
        + SearchVector("category__name", weight="B", config="english")
        + SearchVector("description", weight="C", config="english")
        + SearchVector(Cast("attributes", TextField()), weight="C", config="english")
    )


def or_query(text: str) -> SearchQuery | None:
    """OR together the query's terms: documents matching more (and rarer, higher-weighted)
    terms rank higher. websearch/plain AND semantics would return nothing for long
    natural-language queries."""
    terms = [t for t in _TERM_RE.findall(text.lower()) if len(t) > 1][:16]
    query = None
    for term in terms:
        q = SearchQuery(term, search_type="plain", config="english")
        query = q if query is None else query | q
    return query


def keyword_search(text: str, filters: SearchFilters, k: int = CANDIDATES_PER_RETRIEVER) -> list[tuple[int, float]]:
    query = or_query(text)
    if query is None:
        return []
    qs = filters.apply(Product.objects.filter(is_active=True))
    vector = _product_search_vector()
    rows = (
        # Match with `@@` (document=query); ts_rank alone is not a match test (see store/views.py).
        qs.annotate(document=vector, rank=SearchRank(vector, query))
        .filter(document=query)
        .order_by("-rank", "id")
        .values_list("id", "rank")[:k]
    )
    return [(pid, float(rank)) for pid, rank in rows]


def vector_search(text: str, filters: SearchFilters, k: int = CANDIDATES_PER_RETRIEVER) -> list[tuple[int, float]]:
    """Returns (product_id, cosine similarity). Filters are applied before ranking."""
    if not text.strip():
        return []
    qvec = embed_query(text)
    qs = filters.apply(Product.objects.filter(is_active=True, embedding_record__isnull=False))
    rows = (
        qs.annotate(distance=CosineDistance("embedding_record__vector", qvec))
        .order_by("distance", "id")
        .values_list("id", "distance")[:k]
    )
    return [(pid, 1.0 - float(distance)) for pid, distance in rows]


def rrf_fuse(rankings: list[list[int]], weights: list[float] | None = None, k: int | None = None) -> list[tuple[int, float]]:
    """Weighted Reciprocal Rank Fusion. `rankings` are lists of ids, best first.

    score(d) = sum_i weight_i / (k + rank_i(d))
    """
    k = settings.AI["RRF_K"] if k is None else k
    weights = weights or [1.0] * len(rankings)
    scores: dict[int, float] = {}
    for ranking, weight in zip(rankings, weights):
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + weight / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def hybrid_weights() -> list[float]:
    """[keyword, vector]. Keyword is down-weighted: on the search eval, equal weights let noisy
    OR-matches outrank the right product (hit@1 0.913); keyword weight 0.2-0.75 all reached
    hit@1 0.957 while keeping recall@5 at 1.0, so 0.5 sits in the middle of that plateau."""
    return [settings.AI["RRF_KEYWORD_WEIGHT"], 1.0]


def search_products(text: str, filters: SearchFilters | None = None, mode: str = "hybrid",
                    limit: int = 10, attach_products: bool = True) -> list[SearchHit]:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    filters = filters or SearchFilters()
    text = (text or "").strip()

    keyword = keyword_search(text, filters) if mode in ("keyword", "hybrid") else []
    vector = vector_search(text, filters) if mode in ("vector", "hybrid") else []
    keyword_rank = {pid: i for i, (pid, _) in enumerate(keyword, start=1)}
    vector_rank = {pid: i for i, (pid, _) in enumerate(vector, start=1)}
    similarity = dict(vector)

    if mode == "keyword":
        ranked = keyword
    elif mode == "vector":
        ranked = vector
    else:
        ranked = rrf_fuse([[pid for pid, _ in keyword], [pid for pid, _ in vector]], weights=hybrid_weights())

    if not text:  # no query: just list filtered products
        ids = list(filters.apply(Product.objects.filter(is_active=True)).order_by("name").values_list("id", flat=True)[:limit])
        ranked = [(pid, 0.0) for pid in ids]

    hits = [
        SearchHit(
            product_id=pid,
            score=round(score, 6),
            keyword_rank=keyword_rank.get(pid),
            vector_rank=vector_rank.get(pid),
            similarity=round(similarity[pid], 4) if pid in similarity else None,
        )
        for pid, score in ranked[:limit]
    ]
    if attach_products and hits:
        products = annotated_products().in_bulk([h.product_id for h in hits])
        for hit in hits:
            hit.product = products.get(hit.product_id)
    return hits


def similar_products(product: Product, limit: int = 4) -> list[tuple[Product, float]]:
    record = getattr(product, "embedding_record", None)
    if record is None:
        return []
    rows = (
        annotated_products()
        .filter(is_active=True, embedding_record__isnull=False)
        .exclude(pk=product.pk)
        .annotate(distance=CosineDistance("embedding_record__vector", record.vector))
        .order_by("distance", "id")[:limit]
    )
    return [(p, round(1.0 - float(p.distance), 4)) for p in rows]
