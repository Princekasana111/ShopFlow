from django.contrib import admin

from .models import Cart, CartItem, Category, Order, OrderItem, OrderStatusEvent, Product, Review


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "brand", "price", "stock", "is_active"]
    list_filter = ["category", "is_active"]
    list_editable = ["price", "stock", "is_active"]
    search_fields = ["name", "brand", "description"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["product", "user", "rating", "is_flagged", "created_at"]
    list_filter = ["is_flagged", "rating"]
    search_fields = ["body", "title"]


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ["user", "updated_at"]
    inlines = [CartItemInline]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ["product", "product_name", "unit_price", "quantity"]


class OrderStatusEventInline(admin.TabularInline):
    model = OrderStatusEvent
    extra = 0
    readonly_fields = ["status", "note", "created_at"]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "status", "total", "shipping_city", "created_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["user__username", "shipping_name", "shipping_phone"]
    readonly_fields = ["total", "created_at", "updated_at"]
    inlines = [OrderItemInline, OrderStatusEventInline]
