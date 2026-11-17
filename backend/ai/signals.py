from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from store.models import Product, Review

from . import guardrails
from .indexing import auto_embed_enabled, embed_product_safely


@receiver(post_save, sender=Product, dispatch_uid="ai_embed_product_on_save")
def embed_product_on_save(sender, instance, raw=False, **kwargs):
    if raw or not auto_embed_enabled():
        return
    product_id = instance.pk
    transaction.on_commit(lambda: embed_product_safely(product_id))


@receiver(pre_save, sender=Review, dispatch_uid="ai_flag_injected_review")
def flag_injected_review(sender, instance, raw=False, **kwargs):
    """Indirect prompt-injection defence: reviews end up inside the assistant's tool results."""
    if raw:
        return
    matches = guardrails.detect_prompt_injection(f"{instance.title}\n{instance.body}")
    if matches and not instance.is_flagged:
        instance.is_flagged = True
        guardrails.record_event(
            "review_flagged",
            user=instance.user,
            excerpt=instance.body,
            product_id=instance.product_id,
            patterns=matches,
        )
