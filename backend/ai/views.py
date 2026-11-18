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
from .llm import LLMError, get_agent_llm, get_llm
from .models import ChatSession, KnowledgeChunk, ProductEmbedding
from .observability import dashboard_metrics
from .query_understanding import IGNORABLE, plan_search
from .search import MODES, search_products, similar_products

logger = logging.getLogger(__name__)


class StatusView(APIView):
    """Which LLM and embedding model are active, and how much is indexed."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from .llm.switch import local_switch_on

        llm, agent = get_llm(), get_agent_llm()
        local = settings.AI["LOCAL_LLM_URL"]
        switched_on = bool(local) and local_switch_on(fresh=True)
        degraded = getattr(llm, "degraded", False)
        llm_info = None
        if llm.name == "local" and not switched_on:  # staff turned it off: the offline rules answer
            llm_info = {"provider": "offline", "model": "rule-based-v1", "is_live": False, "degraded": False}
        elif llm.name == "local" and not degraded:
            # Check the local model is really up, so the badge doesn't say "Local AI" while Ollama is stopped
            # (a request would only discover it by failing). Remembered for 30 seconds.
            from django.core.cache import cache

            try:
                up = cache.get("local-llm-ready")
                if up is None:
                    up = llm.primary.ready()
                    cache.set("local-llm-ready", up, 30)
            except Exception:  # the status badge must never break the page
                up = False
            degraded = not up
        return Response(
            {
                "llm": llm_info or {"provider": llm.name, "model": llm.model, "is_live": llm.is_live and not degraded, "degraded": degraded},
                # The shopping assistant's tool loop never runs on the local model.
                "assistant": {"provider": agent.name, "model": agent.model, "is_live": agent.is_live, "degraded": getattr(agent, "degraded", False)},
                "local_model": {"enabled": bool(local), "on": switched_on, "model": settings.AI["LOCAL_LLM_MODEL"] if local else None,
                                "features": settings.AI["LOCAL_LLM_FEATURES"] if local else []},
                "offers": {"min_price": settings.AI["OFFER_MIN_PRICE"], "deal_minutes": settings.AI["OFFER_DEAL_MINUTES"]},
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


def _ignored(params) -> list[str]:
    return [x for x in params.get("ignore", "").split(",") if x in IGNORABLE]


def _plan(request, query: str):
    """Filters for a search request: the parsed intent, overridden by explicit parameters, minus `ignore`d constraints."""
    params = request.query_params
    return plan_search(
        query,
        parse=params.get("parse", "true").lower() not in ("0", "false", "no"),
        category=params.get("category") or None,
        min_price=_decimal(params.get("min_price"), "min_price"),
        max_price=_decimal(params.get("max_price"), "max_price"),
        in_stock=params.get("in_stock") in ("1", "true"),
        ignore=_ignored(params),
        user=request.user,
    )


class SearchView(APIView):
    """GET /api/ai/search/?q=...&mode=hybrid|vector|keyword&parse=true

    With parse=true (default) the query is first turned into structured filters by the LLM
    (category, price range, stock). Explicit category/min_price/max_price/in_stock params override the
    parsed values, and `ignore=budget,category,stock` then drops those constraints wherever they came from.
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
        intent, parser_meta, semantic_query, filters = _plan(request, query)

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
                "ignored": _ignored(params),
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
        result = rag.answer_question(serializer.validated_data["question"], user=request.user)
        if not request.user.is_staff:
            result.pop("retrieved", None)  # shoppers get the answer and its sources; what the search retrieved is for staff
        return Response(result)


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
    skip_owned = serializers.BooleanField(default=True, help_text="Signed-in shoppers: leave out needs already covered by things they own.")


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
            return Response(build_bundle(serializer.validated_data["goal"], float(budget) if budget is not None else None,
                                         user=request.user, skip_owned=serializer.validated_data["skip_owned"]))
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
        data = complete_the_kit(product, user=request.user)
        if request.user.is_authenticated:  # the kit is cached for everyone; mark what this shopper already has
            from .product_kinds import kind_of
            from .purchase_check import owned_kinds

            mine = owned_kinds(request.user)
            items = []
            for item in data["items"]:
                owned = mine.get(kind_of(item["product"]["name"]).key)
                items.append({**item, "owned": {"name": owned.facts.name, "order_id": owned.order_id} if owned else None})
            data = {**data, "items": items}
        return Response(data)


class PurchaseCheckSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1, required=False)
    size = serializers.CharField(max_length=20, required=False, allow_blank=True)
    requirements = serializers.CharField(max_length=500, required=False, allow_blank=True)


class PurchaseCheckView(APIView):
    """POST {product_id?, size?, requirements?}: the five pre-purchase checks on the cart, or on one product."""

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_search"

    def post(self, request):
        from store.services import CartError, validate_size

        from .purchase_check import purchase_check

        serializer = PurchaseCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        product = None
        if data.get("product_id"):
            product = get_object_or_404(annotated_products(), pk=data["product_id"], is_active=True)  # with rating
            try:
                validate_size(product, data.get("size"))
            except CartError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        try:
            return Response(purchase_check(request.user, product=product, size=data.get("size"), requirements=data.get("requirements", "")))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class OwnedView(APIView):
    """GET: what the signed-in shopper already owns, grouped by kind, with replacement hints."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .purchase_check import owned_inventory

        return Response(owned_inventory(request.user))


# ---------------------------------------------------------------------------
# Make an offer, listing vs reviews, fit advisor, "why isn't this in my results?"
# ---------------------------------------------------------------------------

class StartOfferSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)


class OfferMessageSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=500, trim_whitespace=True)


class AcceptOfferSerializer(serializers.Serializer):
    size = serializers.CharField(max_length=20, required=False, allow_blank=True)
    add_to_cart = serializers.BooleanField(default=True)


class OffersView(APIView):
    """GET: the shopper's bargaining chats and deals ("My offers").
    POST {product_id}: open (or resume) a "Make an offer" chat with the AI seller."""

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_chat"

    def get_throttles(self):
        return [] if self.request.method == "GET" else super().get_throttles()

    def get(self, request):
        from .negotiation import list_offers

        return Response(list_offers(request.user))

    def post(self, request):
        from .negotiation import OfferError, start_offer

        serializer = StartOfferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = get_object_or_404(Product, pk=serializer.validated_data["product_id"], is_active=True)
        try:
            return Response(start_offer(request.user, product))
        except OfferError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class OfferMessageView(APIView):
    """POST {message}: the shopper's next message; returns the seller's reply and the new state."""

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_chat"

    def post(self, request, offer_id):
        from .negotiation import OfferError, send_message

        serializer = OfferMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return Response(send_message(request.user, offer_id, serializer.validated_data["message"]))
        except (OfferError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class AcceptOfferView(APIView):
    """POST {size?, add_to_cart?}: agree to the seller's current price and put the deal in the cart."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, offer_id):
        from .negotiation import OfferError, accept_offer

        serializer = AcceptOfferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return Response(accept_offer(request.user, offer_id, size=serializer.validated_data.get("size") or None,
                                         add_to_cart=serializer.validated_data["add_to_cart"]))
        except OfferError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class ReopenOfferView(APIView):
    """POST: "Change my offer": put an agreed deal back on the table and keep bargaining."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, offer_id):
        from .negotiation import OfferError, reopen_offer

        try:
            return Response(reopen_offer(request.user, offer_id))
        except OfferError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class DropOfferView(APIView):
    """POST: cancel a deal (it leaves the cart) or end an open chat."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, offer_id):
        from .negotiation import OfferError, drop_offer

        try:
            return Response(drop_offer(request.user, offer_id))
        except OfferError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class ListingCheckView(APIView):
    """GET: where reviews back up or contradict the product listing's claims."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_search"

    def get(self, request, product_id):
        from .listing_check import check_listing

        product = get_object_or_404(Product, pk=product_id, is_active=True)
        return Response(check_listing(product, user=request.user))


class ListingIssuesView(APIView):
    """Staff only: every listing claim that reviewers dispute, across the catalog."""

    permission_classes = [permissions.IsAdminUser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_admin"

    def get(self, request):
        from .listing_check import listing_issues

        return Response(listing_issues(user=request.user))


class FitView(APIView):
    """GET ?size=: how the product fits according to its reviews, and which size to pick."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_search"

    def get(self, request, product_id):
        from store.sizes import SizePrefs

        from store.sizes import product_sizes

        from .fit import fit_summary, usual_size

        product = get_object_or_404(Product, pk=product_id, is_active=True)
        usual = ""
        if request.user.is_authenticated:
            from accounts.models import profile_for

            usual = usual_size(SizePrefs.from_profile(profile_for(request.user)), product_sizes(product))
        return Response(fit_summary(product, usual=usual, picked=request.query_params.get("size") or None, user=request.user))


