"""Natural-language query -> structured search intent.

"waterproof running shoes under 3k in stock" ->
    SearchIntent(semantic_query="waterproof running shoes", category_slug="footwear",
                 max_price=3000, in_stock_only=True)

Live mode uses Claude structured outputs (the response is constrained to the Pydantic schema
and validated). Offline mode uses `heuristic_parse`, which is also the baseline the
query-parsing eval compares against. Results are cached, so repeated queries cost nothing.
"""

from __future__ import annotations

import hashlib
import logging
import re
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from pydantic import BaseModel, ConfigDict, Field

from store.models import Category

from .llm import LLMError, get_llm
from .search import SearchFilters

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60 * 60


class SearchIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic_query: str = Field(description="What the shopper is looking for, without price, stock or category constraints.")
    category_slug: str | None = Field(description="Slug of the single best matching category, or null if unclear.")
    min_price: float | None = Field(description="Minimum price in INR, or null.")
    max_price: float | None = Field(description="Maximum price in INR, or null.")
    in_stock_only: bool = Field(description="True only if the shopper asked for items that are in stock / available now.")


SYSTEM_PROMPT = """You convert a shopper's search box text into structured search filters for an Indian online store. Prices are in INR.
Rules:
- category_slug must be one of the provided slugs, or null when the query does not clearly belong to one category.
- Only set min_price / max_price when the shopper states a price limit. "under 3k" means max_price 3000; "around 2000" is not a limit.
- semantic_query keeps the descriptive words (product type, features, use case, audience) and drops price, stock and filler words. Never invent requirements."""


# ---------------------------------------------------------------------------
# Heuristic parser (offline mode + eval baseline)
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS = {
    "electronics": ["headphone", "headphones", "earbuds", "earphones", "speaker", "charger", "power bank", "powerbank",
                    "smartwatch", "watch", "keyboard", "mouse", "webcam", "laptop", "phone", "tablet", "camera", "monitor"],
    "footwear": ["shoe", "shoes", "sneaker", "sneakers", "sandal", "sandals", "slipper", "slippers", "boots", "trainers", "loafers"],
    "clothing": ["shirt", "t-shirt", "tshirt", "tee", "jacket", "hoodie", "jeans", "kurta", "dress", "socks", "trousers", "shorts", "raincoat"],
    "home-kitchen": ["kitchen", "cookware", "pan", "kettle", "flask", "bottle", "mug", "knife", "mixer", "blender",
                     "lamp", "bedsheet", "pillow", "cushion", "home", "cooker", "tumbler"],
    "books": ["book", "books", "novel", "guide", "paperback", "read", "reading"],
    "sports-fitness": ["yoga", "dumbbell", "dumbbells", "gym", "fitness", "cricket", "football", "badminton",
                       "racket", "skipping", "workout", "exercise", "cycling", "resistance band"],
}

_NUM = r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?"
_BETWEEN_RE = re.compile(rf"\bbetween\s+{_NUM}\s+(?:and|to|-)\s+{_NUM}", re.I)
_RANGE_RE = re.compile(rf"(?:₹|rs\.?|inr)\s*(\d[\d,]*)\s*(k)?\s*(?:-|to)\s*(?:₹|rs\.?|inr)?\s*(\d[\d,]*)\s*(k)?", re.I)
_MAX_RE = re.compile(rf"\b(?:under|below|less than|upto|up to|within|max(?:imum)?|cheaper than|not more than|<)\s*{_NUM}", re.I)
_MIN_RE = re.compile(rf"\b(?:over|above|more than|at least|min(?:imum)?|starting|from|>)\s*{_NUM}", re.I)
_STOCK_RE = re.compile(r"\b(in stock|available now|in-stock|ready to ship)\b", re.I)


def _amount(number: str, k: str | None) -> float:
    value = float(number.replace(",", ""))
    return value * 1000 if k else value


def _guess_category(text: str, valid_slugs: set[str]) -> str | None:
    lowered = text.lower()
    scores = {}
    for slug, words in CATEGORY_KEYWORDS.items():
        if slug not in valid_slugs:
            continue
        hits = sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", lowered))
        if hits:
            scores[slug] = hits
    if not scores:
        return None
    best = max(scores.values())
    winners = [slug for slug, score in scores.items() if score == best]
    return winners[0] if len(winners) == 1 else None


