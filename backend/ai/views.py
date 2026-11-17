import json
import logging
import time
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from store.models import Product
from store.selectors import annotated_products
from store.serializers import ProductListSerializer

from . import copywriter, rag, reviews
from .agent.assistant import SessionNotFound, run_turn, session_transcript
from .embeddings import get_embedder
from .llm import LLMError, get_llm
from .models import ChatSession, KnowledgeChunk, ProductEmbedding
from .observability import dashboard_metrics
from .query_understanding import intent_to_filters, parse_query
from .search import MODES, SearchFilters, search_products, similar_products

logger = logging.getLogger(__name__)


class StatusView(APIView):
    """Which LLM and embedding model are active, and how much is indexed."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        llm = get_llm()
        return Response(
            {
                "llm": {"provider": llm.name, "model": llm.model, "is_live": llm.is_live, "degraded": getattr(llm, "degraded", False)},
                "embeddings": {"provider": settings.AI["EMBEDDING_PROVIDER"], "model": get_embedder().name, "dim": settings.AI["EMBEDDING_DIM"]},
                "index": {
                    "products": Product.objects.filter(is_active=True).count(),
                    "product_embeddings": ProductEmbedding.objects.count(),
                    "knowledge_chunks": KnowledgeChunk.objects.count(),
                },
            }
        )


def _int_param(params, name, default, low, high):
    """Parse an integer query parameter; missing or invalid values fall back to the default."""
    try:
        value = int(params.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def _decimal(value, name):
    if value in (None, ""):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        raise serializers.ValidationError({name: "Must be a number."})


class SearchView(APIView):
    """GET /api/ai/search/?q=...&mode=hybrid|vector|keyword&parse=true

    With parse=true (default) the query is first turned into structured filters by the LLM
    (category, price range, stock). Explicit category/min_price/max_price/in_stock params
    override the parsed values.
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_search"

    def get(self, request):
        started = time.perf_counter()
        params = request.query_params
        query = params.get("q", "").strip()[:300]
        mode = params.get("mode", "hybrid")
        if mode not in MODES:
            return Response({"detail": f"mode must be one of {', '.join(MODES)}"}, status=status.HTTP_400_BAD_REQUEST)
        limit = _int_param(params, "limit", 12, 1, 30)
        use_parser = params.get("parse", "true").lower() not in ("0", "false", "no") and bool(query)

        intent, parser_meta, semantic_query = None, None, query
        filters = SearchFilters()
        if use_parser:
            intent, parser_meta = parse_query(query, user=request.user)
            filters = intent_to_filters(intent)
            semantic_query = intent.semantic_query

        if params.get("category"):
            filters.category = params["category"]
        if (v := _decimal(params.get("min_price"), "min_price")) is not None:
            filters.min_price = v
        if (v := _decimal(params.get("max_price"), "max_price")) is not None:
            filters.max_price = v
        if params.get("in_stock") in ("1", "true"):
            filters.in_stock_only = True

        hits = search_products(semantic_query, filters, mode=mode, limit=limit)
        results = []
        for hit in hits:
            if hit.product is None:
                continue
            row = ProductListSerializer(hit.product).data
            row["match"] = {"score": hit.score, "keyword_rank": hit.keyword_rank, "vector_rank": hit.vector_rank, "similarity": hit.similarity}
            results.append(row)
        return Response(
            {
                "query": query,
                "semantic_query": semantic_query,
                "mode": mode,
                "intent": intent.model_dump() if intent else None,
                "parser": parser_meta,
                "filters": filters.as_dict(),
                "results": results,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        )


class SimilarProductsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, product_id):
        product = get_object_or_404(Product.objects.select_related("embedding_record"), pk=product_id, is_active=True)
        rows = []
        for p, sim in similar_products(product, limit=_int_param(request.query_params, "limit", 4, 1, 12)):
            row = ProductListSerializer(p).data
            row["similarity"] = sim
            rows.append(row)
        return Response(rows)


class ReviewInsightsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, product_id):
        product = get_object_or_404(Product, pk=product_id, is_active=True)
        refresh = request.query_params.get("refresh") == "1" and request.user.is_staff
        return Response(reviews.get_review_insights(product, user=request.user, refresh=refresh))


class AskSerializer(serializers.Serializer):
    question = serializers.CharField(min_length=3, max_length=500)


