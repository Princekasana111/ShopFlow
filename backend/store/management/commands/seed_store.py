import json
import os
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import ShopperProfile
from store import services
from store.models import Category, Order, Product, Review

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "catalog.json"


class Command(BaseCommand):
    help = "Create the demo catalog, reviews, users and sample orders if missing. Never overwrites existing rows."

    @transaction.atomic
    def handle(self, *args, **options):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        User = get_user_model()

        admin_password = os.environ.get("SEED_ADMIN_PASSWORD", "admin12345")
        demo_password = os.environ.get("SEED_DEMO_PASSWORD", "demo12345")
        admin, created = User.objects.get_or_create(username="admin", defaults={"email": "admin@shopflow.example", "is_staff": True, "is_superuser": True})
        if created:
            admin.set_password(admin_password)
            admin.save()
        demo, created = User.objects.get_or_create(username="demo", defaults={"email": "demo@shopflow.example"})
        if created:
            demo.set_password(demo_password)
            demo.save()

        categories = {}
        for c in data["categories"]:
            categories[c["slug"]], _ = Category.objects.get_or_create(slug=c["slug"], defaults={"name": c["name"], "description": c["description"]})

        for p in data["products"]:
            # get_or_create, not update_or_create: the container runs this on every start, and it
            # must never undo sold stock or edits made in the admin or the AI copywriter.
            Product.objects.get_or_create(
                slug=p["slug"],
                defaults={
                    "name": p["name"],
                    "brand": p["brand"],
                    "category": categories[p["category"]],
                    "price": p["price"],
                    "stock": p["stock"],
                    "description": p["description"],
                    "attributes": p["attributes"],
                    "is_active": True,
                },
            )

        for r in data["reviews"]:
            reviewer, created = User.objects.get_or_create(username=r["user"], defaults={"email": f"{r['user']}@shopflow.example"})
            if created:
                reviewer.set_unusable_password()
                reviewer.save()
            if not Review.objects.filter(product__slug=r["product"], user=reviewer).exists():
                Review.objects.create(
                    product=Product.objects.get(slug=r["product"]), user=reviewer,
                    rating=r["rating"], title=r["title"], body=r["body"],
                    size_bought=r.get("size_bought", ""), fit=r.get("fit", ""),
                )

        # Saved sizes and standing needs for the demo customer, used by the purchase check. Created
        # before the sample orders so the running shoes in them get the saved size.
        ShopperProfile.objects.get_or_create(user=demo, defaults={
            "shoe_size_uk": 9, "clothing_size": "M", "waist_in": 32,
            "needs": "I run outdoors most mornings, often in the rain. I cook on an induction stove. My laptop only has USB-C ports.",
        })

        if not Order.objects.filter(user=demo).exists():
            self._sample_orders(demo)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {Category.objects.count()} categories, {Product.objects.count()} products, "
            f"{Review.objects.count()} reviews ({Review.objects.filter(is_flagged=True).count()} flagged by the guardrail)."
        ))
        self.stdout.write("Logins: admin / (SEED_ADMIN_PASSWORD or 'admin12345'), demo / (SEED_DEMO_PASSWORD or 'demo12345')")

    def _sample_orders(self, demo):
        shipping = services.ShippingDetails(name="Demo Customer", phone="9876543210", address="12 MG Road", city="Bengaluru", pincode="560001")
        for slugs, final_status in [
            (["thermosteel-insulated-flask-1l", "grippro-anti-slip-yoga-mat"], Order.Status.DELIVERED),
            (["stride-runner-road-running-shoes"], Order.Status.SHIPPED),
        ]:
            for slug in slugs:
                services.add_to_cart(demo, Product.objects.get(slug=slug).pk, 1)
            order = services.checkout(demo, shipping)
            services.update_order_status(order, Order.Status.SHIPPED, "Handed to courier")
            if final_status == Order.Status.DELIVERED:
                services.update_order_status(order, Order.Status.DELIVERED, "Delivered")
