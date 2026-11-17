from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from store.models import Category, Product


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def make_user(db):
    def _make(username="alice", staff=False, password="Str0ng-pass!"):
        user = get_user_model().objects.create_user(username=username, email=f"{username}@example.com", password=password)
        if staff:
            user.is_staff = True
            user.save()
        return user

    return _make


@pytest.fixture
def user(make_user):
    return make_user("alice")


@pytest.fixture
def other_user(make_user):
    return make_user("bob")


@pytest.fixture
def admin_user(make_user):
    return make_user("boss", staff=True)


def _client_for(user):
    client = APIClient()
    if user is not None:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def anon_client():
    return APIClient()


@pytest.fixture
def client_for():
    return _client_for


@pytest.fixture
def catalog(db, django_capture_on_commit_callbacks):
    """A small catalog; product embeddings are created by the post_save signal (hash embedder)."""
    with django_capture_on_commit_callbacks(execute=True):
        electronics = Category.objects.create(name="Electronics", slug="electronics")
        footwear = Category.objects.create(name="Footwear", slug="footwear")
        home = Category.objects.create(name="Home & Kitchen", slug="home-kitchen")
        products = {
            "headphones": Product.objects.create(
                category=electronics, name="Aurora ANC Wireless Headphones", slug="aurora", brand="Sonora",
                description="Over-ear bluetooth headphones with active noise cancellation for flights.",
                price=Decimal("7999.00"), stock=5, attributes={"battery": "30 hours"},
            ),
            "speaker": Product.objects.create(
                category=electronics, name="Boombox Mini Bluetooth Speaker", slug="boombox", brand="Volt",
                description="Portable waterproof speaker for the beach and pool parties.",
                price=Decimal("1799.00"), stock=10,
            ),
            "shoes": Product.objects.create(
                category=footwear, name="Stride Runner Road Running Shoes", slug="stride-runner", brand="Stride",
                description="Lightweight running shoes with foam cushioning for road runs.",
                price=Decimal("3299.00"), stock=2,
            ),
            "flask": Product.objects.create(
                category=home, name="ThermoSteel Insulated Flask", slug="flask", brand="Hearth",
                description="Vacuum insulated flask keeps tea or coffee hot for 24 hours.",
                price=Decimal("1199.00"), stock=0,
            ),
        }
    return products


@pytest.fixture
def knowledge(db):
    from ai.rag import ingest_knowledge

    return ingest_knowledge()
