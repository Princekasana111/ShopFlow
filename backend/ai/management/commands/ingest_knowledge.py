from django.core.management.base import BaseCommand

from ai.rag import ingest_knowledge


class Command(BaseCommand):
    help = "Chunk and embed the help-center markdown files (backend/knowledge/*.md) for RAG."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=None, help="Directory of .md files (default: settings.AI['KNOWLEDGE_DIR']).")

    def handle(self, *args, **options):
        stats = ingest_knowledge(options["dir"])
        self.stdout.write(self.style.SUCCESS(
            f"Documents: {stats['documents']}, chunks: {stats['chunks']}, embedded: {stats['embedded']}, "
            f"deleted: {stats['deleted']} (model: {stats['model']})"
        ))
