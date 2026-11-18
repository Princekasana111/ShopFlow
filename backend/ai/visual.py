"""Snap & Search: find products from a photo.

Two signals, fused with Reciprocal Rank Fusion:

1. CLIP (always, free, local). The CLIP vision model embeds the photo and the CLIP text model
   embeds every product ("a photo of <name>, a <category> product") into one shared vector
   space, so a photo can be matched against product *text* with no product images and no
   training (zero-shot). On 8 labelled photos it put the right product first 7 times; the
   smaller nomic-embed-vision model managed 6 (see README).
2. Claude vision (when an API key is set). Claude describes the photo as a structured search
   query (product type, category, key attributes) and that query runs through hybrid search.

If Claude is unavailable the CLIP results are returned on their own.
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
import threading
import time
from functools import lru_cache

from django.conf import settings
from pgvector.django import CosineDistance
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from store.models import Category, Product
from store.selectors import annotated_products

from .embeddings import content_hash
from .llm import LLMError, get_llm
from .models import ProductVisualEmbedding
from .search import SearchFilters, hybrid_weights, rrf_fuse, search_products

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_PIXELS = 40_000_000  # refuse decompression bombs before decoding
CLAUDE_MAX_SIDE = 768    # downscale before sending to Claude: fewer image tokens, same accuracy for this task

CATEGORY_PHRASE = {
    "electronics": "electronics", "footwear": "footwear", "clothing": "clothing",
    "home-kitchen": "home and kitchen", "books": "book", "sports-fitness": "sports and fitness",
}


class ImageRejected(ValueError):
    """The upload is not an acceptable image. The message is safe to show to the user."""


def load_image(data: bytes) -> Image.Image:
    if len(data) > settings.AI["MAX_UPLOAD_BYTES"]:
        raise ImageRejected("Image is larger than 5 MB.")
    try:
        image = Image.open(io.BytesIO(data))
        if image.format not in ALLOWED_FORMATS:
            raise ImageRejected("Upload a JPEG, PNG or WebP image.")
        if image.width * image.height > MAX_PIXELS:
            raise ImageRejected("Image dimensions are too large.")
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ImageRejected("That file is not a readable image.")
    return image.convert("RGB")


# ---------------------------------------------------------------------------
# Encoders
# ---------------------------------------------------------------------------

class ClipEncoder:
    def __init__(self, vision_model: str, text_model: str, cache_dir: str):
        from fastembed import ImageEmbedding, TextEmbedding

        self.name = f"{vision_model}+{text_model}"
        self._vision = ImageEmbedding(vision_model, cache_dir=cache_dir)
        self._text = TextEmbedding(text_model, cache_dir=cache_dir)
        self._lock = threading.Lock()

    def embed_image(self, image: Image.Image) -> list[float]:
        with self._lock:
            return next(iter(self._vision.embed([image]))).tolist()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            return [v.tolist() for v in self._text.embed(texts)]


class HashClip:
    """Deterministic stand-in for the test suite (no model download)."""

    name = "hash-clip-v1"

    def __init__(self, dim: int):
        self.dim = dim

    def _vec(self, seed: bytes) -> list[float]:
        values = []
        counter = 0
        while len(values) < self.dim:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "little")).digest()
            values.extend((b - 127.5) / 127.5 for b in digest)
            counter += 1
        values = values[: self.dim]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]

    def embed_image(self, image: Image.Image) -> list[float]:
        return self._vec(image.tobytes()[:4096])

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t.encode()) for t in texts]


def visual_enabled() -> bool:
    return settings.AI["VISUAL_PROVIDER"] != "off"


@lru_cache(maxsize=1)
def get_clip():
    cfg = settings.AI
    if cfg["VISUAL_PROVIDER"] == "hash":
        return HashClip(dim=cfg["CLIP_DIM"])
    return ClipEncoder(cfg["CLIP_VISION_MODEL"], cfg["CLIP_TEXT_MODEL"], cfg["FASTEMBED_CACHE_DIR"])


def product_visual_text(product) -> str:
    phrase = CATEGORY_PHRASE.get(product.category.slug, product.category.name.lower())
    return f"a photo of {product.name}, a {phrase} product"


def embed_products_visual(products, force: bool = False) -> dict:
    if not visual_enabled():
        return {"embedded": 0, "skipped": 0, "model": "off"}
    clip = get_clip()
    products = list(products)
    existing = {e.product_id: e for e in ProductVisualEmbedding.objects.filter(product_id__in=[p.pk for p in products])}
    todo = []
    for product in products:
        text = product_visual_text(product)
        digest = content_hash(text, clip.name)
        record = existing.get(product.pk)
        if force or record is None or record.content_hash != digest:
            todo.append((product, text, digest))
    if todo:
        for (product, _, digest), vector in zip(todo, clip.embed_texts([t for _, t, _ in todo])):
            ProductVisualEmbedding.objects.update_or_create(
                product=product, defaults={"vector": vector, "content_hash": digest, "model_name": clip.name}
            )
    return {"embedded": len(todo), "skipped": len(products) - len(todo), "model": clip.name}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class VisualQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_product: bool = Field(description="False if the photo does not show something a shop could sell.")
    description: str = Field(description="One short sentence describing what the photo shows.")
    search_query: str = Field(description="A product search query for this item, e.g. 'white electric kettle'. Empty if not a product.")
    category_slug: str | None = Field(description="Best matching category slug from the provided list, or null.")


VISION_PROMPT = """You help shoppers find products from a photo at ShopFlow, an Indian online store.
Identify the main item in the photo and write a short product search query for it (product type plus 1-3 visible attributes such as colour or material).
Pick a category only from the provided list. If the photo doesn't show a shoppable item, set is_product to false."""


