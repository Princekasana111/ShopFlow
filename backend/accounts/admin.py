from django.contrib import admin

from .models import ShopperProfile


@admin.register(ShopperProfile)
class ShopperProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "shoe_size_uk", "clothing_size", "waist_in", "updated_at"]
    search_fields = ["user__username"]
