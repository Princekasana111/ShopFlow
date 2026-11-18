"""Why isn't this in my results? Explains, from the search's own numbers, why one product is missing
from a search, and what would bring it in.

No LLM writes the explanation. It re-runs the same pipeline that produced the results (query
understanding, filters, keyword and meaning retrieval, rank fusion) and reports where the product
dropped out: a filter it fails (with the price, category or stock that failed it), or the rank it
reached against the number of results shown, with the signals behind that rank. A suggested fix is
only offered after it has been tried: the search is re-run with the fix and the product must then
appear in the results.
"""

from __future__ import annotations

import re
from decimal import Decimal

from store.models import Category, Product

from .negotiation import rupees
from .query_understanding import plan_search
from .search import CANDIDATES_PER_RETRIEVER, SearchFilters, search_products

MAX_LIMIT = 30
_TERM_RE = re.compile(r"[a-z0-9]+")
_STOP = set("a an the and or for to of in on with my me i is are it this that something some any very good best under over above below".split())


def _rank(query: str, filters: SearchFilters, mode: str, product_id: int):
    hits = search_products(query, filters, mode=mode, limit=2 * CANDIDATES_PER_RETRIEVER, attach_products=False)
    for i, hit in enumerate(hits, start=1):
        if hit.product_id == product_id:
            return i, hit, hits
    return None, None, hits


def _words(product: Product) -> set[str]:
    text = " ".join([product.name, product.brand, product.category.name, product.description,
                     " ".join(f"{k} {v}" for k, v in (product.attributes or {}).items())]).lower()
    return set(_TERM_RE.findall(text))


def _stem(word: str) -> str:
    return word[:5] if len(word) > 5 else word


def word_overlap(query: str, product: Product) -> tuple[list[str], list[str]]:
    terms = [t for t in dict.fromkeys(_TERM_RE.findall(query.lower())) if len(t) > 1 and t not in _STOP]
    have = {_stem(w) for w in _words(product)}
    matched = [t for t in terms if _stem(t) in have]
    return matched, [t for t in terms if t not in matched]


def filter_failures(product: Product, filters: SearchFilters, explicit_category: bool) -> list[dict]:
    out = []
    if filters.category and product.category.slug != filters.category:
        wanted = Category.objects.filter(slug=filters.category).values_list("name", flat=True).first() or filters.category
        how = "you picked the" if explicit_category else "your search was read as"
        out.append({"code": "category", "title": "Different category",
                    "detail": f"It's in {product.category.name}, and {how} {wanted} category.",
                    "fix": {"category": ""} if explicit_category else {"ignore": "category"}})
    if filters.max_price is not None and product.price > filters.max_price:
        out.append({"code": "over_budget", "title": "Over your budget",
                    "detail": f"It costs {rupees(product.price)}, more than your {rupees(filters.max_price)} limit.", "fix": {"ignore": "budget"}})
    if filters.min_price is not None and product.price < filters.min_price:
        out.append({"code": "under_minimum", "title": "Below your minimum price",
                    "detail": f"It costs {rupees(product.price)}, less than your {rupees(filters.min_price)} minimum.", "fix": {"ignore": "budget"}})
    if filters.in_stock_only and product.stock <= 0:
        out.append({"code": "out_of_stock", "title": "Out of stock",
                    "detail": "It's sold out, and you asked for things in stock.", "fix": {"ignore": "stock"}})
    return out


def _fix_label(failures: list[dict]) -> str:
    codes = {f["code"] for f in failures}
    parts = []
    if codes & {"over_budget", "under_minimum"}:
        parts.append("the budget")
    if "category" in codes:
        parts.append("the category")
    if "out_of_stock" in codes:
        parts.append("the in-stock filter")
    return "Search again without " + " and ".join(parts)