def clip_rank(image: Image.Image, limit: int = 20) -> list[tuple[int, float]]:
    vector = get_clip().embed_image(image)
    rows = (
        Product.objects.filter(is_active=True, visual_record__isnull=False)
        .annotate(distance=CosineDistance("visual_record__vector", vector))
        .order_by("distance", "id")
        .values_list("id", "distance")[:limit]
    )
    return [(pid, 1.0 - float(d)) for pid, d in rows]


def understand_photo(image: Image.Image, user=None) -> tuple[VisualQuery | None, dict]:
    """Claude vision -> structured query. Returns (None, meta) when no model that can see is available
    (the local model has no vision, so photo search then uses CLIP alone)."""
    llm = get_llm()
    if not llm.supports_vision:
        return None, {"provider": llm.name, "model": llm.model}
    small = image.copy()
    small.thumbnail((CLAUDE_MAX_SIDE, CLAUDE_MAX_SIDE))
    buffer = io.BytesIO()
    small.save(buffer, format="JPEG", quality=85)
    categories = "\n".join(f"- {slug}: {name}" for slug, name in Category.objects.values_list("slug", "name"))
    empty = VisualQuery(is_product=False, description="", search_query="", category_slug=None)
    try:
        result = llm.parse(
            feature="visual_search",
            system=VISION_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(buffer.getvalue()).decode()}},
                    {"type": "text", "text": f"Categories:\n{categories}\n\nWhat product is this, and how should I search for it?"},
                ],
            }],
            schema=VisualQuery,
            offline=lambda: empty,
            max_tokens=settings.AI["MAX_TOKENS_STRUCTURED"],
            effort=settings.AI["EFFORT_STRUCTURED"],
            user=user,
        )
    except LLMError:
        return None, {"provider": "offline", "model": "clip-only (fallback)"}
    query = result.value
    if result.provider == "offline" or not query.search_query.strip():
        return None, {"provider": result.provider, "model": result.model}
    if query.category_slug and not Category.objects.filter(slug=query.category_slug).exists():
        query.category_slug = None
    return query, {"provider": result.provider, "model": result.model}


def visual_search(data: bytes, user=None, limit: int = 12) -> dict:
    started = time.perf_counter()
    image = load_image(data)
    clip_hits = clip_rank(image)
    clip_rank_of = {pid: i for i, (pid, _) in enumerate(clip_hits, start=1)}
    clip_sim = dict(clip_hits)

    understood, meta = understand_photo(image, user=user)
    text_rank_of: dict[int, int] = {}
    if understood and understood.is_product:
        text_hits = search_products(understood.search_query, SearchFilters(category=understood.category_slug), limit=20, attach_products=False)
        text_rank_of = {h.product_id: i for i, h in enumerate(text_hits, start=1)}
        ranked = rrf_fuse([[pid for pid, _ in clip_hits], [h.product_id for h in text_hits]], weights=[1.0, hybrid_weights()[1]])
        method = "claude+clip"
    else:
        ranked = [(pid, sim) for pid, sim in clip_hits]
        method = "clip"

    ids = [pid for pid, _ in ranked[:limit]]
    products = annotated_products().in_bulk(ids)
    from store.serializers import ProductListSerializer  # local import keeps ai -> store dependency one-way at import time

    results = []
    for pid in ids:
        if pid not in products:
            continue
        row = ProductListSerializer(products[pid]).data
        row["match"] = {"clip_rank": clip_rank_of.get(pid), "clip_similarity": round(clip_sim[pid], 4) if pid in clip_sim else None, "text_rank": text_rank_of.get(pid)}
        results.append(row)
    top_clip = clip_hits[0][1] if clip_hits else 0.0
    low_confidence = (understood is not None and not understood.is_product) or (understood is None and top_clip < settings.AI["CLIP_LOW_CONFIDENCE"])
    return {
        "method": method,
        "low_confidence": low_confidence,
        "understood": understood.model_dump() if understood else None,
        "provider": meta["provider"],
        "model": meta["model"],
        "results": results,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }
