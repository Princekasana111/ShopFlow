"""AI Shopping Planner: a goal and a budget in, an optimal bundle out.

    "Monsoon trek in Himachal, budget ₹8,000"
      1. plan     LLM (structured output) -> needs: hiking boots (must), rain jacket (must), ...
      2. retrieve hybrid search per need -> up to 4 in-stock candidates each
      3. optimize exact multiple-choice knapsack: at most one product per need, maximise
                  must-have coverage, then relevance and rating, never exceed the budget

The LLM plans; plain code enforces the budget. Arithmetic constraints are never left to the
model, so the bundle total can't exceed the budget.

"Complete the kit" on product pages reuses the same planner to suggest complementary items.
Raw embedding similarity was tried first and rejected: it suggested a monitor for a frying
pan and kids' sneakers for headphones. Similar is not the same as complementary.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from django.conf import settings
from django.core.cache import cache
from pydantic import BaseModel, ConfigDict, Field

from store.models import Category

from . import guardrails
from .agent.tools import product_card
from .llm import LLMError, get_llm
from .query_understanding import heuristic_parse
from .search import SearchFilters, search_products

MAX_NEEDS = 7
CANDIDATES_PER_NEED = 4


class PlannedNeed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(description="Short name of the need, e.g. 'Rain jacket'.")
    search_query: str = Field(description="Product search query for this need.")
    category_slug: str | None = Field(description="Category slug from the provided list, or null.")
    priority: Literal["must", "nice"] = Field(description="'must' if the goal fails without it, else 'nice'.")
    reason: str = Field(description="One short sentence: why this helps with the goal.")


class ShoppingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(description="One sentence restating the goal.")
    budget_inr: float | None = Field(description="Total budget in INR if the shopper gave one, else null.")
    needs: list[PlannedNeed] = Field(description="2 to 7 needs ordered by importance, most important first.")


PLAN_PROMPT = """You plan shopping lists for ShopFlow, an Indian online store. Given a shopper's goal, list the 2-7 product needs that best serve it, ordered by importance (the item the goal depends on most comes first).
- Only plan items a store in these categories could sell; use only the provided category slugs.
- Keep search queries short and concrete (product type plus one key attribute).
- Extract the total budget in INR if the shopper states one ("under 8k" means 8000); otherwise null.
- Do not pick specific products or prices; the store's search and optimiser do that."""

KIT_PROMPT = """You suggest complementary items for a product at ShopFlow, an Indian online store: things a shopper buying this product is likely to also need.
- Suggest 2-4 needs from the provided categories, never another product of the same type.
- Keep search queries short and concrete."""


