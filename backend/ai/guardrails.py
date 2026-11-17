"""Guardrails around every LLM interaction.

1. Input checks before a message reaches the model (length, prompt-injection patterns).
2. Indirect prompt injection: customer reviews are user-generated text that ends up inside
   tool results, so reviews are scanned on save and flagged ones never reach a prompt.
3. Output grounding: prices or numbers the model writes must appear in the data it was given;
   anything else is logged as a possible hallucination and surfaced to the UI.

Pattern matching is a cheap first line of defence, not a complete one. The structural
defences matter more: tools act only as the signed-in user, the assistant cannot place
orders, and tool output is framed as untrusted data in the system prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.conf import settings

INJECTION_PATTERNS: dict[str, re.Pattern] = {
    "ignore_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|your|the)\b[^.\n]{0,30}"
        r"\b(instructions?|rules|prompts?|guidelines|directions)\b",
        re.I,
    ),
    "reveal_system_prompt": re.compile(
        r"\b(reveal|show|print|repeat|output|tell me|what is|what's|display)\b[^.\n]{0,40}"
        r"\b(system|developer|hidden|initial|original)\s+(prompt|instructions?|message)\b",
        re.I,
    ),
    "role_override": re.compile(
        r"\b(you are now|from now on you are|act as|pretend (to be|you are)|roleplay as)\b[^.\n]{0,40}"
        r"\b(admin|administrator|developer|system|root|unrestricted|jailbroken|dan)\b",
        re.I,
    ),
    "developer_mode": re.compile(r"\b(developer|god|jailbreak|dan)\s+mode\b", re.I),
    "fake_system_tag": re.compile(r"(<\s*/?\s*(system|instructions?)\s*>|\[\s*(system|inst)\s*\]|###\s*system)", re.I),
    "tool_hijack": re.compile(
        r"\b(call|use|invoke|run)\b[^.\n]{0,20}\b(add_to_cart|tool|function)\b[^.\n]{0,40}\b(for every|for all|other users?|without asking)\b",
        re.I,
    ),
}


def detect_prompt_injection(text: str) -> list[str]:
    """Return the names of the injection patterns that match `text` (empty list = clean)."""
    return [name for name, pattern in INJECTION_PATTERNS.items() if pattern.search(text or "")]


@dataclass
class InputCheck:
    allowed: bool
    kind: str = ""
    reply: str = ""
    matches: list[str] = field(default_factory=list)


BLOCKED_REPLY = (
    "I can only help with shopping at ShopFlow: finding products, your cart, your orders and "
    "our store policies. I can't change how I work or share my instructions."
)


def check_user_message(text: str) -> InputCheck:
    text = (text or "").strip()
    limit = settings.AI["MAX_INPUT_CHARS"]
    if not text:
        return InputCheck(False, "empty", "Please type a message.")
    if len(text) > limit:
        return InputCheck(False, "input_too_long", f"Please keep messages under {limit} characters.")
    matches = detect_prompt_injection(text)
    if matches:
        return InputCheck(False, "prompt_injection", BLOCKED_REPLY, matches)
    return InputCheck(True)


# ---------------------------------------------------------------------------
# Output grounding
# ---------------------------------------------------------------------------

_PRICE_RE = re.compile(r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.I)
_NUMBER_RE = re.compile(r"(?<![\w.])([0-9][0-9,]*(?:\.[0-9]+)?)(?![\w])")


def _to_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def numbers_in(text: str) -> set[Decimal]:
    return {d for d in (_to_decimal(m) for m in _NUMBER_RE.findall(text or "")) if d is not None}


def find_ungrounded_prices(answer: str, evidence: list[str]) -> list[str]:
    """Prices written in `answer` (₹1,299 / Rs. 1299 / INR 1299) that appear nowhere in `evidence`."""
    allowed = set()
    for chunk in evidence:
        allowed |= numbers_in(chunk)
    ungrounded = []
    for raw in _PRICE_RE.findall(answer or ""):
        value = _to_decimal(raw)
        if value is not None and value not in allowed:
            ungrounded.append(raw)
    return ungrounded


def find_ungrounded_numbers(generated: str, source: str, ignore_below: int = 10) -> list[str]:
    """Numbers in generated copy (e.g. "40-hour battery") that are not in the source facts.

    Small numbers (< `ignore_below`) are skipped: they are usually counts in ordinary prose.
    """
    allowed = numbers_in(source)
    flagged = []
    for raw in _NUMBER_RE.findall(generated or ""):
        value = _to_decimal(raw)
        if value is None or value < ignore_below or value in allowed:
            continue
        flagged.append(raw)
    return sorted(set(flagged))


def record_event(kind: str, *, user=None, excerpt: str = "", **detail) -> None:
    from .models import GuardrailEvent

    GuardrailEvent.objects.create(
        kind=kind,
        user=user if getattr(user, "is_authenticated", False) else None,
        excerpt=(excerpt or "")[:300],
        detail=detail,
    )
