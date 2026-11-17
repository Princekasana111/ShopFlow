from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CartItemView, CartView, CategoryViewSet, OrderViewSet, ProductViewSet

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("products", ProductViewSet, basename="product")
router.register("orders", OrderViewSet, basename="order")

urlpatterns = [
    path("cart/", CartView.as_view(), name="cart"),
    path("cart/items/<int:product_id>/", CartItemView.as_view(), name="cart-item"),
] + router.urls