def heuristic_parse(query: str, valid_slugs: set[str]) -> SearchIntent:
    text = query.strip()
    min_price = max_price = None
    remaining = text

    if m := _BETWEEN_RE.search(text):
        min_price, max_price = _amount(m.group(1), m.group(2)), _amount(m.group(3), m.group(4))
        remaining = remaining.replace(m.group(0), " ")
    elif m := _RANGE_RE.search(text):
        min_price, max_price = _amount(m.group(1), m.group(2)), _amount(m.group(3), m.group(4))
        remaining = remaining.replace(m.group(0), " ")
    else:
        if m := _MAX_RE.search(text):
            max_price = _amount(m.group(1), m.group(2))
            remaining = remaining.replace(m.group(0), " ")
        if m := _MIN_RE.search(text):
            min_price = _amount(m.group(1), m.group(2))
            remaining = remaining.replace(m.group(0), " ")

    in_stock = bool(_STOCK_RE.search(text))
    remaining = _STOCK_RE.sub(" ", remaining)
    remaining = re.sub(r"\b(rupees|rs|inr|price|priced|budget|for me|please|show me|i want|i need|looking for)\b", " ", remaining, flags=re.I)
    semantic = re.sub(r"\s+", " ", remaining).strip(" ,.-") or text

    return SearchIntent(
        semantic_query=semantic,
        category_slug=_guess_category(text, valid_slugs),
        min_price=min_price,
        max_price=max_price,
        in_stock_only=in_stock,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _validate(intent: SearchIntent, query: str, valid_slugs: set[str]) -> SearchIntent:
    """Never trust model output blindly: unknown categories and impossible prices are dropped."""
    data = intent.model_dump()
    if data["category_slug"] not in valid_slugs:
        data["category_slug"] = None
    for key in ("min_price", "max_price"):
        if data[key] is not None and data[key] < 0:
            data[key] = None
    if data["min_price"] is not None and data["max_price"] is not None and data["min_price"] > data["max_price"]:
        data["min_price"], data["max_price"] = data["max_price"], data["min_price"]
    if not data["semantic_query"].strip():
        data["semantic_query"] = query
    return SearchIntent(**data)


def parse_query(query: str, user=None) -> tuple[SearchIntent, dict]:
    """Returns (intent, meta). meta reports provider, model and whether the cache was hit."""
    llm = get_llm()
    categories = list(Category.objects.values_list("slug", "name"))
    valid_slugs = {slug for slug, _ in categories}
    key = "intent:" + hashlib.sha256(f"{llm.name}:{llm.model}:{query.strip().lower()}:{sorted(valid_slugs)}".encode()).hexdigest()

    if cached := cache.get(key):
        return SearchIntent(**cached["intent"]), {"provider": cached["provider"], "model": cached["model"], "cached": True}

    category_list = "\n".join(f"- {slug}: {name}" for slug, name in categories)
    try:
        result = llm.parse(
            feature="search_parse",
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Categories:\n{category_list}\n\nSearch text: {query}"}],
            schema=SearchIntent,
            offline=lambda: heuristic_parse(query, valid_slugs),
            max_tokens=settings.AI["MAX_TOKENS_STRUCTURED"],
            effort=settings.AI["EFFORT_STRUCTURED"],
            user=user,
        )
        intent, meta = result.value, {"provider": result.provider, "model": result.model, "cached": False}
    except LLMError as exc:
        # Graceful degradation: search still works with the rule-based parser.
        logger.warning("LLM query parsing failed, using heuristic parser: %s", exc)
        intent = heuristic_parse(query, valid_slugs)
        meta = {"provider": "offline", "model": "rule-based-v1 (fallback)", "cached": False, "degraded": True}

    intent = _validate(intent, query, valid_slugs)
    if meta["provider"] == llm.name:  # don't cache fallback answers: retry the LLM once it is back
        cache.set(key, {"intent": intent.model_dump(), "provider": meta["provider"], "model": meta["model"]}, CACHE_TTL_SECONDS)
    return intent, meta


def intent_to_filters(intent: SearchIntent) -> SearchFilters:
    return SearchFilters(
        category=intent.category_slug,
        min_price=Decimal(str(intent.min_price)) if intent.min_price is not None else None,
        max_price=Decimal(str(intent.max_price)) if intent.max_price is not None else None,
        in_stock_only=intent.in_stock_only,
    )
