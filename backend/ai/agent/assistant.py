"""The shopping assistant's agent loop.

    customer message
      -> input guardrails (length, prompt-injection patterns)
      -> loop: stream one model turn -> run the requested tools as the signed-in customer
               -> feed results back, until the model answers without tools
               (bounded by ASSISTANT_MAX_TOOL_ROUNDS)
      -> output grounding check (every price in the answer must come from a tool result)
      -> persist and emit events for the UI

`run_turn` is a generator of plain-dict events; the HTTP view turns them into Server-Sent
Events and the eval runner consumes them directly.

History handling: messages are persisted append-only and replayed verbatim, thinking blocks
included. An assistant message that requested tools is saved together with its tool results
in one transaction, so a crash can never leave a `tool_use` without its `tool_result`.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

from django.conf import settings
from django.db import transaction
from django.db.models import Max

from .. import guardrails
from ..llm import LLMError, LLMProvider, Usage, get_llm
from ..models import ChatMessage, ChatSession
from .prompts import SYSTEM_PROMPT
from .tools import ToolContext, ToolOutcome, execute_tool, tool_definitions

MAX_PRODUCT_CARDS = 6


class SessionNotFound(Exception):
    pass


def _event(event: str, /, **data: Any) -> dict:
    return {"event": event, "data": data}


def _next_seq(session: ChatSession) -> int:
    current = session.messages.aggregate(m=Max("seq"))["m"]
    return 0 if current is None else current + 1


def _persist(session: ChatSession, messages: list[tuple[dict, dict | None]]) -> list[ChatMessage]:
    with transaction.atomic():
        seq = _next_seq(session)
        saved = []
        for offset, (message, display) in enumerate(messages):
            saved.append(
                ChatMessage.objects.create(
                    session=session, seq=seq + offset, role=message["role"], content=message["content"], display=display
                )
            )
    return saved


def _session_for(user, session_id: str | None, llm: LLMProvider, first_message: str) -> tuple[ChatSession, bool]:
    """Return (session, is_new). A session stays on the provider/model that started it."""
    if session_id:
        session = ChatSession.objects.filter(id=session_id, user=user).first()
        if session is None:
            raise SessionNotFound(session_id)
        if session.provider == llm.name and session.model == llm.model:
            return session, False
    title = first_message.strip().splitlines()[0][:80] if first_message.strip() else "New chat"
    return ChatSession.objects.create(user=user, title=title, provider=llm.name, model=llm.model), True


def _evidence_from_history(history: list[dict]) -> list[str]:
    evidence = []
    for message in history:
        if message["role"] == "user" and isinstance(message["content"], list):
            evidence.extend(str(b.get("content", "")) for b in message["content"] if b.get("type") == "tool_result")
    return evidence


def run_turn(*, user, message: str, session_id: str | None = None, llm: LLMProvider | None = None) -> Iterator[dict]:
    cfg = settings.AI
    llm = llm or get_llm()
    started = time.perf_counter()

    session, is_new = _session_for(user, session_id, llm, message)
    yield _event(
        "session",
        session_id=str(session.id),
        is_new=is_new,
        provider=llm.name,
        model=llm.model,
        is_live=llm.is_live,
        degraded=getattr(llm, "degraded", False),
    )

    # ---- input guardrails ---------------------------------------------------------
    check = guardrails.check_user_message(message)
    if not check.allowed:
        if check.kind in ("prompt_injection", "input_too_long"):
            guardrails.record_event(check.kind, user=user, excerpt=message, patterns=check.matches)
        # Blocked messages are never sent to the model and never enter the replayed history.
        yield _event("text", delta=check.reply)
        yield _event("done", blocked=True, reason=check.kind, latency_ms=int((time.perf_counter() - started) * 1000))
        return

    if session.messages.count() >= cfg["ASSISTANT_MAX_MESSAGES"]:
        yield _event("error", message="This conversation has reached its length limit. Please start a new chat.")
        return

    history = [{"role": m.role, "content": m.content} for m in session.messages.order_by("seq")]
    user_message = {"role": "user", "content": [{"type": "text", "text": message.strip()}]}
    _persist(session, [(user_message, {"text": message.strip()})])
    messages = history + [user_message]

    tools = tool_definitions()
    ctx = ToolContext(user=user)
    evidence = _evidence_from_history(history)
    usage = Usage(cost_usd=0.0)
    texts: list[str] = []
    products: dict[int, dict] = {}
    added_products: dict[int, dict] = {}
    sources: list[dict] = []
    tool_log: list[dict] = []
    cart_updated = False
    final_message: ChatMessage | None = None
    stop = "end_turn"
    answered_by = ""
    max_rounds = cfg["ASSISTANT_MAX_TOOL_ROUNDS"]

    try:
        for round_index in range(max_rounds + 1):
            result = None
            for event in llm.stream_turn(
                feature="assistant",
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=tools,
                max_tokens=cfg["MAX_TOKENS_ASSISTANT"],
                effort=cfg["EFFORT_ASSISTANT"],
                user=user,
            ):
                if event.kind == "text" and event.text:
                    yield _event("text", delta=event.text)
                elif event.kind == "final":
                    result = event.result
            if result is None:
                raise LLMError("The model stream ended without a final message.")

            usage.input_tokens += result.usage.input_tokens
            usage.output_tokens += result.usage.output_tokens
            usage.cache_read_tokens += result.usage.cache_read_tokens
            usage.cache_creation_tokens += result.usage.cache_creation_tokens
            if usage.cost_usd is not None and result.usage.cost_usd is not None:
                usage.cost_usd += result.usage.cost_usd
            else:
                usage.cost_usd = None
            stop = result.stop_reason or ""
            answered_by = result.provider or llm.name

            if stop == "refusal":
                # Partial output from a declined request is discarded, not stored.
                yield _event("refusal", message="Sorry, I can't help with that request. Is there something else I can find for you?")
                break

            assistant_message = {"role": "assistant", "content": result.content}
            if result.text.strip():
                texts.append(result.text.strip())

            tool_uses = result.tool_uses
            if stop == "max_tokens":
                # A truncated tool input can still parse as a valid object; never run it.
                if result.content and not tool_uses:
                    final_message = _persist(session, [(assistant_message, None)])[0]
                yield _event("error", message="The answer was cut off. Please ask a shorter question.")
                break

            if not tool_uses:
                if result.content:
                    final_message = _persist(session, [(assistant_message, None)])[0]
                break

            budget_exhausted = round_index == max_rounds
            tool_results = []
            for tool_use in tool_uses:
                yield _event("tool_start", id=tool_use["id"], name=tool_use["name"], input=tool_use.get("input", {}))
                if budget_exhausted:
                    outcome = ToolOutcome(content='{"error": "Tool budget for this turn is used up. Answer with what you have."}',
                                          is_error=True, summary="Tool budget used up")
                else:
                    outcome = execute_tool(tool_use["name"], tool_use.get("input", {}), ctx)
                if outcome.is_error and outcome.summary == "Invalid tool input":
                    guardrails.record_event("tool_input_invalid", user=user, excerpt=str(tool_use.get("input"))[:300], tool=tool_use["name"])
                block = {"type": "tool_result", "tool_use_id": tool_use["id"], "content": outcome.content}
                if outcome.is_error:
                    block["is_error"] = True
                tool_results.append(block)
                evidence.append(outcome.content)
                for card in outcome.products:
                    products.setdefault(card["id"], card)
                    if outcome.cart_updated:
                        added_products.setdefault(card["id"], card)
                sources.extend(s for s in outcome.sources if s not in sources)
                cart_updated = cart_updated or outcome.cart_updated
                tool_log.append({"name": tool_use["name"], "input": tool_use.get("input", {}), "summary": outcome.summary, "is_error": outcome.is_error})
                yield _event(
                    "tool_result",
                    id=tool_use["id"],
                    name=tool_use["name"],
                    summary=outcome.summary,
                    is_error=outcome.is_error,
                    products=outcome.products,
                    sources=outcome.sources,
                    cart_updated=outcome.cart_updated,
                )

            tool_message = {"role": "user", "content": tool_results}
            _persist(session, [(assistant_message, None), (tool_message, None)])
            messages += [assistant_message, tool_message]

            if budget_exhausted:
                guardrails.record_event("max_tool_rounds", user=user, excerpt=message, rounds=max_rounds)
                stop = "max_tool_rounds"
                yield _event("error", message="I needed too many steps for that. Could you narrow the request down?")
                break
    except LLMError:
        yield _event("error", message="The assistant is temporarily unavailable. Please try again in a moment.")
        stop = "error"

    answer = "\n\n".join(texts)
    ungrounded = guardrails.find_ungrounded_prices(answer, evidence)
    if ungrounded:
        guardrails.record_event("ungrounded_price", user=user, excerpt=answer, prices=ungrounded)

    display = {
        "text": answer,
        # After an add-to-cart, show what was added rather than every search result.
        "products": list((added_products or products).values())[:MAX_PRODUCT_CARDS],
        "sources": sources[:4],
        "tools": tool_log,
        "grounding": {"ungrounded_prices": ungrounded},
    }
    if final_message is not None:
        final_message.display = display
        final_message.save(update_fields=["display"])
    elif answer or tool_log:
        # No clean final message (error / refusal / budget): keep a display-only record for the UI.
        # It is stored as an assistant message with text content so the replayed history stays valid.
        if answer:
            _persist(session, [({"role": "assistant", "content": [{"type": "text", "text": answer}]}, display)])
    session.save(update_fields=["updated_at"])

    yield _event(
        "done",
        blocked=False,
        stop_reason=stop,
        answered_by=answered_by,
        products=display["products"],
        sources=display["sources"],
        tools=tool_log,
        cart_updated=cart_updated,
        grounding=display["grounding"],
        usage={
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_creation_tokens": usage.cache_creation_tokens,
            "cost_usd": round(usage.cost_usd, 6) if usage.cost_usd is not None else None,
        },
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def session_transcript(session: ChatSession) -> list[dict]:
    """What the UI shows for a past conversation: customer messages and final answers."""
    out = []
    for m in session.messages.exclude(display__isnull=True).order_by("seq"):
        out.append({"id": m.id, "role": m.role, **m.display, "created_at": m.created_at.isoformat()})
    return out