class SearchExplainView(APIView):
    """GET ?q=&product_id= (plus the search's own mode, limit, category, price, in_stock and ignore params):
    why that product isn't in the results, and a tested fix."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_search"

    def get(self, request):
        from .search_explain import explain

        params = request.query_params
        query = params.get("q", "").strip()[:300]
        mode = params.get("mode", "hybrid")
        if not query:
            return Response({"detail": "Send the search text as q."}, status=status.HTTP_400_BAD_REQUEST)
        if mode not in MODES:
            return Response({"detail": f"mode must be one of {', '.join(MODES)}"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            product_id = int(params.get("product_id", ""))
        except ValueError:
            return Response({"detail": "Send the product's id as product_id."}, status=status.HTTP_400_BAD_REQUEST)
        product = get_object_or_404(Product.objects.select_related("category"), pk=product_id)
        if not product.is_active and not request.user.is_staff:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(explain(
            query, product, mode=mode, limit=_int_param(params, "limit", 12, 1, 30),
            parse=params.get("parse", "true").lower() not in ("0", "false", "no"),
            category=params.get("category") or None,
            min_price=_decimal(params.get("min_price"), "min_price"),
            max_price=_decimal(params.get("max_price"), "max_price"),
            in_stock=params.get("in_stock") in ("1", "true"),
            ignore=_ignored(params), user=request.user,
        ))


class LocalSwitchSerializer(serializers.Serializer):
    on = serializers.BooleanField()


class LocalModelView(APIView):
    """Staff only. GET: the local model's state. POST {on}: turn it on or off for the whole site."""

    permission_classes = [permissions.IsAdminUser]

    def _state(self, note: str = "") -> dict:
        from .llm.local_provider import LocalProvider
        from .llm.switch import local_switch_on

        cfg = settings.AI
        if not cfg["LOCAL_LLM_URL"]:
            return {"configured": False, "on": False, "ready": False, "model": None, "features": [], "note": note}
        probe = LocalProvider(cfg["LOCAL_LLM_URL"], cfg["LOCAL_LLM_MODEL"])
        return {"configured": True, "on": local_switch_on(fresh=True), "ready": probe.ready(), "model": cfg["LOCAL_LLM_MODEL"],
                "features": cfg["LOCAL_LLM_FEATURES"], "note": note}

    def get(self, request):
        return Response(self._state())

    def post(self, request):
        from django.core.cache import cache

        from .llm.switch import set_local_switch

        serializer = LocalSwitchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not settings.AI["LOCAL_LLM_URL"]:
            return Response({"detail": "No local model is set up. Add COMPOSE_PROFILES=local-llm and LOCAL_LLM_URL to .env (see the README)."},
                            status=status.HTTP_400_BAD_REQUEST)
        result = set_local_switch(serializer.validated_data["on"], user=request.user)
        cache.delete("local-llm-ready")  # the status badge re-checks at once
        return Response(self._state(result["note"]))
