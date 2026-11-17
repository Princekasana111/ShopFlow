from django.core.management import call_command
from django.core.management.base import BaseCommand

from ai.indexing import suspend_auto_embed


class Command(BaseCommand):
    help = "Seed demo data, then build the vector indexes (products + help center) in one batch."

    def handle(self, *args, **options):
        with suspend_auto_embed():
            call_command("seed_store")
        call_command("embed_catalog")
        call_command("ingest_knowledge")
