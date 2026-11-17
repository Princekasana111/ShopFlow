from django.core.management.base import BaseCommand

from ai.indexing import embed_products
from ai.visual import embed_products_visual
from store.models import Product


class Command(BaseCommand):
    help = "Embed products into pgvector. Unchanged products are skipped unless --force."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Re-embed every product.")

    def handle(self, *args, **options):
        products = Product.objects.select_related("category").all()
        stats = embed_products(products, force=options["force"])
        self.stdout.write(self.style.SUCCESS(f"Products embedded: {stats['embedded']}, unchanged: {stats['skipped']} (model: {stats['model']})"))
        visual = embed_products_visual(products, force=options["force"])
        self.stdout.write(self.style.SUCCESS(f"Photo-search (CLIP) index: {visual['embedded']} embedded, {visual['skipped']} unchanged (model: {visual['model']})"))
