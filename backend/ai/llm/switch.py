"""The staff on/off switch for the local model.

Off means the site stops using the local model at once: every feature it handled goes to the next
provider (Claude if a key is set, otherwise the offline rules). The switch is saved in the database,
so it holds across server processes and restarts, and each process re-reads it at most every few
seconds. Turning it off also asks Ollama to unload the model (freeing about 2.3 GB of memory);
turning it on loads it again in the background, so the first answer isn't slowed by loading.
"""

from __future__ import annotations

import threading
import time

import httpx
from django.conf import settings

KEY = "local_llm"
RECHECK_SECONDS = 3.0

_lock = threading.Lock()
_cached = {"value": True, "until": 0.0}


def local_switch_on(fresh: bool = False) -> bool:
    """Whether staff have the local model switched on (default: on). Never raises. Requests re-read it
    at most every few seconds; `fresh` reads the database now (the status badge and the switch card)."""
    now = time.monotonic()
    if not fresh and now < _cached["until"]:
        return _cached["value"]
    try:
        from ai.models import RuntimeSetting

        row = RuntimeSetting.objects.filter(key=KEY).first()
        value = bool(row.value.get("on", True)) if row else True
    except Exception:  # the database being briefly unavailable must not break AI features
        value = _cached["value"]
    with _lock:
        _cached.update(value=value, until=now + RECHECK_SECONDS)
    return value


def _ollama(payload: dict, timeout: float) -> str:
    """Ask Ollama to load or unload the model. Best effort: returns "" or a short error, never raises."""
    try:
        r = httpx.post(f"{settings.AI['LOCAL_LLM_URL'].rstrip('/')}/api/generate", json=payload, timeout=timeout)
        return "" if r.status_code == 200 else f"Ollama answered HTTP {r.status_code}"
    except Exception as exc:
        return f"Ollama couldn't be reached ({type(exc).__name__})"


def set_local_switch(on: bool, user=None) -> dict:
    from ai.models import RuntimeSetting

    RuntimeSetting.objects.update_or_create(key=KEY, defaults={"value": {"on": on}, "updated_by": user if getattr(user, "is_authenticated", False) else None})
    with _lock:
        _cached.update(value=on, until=time.monotonic() + RECHECK_SECONDS)
    model = settings.AI["LOCAL_LLM_MODEL"]
    note = ""
    if not on:
        note = _ollama({"model": model, "keep_alive": 0}, timeout=10)  # unload: frees the memory
    else:
        # load it in the background (it can take ~20 s on a CPU), so the button answers at once
        threading.Thread(target=_ollama, args=({"model": model, "keep_alive": "30m"}, 120), daemon=True).start()
    return {"on": on, "note": note}
