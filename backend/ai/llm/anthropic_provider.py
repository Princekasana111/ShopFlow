"""Claude via the official Anthropic Python SDK.

Design notes (Claude Opus 5.5):
* Thinking is always on for this model; `output_config.effort` is the depth/latency/cost knob.
* Server-side refusal fallbacks (beta `server-side-fallback-2026-07-01`, `fallbacks="default"`):
  if a safety classifier declines, the API re-runs the request on a fallback model inside the
  same call instead of failing the customer's turn.
* `response.content` (thinking blocks included) is stored and replayed verbatim: append-only
  history keeps preserved thinking valid and the prompt cache warm.
* Tool definitions are static and the system prompt never changes, so the
  `tools` + `system` prefix is cached across turns and across customers.
"""

from __future__ import annotations

from typing import Any, Iterator

import anthropic
from pydantic import ValidationError

from ..observability import estimate_cost_usd
from .base import LLMError, LLMProvider, LLMRefusal, ParseResult, StreamEvent, TurnResult, Usage

FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Block types that are safe to echo from before a mid-output fallback boundary.
_ECHO_BEFORE_FALLBACK = {"text"}


def sanitize_for_echo(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prepare a response's content for replay after a server-side fallback.

    After a mid-output fallback the API requires that thinking / redacted_thinking /
    tool_use (and other model-internal) blocks that appear *before* the final `fallback`
    block are omitted, while the `fallback` block itself stays exactly where it was.
    Text blocks and everything after the boundary are kept. Without a fallback block the
    content is returned unchanged.
    """
    boundary = max((i for i, b in enumerate(content) if b.get("type") == "fallback"), default=None)
    if boundary is None:
        return content
    kept = [b for b in content[:boundary] if b.get("type") in _ECHO_BEFORE_FALLBACK]
    return kept + content[boundary:]


def _usage_from_response(message, requested_model: str) -> tuple[Usage, bool]:
    """Sum usage over every attempt (a fallback adds attempts) and estimate cost per model."""
    usage = message.usage
    iterations = getattr(usage, "iterations", None) or []
    attempts = [it for it in iterations if getattr(it, "type", "") in ("message", "fallback_message")]
    fallback_used = any(getattr(it, "type", "") == "fallback_message" for it in iterations)
    if not attempts:
        attempts = [usage]

    total = Usage()
    cost: float | None = 0.0
    for attempt in attempts:
        model = getattr(attempt, "model", None) or (message.model if attempt is usage else requested_model)
        inp = attempt.input_tokens or 0
        out = attempt.output_tokens or 0
        cr = getattr(attempt, "cache_read_input_tokens", 0) or 0
        cc = getattr(attempt, "cache_creation_input_tokens", 0) or 0
        total.input_tokens += inp
        total.output_tokens += out
        total.cache_read_tokens += cr
        total.cache_creation_tokens += cc
        attempt_cost = estimate_cost_usd(str(model), inp, out, cr, cc)
        cost = None if (cost is None or attempt_cost is None) else cost + attempt_cost
    total.cost_usd = round(cost, 6) if cost is not None else None
    return total, fallback_used


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    is_live = True

    def __init__(self, model: str, use_fallbacks: bool = True, client: anthropic.Anthropic | None = None):
        self.model = model
        self.use_fallbacks = use_fallbacks
        self.client = client or anthropic.Anthropic(max_retries=2, timeout=120.0)

    def _fallback_kwargs(self) -> dict[str, Any]:
        if not self.use_fallbacks:
            return {}
        return {"betas": [FALLBACK_BETA], "fallbacks": "default"}

    # ---- agent turns (streaming + tools) -------------------------------------------

    def _stream_turn(self, *, system, messages, tools, max_tokens, effort) -> Iterator[StreamEvent]:
        # eager_input_streaming streams tool inputs as they are generated. With it on, the
        # API no longer validates tool inputs, so every input is validated with Pydantic in
        # ai/agent/tools.py before a tool runs.
        tool_defs = [{**tool, "eager_input_streaming": True} for tool in tools]
        try:
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=tool_defs,
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                cache_control={"type": "ephemeral"},
                **self._fallback_kwargs(),
            ) as stream:
                for event in stream:
                    if event.type == "text":
                        yield StreamEvent(kind="text", text=event.text)
                final = stream.get_final_message()
                request_id = stream.request_id or ""
        except ValueError as exc:
            # The SDK raises ValueError from the stream iterator when a tool input is not
            # parseable JSON at all. API errors are not ValueError and propagate unchanged.
            raise LLMError(f"Model produced an unparseable tool input: {exc}") from exc
        except anthropic.APIError as exc:
            raise LLMError(f"Anthropic API error: {exc}") from exc

        usage, fallback_used = _usage_from_response(final, self.model)
        content = [block.to_dict(mode="json") for block in final.content]
        result = TurnResult(
            content=sanitize_for_echo(content),
            stop_reason=final.stop_reason,
            model=final.model,
            usage=usage,
            request_id=request_id,
            fallback_used=fallback_used,
            provider=self.name,
        )
        yield StreamEvent(kind="final", result=result)

    # ---- structured outputs -------------------------------------------------------

    def _parse(self, *, system, messages, schema, offline, max_tokens, effort, model) -> ParseResult:
        model = model or self.model
        try:
            response = self.client.beta.messages.parse(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                output_format=schema,
                output_config={"effort": effort},
                **self._fallback_kwargs(),
            )
        except anthropic.APIError as exc:
            raise LLMError(f"Anthropic API error: {exc}") from exc
        except ValidationError as exc:
            raise LLMError(f"Structured output failed validation: {exc}") from exc

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise LLMRefusal(category=getattr(details, "category", None))
        if response.stop_reason == "max_tokens":
            raise LLMError("Structured output was truncated (max_tokens reached).")
        value = response.parsed_output
        if value is None:
            raise LLMError("Model returned no structured output.")
        usage, _ = _usage_from_response(response, model)
        return ParseResult(value=value, model=response.model, usage=usage, request_id=getattr(response, "_request_id", "") or "", provider=self.name)
