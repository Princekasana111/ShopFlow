from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    brand = models.CharField(max_length=100, blank=True)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    stock = models.PositiveIntegerField(default=0)
    attributes = models.JSONField(default=dict, blank=True)
    # "Make an offer": the lowest price the AI seller may agree to. Empty means the list price minus
    # the store's default maximum discount (see ai.negotiation). At or above the price turns bargaining
    # off for this product. Never sent to the LLM or to the browser.
    floor_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))],
        help_text="Lowest price the AI seller may agree to. Empty = the default maximum discount; at or above the price = no bargaining.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["price"]), models.Index(fields=["is_active", "category"])]

    def __str__(self):
        return self.name

    @property
    def in_stock(self) -> bool:
        return self.stock > 0


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=120, blank=True)
    body = models.TextField(max_length=2000)

    class Fit(models.TextChoices):
        SMALL = "small", "Runs small"
        TRUE = "true", "True to size"
        LARGE = "large", "Runs large"

    # Optional, for sized products: the size the reviewer bought and how it fit (the fit advisor).
    size_bought = models.CharField(max_length=20, blank=True, default="")
    fit = models.CharField(max_length=5, choices=Fit.choices, blank=True, default="")
    # Set by the AI guardrail when the review text looks like a prompt-injection attempt.
    # Flagged reviews are hidden from every LLM prompt.
    is_flagged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["product", "user"], name="one_review_per_user_per_product")]

    def __str__(self):
        return f"{self.rating}★ {self.product} by {self.user}"


class Cart(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart of {self.user}"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    # Chosen size for sized products (see store.sizes); blank until chosen. One line per product,
    # so one size per product per cart.
    size = models.CharField(max_length=20, blank=True, default="")
    # A price agreed with the AI seller ("Make an offer"). It covers one unit, so a line with a deal
    # always has quantity 1. An expired deal falls back to the list price.
    offer = models.ForeignKey("Offer", on_delete=models.SET_NULL, null=True, blank=True, related_name="cart_items")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["cart", "product"], name="one_line_per_product")]

    @property
    def deal(self) -> "Offer | None":
        offer = self.offer
        return offer if offer is not None and offer.product_id == self.product_id and offer.is_valid_deal else None

    @property
    def unit_price(self) -> Decimal:
        deal = self.deal
        # If staff cut the list price below an agreed deal, the shopper pays the lower one.
        return min(deal.deal_price, self.product.price) if deal else self.product.price

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SHIPPED = "SHIPPED", "Shipped"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"

    # Order lifecycle. Anything not listed here is rejected by store.services.update_order_status.
    ALLOWED_TRANSITIONS = {
        Status.PENDING: {Status.SHIPPED, Status.CANCELLED},
        Status.SHIPPED: {Status.DELIVERED},
        Status.DELIVERED: set(),
        Status.CANCELLED: set(),
    }

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    shipping_name = models.CharField(max_length=120)
    shipping_phone = models.CharField(max_length=20)
    shipping_address = models.CharField(max_length=255)
    shipping_city = models.CharField(max_length=80)
    shipping_pincode = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"]), models.Index(fields=["status"])]

    def __str__(self):
        return f"Order #{self.pk} ({self.status})"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    # SET_NULL keeps order history intact if a product is later deleted.
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, related_name="order_items")
    # Snapshot of name and price at purchase time: later catalog edits must not rewrite past orders.
    product_name = models.CharField(max_length=200)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    size = models.CharField(max_length=20, blank=True, default="")

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity


class OrderStatusEvent(models.Model):
    """Audit trail that powers order tracking (one row per status change)."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=20, choices=Order.Status.choices)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class Offer(models.Model):
    """One "Make an offer" conversation with the AI seller, and the deal it may end in.

    The price rules are code (ai.negotiation); the LLM only reads the shopper's message and writes the
    seller's words, and it is never told the floor price. An agreed deal is for one unit, is valid
    until `expires_at`, and can be used in one order.
    """

    class Status(models.TextChoices):
        OPEN = "OPEN", "Negotiating"
        AGREED = "AGREED", "Deal agreed"
        USED = "USED", "Used in an order"
        CLOSED = "CLOSED", "Ended without a deal"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="offers")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="offers")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    list_price = models.DecimalField(max_digits=10, decimal_places=2)
    counter_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # the seller's current price
    deal_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    rounds = models.PositiveSmallIntegerField(default=0)  # concessions made so far
    turns = models.PositiveSmallIntegerField(default=0)  # shopper messages so far
    messages = models.JSONField(default=list, blank=True)  # [{"role": "shopper"|"seller", "text", "price", "action", "at"}]
    expires_at = models.DateTimeField(null=True, blank=True)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="offers")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "product", "-created_at"])]

    def __str__(self):
        return f"Offer #{self.pk} on {self.product} ({self.status})"

    @property
    def is_valid_deal(self) -> bool:
        return self.status == self.Status.AGREED and self.deal_price is not None and self.expires_at is not None and self.expires_at > timezone.now()
