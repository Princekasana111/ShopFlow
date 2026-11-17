"""Claude with an automatic offline fallback.

If a Claude call fails (invalid or expired key, no credits, network down, API outage), the
request is answered by the offline provider instead of failing, and Claude is skipped for a
cool-down period so customers don't wait on a dead dependency every time. Failed calls are
still logged as errors in `LLMCall`, so the outage is visible on the AI dashboard.

Not a fallback trigger: refusals (a policy decision, handled by the API's own refusal
fallbacks) and failures after text has already streamed to the customer.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Iterator

from .base import LLMError, LLMProvider, LLMRefusal, ParseResult, StreamEvent

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

    def _trip(self, exc: Exception) -> None:
        with self._lock:
            self._down_until = time.monotonic() + self.cooldown_seconds
            self.last_error = f"{type(exc).__name__}: {exc}"[:300]
        logger.warning("Claude unavailable, using offline fallback for %ss: %s", self.cooldown_seconds, exc)

    def reset(self) -> None:
        self._down_until = 0.0
        self.last_error = ""

    # ---- calls (the wrapped providers do their own LLMCall logging) ------------------

    def stream_turn(self, **kwargs) -> Iterator[StreamEvent]:
        if not self.degraded:
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
        if not self.degraded:
            try:
                return self.primary.parse(**kwargs)
            except LLMRefusal:
                raise
            except LLMError as exc:
                self._trip(exc)
        return self.backup.parse(**kwargs)

    def _stream_turn(self, **kwargs):  # pragma: no cover - public methods are overridden
        raise NotImplementedError

    def _parse(self, **kwargs):  # pragma: no cover
        raise NotImplementedError
