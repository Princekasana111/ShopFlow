"""Rule-based "brain" for the offline provider.

Maps a customer message to tool calls with regular expressions, then writes a templated
answer from the tool results. It exists so the assistant works with no API key and so tests
are deterministic. It is also the baseline the agent eval compares Claude against.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from ..query_understanding import heuristic_parse

POLICY_RE = re.compile(
    r"\b(return|returns|refund|refunds|exchange|shipping|ship|delivery|deliver|delivered|warranty|guarantee|payment|payments|pay|"
    r"cod|cash on delivery|emi|upi|invoice|gst|cancel|cancellation|privacy|support|contact|policy|policies)\b",
    re.I,
)
ADD_RE = re.compile(r"\b(add|put)\b.*\b(cart|basket)\b|\bbuy\b", re.I)
CART_RE = re.compile(r"\b(cart|basket)\b", re.I)
ORDER_ID_RE = re.compile(r"\border\s*(?:#|no\.?|number)?\s*(\d+)\b", re.I)
ORDERS_RE = re.compile(r"\b(my orders?|recent orders?|order status|track|tracking|where is my)\b", re.I)
PRODUCT_ID_RE = re.compile(r"\bproduct\s*(?:#|id)?\s*(\d+)\b", re.I)
QTY_RE = re.compile(r"\b(?:add|buy|put)\s+(\d{1,2})\b|\b(\d{1,2})\s*(?:x|pcs|pieces|units)\b", re.I)
FILLER_RE = re.compile(r"\b(add|put|buy|to|in|into|my|the|a|an|me|one|please|cart|basket|cheapest|some|for|i|want|would|like)\b", re.I)


def _blocks(message: dict) -> list[dict]:
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return list(content or [])


def _current_turn(messages: list[dict]) -> tuple[str, list[dict]]:
    for i in range(len(messages) - 1, -1, -1):
        message = messages[i]
        if message["role"] == "user":
            texts = [b["text"] for b in _blocks(message) if b.get("type") == "text"]
            if texts:
                return " ".join(texts), messages[i + 1:]
    return "", []


def _calls_this_turn(rest: list[dict]) -> list[dict]:
    """[{name, input, result (parsed JSON or None), is_error}] in call order."""
    results = {}
    for message in rest:
        if message["role"] == "user":
            for b in _blocks(message):
                if b.get("type") == "tool_result":
                    try:
                        parsed = json.loads(b.get("content") or "null")
                    except (TypeError, json.JSONDecodeError):
                        parsed = None
                    results[b["tool_use_id"]] = (parsed, bool(b.get("is_error")))
    calls = []
    for message in rest:
        if message["role"] == "assistant":
            for b in _blocks(message):
                if b.get("type") == "tool_use":
                    parsed, is_error = results.get(b["id"], (None, False))
                    calls.append({"name": b["name"], "input": b.get("input", {}), "result": parsed, "is_error": is_error})
    return calls


def _stems(text: str) -> set[str]:
    """Lower-cased words with a trailing plural 's' removed ("mats" -> "mat")."""
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"[a-z0-9]+", text.lower())}


def _tool_use(name: str, tool_input: dict) -> dict:
    return {"type": "tool_use", "id": f"toolu_offline_{uuid.uuid4().hex[:16]}", "name": name, "input": tool_input}


def classify(text: str) -> tuple[str, dict]:
    """Return (intent, first tool input)."""
    if ADD_RE.search(text):
        query = re.sub(r"\s+", " ", FILLER_RE.sub(" ", QTY_RE.sub(" ", text))).strip(" ,.") or text
        return "add_to_cart", {"query": query, "limit": 5}
    if CART_RE.search(text):
        return "view_cart", {}
    if m := ORDER_ID_RE.search(text):
        return "get_order_status", {"order_id": int(m.group(1))}
    if ORDERS_RE.search(text):
        return "list_my_orders", {"limit": 5}
    if POLICY_RE.search(text):
        return "search_store_policies", {"question": text[:300]}
    if m := PRODUCT_ID_RE.search(text):
        return "get_product_details", {"product_id": int(m.group(1))}
    intent = heuristic_parse(text, {"electronics", "footwear", "clothing", "home-kitchen", "books", "sports-fitness"})
    tool_input = {"query": intent.semantic_query[:200] or text[:200], "limit": 5}
    if intent.max_price is not None:
        tool_input["max_price"] = intent.max_price
    if intent.min_price is not None:
        tool_input["min_price"] = intent.min_price
    if intent.category_slug:
        tool_input["category"] = intent.category_slug
    if intent.in_stock_only:
        tool_input["in_stock_only"] = True
    return "search_products", tool_input


def _price(value: str) -> str:
    amount = float(value)
    return f"₹{amount:,.0f}" if amount == int(amount) else f"₹{amount:,.2f}"


def _compose(text: str, calls: list[dict]) -> str:
    last = calls[-1]
    data = last["result"] or {}
    if last["is_error"]:
        return f"Sorry, I couldn't do that: {data.get('error', 'something went wrong')}."

    name = last["name"]
    if name == "search_products":
        results = data.get("results", [])
        if not results:
            return "I couldn't find products matching that. Try different words or a wider price range."
        lines = [f"- **{p['name']}** ({p['brand']}) — {_price(p['price'])}" + (f", {p['avg_rating']}★" if p.get("avg_rating") else "") for p in results]
        return f"Here are {len(results)} options I found:\n" + "\n".join(lines) + "\n\nWant me to add one of these to your cart?"
    if name == "get_product_details":
        rating = f" Rated {data['avg_rating']}★ by {data['review_count']} customers." if data.get("avg_rating") else ""
        stock = "In stock." if data.get("stock", 0) > 0 else "Currently out of stock."
        return f"**{data['name']}** by {data['brand']} costs {_price(data['price'])}. {stock}{rating}\n\n{data['description']}"
    if name == "add_to_cart":
        cart = data["cart"]
        return (f"Added {data['added']['quantity_added']} × **{data['added']['name']}** to your cart. "
                f"Your cart now has {cart['item_count']} item(s), total {_price(cart['total'])}. "
                "Review it on the Cart page when you're ready to check out.")
    if name == "view_cart":
        if not data.get("items"):
            return "Your cart is empty."
        lines = [f"- {i['quantity']} × {i['name']} — {_price(i['line_total'])}" for i in data["items"]]
        return "Your cart:\n" + "\n".join(lines) + f"\n\nTotal: {_price(data['total'])}. Check out from the Cart page."
    if name == "list_my_orders":
        orders = data.get("orders", [])
        if not orders:
            return "You haven't placed any orders yet."
        lines = [f"- Order #{o['order_id']} — {o['status'].title()} — {_price(o['total'])} (placed {o['placed_on']})" for o in orders]
        return "Your recent orders:\n" + "\n".join(lines)
    if name == "get_order_status":
        latest = data["history"][-1] if data.get("history") else None
        when = f" (updated {latest['at'][:10]})" if latest else ""
        return f"Order #{data['order_id']} is **{data['status'].title()}**{when}. Total {_price(data['total'])}."
    if name == "search_store_policies":
        results = data.get("results", [])
        if not results:
            return "I couldn't find that in our help center. Please contact ShopFlow support."
        top = results[0]
        sentences = re.split(r"(?<=[.!?])\s+", top["text"].strip())
        return " ".join(sentences[:3]) + f" [{top['source']}]"
    return "Done."


def decide_next_turn(messages: list[dict], tools: list[dict]) -> list[dict]:
    text, rest = _current_turn(messages)
    calls = _calls_this_turn(rest)
    intent, first_input = classify(text)

    if not calls:
        tool = "search_products" if intent == "add_to_cart" else intent
        return [_tool_use(tool, first_input)]

    last = calls[-1]
    if intent == "add_to_cart" and last["name"] == "search_products" and not last["is_error"]:
        results = (last["result"] or {}).get("results", [])
        if results:
            if re.search(r"\bcheapest\b", text, re.I):
                # Cheapest among the results that actually match what was asked for, so
                # "the cheapest yoga mat" can't pick a cheaper book that merely ranked nearby.
                wanted = _stems(last["input"].get("query", ""))
                matching = [p for p in results if wanted and wanted <= _stems(p["name"])] or results[:1]
                choice = min(matching, key=lambda p: float(p["price"]))
            else:
                choice = results[0]
            qty_match = QTY_RE.search(text)
            quantity = int(next(g for g in qty_match.groups() if g)) if qty_match else 1
            return [_tool_use("add_to_cart", {"product_id": choice["id"], "quantity": max(1, min(quantity, 10))})]

    return [{"type": "text", "text": _compose(text, calls)}]
