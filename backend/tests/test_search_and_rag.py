import pytest

from ai.models import KnowledgeChunk
from ai.query_understanding import heuristic_parse
from ai.rag import chunk_markdown, ingest_knowledge
from ai.search import SearchFilters, rrf_fuse, search_products

pytestmark = pytest.mark.django_db
SLUGS = {"electronics", "footwear", "clothing", "home-kitchen", "books", "sports-fitness"}


def test_rrf_fuse_weights_and_ordering():
    fused = rrf_fuse([[1, 2, 3], [3, 1]], weights=[1.0, 1.0], k=60)
    assert [i for i, _ in fused] == [1, 3, 2]
    # Down-weighting the first list lets the second list's top item win.
    fused = rrf_fuse([[1, 2, 3], [3, 1]], weights=[0.2, 1.0], k=60)
    assert fused[0][0] == 3


@pytest.mark.parametrize("mode", ["keyword", "vector", "hybrid"])
def test_search_modes_find_the_obvious_product(catalog, mode):
    hits = search_products("running shoes", mode=mode, limit=3)
    assert hits and hits[0].product.slug == "stride-runner"


def test_hybrid_reports_where_each_hit_came_from(catalog):
    hit = search_products("bluetooth speaker", mode="hybrid", limit=1)[0]
    assert hit.product.slug == "boombox"
    assert hit.keyword_rank == 1 and hit.vector_rank is not None and hit.similarity is not None


def test_filters_are_applied_before_ranking(catalog):
    hits = search_products("headphones speaker", SearchFilters(category="electronics", max_price=2000), limit=5)
    assert [h.product.slug for h in hits] == ["boombox"]
    hits = search_products("insulated flask", SearchFilters(in_stock_only=True), limit=5)
    assert "flask" not in [h.product.slug for h in hits]


@pytest.mark.parametrize(
    "query, category, min_price, max_price, in_stock",
    [
        ("running shoes under 3k", "footwear", None, 3000, False),
        ("kitchen stuff between 1000 and 2500", "home-kitchen", 1000, 2500, False),
        ("in stock earbuds below ₹2,500", "electronics", None, 2500, True),
        ("gift ideas", None, None, None, False),
    ],
)
def test_heuristic_query_parser(query, category, min_price, max_price, in_stock):
    intent = heuristic_parse(query, SLUGS)
    assert (intent.category_slug, intent.min_price, intent.max_price, intent.in_stock_only) == (category, min_price, max_price, in_stock)


def test_search_api_parses_intent_and_explains_matches(anon_client, catalog):
    r = anon_client.get("/api/ai/search/", {"q": "speaker under 2000"})
    assert r.status_code == 200
    assert r.data["intent"]["max_price"] == 2000 and r.data["filters"]["category"] == "electronics"
    assert r.data["parser"]["provider"] == "offline"
    assert [p["slug"] for p in r.data["results"]] == ["boombox"]
    assert set(r.data["results"][0]["match"]) == {"score", "keyword_rank", "vector_rank", "similarity"}
    assert anon_client.get("/api/ai/search/", {"q": "x", "mode": "nope"}).status_code == 400
    # A non-numeric limit falls back to the default instead of a 500.
    assert anon_client.get("/api/ai/search/", {"q": "speaker", "limit": "abc"}).status_code == 200


def test_similar_products_endpoint(anon_client, catalog):
    r = anon_client.get(f"/api/ai/products/{catalog['headphones'].pk}/similar/")
    assert r.status_code == 200 and len(r.data) == 3
    assert anon_client.get(f"/api/ai/products/{catalog['headphones'].pk}/similar/", {"limit": "abc"}).status_code == 200
    assert catalog["headphones"].pk not in [p["id"] for p in r.data]


def test_chunk_markdown_splits_by_section_with_context_header():
    chunks = chunk_markdown("returns", "# Returns\n\n## Window\nTen days.\n\n## Refunds\nFive days.\n")
    assert [(c.section, c.content) for c in chunks] == [("Window", "Returns › Window\nTen days."), ("Refunds", "Returns › Refunds\nFive days.")]


def test_ingest_is_idempotent(knowledge):
    assert knowledge["chunks"] > 10 and knowledge["embedded"] == knowledge["chunks"]
    again = ingest_knowledge()
    assert again["embedded"] == 0 and again["deleted"] == 0
    assert KnowledgeChunk.objects.count() == knowledge["chunks"]


def test_ask_endpoint_returns_grounded_answer_with_citation(anon_client, knowledge, settings):
    settings.AI = {**settings.AI, "RAG_MIN_SIMILARITY": 0.0}  # threshold is calibrated for bge, not the test embedder
    r = anon_client.post("/api/ai/ask/", {"question": "How long do refunds take for prepaid orders?"}, format="json")
    assert r.status_code == 200
    assert r.data["citations"] and r.data["citations"][0]["doc_slug"] == "returns"
    assert r.data["retrieved"][0]["section"] == "Refund timelines"


def test_ask_endpoint_declines_when_nothing_relevant(anon_client, knowledge, settings):
    settings.AI = {**settings.AI, "RAG_MIN_SIMILARITY": 0.99}
    r = anon_client.post("/api/ai/ask/", {"question": "What is the capital of France?"}, format="json")
    assert r.status_code == 200 and r.data["answerable"] is False and r.data["citations"] == []
