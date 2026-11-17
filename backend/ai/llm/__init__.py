"""LLM provider selection.

LLM_PROVIDER=auto      -> Claude if ANTHROPIC_API_KEY is set, otherwise offline (default)
LLM_PROVIDER=anthropic -> Claude (the SDK also accepts ANTHROPIC_AUTH_TOKEN or an `ant` profile)
LLM_PROVIDER=offline   -> deterministic rule-based provider, no network, no cost
"""

from __future__ import annotations

import os
from functools import lru_cache

from django.conf import settings

from .base import LLMError, LLMProvider, LLMRefusal, ParseResult, StreamEvent, TurnResult, Usage

__all__ = [
    "LLMError", "LLMProvider", "LLMRefusal", "ParseResult", "StreamEvent", "TurnResult", "Usage",
    "get_llm", "resolve_provider_name",
]


def resolve_provider_name() -> str:
    choice = settings.AI["LLM_PROVIDER"].strip().lower()
    if choice == "auto":
        return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "offline"
    if choice not in {"anthropic", "offline"}:
        raise ValueError(f"Unknown LLM_PROVIDER {choice!r}; use auto, anthropic or offline.")
    return choice


def _offline() -> LLMProvider:
    from ai.agent.offline_policy import decide_next_turn

    from .offline_provider import OfflineProvider

    return OfflineProvider(agent_policy=decide_next_turn)


@lru_cache(maxsize=1)
def get_llm() -> LLMProvider:
    if resolve_provider_name() != "anthropic":
        return _offline()

    from .anthropic_provider import AnthropicProvider

    claude = AnthropicProvider(model=settings.AI["ANTHROPIC_MODEL"], use_fallbacks=settings.AI["ANTHROPIC_FALLBACKS"])
    if not settings.AI["FALLBACK_TO_OFFLINE"]:
        return claude
    from .resilient import ResilientProvider

    # A bad key, empty credit balance or outage degrades to offline mode instead of failing.
    return ResilientProvider(primary=claude, backup=_offline(), cooldown_seconds=settings.AI["FALLBACK_COOLDOWN_SECONDS"])
