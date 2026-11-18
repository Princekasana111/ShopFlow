from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class ShopperProfile(models.Model):
    """Sizes and standing needs a shopper has told us about. Used by the purchase check."""

    class ClothingSize(models.TextChoices):
        XS = "XS", "XS"
        S = "S", "S"
        M = "M", "M"
        L = "L", "L"
        XL = "XL", "XL"
        XXL = "XXL", "XXL"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shopper_profile")
    shoe_size_uk = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(15)])
    clothing_size = models.CharField(max_length=3, choices=ClothingSize.choices, blank=True)
    waist_in = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(24), MaxValueValidator(48)])
    needs = models.TextField(
        blank=True, max_length=500,
        help_text="Standing needs in the shopper's words, e.g. 'I cook on induction; my laptop only has USB-C ports'.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile of {self.user}"


def profile_for(user) -> ShopperProfile | None:
    """The user's profile, or None. Reading never creates one."""
    if not getattr(user, "is_authenticated", False):
        return None
    return ShopperProfile.objects.filter(user=user).first()
