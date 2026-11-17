"""Django settings for ShopFlow.

Every value that differs between environments is read from environment variables
(optionally loaded from a `.env` file in the repo root or in `backend/`).
"""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR.parent / ".env")
load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-secret-key-change-me-in-production")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0,backend")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:3000,http://localhost:5173")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "drf_spectacular",
    "accounts",
    "store",
    "ai",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# PostgreSQL with the pgvector extension (docker image: pgvector/pgvector:pg16).
# Default port 5433 matches the host port published by docker-compose.yml.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "shopflow"),
        "USER": env("POSTGRES_USER", "postgres"),
        "PASSWORD": env("POSTGRES_PASSWORD", "postgres"),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "5433"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
# In development, serve static files straight from the apps (no collectstatic needed).
WHITENOISE_USE_FINDERS = DEBUG
WHITENOISE_AUTOREFRESH = DEBUG

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "shopflow",
    }
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework_simplejwt.authentication.JWTAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticatedOrReadOnly",),
    "DEFAULT_PAGINATION_CLASS": "store.pagination.StandardPagination",
    "PAGE_SIZE": 12,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {
        "auth": env("THROTTLE_AUTH", "20/min"),
        "ai_chat": env("THROTTLE_AI_CHAT", "20/min"),
        "ai_search": env("THROTTLE_AI_SEARCH", "60/min"),
        "ai_admin": env("THROTTLE_AI_ADMIN", "30/min"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(env("JWT_ACCESS_MINUTES", "60"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "ShopFlow API",
    "DESCRIPTION": "E-commerce REST API with GenAI features: hybrid semantic search, RAG, and a tool-calling shopping assistant.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ---------------------------------------------------------------------------
# GenAI configuration
# ---------------------------------------------------------------------------
AI = {
    # "auto" uses Claude when ANTHROPIC_API_KEY is set, otherwise the offline rule-based provider.
    # "anthropic" forces Claude (credentials can also come from an `ant auth login` profile).
    "LLM_PROVIDER": env("LLM_PROVIDER", "auto"),
    "ANTHROPIC_MODEL": env("ANTHROPIC_MODEL", "claude-opus-5-5"),
    # Server-side refusal fallbacks (beta). On a safety-classifier decline the API retries on a
    # fallback model inside the same request instead of failing the user's turn.
    "ANTHROPIC_FALLBACKS": env_bool("ANTHROPIC_FALLBACKS", True),
    # If Claude can't be reached (bad key, no credits, outage), answer with the offline
    # provider instead of failing, and retry Claude after the cool-down.
    "FALLBACK_TO_OFFLINE": env_bool("AI_FALLBACK_TO_OFFLINE", True),
    "FALLBACK_COOLDOWN_SECONDS": float(env("AI_FALLBACK_COOLDOWN_SECONDS", "300")),
    # Claude Opus 5.5 always thinks; effort is the control for depth, latency and cost.
    "EFFORT_ASSISTANT": env("AI_EFFORT_ASSISTANT", "medium"),
    "EFFORT_STRUCTURED": env("AI_EFFORT_STRUCTURED", "low"),
    # Output-token ceilings (thinking counts toward these). They cap worst-case cost per call.
    "MAX_TOKENS_ASSISTANT": int(env("AI_MAX_TOKENS_ASSISTANT", "16000")),
    "MAX_TOKENS_STRUCTURED": int(env("AI_MAX_TOKENS_STRUCTURED", "8000")),
    # Embeddings: "fastembed" runs BAAI/bge-small-en-v1.5 locally on CPU (free, no API key).
    # "hash" is a deterministic hashing embedder used by the test suite.
    "EMBEDDING_PROVIDER": env("EMBEDDING_PROVIDER", "fastembed"),
    "EMBEDDING_MODEL": env("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
    "EMBEDDING_DIM": 384,
    "EMBEDDING_QUERY_PREFIX": env("EMBEDDING_QUERY_PREFIX", ""),
    "FASTEMBED_CACHE_DIR": env("FASTEMBED_CACHE_DIR", str(BASE_DIR / ".cache" / "fastembed")),
    "AUTO_EMBED_ON_SAVE": env_bool("AI_AUTO_EMBED_ON_SAVE", True),
    # Snap & Search (photo search): CLIP maps photos and product text into one vector space.
    # "clip" (local, free), "hash" (tests) or "off".
    "VISUAL_PROVIDER": env("VISUAL_PROVIDER", "clip"),
    "CLIP_VISION_MODEL": "Qdrant/clip-ViT-B-32-vision",
    "CLIP_TEXT_MODEL": "Qdrant/clip-ViT-B-32-text",
    "CLIP_DIM": 512,
    "MAX_UPLOAD_BYTES": 5 * 1024 * 1024,
    # Below this CLIP photo-to-text similarity the match is flagged as uncertain. On 11 test
    # photos (8 labelled product photos + 3 non-product photos), non-product photos scored 0.20-0.24
    # and most products 0.26-0.36.
    "CLIP_LOW_CONFIDENCE": 0.25,
    # AI Shopping Planner relevance gate (bge-small scale): a product can cover a need only if it is
    # within MARGIN of the best match and above MIN_SIMILARITY.
    "PLANNER_RELATIVE_MARGIN": 0.06,
    "PLANNER_MIN_SIMILARITY": 0.6,
    # "Ask this product": min cosine similarity between a question and the product's specs,
    # description or reviews (calibrated for bge-small) before the offline answerer replies.
    "PRODUCT_QA_MIN_SIMILARITY": float(env("AI_PRODUCT_QA_MIN_SIMILARITY", "0.62")),
    # Offline RAG answerer: min cosine similarity (calibrated for bge-small) to answer at all.
    "RAG_MIN_SIMILARITY": float(env("AI_RAG_MIN_SIMILARITY", "0.55")),
    "KNOWLEDGE_DIR": env("AI_KNOWLEDGE_DIR", str(BASE_DIR / "knowledge")),
    "RRF_K": 60,
    # Weight of the keyword list in hybrid fusion (vector = 1.0). Chosen with the search eval.
    "RRF_KEYWORD_WEIGHT": float(env("AI_RRF_KEYWORD_WEIGHT", "0.5")),
    # Assistant guardrails
    "ASSISTANT_MAX_TOOL_ROUNDS": int(env("AI_ASSISTANT_MAX_TOOL_ROUNDS", "6")),
    "ASSISTANT_MAX_MESSAGES": int(env("AI_ASSISTANT_MAX_MESSAGES", "60")),
    "MAX_INPUT_CHARS": int(env("AI_MAX_INPUT_CHARS", "1000")),
    # Model used as the LLM-as-judge in evals (only runs when a live LLM is configured).
    "EVAL_JUDGE_MODEL": env("EVAL_JUDGE_MODEL", "claude-opus-5-5"),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "httpx": {"level": "WARNING"},
        "httpx2": {"level": "WARNING"},
        "huggingface_hub": {"level": "WARNING"},
    },
}
