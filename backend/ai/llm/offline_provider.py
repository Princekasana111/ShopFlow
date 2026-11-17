"""Deterministic, rule-based stand-in for an LLM.

Lets the whole app (search, RAG, assistant, copywriter, evals) run with no API key and no
cost, and makes the test suite deterministic. It is clearly labelled as "offline" in API
responses and in the UI; it is not presented as AI output.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

from .base import LLMProvider, ParseResult, StreamEvent, TurnResult, Usage

# The agent policy decides the next assistant turn from the conversation so far.
AgentPolicy = Callable[[list[dict[str, Any]], list[dict[str, Any]]], list[dict[str, Any]]]


class OfflineProvider(LLMProvider):
    name = "offline"
    model = "rule-based-v1"
    is_live = False

    def __init__(self, agent_policy: AgentPolicy):
        self.agent_policy = agent_policy

    def _stream_turn(self, *, system, messages, tools, max_tokens, effort) -> Iterator[StreamEvent]:
        content = self.agent_policy(messages, tools)
        for block in content:
            if block["type"] == "text":
                # Emit word by word so the UI exercises the same streaming path as Claude.
                words = block["text"].split(" ")
                for i, word in enumerate(words):
                    yield StreamEvent(kind="text", text=word if i == 0 else " " + word)
        stop_reason = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
        yield StreamEvent(
            kind="final",
            result=TurnResult(content=content, stop_reason=stop_reason, model=self.model, usage=Usage(cost_usd=0.0), provider=self.name),
        )

    def _parse(self, *, system, messages, schema, offline, max_tokens, effort, model) -> ParseResult:
        value = offline()
        if not isinstance(value, schema):
            value = schema.model_validate(value)
        return ParseResult(value=value, model=self.model, usage=Usage(cost_usd=0.0), provider=self.name)