# Curated scenarios for offline mode (and the baseline the planner eval compares against).
N = lambda label, query, category, priority, reason: (label, query, category, priority, reason)  # noqa: E731
SCENARIOS: list[tuple[str, str, list[tuple]]] = [
    ("trek", r"\b(treks?|trekking|hik(e|es|ing)|himalaya\w*|mountains?|camping|trails?)\b", [
        N("Hiking boots", "waterproof hiking boots", "footwear", "must", "Grip and ankle support on rough trails."),
        N("Trekking socks", "merino wool trekking socks", "clothing", "must", "Warm, odour-resistant socks prevent blisters."),
        N("Power bank", "portable power bank for travel", "electronics", "nice", "Keeps your phone alive far from sockets."),
        N("Insulated flask", "insulated flask hot drinks", "home-kitchen", "nice", "Hot tea on cold mornings."),
    ]),
    ("monsoon", r"\b(monsoon|rain|rainy|rains|wet)\b", [
        N("Rain jacket", "waterproof packable rain jacket", "clothing", "must", "Stay dry in heavy rain."),
        N("Rain-ready footwear", "waterproof flip flops for rain", "footwear", "nice", "Quick-drying footwear for wet days."),
    ]),
    ("cold", r"\b(winter|cold|snow|manali|shimla|ladakh|december|january)\b", [
        N("Warm jacket", "warm windproof puffer jacket", "clothing", "must", "Insulation against the cold."),
        N("Warm layer", "fleece hoodie warm layer", "clothing", "nice", "An extra layer for chilly evenings."),
    ]),
    ("running", r"\b(run|runs|running|runner|marathon|jog|jogging|5k|10k)\b", [
        N("Running shoes", "cushioned road running shoes", "footwear", "must", "Cushioning protects your joints."),
        N("Quick-dry t-shirt", "moisture wicking sports t-shirt", "clothing", "must", "Stays light and dry on long runs."),
        N("Fitness tracker", "GPS fitness smartwatch", "electronics", "nice", "Tracks pace, distance and heart rate."),
        N("Recovery", "foam roller muscle recovery", "sports-fitness", "nice", "Eases sore muscles after runs."),
    ]),
    ("gym", r"\b(gym|workouts?|strength|fitness|exercise|weights)\b", [
        N("Dumbbells", "adjustable dumbbells", "sports-fitness", "must", "The core of home strength training."),
        N("Resistance bands", "resistance bands set", "sports-fitness", "must", "Versatile, portable resistance."),
        N("Exercise mat", "anti slip exercise mat", "sports-fitness", "nice", "Cushions floor exercises."),
        N("Cardio", "speed skipping rope", "sports-fitness", "nice", "Quick cardio at home."),
    ]),
    ("yoga", r"\b(yoga|pilates|meditat\w*|stretch\w*)\b", [
        N("Yoga mat", "anti slip yoga mat", "sports-fitness", "must", "Grip and cushioning for poses."),
        N("Yoga wear", "high waist yoga leggings", "clothing", "must", "Stretchy, squat-proof movement."),
        N("Mindfulness", "meditation book stress", "books", "nice", "Builds a calm daily practice."),
    ]),
    ("home_office", r"\b(home office|work from home|wfh|remote work|desk setup|office setup|workstation)\b", [
        N("Monitor", "second screen monitor", "electronics", "must", "More screen space for work."),
        N("Keyboard", "mechanical keyboard", "electronics", "must", "Comfortable all-day typing."),
        N("Mouse", "wireless mouse", "electronics", "must", "Precise, comfortable pointing."),
        N("Webcam", "webcam for video calls", "electronics", "nice", "Clear video for meetings."),
        N("Desk lamp", "LED desk lamp", "home-kitchen", "nice", "Good light for late work."),
    ]),
    ("coding", r"\b(coding|code|programming|programmers?|python|developers?|software|dsa)\b", [
        N("Beginner programming book", "python programming book for beginners", "books", "must", "A structured way to learn."),
        N("Interview prep", "coding interview data structures book", "books", "nice", "Practice for interviews and contests."),
        N("Keyboard", "mechanical keyboard for programmers", "electronics", "nice", "Nicer to type on for hours."),
    ]),
    ("kitchen", r"\b(kitchen|cook|cooking|cookware|frying pan|pans?|knife|kettle|fryer|recipes?|new home|new flat|apartment|hostel|bachelor)\b", [
        N("Frying pan", "non stick frying pan", "home-kitchen", "must", "Everyday cooking with little oil."),
        N("Chef knife", "chef knife", "home-kitchen", "must", "One sharp knife does most prep."),
        N("Cutting board", "cutting board set", "home-kitchen", "must", "Safe, knife-friendly chopping."),
        N("Kettle", "electric kettle", "home-kitchen", "nice", "Tea, coffee and instant meals fast."),
        N("Cookbook", "indian recipes cookbook", "books", "nice", "Easy recipes to start with."),
    ]),
    ("kids", r"\b(kids?|child|children|son|daughter|nephew|niece|planets?|space)\b", [
        N("Kids' book", "illustrated book for children space planets", "books", "must", "Fun facts that spark curiosity."),
        N("Fun shoes", "kids light up sneakers", "footwear", "nice", "Shoes kids actually want to wear."),
    ]),
    ("travel", r"\b(travel|trip|vacation|holiday|flights?|journey|goa|beach)\b", [
        N("Power bank", "portable power bank for travel", "electronics", "must", "Charge on the go."),
        N("Headphones", "noise cancelling headphones for flights", "electronics", "nice", "Quiet flights and trains."),
        N("Water bottle", "steel water bottle", "home-kitchen", "nice", "Stay hydrated without buying plastic."),
        N("Sandals", "comfortable sandals for travel", "footwear", "nice", "Easy footwear for warm places."),
    ]),
    ("cricket", r"\b(cricket|batting)\b", [N("Cricket bat", "cricket bat", "sports-fitness", "must", "The essential for any match.")]),
    ("football", r"\b(football|soccer)\b", [N("Football", "football size 5", "sports-fitness", "must", "A match ball for grass and turf.")]),
    ("badminton", r"\b(badminton|shuttle)\b", [
        N("Racket", "badminton racket", "sports-fitness", "must", "A light racket for fast play."),
        N("Court shoes", "badminton court shoes", "footwear", "must", "Grip on indoor courts."),
    ]),
    ("cycling", r"\b(cycl\w*|bikes?|biking)\b", [N("Helmet", "cycling helmet", "sports-fitness", "must", "Safety first on every ride.")]),
    ("festive", r"\b(diwali|eid|festivals?|festive|wedding|puja|pooja)\b", [
        N("Festive wear", "festive cotton kurta", "clothing", "must", "Comfortable traditional wear."),
        N("Formal shoes", "leather formal shoes", "footwear", "nice", "Polished shoes for occasions."),
    ]),
]

