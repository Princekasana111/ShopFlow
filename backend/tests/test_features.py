import pytest

from ai.evals import metrics
from ai.models import ReviewSummary
from store.models import Review

pytestmark = pytest.mark.django_db


def test_ir_metrics():
    ranked = ["a", "b", "c", "d"]
    assert metrics.recall_at_k(ranked, {"b", "z"}, 2) == 0.5
    assert metrics.reciprocal_rank(ranked, {"c"}) == pytest.approx(1 / 3)
    assert metrics.hit_at_k(ranked, {"a"}, 1) == 1.0
    assert metrics.ndcg_at_k(ranked, {"a"}, 10) == 1.0
    assert metrics.ndcg_at_k(["x", "a"], {"a"}, 10) == pytest.approx(0.6309, abs=1e-4)


def test_copywriter_is_staff_only_and_returns_structured_copy(client_for, user, admin_user, catalog):
    payload = {"product_id": catalog["headphones"].pk, "tone": "premium"}
    assert client_for(user).post("/api/ai/copywriter/", payload, format="json").status_code == 403
    r = client_for(admin_user).post("/api/ai/copywriter/", payload, format="json")
    assert r.status_code == 200
    assert set(r.data["copy"]) == {"headline", "description", "highlights", "tags", "seo_meta_description"}
    assert 3 <= len(r.data["copy"]["highlights"]) <= 5 and len(r.data["copy"]["seo_meta_description"]) <= 160
    assert r.data["warnings"] == []


def test_review_insights_are_cached_until_reviews_change(anon_client, catalog, make_user):
    url = f"/api/ai/products/{catalog['speaker'].pk}/review-insights/"
    assert anon_client.get(url).data["available"] is False
    for name, rating, body in [("u1", 5, "Loud and waterproof. Great at the beach."), ("u2", 2, "Bass distorts at full volume.")]:
        Review.objects.create(product=catalog["speaker"], user=make_user(name), rating=rating, body=body)
    first = anon_client.get(url).data
    assert first["available"] and not first["cached"] and first["sentiment"] in {"positive", "mixed", "negative"}
    assert anon_client.get(url).data["cached"] is True
    Review.objects.create(product=catalog["speaker"], user=make_user("u3"), rating=4, body="Good battery life.")
    assert anon_client.get(url).data["cached"] is False
    assert ReviewSummary.objects.count() == 1


def test_status_endpoint(anon_client, catalog):
    data = anon_client.get("/api/ai/status/").data
    assert data["llm"] == {"provider": "offline", "model": "rule-based-v1", "is_live": False, "degraded": False}
    assert data["index"]["product_embeddings"] == 4
