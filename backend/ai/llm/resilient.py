"""A provider with an automatic fallback: Claude -> (local model ->) offline rules.

If a call to the primary fails (invalid or expired key, no credits, network down, API outage, the
local model not running or timing out), the request is answered by the backup instead of failing,
and the primary is skipped for a cool-down period so customers don't wait on a dead dependency every
time. Failed calls are still logged as errors in `LLMCall`, so the outage is visible on the AI
dashboard.

Requests the primary can't or shouldn't answer go straight to the backup without counting as a
failure: images when it has no vision, the assistant's tool loop when it doesn't run agents, features
it doesn't handle, and calls it turns away because it is busy (`LLMBusy`).

Not a fallback trigger: refusals (a policy decision, handled by the API's own refusal fallbacks) and
failures after text has already streamed to the customer.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Iterator

from .base import LLMBusy, LLMError, LLMProvider, LLMRefusal, ParseResult, StreamEvent

logger = logging.getLogger(__name__)


class ResilientProvider(LLMProvider):
    def __init__(self, primary: LLMProvider, backup: LLMProvider, cooldown_seconds: float = 300.0):
        self.primary = primary
        self.backup = backup
        self.cooldown_seconds = cooldown_seconds
        self.name = primary.name    # sessions stay pinned to the primary provider
        self.model = primary.model
        self._down_until = 0.0
        self.last_error = ""
        self._lock = threading.Lock()

    # ---- health ---------------------------------------------------------------------

    @property
    def degraded(self) -> bool:
        return time.monotonic() < self._down_until

    @property
    def is_live(self) -> bool:
        return not self.degraded

    @property
    def supports_vision(self) -> bool:
        return (not self.degraded and self.primary.supports_vision) or self.backup.supports_vision

    @property
    def supports_agent(self) -> bool:
        return (not self.degraded and self.primary.supports_agent) or self.backup.supports_agent

    def handles(self, feature: str) -> bool:
        return (not self.degraded and self.primary.handles(feature)) or self.backup.handles(feature)

    def _trip(self, exc: Exception) -> None:
        with self._lock:
            self._down_until = time.monotonic() + self.cooldown_seconds
            self.last_error = f"{type(exc).__name__}: {exc}"[:300]
        logger.warning("%s unavailable, using the fallback for %ss: %s", self.primary.name, self.cooldown_seconds, exc)

    def reset(self) -> None:
        self._down_until = 0.0
        self.last_error = ""

    # ---- calls (the wrapped providers do their own LLMCall logging) ------------------

    def stream_turn(self, **kwargs) -> Iterator[StreamEvent]:
        if not self.degraded and self.primary.supports_agent:
            streamed_text = False
            try:
                for event in self.primary.stream_turn(**kwargs):
                    streamed_text = streamed_text or event.kind == "text"
                    yield event
                return
            except LLMError as exc:
                if streamed_text or isinstance(exc, LLMRefusal):
                    raise  # the customer already saw partial output; don't splice in another answer
                self._trip(exc)
        yield from self.backup.stream_turn(**kwargs)

    def parse(self, **kwargs) -> ParseResult:
        if not self.degraded and self._primary_can(kwargs):
            try:
                return self.primary.parse(**kwargs)
            except LLMRefusal:
                raise
            except LLMBusy:
                pass  # busy, not down: answer this one with the backup, no cool-down
            except LLMError as exc:
                self._trip(exc)
        return self.backup.parse(**kwargs)

    def _primary_can(self, kwargs) -> bool:
        if not self.primary.handles(kwargs.get("feature", "")):
            return False
        has_image = any(isinstance(m.get("content"), list) and any(b.get("type") == "image" for b in m["content"])
                        for m in kwargs.get("messages", []))
        return self.primary.supports_vision or not has_image

    def _stream_turn(self, **kwargs):  # pragma: no cover - public methods are overridden
        raise NotImplementedError

    def _parse(self, **kwargs):  # pragma: no cover
        raise NotImplementedError
