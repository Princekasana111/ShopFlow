import uuid

from django.conf import settings
from django.db import models
from pgvector.django import HnswIndex, VectorField

EMBEDDING_DIM = settings.AI["EMBEDDING_DIM"]


class ProductEmbedding(models.Model):
    """Vector representation of a product, kept in sync by signals (see ai/signals.py)."""

    product = models.OneToOneField("store.Product", on_delete=models.CASCADE, related_name="embedding_record")
    vector = VectorField(dimensions=EMBEDDING_DIM)
    # SHA-256 of the embedded text + model name: unchanged products are never re-embedded.
    content_hash = models.CharField(max_length=64)
    model_name = models.CharField(max_length=100)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            HnswIndex(
                name="product_embedding_hnsw",
                fields=["vector"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            )
        ]


class ProductVisualEmbedding(models.Model):
    """CLIP text embedding of a product. Photos are embedded into the same space by the CLIP
    vision model, so a customer's photo can be matched against product text (zero-shot)."""

    product = models.OneToOneField("store.Product", on_delete=models.CASCADE, related_name="visual_record")
    vector = VectorField(dimensions=settings.AI["CLIP_DIM"])
    content_hash = models.CharField(max_length=64)
    model_name = models.CharField(max_length=100)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            HnswIndex(name="product_visual_hnsw", fields=["vector"], m=16, ef_construction=64, opclasses=["vector_cosine_ops"])
        ]


class KnowledgeChunk(models.Model):
    """A section of a help-center document, embedded for retrieval-augmented generation."""

    doc_slug = models.SlugField(max_length=100)
    doc_title = models.CharField(max_length=200)
    section = models.CharField(max_length=200)
    chunk_index = models.PositiveIntegerField()
    content = models.TextField()
    vector = VectorField(dimensions=EMBEDDING_DIM)
    content_hash = models.CharField(max_length=64)
    model_name = models.CharField(max_length=100)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["doc_slug", "chunk_index"]
        constraints = [models.UniqueConstraint(fields=["doc_slug", "chunk_index"], name="unique_chunk_position")]
        indexes = [
            HnswIndex(
                name="knowledge_chunk_hnsw",
                fields=["vector"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            )
        ]

    def __str__(self):
        return f"{self.doc_title} › {self.section} [{self.chunk_index}]"


class ChatSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_sessions")
    title = models.CharField(max_length=120, blank=True)
    # A session is pinned to the provider/model that started it so the replayed history
    # (including Claude's thinking blocks) always goes back to a model that can read it.
    provider = models.CharField(max_length=30)
    model = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class ChatMessage(models.Model):
    """One message of a conversation, stored exactly as sent to / received from the model.

    `content` holds the raw content blocks and is replayed verbatim on the next turn
    (append-only history: required for Claude's preserved thinking and prompt caching).
    `display` holds what the UI shows (text, product cards, citations).
    """

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    seq = models.PositiveIntegerField()
    role = models.CharField(max_length=10, choices=[("user", "user"), ("assistant", "assistant")])
    content = models.JSONField()
    display = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["seq"]
        constraints = [models.UniqueConstraint(fields=["session", "seq"], name="unique_message_seq")]


class LLMCall(models.Model):
    """Observability: one row per LLM request (tokens, latency, estimated cost, outcome)."""

    class Status(models.TextChoices):
        OK = "ok"
        ERROR = "error"
        REFUSAL = "refusal"

    feature = models.CharField(max_length=40, db_index=True)
    provider = models.CharField(max_length=30)
    model = models.CharField(max_length=100)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OK)
    stop_reason = models.CharField(max_length=30, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_creation_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    fallback_used = models.BooleanField(default=False)
    request_id = models.CharField(max_length=100, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class GuardrailEvent(models.Model):
    class Kind(models.TextChoices):
        PROMPT_INJECTION = "prompt_injection"
        INPUT_TOO_LONG = "input_too_long"
        REVIEW_FLAGGED = "review_flagged"
        UNGROUNDED_PRICE = "ungrounded_price"
        UNGROUNDED_NUMBER = "ungrounded_number"
        TOOL_INPUT_INVALID = "tool_input_invalid"
        MAX_TOOL_ROUNDS = "max_tool_rounds"

    kind = models.CharField(max_length=30, choices=Kind.choices, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    excerpt = models.CharField(max_length=300, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class ReviewSummary(models.Model):
    """Cached AI summary of a product's reviews; regenerated when the review set changes."""

    product = models.OneToOneField("store.Product", on_delete=models.CASCADE, related_name="review_summary")
    data = models.JSONField()
    reviews_fingerprint = models.CharField(max_length=64)
    provider = models.CharField(max_length=30)
    model = models.CharField(max_length=100)
    updated_at = models.DateTimeField(auto_now=True)


class EvalRun(models.Model):
    suite = models.CharField(max_length=30, db_index=True)
    config = models.JSONField(default=dict)
    metrics = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class RuntimeSetting(models.Model):
    """A setting staff can change while the site runs (for example the local model's on/off switch).
    Stored in the database so every server process, and every restart, sees the same value."""

    key = models.CharField(max_length=60, primary_key=True)
    value = models.JSONField(default=dict, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.key} = {self.value}"
