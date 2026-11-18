"""Work out review summaries, listing checks and fit advice ahead of time.

Run in the background by the container entrypoint. With a slow model (the local one on a CPU) this
means product pages open instantly instead of waiting for three model calls. Results go to the
database (summaries) and the shared database cache (listing checks, fit), so every server process
uses them. Anything that fails falls back to the offline rules and is not stored as the model's
answer, so the next page view tries the model again.
"""

import time

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand

from ai.fit import fit_summary
from ai.listing_check import check_listing
from ai.llm import get_llm
from ai.reviews import get_review_insights
from store.models import Product
from store.sizes import product_sizes


def local_model_ready(timeout_seconds: float) -> bool:
    """Wait until Ollama is up and has the model (it downloads it on first start)."""
    url, model = settings.AI["LOCAL_LLM_URL"].rstrip("/"), settings.AI["LOCAL_LLM_MODEL"]
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            names = {m.get("name") for m in httpx.get(f"{url}/api/tags", timeout=3).json().get("models", [])}
            if model in names or f"{model}:latest" in names:
                return True
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(5)
    return False


class Command(BaseCommand):
    help = "Pre-compute review summaries, listing checks and fit advice for products with reviews."

    def add_arguments(self, parser):
        parser.add_argument("--quiet", action="store_true")
        parser.add_argument("--wait", type=float, default=600, help="Seconds to wait for the local model to be ready.")

    def handle(self, *args, **options):
        say = (lambda *a: None) if options["quiet"] else self.stdout.write
        llm = get_llm()
        if settings.AI["LOCAL_LLM_URL"] and any(llm.handles(f) for f in ("review_summary", "listing_check", "fit_read")):
            ready = local_model_ready(options["wait"])  # only worth waiting for if it does one of these jobs
            say(f"Local model {'ready' if ready else 'not ready; using the offline rules where needed'}.")
        started = time.monotonic()
        done = 0
        for product in Product.objects.filter(is_active=True, reviews__is_flagged=False).distinct().order_by("pk"):
            for name, job in (("summary", get_review_insights), ("listing", check_listing),
                              ("fit", fit_summary if product_sizes(product) else None)):
                if job is None:
                    continue
                try:
                    job(product)
                    done += 1
                except Exception as exc:  # warming must never take the server down
                    self.stderr.write(f"warm_ai: {name} for {product.slug} failed: {exc}")
        say(f"Warmed {done} results in {time.monotonic() - started:.0f} s with {llm.name} ({llm.model}).")
