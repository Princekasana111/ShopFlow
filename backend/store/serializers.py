from rest_framework import serializers

from .models import Cart, CartItem, Category, Order, OrderItem, OrderStatusEvent, Product, Review
from .services import cart_items, cart_total


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "description"]


class ProductListSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    avg_rating = serializers.FloatField(read_only=True, allow_null=True)
    review_count = serializers.IntegerField(read_only=True)
    short_description = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "name", "slug", "brand", "price", "stock", "category",
            "avg_rating", "review_count", "short_description",
        ]

    def get_short_description(self, obj) -> str:
        text = obj.description.strip()
        return text if len(text) <= 140 else text[:137].rsplit(" ", 1)[0] + "..."


class ProductDetailSerializer(ProductListSerializer):
    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + ["description", "attributes", "is_active", "updated_at"]


class ProductWriteSerializer(serializers.ModelSerializer):
    category_id = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(), source="category")

    class Meta:
        model = Product
        fields = [
            "id", "name", "slug", "brand", "description", "price", "stock",
            "category_id", "attributes", "is_active",
        ]


class ReviewSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Review
        fields = ["id", "username", "rating", "title", "body", "is_flagged", "created_at"]
        read_only_fields = ["id", "username", "is_flagged", "created_at"]


class CartItemSerializer(serializers.ModelSerializer):
    product = ProductListSerializer(read_only=True)
    line_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = CartItem
        fields = ["id", "product", "quantity", "line_total"]


class CartSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ["id", "items", "total", "item_count", "updated_at"]

    def get_items(self, cart):
        return CartItemSerializer(cart_items(cart), many=True).data

    def get_total(self, cart) -> str:
        return f"{cart_total(cart):.2f}"

    def get_item_count(self, cart) -> int:
        return sum(item.quantity for item in cart.items.all())


class AddCartItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=10, default=1)


class UpdateCartItemSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=0, max_value=10)


class OrderItemSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    category = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = ["id", "product", "product_name", "category", "unit_price", "quantity", "line_total"]

    def get_category(self, item) -> str | None:
        return item.product.category.name if item.product_id else None


class OrderStatusEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderStatusEvent
        fields = ["status", "note", "created_at"]


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    events = OrderStatusEventSerializer(many=True, read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Order
        fields = [
            "id", "username", "status", "total", "items", "events",
            "shipping_name", "shipping_phone", "shipping_address", "shipping_city", "shipping_pincode",
            "created_at", "updated_at",
        ]


class CheckoutSerializer(serializers.Serializer):
    shipping_name = serializers.CharField(max_length=120)
    shipping_phone = serializers.RegexField(r"^[6-9]\d{9}$", error_messages={"invalid": "Enter a valid 10-digit Indian mobile number."})
    shipping_address = serializers.CharField(max_length=255)
    shipping_city = serializers.CharField(max_length=80)
    shipping_pincode = serializers.RegexField(r"^[1-9]\d{5}$", error_messages={"invalid": "Enter a valid 6-digit PIN code."})


class OrderStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.Status.choices)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)
