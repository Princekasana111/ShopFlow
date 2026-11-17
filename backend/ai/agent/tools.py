"""Tools the shopping assistant can call.

Security model:
* Every tool runs as the signed-in customer (`ToolContext.user`) taken from the
  authenticated request, never from model output. The model cannot read another customer's
  cart or orders, whatever it is told.
* Inputs are validated with Pydantic before any tool runs (the model's arguments are
  untrusted). Invalid input returns an `is_error` tool result the model can recover from.
* Cart changes go through `store.services`, the same rules the REST API enforces
  (stock checks, per-line limits). There is deliberately no checkout tool: placing an order
  and paying stay with the customer in the UI (human in the loop).
* Customer reviews are user-generated text, returned under a field name that marks them as
  untrusted, and flagged reviews are excluded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from store import services
from store.models import Category, Order
from store.selectors import annotated_products

from ..rag import retrieve
from ..search import SearchFilters, search_products

CATEGORY_SLUGS = ["electronics", "footwear", "clothing", "home-kitchen", "books", "sports-fitness"]


@dataclass
class ToolContext:
    user: Any


@dataclass
class ToolOutcome:
    content: str
    is_error: bool = False
    summary: str = ""
    products: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    cart_updated: bool = False


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def product_card(product) -> dict:
    return {
        "id": product.pk,
        "name": product.name,
        "brand": product.brand,
        "category": product.category.name,
        "price": f"{product.price:.2f}",
        "stock": product.stock,
        "avg_rating": round(product.avg_rating, 1) if getattr(product, "avg_rating", None) else None,
        "review_count": getattr(product, "review_count", 0),
    }


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------

class SearchProductsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=200, description="What the customer wants, in plain words, e.g. 'waterproof running shoes'. Do not include price limits here.")
    category: str | None = Field(default=None, description=f"Optional category slug: one of {', '.join(CATEGORY_SLUGS)}.")
    min_price: float | None = Field(default=None, ge=0, description="Optional minimum price in INR.")
    max_price: float | None = Field(default=None, ge=0, description="Optional maximum price in INR.")
    in_stock_only: bool = Field(default=False, description="Only return products that are in stock.")
    limit: int = Field(default=5, ge=1, le=10, description="Number of results (1-10).")


class ProductIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(ge=1, description="Product id from search_products results.")


class AddToCartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(ge=1, description="Product id from search_products or get_product_details results.")
    quantity: int = Field(default=1, ge=1, le=10, description="How many units to add (1-10).")


class NoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListOrdersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=5, ge=1, le=20, description="How many recent orders to return.")


class OrderIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: int = Field(ge=1, description="The order number, e.g. 12 for order #12.")


class PolicyQuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=300, description="The customer's policy question in their own words.")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _search_products(ctx: ToolContext, inp: SearchProductsInput) -> ToolOutcome:
    notes = []
    category = inp.category
    if category and not Category.objects.filter(slug=category).exists():
        notes.append(f"Unknown category '{category}' was ignored.")
        category = None
    filters = SearchFilters(
        category=category,
        min_price=Decimal(str(inp.min_price)) if inp.min_price is not None else None,
        max_price=Decimal(str(inp.max_price)) if inp.max_price is not None else None,
        in_stock_only=inp.in_stock_only,
    )
    hits = search_products(inp.query, filters, mode="hybrid", limit=inp.limit)
    results = []
    for hit in hits:
        if hit.product is None:
            continue
        card = product_card(hit.product)
        card["summary"] = hit.product.description[:200]
        card["relevance"] = hit.similarity
        results.append(card)
    payload = {"query": inp.query, "filters": filters.as_dict(), "results": results}
    if notes:
        payload["notes"] = notes
    if not results:
        payload["notes"] = notes + ["No products matched. Suggest broadening the search or removing filters."]
    return ToolOutcome(
        content=_json(payload),
        summary=f"Found {len(results)} product(s) for “{inp.query}”",
        products=[{k: v for k, v in r.items() if k not in ("summary", "relevance")} for r in results],
    )


def _get_product_details(ctx: ToolContext, inp: ProductIdInput) -> ToolOutcome:
    product = annotated_products().filter(pk=inp.product_id, is_active=True).first()
    if product is None:
        return ToolOutcome(content=_json({"error": f"No product with id {inp.product_id}."}), is_error=True, summary="Product not found")
    reviews = list(product.reviews.filter(is_flagged=False).order_by("-created_at")[:3])
    payload = {
        **product_card(product),
        "description": product.description,
        "attributes": product.attributes,
        "customer_reviews_untrusted": [{"rating": r.rating, "text": r.body[:300]} for r in reviews],
    }
    return ToolOutcome(content=_json(payload), summary=f"Looked up {product.name}", products=[product_card(product)])


def _cart_payload(user) -> dict:
    cart = services.get_cart(user)
    items = list(services.cart_items(cart))
    return {
        "items": [
            {
                "product_id": item.product_id,
                "name": item.product.name,
                "quantity": item.quantity,
                "unit_price": f"{item.product.price:.2f}",
                "line_total": f"{item.line_total:.2f}",
            }
            for item in items
        ],
        "item_count": sum(item.quantity for item in items),
        "total": f"{sum((i.line_total for i in items), Decimal('0')):.2f}",
    }


def _add_to_cart(ctx: ToolContext, inp: AddToCartInput) -> ToolOutcome:
    try:
        item = services.add_to_cart(ctx.user, inp.product_id, inp.quantity)
    except services.CartError as exc:
        return ToolOutcome(content=_json({"error": str(exc)}), is_error=True, summary=str(exc))
    product = annotated_products().get(pk=item.product_id)
    payload = {"added": {"product_id": product.pk, "name": product.name, "quantity_added": inp.quantity}, "cart": _cart_payload(ctx.user)}
    return ToolOutcome(
        content=_json(payload),
        summary=f"Added {inp.quantity} × {product.name} to cart",
        products=[product_card(product)],
        cart_updated=True,
    )


def _view_cart(ctx: ToolContext, inp: NoInput) -> ToolOutcome:
    payload = _cart_payload(ctx.user)
    return ToolOutcome(content=_json(payload), summary=f"Cart has {payload['item_count']} item(s)")


def _order_payload(order: Order, with_events: bool = False) -> dict:
    data = {
        "order_id": order.pk,
        "status": order.status,
        "total": f"{order.total:.2f}",
        "placed_on": order.created_at.date().isoformat(),
        "items": [{"name": i.product_name, "quantity": i.quantity, "unit_price": f"{i.unit_price:.2f}"} for i in order.items.all()],
    }
    if with_events:
        data["history"] = [{"status": e.status, "at": e.created_at.isoformat(timespec="minutes"), "note": e.note} for e in order.events.all()]
    return data


def _list_my_orders(ctx: ToolContext, inp: ListOrdersInput) -> ToolOutcome:
    orders = Order.objects.filter(user=ctx.user).prefetch_related("items")[: inp.limit]
    payload = {"orders": [_order_payload(o) for o in orders]}
    if not payload["orders"]:
        payload["notes"] = ["This customer has no orders yet."]
    return ToolOutcome(content=_json(payload), summary=f"Found {len(payload['orders'])} order(s)")


def _get_order_status(ctx: ToolContext, inp: OrderIdInput) -> ToolOutcome:
    # Scoped to the signed-in user: another customer's order id is indistinguishable from a missing one.
    order = Order.objects.filter(user=ctx.user, pk=inp.order_id).prefetch_related("items", "events").first()
    if order is None:
        return ToolOutcome(content=_json({"error": f"No order #{inp.order_id} on this account."}), is_error=True, summary="Order not found")
    return ToolOutcome(content=_json(_order_payload(order, with_events=True)), summary=f"Order #{order.pk} is {order.status.lower()}")


def _search_store_policies(ctx: ToolContext, inp: PolicyQuestionInput) -> ToolOutcome:
    retrieved = retrieve(inp.question, k=3)
    results = [
        {"source": f"{r.chunk.doc_title} › {r.chunk.section}", "text": r.chunk.content.split("\n", 1)[-1]}
        for r in retrieved
    ]
    sources = [
        {"doc_title": r.chunk.doc_title, "section": r.chunk.section, "excerpt": r.chunk.content.split("\n", 1)[-1][:240]}
        for r in retrieved
    ]
    return ToolOutcome(content=_json({"results": results}), summary=f"Checked {len(results)} help-center section(s)", sources=sources)


@dataclass
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[ToolContext, Any], ToolOutcome]


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool("search_products",
             "Search the ShopFlow catalog with hybrid semantic + keyword search. Use it for any request to find, "
             "recommend or compare products. Put price limits in min_price/max_price, not in the query.",
             SearchProductsInput, _search_products),
        Tool("get_product_details",
             "Get full details for one product: description, specifications, rating and recent customer reviews.",
             ProductIdInput, _get_product_details),
        Tool("add_to_cart",
             "Add a product to the signed-in customer's cart. Only call this when the customer explicitly asks to add or buy something.",
             AddToCartInput, _add_to_cart),
        Tool("view_cart", "Show the signed-in customer's cart: items, quantities and total.", NoInput, _view_cart),
        Tool("list_my_orders", "List the signed-in customer's most recent orders with status and totals.", ListOrdersInput, _list_my_orders),
        Tool("get_order_status", "Get the status and tracking history of one of the signed-in customer's orders.", OrderIdInput, _get_order_status),
        Tool("search_store_policies",
             "Search ShopFlow's help center (shipping, delivery times, returns, refunds, payments, COD, warranty, account and support). "
             "Use it for every policy question and cite the returned source names.",
             PolicyQuestionInput, _search_store_policies),
    ]
}


def _clean_schema(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _clean_schema(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_clean_schema(v) for v in node]
    return node


def tool_definitions() -> list[dict]:
    """Static tool list (same bytes every request) so the tools+system prefix is cacheable."""
    return [
        {"name": t.name, "description": t.description, "input_schema": _clean_schema(t.input_model.model_json_schema())}
        for t in TOOLS.values()
    ]


def execute_tool(name: str, raw_input: Any, ctx: ToolContext) -> ToolOutcome:
    tool = TOOLS.get(name)
    if tool is None:
        return ToolOutcome(content=_json({"error": f"Unknown tool {name}."}), is_error=True, summary=f"Unknown tool {name}")
    try:
        parsed = tool.input_model.model_validate(raw_input if isinstance(raw_input, dict) else {})
    except ValidationError as exc:
        errors = [{"field": ".".join(str(p) for p in e["loc"]), "problem": e["msg"]} for e in exc.errors()]
        return ToolOutcome(content=_json({"error": "Invalid tool input", "details": errors}), is_error=True, summary="Invalid tool input")
    try:
        return tool.handler(ctx, parsed)
    except Exception as exc:  # a failing tool must not crash the conversation
        return ToolOutcome(content=_json({"error": f"{name} failed: {type(exc).__name__}"}), is_error=True, summary=f"{name} failed")