_BUDGET_RE = re.compile(r"\b(?:budget|spend|under|within|upto|up to|max(?:imum)?)\b[^0-9₹]{0,12}(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?\b", re.I)
_CURRENCY_RE = re.compile(r"(?:₹|rs\.?\s*|inr\s*)(\d[\d,]*(?:\.\d+)?)\s*(k)?\b", re.I)


def parse_budget(text: str) -> float | None:
    for regex in (_BUDGET_RE, _CURRENCY_RE):
        amounts = [float(n.replace(",", "")) * (1000 if k else 1) for n, k in regex.findall(text)]
        if amounts:
            return max(amounts)
    return heuristic_parse(text, set()).max_price


def heuristic_plan(goal: str) -> ShoppingPlan:
    needs, seen = [], set()
    for _, pattern, items in SCENARIOS:
        if re.search(pattern, goal, re.I):
            for label, query, category, priority, reason in items:
                if label not in seen:
                    seen.add(label)
                    needs.append(PlannedNeed(label=label, search_query=query, category_slug=category, priority=priority, reason=reason))
    if not needs:  # unknown goal: treat comma / "and" separated parts as needs
        cleaned = re.sub(r"(?:budget|under|within|for|of|₹|rs\.?|inr)?\s*\d[\d,]*\s*k?\b", " ", goal, flags=re.I)
        parts = [p.strip(" .") for p in re.split(r",|\band\b|\+|;", cleaned) if len(p.strip(" .")) > 2]
        for part in parts[:MAX_NEEDS] or [goal]:
            needs.append(PlannedNeed(label=part[:1].upper() + part[1:60], search_query=part[:120], category_slug=None, priority="must", reason="You asked for this."))
    needs.sort(key=lambda n: n.priority != "must")
    return ShoppingPlan(summary=goal.strip()[:200], budget_inr=parse_budget(goal), needs=needs[:MAX_NEEDS])


# ---------------------------------------------------------------------------
# Optimisation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    product_id: int
    price_paise: int
    value: float


def choose_bundle(groups: list[list[Candidate]], budget_paise: int | None) -> tuple[int, ...]:
    """Exact multiple-choice knapsack: pick at most one candidate per group, maximise total
    value, total cost <= budget. Returns the chosen candidate index per group (-1 = none).

    Dynamic programming over a Pareto frontier of (cost, value) states: a state that costs
    more and is worth no more than another can never become optimal, so it is dropped.
    """
    states: dict[int, tuple[float, tuple[int, ...]]] = {0: (0.0, ())}
    for group in groups:
        nxt: dict[int, tuple[float, tuple[int, ...]]] = {}

        def offer(cost: int, value: float, picks: tuple[int, ...]):
            if budget_paise is not None and cost > budget_paise:
                return
            if cost not in nxt or nxt[cost][0] < value:
                nxt[cost] = (value, picks)

        for cost, (value, picks) in states.items():
            offer(cost, value, picks + (-1,))
            for index, cand in enumerate(group):
                offer(cost + cand.price_paise, value + cand.value, picks + (index,))
        frontier, best = {}, float("-inf")
        for cost in sorted(nxt):
            value, picks = nxt[cost]
            if value > best + 1e-9:
                frontier[cost] = (value, picks)
                best = value
        states = frontier
    _, (_, picks) = max(states.items(), key=lambda kv: (kv[1][0], -kv[0]))
    return picks


