from django.db.models import Avg, Count, Q

from .models import Product


def annotated_products():
    """Products with their average rating and review count (flagged reviews excluded)."""
    return Product.objects.select_related("category").annotate(
        avg_rating=Avg("reviews__rating", filter=Q(reviews__is_flagged=False)),
        review_count=Count("reviews", filter=Q(reviews__is_flagged=False)),
    )
