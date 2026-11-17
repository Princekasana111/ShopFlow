"""Admin tool: generate product copy from catalog facts with structured outputs.

The generated copy is checked against the source facts: any number in the copy that is not
in the facts (e.g. an invented "40-hour battery") is returned as a warning so the admin
reviews it before publishing. Nothing is saved automatically.
"""

from __future__ import annotations

import json
from typing import Literal

from django.conf import settings
from pydantic import BaseModel, ConfigDict, Field

from . import guardrails
from .llm import get_llm

Tone = Literal["friendly", "premium", "concise"]


class ProductCopy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(description="Catchy one-line headline, at most 80 characters.")
    description: str = Field(description="Product description of 60-120 words in plain prose, built only from the facts.")
    highlights: list[str] = Field(description="3 to 5 short bullet points, each grounded in the facts.")
    tags: list[str] = Field(description="3 to 8 lowercase search tags.")
    seo_meta_description: str = Field(description="Search-engine meta description, at most 160 characters.")


SYSTEM_PROMPT = """You are a copywriter for ShopFlow, an Indian online store. Write product copy using only the facts provided.
- Do not invent specifications, numbers, certifications, awards or comparisons that are not in the facts.
- Do not mention the price or discounts (prices change; the page shows them separately).
- Write for Indian shoppers in clear, simple English."""

TONE_GUIDE = {
    "friendly": "Warm and conversational.",
    "premium": "Polished and understated, focused on quality and craftsmanship.",
    "concise": "Direct and to the point; shortest reasonable sentences.",
}


def product_facts(product) -> dict:
    return {
        "name": product.name,
        "brand": product.brand,
        "category": product.category.name,
        "current_description": product.description,
        "attributes": product.attributes,
    }


def _offline_copy(product) -> ProductCopy:
    attributes = product.attributes or {}
    highlights = [f"{k.replace('_', ' ').capitalize()}: {v}" for k, v in list(attributes.items())[:5]]
    fillers = [f"Brand: {product.brand}" if product.brand else None, f"Category: {product.category.name}", "Easy returns as per store policy"]
    for filler in fillers:
        if len(highlights) >= 3:
            break
        if filler:
            highlights.append(filler)
    first_sentence = product.description.split(". ")[0].rstrip(".") + "."
    return ProductCopy(
        headline=f"{product.name}"[:80],
        description=product.description,
        highlights=highlights[:5],
        tags=sorted({w.lower() for w in [product.category.name, product.brand, *product.name.split()[:3]] if w and len(w) > 2})[:8],
        seo_meta_description=f"Buy {product.name} online at ShopFlow. {first_sentence}"[:160],
    )


def generate_copy(product, tone: Tone = "friendly", user=None) -> dict:
    facts = product_facts(product)
    facts_json = json.dumps(facts, ensure_ascii=False, indent=2)
    llm = get_llm()
    result = llm.parse(
        feature="copywriter",
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Tone: {TONE_GUIDE[tone]}\n\nProduct facts (JSON):\n{facts_json}"}],
        schema=ProductCopy,
        offline=lambda: _offline_copy(product),
        max_tokens=settings.AI["MAX_TOKENS_STRUCTURED"],
        effort=settings.AI["EFFORT_STRUCTURED"],
        user=user,
    )
    copy = result.value
    generated_text = " ".join([copy.headline, copy.description, *copy.highlights, copy.seo_meta_description])
    unverified = guardrails.find_ungrounded_numbers(generated_text, facts_json)
    if unverified:
        guardrails.record_event("ungrounded_number", user=user, excerpt=copy.description, product_id=product.pk, numbers=unverified)
    return {
        "product_id": product.pk,
        "tone": tone,
        "copy": copy.model_dump(),
        "warnings": [f"'{n}' does not appear in the product facts; verify it before publishing." for n in unverified],
        "provider": result.provider,
        "model": result.model,
    }