def explain(query: str, product: Product, *, mode: str = "hybrid", limit: int = 12, parse: bool = True,
            category: str | None = None, min_price: Decimal | None = None, max_price: Decimal | None = None,
            in_stock: bool = False, ignore=(), user=None) -> dict:
    limit = max(1, min(limit, MAX_LIMIT))
    ignore = tuple(ignore)
    plan = dict(parse=parse, category=category, min_price=min_price, max_price=max_price, in_stock=in_stock, user=user)
    intent, _meta, semantic, filters = plan_search(query, ignore=ignore, **plan)
    base = {"query": query, "semantic_query": semantic, "mode": mode, "filters": filters.as_dict(), "ignored": list(ignore),
            "shown_limit": limit, "product_id": product.pk, "product": product.name}

    if not product.is_active:
        return {**base, "status": "unavailable", "rank": None, "headline": f"{product.name} isn't on sale right now.",
                "reasons": [{"code": "inactive", "title": "Not on sale", "detail": "The store has taken it off the shelves."}], "signals": {}, "fix": None}

    rank, hit, hits = _rank(semantic, filters, mode, product.pk)
    matched, missing = word_overlap(semantic, product)
    if rank is not None and rank <= limit:
        return {**base, "status": "shown", "rank": rank, "headline": f"It's already in your results, at #{rank}.",
                "reasons": [], "signals": _signals(hit, hits, limit, matched, missing), "fix": None}

    failures = filter_failures(product, filters, explicit_category=bool(category))
    if failures:
        added = {f["fix"]["ignore"] for f in failures if "ignore" in f["fix"]}
        new_ignore = tuple(sorted(set(ignore) | added))
        new_plan = dict(plan)
        if any("category" in f["fix"] for f in failures):
            new_plan["category"] = None
        if "budget" in added:
            new_plan["min_price"] = new_plan["max_price"] = None
        if "stock" in added:
            new_plan["in_stock"] = False
        _, _, semantic2, filters2 = plan_search(query, ignore=new_ignore, **new_plan)
        rank2, _, _ = _rank(semantic2, filters2, mode, product.pk)
        works = rank2 is not None and rank2 <= limit
        params = {"ignore": ",".join(new_ignore)} if new_ignore else {}
        if new_plan["category"] is None and category:
            params["category"] = ""
        reasons = [{k: f[k] for k in ("code", "title", "detail")} for f in failures]
        if not works:  # be honest: removing the filter wouldn't bring it in either
            reasons.append({"code": "still_low", "title": "Not a close match either",
                            "detail": (f"Even without that filter it would only be #{rank2}, below the top {limit}." if rank2
                                       else "Even without that filter it isn't a close match for your words.")})
        return {**base, "status": "filtered", "rank": None,
                "headline": f"A filter on your search leaves out {product.name}.",
                "reasons": reasons,
                "signals": {"matched_words": matched, "missing_words": missing},
                "fix": {"label": _fix_label(failures), "params": params, "rank_after": rank2, "works": works} if works else None,
                "rank_without_filter": rank2}

    reasons = []
    if rank is None:
        status = "not_matched"
        headline = f"{product.name} isn't close enough to what you searched for."
        reasons.append({"code": "no_match", "title": "Not a close match",
                        "detail": f"It isn't among the {CANDIDATES_PER_RETRIEVER} closest matches "
                                  + {"keyword": "by words.", "vector": "by meaning."}.get(mode, "by meaning or by words.")})
    else:
        status = "ranked_low"
        headline = f"It's at #{rank}, and the page shows the top {limit}."
        reasons.append({"code": "ranked_low", "title": "Ranked below the cut-off", "detail": headline})
    signals = _signals(hit, hits, limit, matched, missing)
    if signals.get("similarity") is not None and signals.get("last_shown_similarity") is not None:
        reasons.append({"code": "meaning", "title": "Meaning match",
                        "detail": f"By meaning it's #{signals['vector_rank']} (similarity {signals['similarity']:.2f}; the last result shown has {signals['last_shown_similarity']:.2f})."})
    if mode != "vector":
        if matched:
            reasons.append({"code": "words", "title": "Words in common", "detail": f"Its listing mentions {', '.join(matched)}" + (f", but not {', '.join(missing)}." if missing else ".")})
        elif missing:
            reasons.append({"code": "words", "title": "No words in common", "detail": f"Its listing doesn't mention {', '.join(missing)}."})
    fix = None
    if rank is not None and limit < rank <= MAX_LIMIT:
        fix = {"label": f"Show the top {MAX_LIMIT} results", "params": {"limit": MAX_LIMIT}, "rank_after": rank, "works": True}
    elif mode != "hybrid":
        rank2, _, _ = _rank(semantic, filters, "hybrid", product.pk)
        if rank2 is not None and rank2 <= limit:
            fix = {"label": "Switch to Hybrid AI search", "params": {"mode": "hybrid"}, "rank_after": rank2, "works": True}
    return {**base, "status": status, "rank": rank, "headline": headline, "reasons": reasons, "signals": signals, "fix": fix}


def _signals(hit, hits, limit: int, matched: list[str], missing: list[str]) -> dict:
    shown = hits[:limit]
    last_sim = next((h.similarity for h in reversed(shown) if h.similarity is not None), None)
    return {
        "fused_rank": next((i for i, h in enumerate(hits, start=1) if hit is not None and h.product_id == hit.product_id), None),
        "keyword_rank": hit.keyword_rank if hit else None,
        "vector_rank": hit.vector_rank if hit else None,
        "similarity": hit.similarity if hit else None,
        "last_shown_similarity": last_sim,
        "matched_words": matched,
        "missing_words": missing,
    }
