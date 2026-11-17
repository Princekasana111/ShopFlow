"""Provider-neutral interface used by every GenAI feature.

Messages and content blocks use the Anthropic Messages API shape
(`{"role": ..., "content": [{"type": "text", ...}, {"type": "tool_use", ...}]}`) as the
canonical internal format. The offline provider reads and writes the same shape, so the
agent loop, persistence and tests are identical whichever provider is active.

Observability lives here, not in the features: `stream_turn()` and `parse()` time every
call and write an `LLMCall` row (tokens, latency, estimated cost, outcome) whether the call
succeeds, is refused, or raises.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Iterator, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """The model call failed (network, API error, truncated output, unparseable output)."""


class LLMRefusal(LLMError):
    """The model (or a safety classifier) declined the request: stop_reason == "refusal"."""

    def __init__(self, message: str = "The model declined this request.", category: str | None = None):
        super().__init__(message)
        self.category = category


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float | None = None


@dataclass
class TurnResult:
    """One assistant turn: the content blocks to append to history, plus metadata."""

    content: list[dict[str, Any]]
    stop_reason: str | None
    model: str
    usage: Usage = field(default_factory=Usage)
    request_id: str = ""
    fallback_used: bool = False
    provider: str = ""

    @property
    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text")

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get("type") == "tool_use"]


@dataclass
class StreamEvent:
    kind: str  # "text" (incremental text delta) or "final" (the complete TurnResult)
    text: str = ""
    result: TurnResult | None = None


@dataclass
class ParseResult(Generic[T]):
    value: T
    model: str
    usage: Usage = field(default_factory=Usage)
    request_id: str = ""
    provider: str = ""


class LLMProvider(ABC):
    name: str = "base"
    model: str = ""
    is_live: bool = False

    # ---- public API (instrumented) -------------------------------------------------

    def stream_turn(
        self,
        *,
        feature: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        effort: str,
        user=None,
    ) -> Iterator[StreamEvent]:
        started = time.perf_counter()
        try:
            for event in self._stream_turn(system=system, messages=messages, tools=tools, max_tokens=max_tokens, effort=effort):
                if event.kind == "final" and event.result is not None:
                    self._record(feature, user, started, result=event.result)
                yield event
        except Exception as exc:
            self._record(feature, user, started, error=exc)
            raise

    def parse(
        self,
        *,
        feature: str,
        system: str,
        messages: list[dict[str, Any]],
        schema: type[T],
        offline: Callable[[], T],
        max_tokens: int,
        effort: str,
        model: str | None = None,
        user=None,
    ) -> ParseResult[T]:
        """Structured output: returns an instance of `schema` validated by Pydantic.

        `offline` is the deterministic implementation the offline provider uses; live
        providers ignore it.
        """
        started = time.perf_counter()
        try:
            result = self._parse(
                system=system, messages=messages, schema=schema, offline=offline,
                max_tokens=max_tokens, effort=effort, model=model,
            )
        except Exception as exc:
            self._record(feature, user, started, error=exc, model=model)
            raise
        self._record(feature, user, started, parse_result=result)
        return result

    # ---- provider implementations -------------------------------------------------

    @abstractmethod
    def _stream_turn(self, *, system, messages, tools, max_tokens, effort) -> Iterator[StreamEvent]: ...

    @abstractmethod
    def _parse(self, *, system, messages, schema, offline, max_tokens, effort, model) -> ParseResult: ...

    # ---- observability -------------------------------------------------------------

    def _record(self, feature, user, started, *, result: TurnResult | None = None,
                parse_result: ParseResult | None = None, error: Exception | None = None, model: str | None = None):
        from ai.models import LLMCall

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = (result.usage if result else parse_result.usage if parse_result else Usage())
        if error is not None:
            status = LLMCall.Status.REFUSAL if isinstance(error, LLMRefusal) else LLMCall.Status.ERROR
        elif result is not None and result.stop_reason == "refusal":
            status = LLMCall.Status.REFUSAL
        else:
            status = LLMCall.Status.OK
        try:
            LLMCall.objects.create(
                feature=feature,
                provider=self.name,
                model=(result.model if result else parse_result.model if parse_result else (model or self.model)),
                user=user if getattr(user, "is_authenticated", False) else None,
                status=status,
                stop_reason=(result.stop_reason or "") if result else ("end_turn" if parse_result else ""),
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_creation_tokens=usage.cache_creation_tokens,
                latency_ms=latency_ms,
                cost_usd=usage.cost_usd,
                fallback_used=bool(result and result.fallback_used),
                request_id=(result.request_id if result else parse_result.request_id if parse_result else ""),
                error=f"{type(error).__name__}: {error}"[:2000] if error else "",
            )
        except Exception:  # observability must never break the feature itself
            logger.exception("Failed to record LLM call")
