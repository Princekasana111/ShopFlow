"""Business logic shared by the REST API and the AI assistant's tools.

Keeping cart and order rules here (not in views) means the assistant cannot bypass them:
it calls exactly the same functions a customer's browser does.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import F

from .models import Cart, CartItem, Order, OrderItem, OrderStatusEvent, Product

MAX_QTY_PER_LINE = 10


class StoreError(Exception):
    """A business-rule violation with a message that is safe to show to the customer."""


class CartError(StoreError):
    pass


class CheckoutError(StoreError):
    pass


class OrderStatusError(StoreError):
    pass


def get_cart(user) -> Cart:
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart


def cart_items(cart: Cart):
    return cart.items.select_related("product", "product__category").order_by("id")


def cart_total(cart: Cart) -> Decimal:
    return sum((item.line_total for item in cart_items(cart)), Decimal("0"))


def add_to_cart(user, product_id: int, quantity: int = 1) -> CartItem:
    if quantity < 1:
        raise CartError("Quantity must be at least 1.")
    try:
        product = Product.objects.get(pk=product_id, is_active=True)
    except Product.DoesNotExist:
        raise CartError(f"Product {product_id} does not exist.")
    cart = get_cart(user)
    item = cart.items.filter(product=product).first()
    new_quantity = quantity + (item.quantity if item else 0)
    if new_quantity > MAX_QTY_PER_LINE:
        raise CartError(f"You can buy at most {MAX_QTY_PER_LINE} of one product per order.")
    if new_quantity > product.stock:
        raise CartError(f"Only {product.stock} unit(s) of {product.name} in stock.")
    if item:
        item.quantity = new_quantity
        item.save(update_fields=["quantity"])
    else:
        item = CartItem.objects.create(cart=cart, product=product, quantity=quantity)
    cart.save(update_fields=["updated_at"])
    return item


def set_cart_quantity(user, product_id: int, quantity: int) -> CartItem | None:
    cart = get_cart(user)
    item = cart.items.select_related("product").filter(product_id=product_id).first()
    if item is None:
        raise CartError("That product is not in your cart.")
    if quantity <= 0:
        item.delete()
        return None
    if quantity > MAX_QTY_PER_LINE:
        raise CartError(f"You can buy at most {MAX_QTY_PER_LINE} of one product per order.")
    if quantity > item.product.stock:
        raise CartError(f"Only {item.product.stock} unit(s) of {item.product.name} in stock.")
    item.quantity = quantity
    item.save(update_fields=["quantity"])
    return item


def clear_cart(user) -> None:
    get_cart(user).items.all().delete()


@dataclass
class ShippingDetails:
    name: str
    phone: str
    address: str
    city: str
    pincode: str


@transaction.atomic
def checkout(user, shipping: ShippingDetails) -> Order:
    """Turn the user's cart into an order.

    Runs in one transaction and locks the product rows (SELECT ... FOR UPDATE), so two
    customers buying the last unit at the same moment cannot both succeed.
    """
    cart = get_cart(user)
    items = list(cart.items.all())
    if not items:
        raise CheckoutError("Your cart is empty.")

    product_ids = [item.product_id for item in items]
    products = {p.pk: p for p in Product.objects.select_for_update().filter(pk__in=product_ids).order_by("pk")}

    total = Decimal("0")
    for item in items:
        product = products.get(item.product_id)
        if product is None or not product.is_active:
            raise CheckoutError("A product in your cart is no longer available.")
        if item.quantity > product.stock:
            raise CheckoutError(f"Only {product.stock} unit(s) of {product.name} left in stock.")
        total += product.price * item.quantity

    order = Order.objects.create(
        user=user,
        total=total,
        shipping_name=shipping.name,
        shipping_phone=shipping.phone,
        shipping_address=shipping.address,
        shipping_city=shipping.city,
        shipping_pincode=shipping.pincode,
    )
    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order,
                product=products[item.product_id],
                product_name=products[item.product_id].name,
                unit_price=products[item.product_id].price,
                quantity=item.quantity,
            )
            for item in items
        ]
    )
    for item in items:
        Product.objects.filter(pk=item.product_id).update(stock=F("stock") - item.quantity)
    OrderStatusEvent.objects.create(order=order, status=Order.Status.PENDING, note="Order placed")
    cart.items.all().delete()
    return order


@transaction.atomic
def update_order_status(order: Order, new_status: str, note: str = "") -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    allowed = Order.ALLOWED_TRANSITIONS.get(order.status, set())
    if new_status not in allowed:
        raise OrderStatusError(f"Cannot change an order from {order.status} to {new_status}.")
    if new_status == Order.Status.CANCELLED:
        for item in order.items.all():
            if item.product_id:
                Product.objects.filter(pk=item.product_id).update(stock=F("stock") + item.quantity)
    order.status = new_status
    order.save(update_fields=["status", "updated_at"])
    OrderStatusEvent.objects.create(order=order, status=new_status, note=note)
    return order


def cancel_order(order: Order, by_user) -> Order:
    if order.user_id != by_user.pk and not by_user.is_staff:
        raise OrderStatusError("You can only cancel your own orders.")
    if order.status != Order.Status.PENDING:
        raise OrderStatusError("Only pending orders can be cancelled.")
    return update_order_status(order, Order.Status.CANCELLED, note="Cancelled by customer")
