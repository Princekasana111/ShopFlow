"""Keeps the vector index in sync with the catalog."""

from __future__ import annotations

import contextlib
import contextvars
import logging

from django.conf import settings

from .embeddings import content_hash, get_embedder
from .models import ProductEmbedding

logger = logging.getLogger(__name__)

_auto_embed_suspended = contextvars.ContextVar("auto_embed_suspended", default=False)


@contextlib.contextmanager
def suspend_auto_embed():
    """Bulk imports turn off per-save embedding and call embed_products() once at the end."""
    token = _auto_embed_suspended.set(True)
    try:
        yield
    finally:
        _auto_embed_suspended.reset(token)


def auto_embed_enabled() -> bool:
    return settings.AI["AUTO_EMBED_ON_SAVE"] and not _auto_embed_suspended.get()


def product_document(product) -> str:
    """The text that represents a product in vector space.

    Name, brand and category come first because they carry the most signal; attributes
    are flattened to "key: value" pairs so specs such as "waterproof: yes" are searchable.
    """
    # Sizes are a buying option, not what the product is; leaving them out keeps search unchanged.
    attributes = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in sorted((product.attributes or {}).items()) if k != "sizes")
    parts = [
        product.name,
        f"Brand: {product.brand}" if product.brand else "",
        f"Category: {product.category.name}",
        product.description,
        f"Attributes: {attributes}" if attributes else "",
    ]
    return "\n".join(p for p in parts if p)


def embed_products(products, force: bool = False) -> dict:
    """Embed products whose text changed since the last run. Returns counts."""
    embedder = get_embedder()
    products = list(products)
    existing = {
        e.product_id: e
        for e in ProductEmbedding.objects.filter(product_id__in=[p.pk for p in products])
    }
    todo = []
    for product in products:
        document = product_document(product)
        digest = content_hash(document, embedder.name)
        record = existing.get(product.pk)
        if force or record is None or record.content_hash != digest:
            todo.append((product, document, digest))

    if todo:
        vectors = embedder.embed_documents([doc for _, doc, _ in todo])
        for (product, _, digest), vector in zip(todo, vectors):
            ProductEmbedding.objects.update_or_create(
                product=product,
                defaults={"vector": vector, "content_hash": digest, "model_name": embedder.name},
            )
    return {"embedded": len(todo), "skipped": len(products) - len(todo), "model": embedder.name}


def embed_product_safely(product_id: int) -> None:
    from store.models import Product

    from .visual import embed_products_visual

    try:
        product = Product.objects.select_related("category").get(pk=product_id)
        embed_products([product])
        embed_products_visual([product])
    except Exception:  # never block a catalog edit because the embedding step failed
        logger.exception("Embedding product %s failed; run `manage.py embed_catalog` to retry", product_id)
