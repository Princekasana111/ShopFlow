from decimal import Decimal

import pytest

from ai.models import ProductEmbedding
from store.models import Order, Product

pytestmark = pytest.mark.django_db

SHIPPING = {
    "shipping_name": "Alice", "shipping_phone": "9876543210", "shipping_address": "1 MG Road",
    "shipping_city": "Bengaluru", "shipping_pincode": "560001",
}


def test_catalog_is_public_and_filterable(anon_client, catalog):
    r = anon_client.get("/api/products/")
    assert r.status_code == 200 and r.data["count"] == 4
    r = anon_client.get("/api/products/", {"category": "electronics", "max_price": "2000"})
    assert [p["slug"] for p in r.data["results"]] == ["boombox"]
    r = anon_client.get("/api/products/", {"in_stock": "true"})
    assert "flask" not in [p["slug"] for p in r.data["results"]]
    r = anon_client.get("/api/products/", {"q": "running shoes"})
    assert r.data["results"][0]["slug"] == "stride-runner"


def test_only_staff_can_write_products(client_for, user, admin_user, catalog, django_capture_on_commit_callbacks):
    payload = {"name": "Volt Power Bank", "slug": "power-bank", "brand": "Volt", "description": "20000mAh power bank.",
               "price": "1599.00", "stock": 3, "category_id": catalog["speaker"].category_id}
    assert client_for(user).post("/api/products/", payload, format="json").status_code == 403
    with django_capture_on_commit_callbacks(execute=True):
        r = client_for(admin_user).post("/api/products/", payload, format="json")
    assert r.status_code == 201, r.data
    # The post_save signal embedded the new product for semantic search.
    assert ProductEmbedding.objects.filter(product_id=r.data["id"]).exists()


def test_cart_respects_stock(client_for, user, catalog):
    client = client_for(user)
    r = client.post("/api/cart/", {"product_id": catalog["shoes"].pk, "quantity": 2}, format="json")
    assert r.status_code == 201 and r.data["item_count"] == 2 and r.data["total"] == "6598.00"
    r = client.post("/api/cart/", {"product_id": catalog["shoes"].pk, "quantity": 1}, format="json")
    assert r.status_code == 400 and "in stock" in r.data["detail"]
    r = client.post("/api/cart/", {"product_id": catalog["flask"].pk, "quantity": 1}, format="json")
    assert r.status_code == 400


def test_checkout_creates_order_decrements_stock_and_clears_cart(client_for, user, catalog):
    client = client_for(user)
    client.post("/api/cart/", {"product_id": catalog["headphones"].pk, "quantity": 2}, format="json")
    client.post("/api/cart/", {"product_id": catalog["speaker"].pk, "quantity": 1}, format="json")
    r = client.post("/api/orders/checkout/", SHIPPING, format="json")
    assert r.status_code == 201, r.data
    assert Decimal(r.data["total"]) == Decimal("7999.00") * 2 + Decimal("1799.00")
    assert r.data["status"] == "PENDING" and len(r.data["items"]) == 2 and r.data["events"][0]["status"] == "PENDING"
    assert Product.objects.get(pk=catalog["headphones"].pk).stock == 3
    assert client.get("/api/cart/").data["item_count"] == 0


def test_checkout_validation(client_for, user, catalog):
    client = client_for(user)
    assert client.post("/api/orders/checkout/", SHIPPING, format="json").status_code == 400  # empty cart
    client.post("/api/cart/", {"product_id": catalog["speaker"].pk, "quantity": 1}, format="json")
    r = client.post("/api/orders/checkout/", {**SHIPPING, "shipping_pincode": "012345", "shipping_phone": "12345"}, format="json")
    assert r.status_code == 400 and {"shipping_pincode", "shipping_phone"} <= set(r.data)


def test_checkout_rechecks_stock_at_purchase_time(client_for, user, catalog):
    client = client_for(user)
    client.post("/api/cart/", {"product_id": catalog["shoes"].pk, "quantity": 2}, format="json")
    Product.objects.filter(pk=catalog["shoes"].pk).update(stock=1)  # someone else bought one
    r = client.post("/api/orders/checkout/", SHIPPING, format="json")
    assert r.status_code == 400 and "left in stock" in r.data["detail"]
    assert not Order.objects.exists()


def test_order_tracking_permissions_and_transitions(client_for, user, other_user, admin_user, catalog):
    client = client_for(user)
    client.post("/api/cart/", {"product_id": catalog["speaker"].pk, "quantity": 1}, format="json")
    order_id = client.post("/api/orders/checkout/", SHIPPING, format="json").data["id"]

    assert client_for(other_user).get(f"/api/orders/{order_id}/").status_code == 404
    assert client.post(f"/api/orders/{order_id}/status/", {"status": "SHIPPED"}, format="json").status_code == 403

    admin = client_for(admin_user)
    assert admin.post(f"/api/orders/{order_id}/status/", {"status": "DELIVERED"}, format="json").status_code == 400
    r = admin.post(f"/api/orders/{order_id}/status/", {"status": "SHIPPED", "note": "Courier picked up"}, format="json")
    assert r.status_code == 200 and [e["status"] for e in r.data["events"]] == ["PENDING", "SHIPPED"]
    assert client.post(f"/api/orders/{order_id}/cancel/").status_code == 400  # shipped orders can't be cancelled


def test_cancel_restores_stock(client_for, user, catalog):
    client = client_for(user)
    client.post("/api/cart/", {"product_id": catalog["shoes"].pk, "quantity": 2}, format="json")
    order_id = client.post("/api/orders/checkout/", SHIPPING, format="json").data["id"]
    assert Product.objects.get(pk=catalog["shoes"].pk).stock == 0
    r = client.post(f"/api/orders/{order_id}/cancel/")
    assert r.status_code == 200 and r.data["status"] == "CANCELLED"
    assert Product.objects.get(pk=catalog["shoes"].pk).stock == 2
