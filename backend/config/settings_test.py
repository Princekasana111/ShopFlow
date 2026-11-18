"""Settings for the pytest suite: deterministic, offline, and fast."""

from .settings import *  # noqa: F401,F403
from .settings import AI, REST_FRAMEWORK

AI.update(
    {
        "LLM_PROVIDER": "offline",
        "LOCAL_LLM_URL": "",  # tests never call a local model (the provider is tested with a mock transport)
        "EMBEDDING_PROVIDER": "hash",
        "VISUAL_PROVIDER": "hash",
        "PLANNER_MIN_SIMILARITY": 0.0,
        "AUTO_EMBED_ON_SAVE": True,
    }
)

# Throttle rates are raised so no test hits a 429 by accident.
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "auth": "1000/min",
    "ai_chat": "1000/min",
    "ai_search": "1000/min",
    "ai_admin": "1000/min",
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "shopflow-tests"}}

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
