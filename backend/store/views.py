from decimal import Decimal, InvalidOperation

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import IntegrityError
from django.db.models import F
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Category, Order
from .permissions import IsAdminOrReadOnly
from .selectors import annotated_products
from .serializers import (
    AddCartItemSerializer,
    CartSerializer,
    CategorySerializer,
    CheckoutSerializer,
    OrderSerializer,
    OrderStatusUpdateSerializer,
    ProductDetailSerializer,
    ProductListSerializer,
    ProductWriteSerializer,
    ReviewSerializer,
    UpdateCartItemSerializer,
)


def _decimal_param(request, name):
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ValidationError({name: "Must be a number."})


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrReadOnly]
    pagination_class = None


class ProductViewSet(viewsets.ModelViewSet):
    """Catalog. Anyone can browse; only staff can create, edit or delete products.

    Query params: `category` (slug), `min_price`, `max_price`, `in_stock=true`,
    `q` (keyword full-text search), `ordering` = price | -price | rating | newest | name.
    """

    permission_classes = [IsAdminOrReadOnly]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return ProductWriteSerializer
        if self.action == "retrieve":
            return ProductDetailSerializer
        return ProductListSerializer

    def get_queryset(self):
        qs = annotated_products()
        user = self.request.user
        if not (user.is_authenticated and user.is_staff):
            qs = qs.filter(is_active=True)
        if self.action != "list":
            return qs

        params = self.request.query_params
        if category := params.get("category"):
            qs = qs.filter(category__slug=category)
        if (min_price := _decimal_param(self.request, "min_price")) is not None:
            qs = qs.filter(price__gte=min_price)
        if (max_price := _decimal_param(self.request, "max_price")) is not None:
            qs = qs.filter(price__lte=max_price)
        if params.get("in_stock") in ("1", "true", "True"):
            qs = qs.filter(stock__gt=0)

        ordering = params.get("ordering", "")
        if q := params.get("q", "").strip():
            vector = SearchVector("name", weight="A") + SearchVector("brand", weight="A") + SearchVector("description", weight="C")
            query = SearchQuery(q, search_type="websearch")
            # Filter on the match itself (SQL `@@`). PostgreSQL's ts_rank returns a tiny non-zero
            # rank (1e-20) for rows that don't match a multi-word query, so `rank > 0` let the
            # whole catalog through for queries like "rain jacket".
            qs = qs.annotate(document=vector, rank=SearchRank(vector, query)).filter(document=query)
            if not ordering:
                return qs.order_by("-rank", "id")

        order_map = {
            "price": ["price", "id"],
            "-price": ["-price", "id"],
            "rating": [F("avg_rating").desc(nulls_last=True), "-review_count", "id"],
            "newest": ["-created_at", "id"],
            "name": ["name", "id"],
        }
        return qs.order_by(*order_map.get(ordering, ["name", "id"]))

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = serializer.save()
        return Response(ProductDetailSerializer(annotated_products().get(pk=product.pk)).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = ProductWriteSerializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ProductDetailSerializer(annotated_products().get(pk=instance.pk)).data)

    @action(detail=True, methods=["get", "post"], permission_classes=[permissions.IsAuthenticatedOrReadOnly])
    def reviews(self, request, pk=None):
        product = self.get_object()
        if request.method == "GET":
            reviews = product.reviews.select_related("user").filter(is_flagged=False)
            return Response(ReviewSerializer(reviews, many=True).data)
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            review = serializer.save(product=product, user=request.user)
        except IntegrityError:
            return Response({"detail": "You have already reviewed this product."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)


class CartView(APIView):
    """GET the cart, POST to add an item, DELETE to empty it."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(CartSerializer(services.get_cart(request.user)).data)

    def post(self, request):
        serializer = AddCartItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.add_to_cart(request.user, **serializer.validated_data)
        except services.CartError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CartSerializer(services.get_cart(request.user)).data, status=status.HTTP_201_CREATED)

    def delete(self, request):
        services.clear_cart(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CartItemView(APIView):
    """PATCH to change a line's quantity (0 removes it), DELETE to remove it."""

    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, product_id):
        serializer = UpdateCartItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.set_cart_quantity(request.user, product_id, serializer.validated_data["quantity"])
        except services.CartError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CartSerializer(services.get_cart(request.user)).data)

    def delete(self, request, product_id):
        try:
            services.set_cart_quantity(request.user, product_id, 0)
        except services.CartError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(CartSerializer(services.get_cart(request.user)).data)


class OrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Customers see their own orders. Staff see every order, unless they pass `?scope=mine`
    (used by the customer-facing "My orders" page)."""

    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Order.objects.select_related("user").prefetch_related("items__product__category", "events")
        if self.request.user.is_staff and self.request.query_params.get("scope") != "mine":
            if status_filter := self.request.query_params.get("status"):
                qs = qs.filter(status=status_filter)
            return qs
        return qs.filter(user=self.request.user)

    @action(detail=False, methods=["post"])
    def checkout(self, request):
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        shipping = services.ShippingDetails(
            name=data["shipping_name"],
            phone=data["shipping_phone"],
            address=data["shipping_address"],
            city=data["shipping_city"],
            pincode=data["shipping_pincode"],
        )
        try:
            order = services.checkout(request.user, shipping)
        except services.CheckoutError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(OrderSerializer(self.get_queryset().get(pk=order.pk)).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        try:
            services.cancel_order(order, request.user)
        except services.OrderStatusError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(OrderSerializer(self.get_queryset().get(pk=order.pk)).data)

    @action(detail=True, methods=["post"], url_path="status", permission_classes=[permissions.IsAdminUser])
    def update_status(self, request, pk=None):
        order = self.get_object()
        serializer = OrderStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.update_order_status(order, serializer.validated_data["status"], serializer.validated_data.get("note", ""))
        except services.OrderStatusError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(OrderSerializer(self.get_queryset().get(pk=order.pk)).data)