def need_weights(needs: list[PlannedNeed]) -> list[float]:
    """Objective, in strict order: cover as many must-haves as possible, then prefer the more
    important ones (needs are listed most important first), then add nice-to-haves.
    Relevance and rating (< 7 points) only break ties within those tiers."""
    musts = [i for i, n in enumerate(needs) if n.priority == "must"]
    nices = [i for i, n in enumerate(needs) if n.priority != "must"]
    weights = [0.0] * len(needs)
    for rank, i in enumerate(musts):
        weights[i] = 1000.0 + 50.0 * (len(musts) - rank)
    for rank, i in enumerate(nices):
        weights[i] = 20.0 + 2.0 * (len(nices) - rank)
    return weights


def _value(weight: float, relevance: float, rating: float | None) -> float:
    return weight + 5.0 * max(relevance, 0.0) + 0.3 * (rating or 3.0)


def _plan(goal: str, user) -> tuple[ShoppingPlan, dict]:
    llm = get_llm()
    categories = "\n".join(f"- {slug}: {name}" for slug, name in Category.objects.values_list("slug", "name"))
    try:
        result = llm.parse(
            feature="planner",
            system=PLAN_PROMPT,
            messages=[{"role": "user", "content": f"Categories:\n{categories}\n\nGoal: {goal}"}],
            schema=ShoppingPlan,
            offline=lambda: heuristic_plan(goal),
            max_tokens=settings.AI["MAX_TOKENS_STRUCTURED"],
            effort=settings.AI["EFFORT_STRUCTURED"],
            user=user,
        )
        return result.value, {"provider": result.provider, "model": result.model}
    except LLMError:
        return heuristic_plan(goal), {"provider": "offline", "model": "rule-based-v1 (fallback)"}


def _candidates(needs: list[PlannedNeed], exclude: set[int] | None = None):
    """Retrieve in-stock candidates per need; a product is assigned to the need it fits best."""
    valid = set(Category.objects.values_list("slug", flat=True))
    retrieved = []
    best_for: dict[int, tuple[float, int]] = {}
    margin, floor = settings.AI["PLANNER_RELATIVE_MARGIN"], settings.AI["PLANNER_MIN_SIMILARITY"]
    for i, need in enumerate(needs):
        filters = SearchFilters(category=need.category_slug if need.category_slug in valid else None, in_stock_only=True)
        hits = [h for h in search_products(need.search_query, filters, limit=CANDIDATES_PER_NEED + 2) if h.product and h.product.pk not in (exclude or set())]
        # Relevance gate: only products close to the best match can cover a need. Without it the
        # optimiser "covered" a rain jacket with a cheap T-shirt to stay under budget.
        top = max((h.similarity or 0.0 for h in hits), default=0.0)
        hits = [h for h in hits if (h.similarity or 0.0) >= max(top - margin, floor)]
        retrieved.append(hits)
        for h in hits:
            sim = h.similarity or 0.0
            if h.product.pk not in best_for or best_for[h.product.pk][0] < sim:
                best_for[h.product.pk] = (sim, i)
    return [[h for h in hits if best_for[h.product.pk][1] == i][:CANDIDATES_PER_NEED] for i, hits in enumerate(retrieved)]


