"""Add size options to the seeded clothing and footwear products (see store.sizes).

Only adds `attributes["sizes"]` where it is missing; never overwrites other attributes or edits.
"""

from django.db import migrations

SIZES = {
    "trailblazer-waterproof-hiking-boots": "UK 6, UK 7, UK 8, UK 9, UK 10, UK 11",
    "stride-runner-road-running-shoes": "UK 6, UK 7, UK 8, UK 9, UK 10, UK 11",
    "stride-aqua-waterproof-running-shoes": "UK 6, UK 7, UK 8, UK 9, UK 10, UK 11",
    "cloudwalk-everyday-sneakers": "UK 6, UK 7, UK 8, UK 9, UK 10, UK 11",
    "comfortflex-sandals": "UK 5, UK 6, UK 7, UK 8, UK 9, UK 10",
    "homesoft-memory-foam-slippers": "UK 6, UK 7, UK 8, UK 9, UK 10, UK 11",
    "classic-leather-oxford-shoes": "UK 6, UK 7, UK 8, UK 9, UK 10",
    "courtpro-badminton-shoes": "UK 6, UK 7, UK 8, UK 9, UK 10, UK 11",
    "kids-light-up-sneakers": "Age 4-5, Age 5-6, Age 6-7, Age 7-8",
    "monsoon-rubber-flip-flops": "UK 6, UK 7, UK 8, UK 9, UK 10, UK 11",
    "drymax-sports-t-shirt": "S, M, L, XL, XXL",
    "organic-cotton-crew-neck-tee": "XS, S, M, L, XL",
    "windproof-puffer-jacket": "S, M, L, XL",
    "packable-rain-jacket": "S, M, L, XL, XXL",
    "flexfit-slim-jeans": "28, 30, 32, 34, 36",
    "linen-blend-casual-shirt": "S, M, L, XL",
    "festive-cotton-kurta": "S, M, L, XL, XXL",
    "fleece-zip-hoodie": "S, M, L, XL",
    "merino-wool-socks-pack-of-3": "UK 3-6, UK 7-11",
    "yogaflex-high-waist-leggings": "XS, S, M, L, XL",
}


def add_sizes(apps, schema_editor):
    Product = apps.get_model("store", "Product")
    for product in Product.objects.filter(slug__in=SIZES):
        attributes = dict(product.attributes or {})
        if "sizes" not in attributes:
            attributes["sizes"] = SIZES[product.slug]
            Product.objects.filter(pk=product.pk).update(attributes=attributes)


class Migration(migrations.Migration):
    dependencies = [("store", "0002_cartitem_size_orderitem_size")]
    operations = [migrations.RunPython(add_sizes, migrations.RunPython.noop)]
