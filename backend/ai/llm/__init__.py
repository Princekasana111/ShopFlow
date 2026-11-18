"""LLM provider selection.

LLM_PROVIDER=auto      -> Claude if ANTHROPIC_API_KEY is set, else the local model if LOCAL_LLM_URL is set,
                          else offline (default)
LLM_PROVIDER=anthropic -> Claude (the SDK also accepts ANTHROPIC_AUTH_TOKEN or an `ant` profile)
LLM_PROVIDER=local     -> a local model served by Ollama at LOCAL_LLM_URL (free, runs on this machine)
LLM_PROVIDER=offline   -> deterministic rule-based provider, no network, no cost

The chain, best first: Claude -> local model -> offline rules. Each link only answers what it can
(the local model has no vision, doesn't run the assistant's tool loop, and only answers the
features in LOCAL_LLM_FEATURES) and falls through to the next one when it is down, busy or fails.
"""

from __future__ import annotations

import os
from functools import lru_cache

from django.conf import settings

from .base import LLMBusy, LLMError, LLMProvider, LLMRefusal, ParseResult, StreamEvent, TurnResult, Usage

__all__ = [
    "LLMBusy", "LLMError", "LLMProvider", "LLMRefusal", "ParseResult", "StreamEvent", "TurnResult", "Usage",
    "get_agent_llm", "get_llm", "resolve_provider_name",
]


def resolve_provider_name() -> str:
    choice = settings.AI["LLM_PROVIDER"].strip().lower()
    if choice == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        return "local" if settings.AI["LOCAL_LLM_URL"] else "offline"
    if choice not in {"anthropic", "local", "offline"}:
        raise ValueError(f"Unknown LLM_PROVIDER {choice!r}; use auto, anthropic, local or offline.")
    return choice


def _offline() -> LLMProvider:
    from ai.agent.offline_policy import decide_next_turn

    from .offline_provider import OfflineProvider

    return OfflineProvider(agent_policy=decide_next_turn)


def _local_or_offline() -> LLMProvider:
    """The local model with the offline rules behind it, or just the rules if no local model is set up."""
    cfg = settings.AI
    if not cfg["LOCAL_LLM_URL"]:
        return _offline()
    from .local_provider import LocalProvider
    from .resilient import ResilientProvider

    local = LocalProvider(
        cfg["LOCAL_LLM_URL"], cfg["LOCAL_LLM_MODEL"], timeout_seconds=cfg["LOCAL_LLM_TIMEOUT_SECONDS"],
        max_tokens=cfg["LOCAL_LLM_MAX_TOKENS"], features=cfg["LOCAL_LLM_FEATURES"],
    )
    return ResilientProvider(primary=local, backup=_offline(), cooldown_seconds=cfg["LOCAL_LLM_COOLDOWN_SECONDS"])


def _claude():
    from .anthropic_provider import AnthropicProvider

    return AnthropicProvider(model=settings.AI["ANTHROPIC_MODEL"], use_fallbacks=settings.AI["ANTHROPIC_FALLBACKS"])


@lru_cache(maxsize=1)
def get_llm() -> LLMProvider:
    """The provider for structured calls (search parsing, summaries, checks, bargaining...)."""
    name = resolve_provider_name()
    if name == "offline":
        return _offline()
    if name == "local":
        return _local_or_offline()
    claude = _claude()
    if not settings.AI["FALLBACK_TO_OFFLINE"]:
        return claude
    from .resilient import ResilientProvider

    # A bad key, empty credit balance or outage degrades to the local model (if any) and then to
    # offline mode, instead of failing.
    return ResilientProvider(primary=claude, backup=_local_or_offline(), cooldown_seconds=settings.AI["FALLBACK_COOLDOWN_SECONDS"])


@lru_cache(maxsize=1)
def get_agent_llm() -> LLMProvider:
    """The provider for the shopping assistant's tool-use loop: Claude (falling back to the offline
    policy) or the offline policy. The local model is never used here: small models are unreliable at
    multi-step tool use, and slow on a CPU."""
    if resolve_provider_name() != "anthropic":
        return _offline()
    claude = _claude()
    if not settings.AI["FALLBACK_TO_OFFLINE"]:
        return claude
    from .resilient import ResilientProvider

    return ResilientProvider(primary=claude, backup=_offline(), cooldown_seconds=settings.AI["FALLBACK_COOLDOWN_SECONDS"])
