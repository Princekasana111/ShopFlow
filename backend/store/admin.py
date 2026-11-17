from django.contrib import admin, messages

from . import services

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


def _set_status(modeladmin, request, queryset, status, note):
    updated = 0
    for order in queryset:
        try:
            services.update_order_status(order, status, note)
            updated += 1
        except services.OrderStatusError as exc:
            modeladmin.message_user(request, f"Order #{order.pk}: {exc}", level=messages.WARNING)
    if updated:
        modeladmin.message_user(request, f"Updated {updated} order(s).")


@admin.action(description="Mark selected orders as shipped")
def mark_shipped(modeladmin, request, queryset):
    _set_status(modeladmin, request, queryset, Order.Status.SHIPPED, "Handed to courier")


@admin.action(description="Mark selected orders as delivered")
def mark_delivered(modeladmin, request, queryset):
    _set_status(modeladmin, request, queryset, Order.Status.DELIVERED, "Delivered")


@admin.action(description="Cancel selected orders (restores stock)")
def cancel_orders(modeladmin, request, queryset):
    _set_status(modeladmin, request, queryset, Order.Status.CANCELLED, "Cancelled by staff")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "status", "total", "shipping_city", "created_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["user__username", "shipping_name", "shipping_phone"]
    # Status is read-only here: editing it directly would skip the transition rules, the status
    # history and the restock on cancel. Use the actions instead, which call store.services.
    readonly_fields = ["status", "total", "created_at", "updated_at"]
    actions = [mark_shipped, mark_delivered, cancel_orders]
    inlines = [OrderItemInline, OrderStatusEventInline]