class AskView(APIView):
    """Help-center question answering with retrieval-augmented generation and citations."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_search"

    def post(self, request):
        serializer = AskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(rag.answer_question(serializer.validated_data["question"], user=request.user))


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=4000, trim_whitespace=True)
    session_id = serializers.UUIDField(required=False, allow_null=True)


class AssistantChatView(APIView):
    """POST /api/ai/assistant/chat/  -> text/event-stream

    Events: session, tool_start, tool_result, text (deltas), refusal, error, done.
    Add ?stream=false to receive one JSON object instead (handy for API clients and tests).
    """

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_chat"

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.validated_data["message"]
        session_id = serializer.validated_data.get("session_id")
        if session_id and not ChatSession.objects.filter(id=session_id, user=request.user).exists():
            return Response({"detail": "Chat session not found."}, status=status.HTTP_404_NOT_FOUND)
        session_id = str(session_id) if session_id else None
        user = request.user

        if request.query_params.get("stream", "true").lower() in ("0", "false"):
            return Response(self._collect(run_turn(user=user, message=message, session_id=session_id)))

        def event_stream():
            try:
                for event in run_turn(user=user, message=message, session_id=session_id):
                    yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False, default=str)}\n\n"
            except SessionNotFound:
                yield 'event: error\ndata: {"message": "Chat session not found."}\n\n'
            except Exception:
                logger.exception("Assistant turn failed")
                yield 'event: error\ndata: {"message": "Something went wrong. Please try again."}\n\n'

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # tell nginx not to buffer the stream
        return response

    @staticmethod
    def _collect(events):
        out = {"text": "", "events": []}
        for event in events:
            name, data = event["event"], event["data"]
            if name == "text":
                out["text"] += data["delta"]
            else:
                out["events"].append(event)
            if name == "session":
                out["session_id"] = data["session_id"]
                out["provider"], out["model"] = data["provider"], data["model"]
            if name == "done":
                out["done"] = data
        return out


class ChatSessionListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        sessions = ChatSession.objects.filter(user=request.user)[:30]
        return Response(
            [
                {"id": str(s.id), "title": s.title, "provider": s.provider, "model": s.model, "updated_at": s.updated_at.isoformat()}
                for s in sessions
            ]
        )


class ChatSessionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, session_id):
        session = get_object_or_404(ChatSession, id=session_id, user=request.user)
        return Response(
            {
                "id": str(session.id),
                "title": session.title,
                "provider": session.provider,
                "model": session.model,
                "messages": session_transcript(session),
            }
        )

    def delete(self, request, session_id):
        get_object_or_404(ChatSession, id=session_id, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CopywriterSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    tone = serializers.ChoiceField(choices=["friendly", "premium", "concise"], default="friendly")


class CopywriterView(APIView):
    """Staff only: draft product copy with structured outputs. Nothing is saved automatically."""

    permission_classes = [permissions.IsAdminUser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_admin"

    def post(self, request):
        serializer = CopywriterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = get_object_or_404(annotated_products(), pk=serializer.validated_data["product_id"])
        try:
            return Response(copywriter.generate_copy(product, tone=serializer.validated_data["tone"], user=request.user))
        except LLMError as exc:
            return Response({"detail": f"Generation failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)


class MetricsView(APIView):
    """Staff only: LLM usage, cost, latency, guardrail events and latest eval results."""

    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        days = _int_param(request.query_params, "days", 7, 1, 90)
        return Response(dashboard_metrics(days))


# ---------------------------------------------------------------------------
# Unique features: AI planner, photo search, product Q&A, complete the kit
# ---------------------------------------------------------------------------

class PlannerSerializer(serializers.Serializer):
    goal = serializers.CharField(min_length=3, max_length=500)
    budget = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("1"), required=False, allow_null=True)


class PlannerView(APIView):
    """POST {goal, budget?}: plan needs with the LLM, then pick the best in-stock bundle within budget."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_search"

    def post(self, request):
        from .planner import build_bundle

        serializer = PlannerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        budget = serializer.validated_data.get("budget")
        try:
            return Response(build_bundle(serializer.validated_data["goal"], float(budget) if budget is not None else None, user=request.user))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class VisualSearchView(APIView):
    """POST multipart `image`: find products that match a photo (CLIP, plus Claude vision when available)."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_search"

    def post(self, request):
        from .visual import ImageRejected, visual_enabled, visual_search

        if not visual_enabled():
            return Response({"detail": "Photo search is turned off on this server."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        upload = request.FILES.get("image")
        if upload is None:
            return Response({"detail": "Attach a photo as `image`."}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size > settings.AI["MAX_UPLOAD_BYTES"]:
            return Response({"detail": "Image is larger than 5 MB."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            return Response(visual_search(upload.read(), user=request.user))
        except ImageRejected as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class ProductQuestionView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_search"

    def post(self, request, product_id):
        from .product_qa import answer_product_question

        serializer = AskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = get_object_or_404(Product, pk=product_id, is_active=True)
        return Response(answer_product_question(product, serializer.validated_data["question"], user=request.user))


class CompleteTheKitView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, product_id):
        from .planner import complete_the_kit

        product = get_object_or_404(Product.objects.select_related("category"), pk=product_id, is_active=True)
        return Response(complete_the_kit(product, user=request.user))