def build_bundle(goal: str, budget: float | None = None, user=None) -> dict:
    started = time.perf_counter()
    check = guardrails.check_user_message(goal)
    if not check.allowed:
        if check.kind == "prompt_injection":
            guardrails.record_event("prompt_injection", user=user, excerpt=goal, patterns=check.matches, feature="planner")
        raise ValueError(check.reply)

    plan, meta = _plan(goal, user)
    valid = set(Category.objects.values_list("slug", flat=True))
    needs = [n for n in plan.needs if n.search_query.strip()][:MAX_NEEDS]
    for n in needs:
        if n.category_slug not in valid:
            n.category_slug = None
    budget_value = budget if budget is not None else plan.budget_inr
    if budget_value is not None and budget_value <= 0:
        budget_value = None
    budget_paise = int(Decimal(str(budget_value)) * 100) if budget_value is not None else None

    groups_hits = _candidates(needs)
    groups = [
        [Candidate(h.product.pk, int(h.product.price * 100), _value(w, h.similarity or 0.0, h.product.avg_rating)) for h in hits]
        for w, hits in zip(need_weights(needs), groups_hits)
    ]
    picks = choose_bundle(groups, budget_paise)

    items, skipped, total = [], [], Decimal("0")
    for need, hits, pick in zip(needs, groups_hits, picks):
        need_data = need.model_dump()
        if pick < 0:
            skipped.append({"need": need_data, "reason": "Nothing suitable in stock" if not hits else "Doesn't fit the budget"})
            continue
        chosen = hits[pick].product
        total += chosen.price
        items.append({
            "need": need_data,
            "product": product_card(chosen),
            "alternatives": [product_card(h.product) for j, h in enumerate(hits) if j != pick],
        })
    return {
        "goal": goal,
        "summary": plan.summary,
        "budget": f"{Decimal(str(budget_value)):.2f}" if budget_value is not None else None,
        "total": f"{total:.2f}",
        "remaining": f"{Decimal(str(budget_value)) - total:.2f}" if budget_value is not None else None,
        "items": items,
        "skipped": skipped,
        "planner": meta,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


# ---------------------------------------------------------------------------
# Complete the kit
# ---------------------------------------------------------------------------

class KitPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    needs: list[PlannedNeed] = Field(description="2 to 4 complementary needs.")


def _heuristic_kit(product) -> KitPlan:
    text = f"{product.name}. {product.description}"
    needs, seen = [], set()
    for _, pattern, items in SCENARIOS:
        if re.search(pattern, text, re.I):
            for label, query, category, priority, reason in items:
                if label not in seen:
                    seen.add(label)
                    needs.append(PlannedNeed(label=label, search_query=query, category_slug=category, priority=priority, reason=reason))
    return KitPlan(needs=needs)


def complete_the_kit(product, user=None, limit: int = 3) -> dict:
    key = f"kit:{product.pk}:{product.updated_at.timestamp()}:{get_llm().name}"
    if cached := cache.get(key):
        return cached
    llm = get_llm()
    categories = "\n".join(f"- {slug}: {name}" for slug, name in Category.objects.values_list("slug", "name"))
    facts = f"Product: {product.name}\nCategory: {product.category.name}\nDescription: {product.description}"
    try:
        result = llm.parse(
            feature="complete_the_kit",
            system=KIT_PROMPT,
            messages=[{"role": "user", "content": f"Categories:\n{categories}\n\n{facts}"}],
            schema=KitPlan,
            offline=lambda: _heuristic_kit(product),
            max_tokens=settings.AI["MAX_TOKENS_STRUCTURED"],
            effort=settings.AI["EFFORT_STRUCTURED"],
            user=user,
        )
        plan, meta = result.value, {"provider": result.provider, "model": result.model}
    except LLMError:
        plan, meta = _heuristic_kit(product), {"provider": "offline", "model": "rule-based-v1 (fallback)"}

    suggestions, used = [], {product.pk}
    for need, hits in zip(plan.needs, _candidates(plan.needs[:6])):
        # Skip a need if the product itself shows up for it: that need *is* this product.
        if any(h.product.pk == product.pk for h in search_products(need.search_query, SearchFilters(category=need.category_slug), limit=3)):
            continue
        pick = next((h.product for h in hits if h.product.pk not in used), None)
        if pick:
            used.add(pick.pk)
            suggestions.append({"label": need.label, "reason": need.reason, "product": product_card(pick)})
        if len(suggestions) >= limit:
            break
    data = {"items": suggestions, **meta}
    cache.set(key, data, 60 * 60 * 24)
    return data
