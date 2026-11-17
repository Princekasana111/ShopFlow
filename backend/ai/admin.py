from django.contrib import admin

from .models import ChatMessage, ChatSession, EvalRun, GuardrailEvent, KnowledgeChunk, LLMCall, ProductEmbedding, ReviewSummary


@admin.register(LLMCall)
class LLMCallAdmin(admin.ModelAdmin):
    list_display = ["created_at", "feature", "provider", "model", "status", "input_tokens", "output_tokens",
                    "cache_read_tokens", "latency_ms", "cost_usd", "fallback_used"]
    list_filter = ["feature", "provider", "status", "fallback_used"]
    readonly_fields = [f.name for f in LLMCall._meta.fields]


@admin.register(GuardrailEvent)
class GuardrailEventAdmin(admin.ModelAdmin):
    list_display = ["created_at", "kind", "user", "excerpt"]
    list_filter = ["kind"]
    readonly_fields = [f.name for f in GuardrailEvent._meta.fields]


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ["seq", "role", "content", "display", "created_at"]


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "title", "provider", "model", "updated_at"]
    list_filter = ["provider"]
    inlines = [ChatMessageInline]


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(admin.ModelAdmin):
    list_display = ["doc_title", "section", "chunk_index", "model_name", "updated_at"]
    list_filter = ["doc_slug"]
    exclude = ["vector"]


@admin.register(ProductEmbedding)
class ProductEmbeddingAdmin(admin.ModelAdmin):
    list_display = ["product", "model_name", "updated_at"]
    exclude = ["vector"]


@admin.register(ReviewSummary)
class ReviewSummaryAdmin(admin.ModelAdmin):
    list_display = ["product", "provider", "model", "updated_at"]


@admin.register(EvalRun)
class EvalRunAdmin(admin.ModelAdmin):
    list_display = ["created_at", "suite", "metrics"]
    list_filter = ["suite"]
