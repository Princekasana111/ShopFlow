"""Business logic shared by the REST API and the AI assistant's tools.

Keeping cart and order rules here (not in views) means the assistant cannot bypass them:
it calls exactly the same functions a customer's browser does.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import F

from .models import Cart, CartItem, Offer, Order, OrderItem, OrderStatusEvent, Product
from .sizes import SizePrefs, preferred_size, product_sizes

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
    return cart.items.select_related("product", "product__category", "offer").order_by("id")


def cart_total(cart: Cart) -> Decimal:
    return sum((item.line_total for item in cart_items(cart)), Decimal("0"))


def validate_size(product: Product, size: str | None) -> str:
    """Return the size to store for this product ("" for unsized products), or raise CartError."""
    sizes = product_sizes(product)
    size = (size or "").strip()
    if not sizes:
        if size:
            raise CartError(f"{product.name} doesn't come in sizes.")
        return ""
    if size and size not in sizes:
        raise CartError(f"Size {size} isn't available for {product.name}. Choose one of: {', '.join(sizes)}.")
    return size


def _saved_size(user, product: Product) -> str:
    """The shopper's saved size for this product, if they saved one and it is made in that size."""
    from accounts.models import profile_for  # store must not import accounts at module load

    size = preferred_size(SizePrefs.from_profile(profile_for(user)), product_sizes(product))
    return size if size in product_sizes(product) else ""


def add_to_cart(user, product_id: int, quantity: int = 1, size: str | None = None) -> CartItem:
    """Add a product. For sized products the size may be given; if not, the shopper's saved size is
    used when the product comes in it, otherwise the line waits for a size (required at checkout)."""
    if quantity < 1:
        raise CartError("Quantity must be at least 1.")
    try:
        product = Product.objects.get(pk=product_id, is_active=True)
    except Product.DoesNotExist:
        raise CartError(f"Product {product_id} does not exist.")
    size = validate_size(product, size)
    cart = get_cart(user)
    item = cart.items.select_related("offer").filter(product=product).first()
    if item and item.deal is not None:
        raise CartError(f"{product.name} is in your cart at your deal price, which is for one unit.")
    if item and size and item.size and size != item.size:
        raise CartError(f"{product.name} is already in your cart in size {item.size}. Change the size there.")
    new_quantity = quantity + (item.quantity if item else 0)
    if new_quantity > MAX_QTY_PER_LINE:
        raise CartError(f"You can buy at most {MAX_QTY_PER_LINE} of one product per order.")
    if new_quantity > product.stock:
        raise CartError(f"Only {product.stock} unit(s) of {product.name} in stock.")
    if item:
        item.quantity = new_quantity
        item.size = size or item.size or (_saved_size(user, product) if product_sizes(product) else "")
        item.save(update_fields=["quantity", "size"])
    else:
        if not size and product_sizes(product):
            size = _saved_size(user, product)
        item = CartItem.objects.create(cart=cart, product=product, quantity=quantity, size=size)
    cart.save(update_fields=["updated_at"])
    return item


def update_cart_line(user, product_id: int, quantity: int | None = None, size: str | None = None) -> CartItem | None:
    """Change a line's quantity (0 removes it) and/or its size."""
    cart = get_cart(user)
    item = cart.items.select_related("product").filter(product_id=product_id).first()
    if item is None:
        raise CartError("That product is not in your cart.")
    if quantity is not None and quantity <= 0:
        item.delete()
        return None
    fields = []
    if quantity is not None:
        if quantity > 1 and item.deal is not None:
            raise CartError(f"Your deal price for {item.product.name} is for one unit. Remove the line to buy more at the list price.")
        if quantity > MAX_QTY_PER_LINE:
            raise CartError(f"You can buy at most {MAX_QTY_PER_LINE} of one product per order.")
        if quantity > item.product.stock:
            raise CartError(f"Only {item.product.stock} unit(s) of {item.product.name} in stock.")
        item.quantity = quantity
        fields.append("quantity")
    if size is not None:
        item.size = validate_size(item.product, size)
        fields.append("size")
    if fields:
        item.save(update_fields=fields)
    return item


def add_offer_to_cart(user, offer: Offer, size: str | None = None) -> CartItem:
    """Put an agreed "Make an offer" deal in the cart: one unit at the deal price."""
    if offer.user_id != user.pk or not offer.is_valid_deal:
        raise CartError("This deal has expired or was already used.")
    product = offer.product
    if not product.is_active or product.stock < 1:
        raise CartError(f"{product.name} is out of stock.")
    cart = get_cart(user)
    item = cart.items.filter(product=product).first()
    if item and item.quantity > 1:
        raise CartError(f"You have {item.quantity} of {product.name} in your cart; the deal is for one. Change the quantity to 1 first.")
    size = validate_size(product, size) or (item.size if item else "") or (_saved_size(user, product) if product_sizes(product) else "")
    if item:
        item.offer, item.size = offer, size
        item.save(update_fields=["offer", "size"])
    else:
        item = CartItem.objects.create(cart=cart, product=product, quantity=1, size=size, offer=offer)
    cart.save(update_fields=["updated_at"])
    return item


def drop_expired_deals(cart: Cart) -> list[str]:
    """Detach deals that expired (or were used elsewhere) from cart lines; returns the product names."""
    dropped = []
    for item in cart.items.select_related("product", "offer").filter(offer__isnull=False):
        if item.deal is None:
            dropped.append(item.product.name)
            item.offer = None
            item.save(update_fields=["offer"])
    return dropped


def set_cart_quantity(user, product_id: int, quantity: int) -> CartItem | None:
    return update_cart_line(user, product_id, quantity=quantity)


def clear_cart(user) -> None:
    get_cart(user).items.all().delete()


@dataclass
class ShippingDetails:
    name: str
    phone: str
    address: str
    city: str
    pincode: str


def checkout(user, shipping: ShippingDetails) -> Order:
    """Turn the user's cart into an order.

    An expired "Make an offer" deal is removed first (and committed) and the order is not placed, so
    the shopper sees the new total before paying it. The order itself is one transaction that locks
    the product rows (SELECT ... FOR UPDATE), so two customers buying the last unit at the same
    moment cannot both succeed.
    """
    dropped = drop_expired_deals(get_cart(user))
    if dropped:
        raise CheckoutError(f"Your deal price for {', '.join(dropped)} expired, so it's back to the list price. Check the total and place the order again.")
    return _checkout(user, shipping)


@transaction.atomic
def _checkout(user, shipping: ShippingDetails) -> Order:
    # Lock the shopper's cart first: a second checkout (a double click, two tabs) waits here, then finds
    # the cart empty, instead of reading the same lines and placing a second order or reusing a deal.
    cart = Cart.objects.select_for_update().get(pk=get_cart(user).pk)
    items = list(cart.items.select_related("offer"))
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
        sizes = product_sizes(product)
        if sizes and item.size not in sizes:
            raise CheckoutError(f"Choose a size for {product.name} before checkout ({', '.join(sizes)}).")
        item.product = product  # the locked row
        total += item.unit_price * item.quantity

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
                unit_price=item.unit_price,
                quantity=item.quantity,
                size=item.size,
            )
            for item in items
        ]
    )
    for item in items:
        Product.objects.filter(pk=item.product_id).update(stock=F("stock") - item.quantity)
        if item.deal is not None:
            Offer.objects.filter(pk=item.offer_id).update(status=Offer.Status.USED, order=order)
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
