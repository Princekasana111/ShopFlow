"""Exercises AnthropicProvider through the real Anthropic SDK with a mocked HTTP transport.

No network and no API key: the SDK builds the real request (so these tests catch invalid
parameters) and parses a realistic server-sent-event stream / JSON response.
"""

import json

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from ai.llm.anthropic_provider import FALLBACK_BETA, AnthropicProvider, _usage_from_response, sanitize_for_echo
from ai.llm.base import LLMRefusal
from ai.models import LLMCall
from ai.query_understanding import SearchIntent

pytestmark = pytest.mark.django_db


def sse(events: list[dict]) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


STREAM = [
    {"type": "message_start", "message": {
        "id": "msg_01", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": [],
        "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 300, "output_tokens": 1, "cache_read_input_tokens": 1500, "cache_creation_input_tokens": 0}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "EqQBCkYIBRgCKkB"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Let me look "}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "that up."}},
    {"type": "content_block_stop", "index": 1},
    {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "toolu_01A", "name": "search_products", "input": {}}},
    {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": "{\"query\": \"running shoes\""}},
    {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": ", \"max_price\": 4000}"}},
    {"type": "content_block_stop", "index": 2},
    {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None}, "usage": {"output_tokens": 120}},
    {"type": "message_stop"},
]


def make_provider(handler, fallbacks=True):
    client = anthropic.Anthropic(
        api_key="test-key",
        base_url="https://api.anthropic.test",
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
        max_retries=0,
    )
    return AnthropicProvider(model="claude-opus-5-5", use_fallbacks=fallbacks, client=client)


def test_stream_turn_builds_valid_request_and_parses_stream():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, headers={"content-type": "text/event-stream", "request-id": "req_123"}, content=sse(STREAM))

    tools = [{"name": "search_products", "description": "Search", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}}]
    provider = make_provider(handler)
    events = list(provider.stream_turn(
        feature="assistant", system="You are helpful.", messages=[{"role": "user", "content": "shoes under 4000"}],
        tools=tools, max_tokens=16000, effort="medium",
    ))

    body = captured["body"]
    assert "/v1/messages" in captured["url"]
    assert FALLBACK_BETA in captured["headers"]["anthropic-beta"]
    assert body["model"] == "claude-opus-5-5" and body["stream"] is True and body["max_tokens"] == 16000
    assert body["fallbacks"] == "default"
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "medium"}
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["tools"][0]["eager_input_streaming"] is True
    assert "temperature" not in body  # sampling params are rejected on current models

    assert "".join(e.text for e in events if e.kind == "text") == "Let me look that up."
    result = events[-1].result
    assert result.stop_reason == "tool_use" and result.request_id == "req_123"
    assert result.content[0] == {"type": "thinking", "thinking": "", "signature": "EqQBCkYIBRgCKkB"}
    assert result.tool_uses == [{"type": "tool_use", "id": "toolu_01A", "name": "search_products", "input": {"query": "running shoes", "max_price": 4000}}]
    assert result.usage.cache_read_tokens == 1500 and result.usage.output_tokens == 120
    # $4/MTok input, $20/MTok output, $0.20/MTok cache read
    assert result.usage.cost_usd == pytest.approx((300 * 4 + 120 * 20 + 1500 * 0.2) / 1e6)

    call = LLMCall.objects.get()
    assert (call.feature, call.provider, call.status, call.cache_read_tokens) == ("assistant", "anthropic", "ok", 1500)


def test_fallbacks_can_be_disabled():
    captured = {}

    def handler(request):
        captured["headers"], captured["body"] = dict(request.headers), json.loads(request.content)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=sse(STREAM))

    list(make_provider(handler, fallbacks=False).stream_turn(
        feature="assistant", system="s", messages=[{"role": "user", "content": "hi"}], tools=[], max_tokens=1000, effort="low"))
    assert "fallbacks" not in captured["body"]
    assert FALLBACK_BETA not in captured["headers"].get("anthropic-beta", "")


def test_structured_output_parse():
    captured = {}
    intent = {"semantic_query": "running shoes", "category_slug": "footwear", "min_price": None, "max_price": 3000, "in_stock_only": False}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json={
            "id": "msg_02", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": json.dumps(intent)}],
            "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 200, "output_tokens": 40},
        })

    result = make_provider(handler).parse(
        feature="search_parse", system="Parse it.", messages=[{"role": "user", "content": "running shoes under 3k"}],
        schema=SearchIntent, offline=lambda: None, max_tokens=4000, effort="low",
    )
    assert result.value == SearchIntent(**intent)
    fmt = captured["body"]["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
    assert captured["body"]["output_config"]["effort"] == "low"
    assert result.usage.cost_usd == pytest.approx((200 * 4 + 40 * 20) / 1e6)


def test_structured_output_refusal_raises_and_is_logged():
    def handler(request):
        return httpx2.Response(200, json={
            "id": "msg_03", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": [],
            "stop_reason": "refusal", "stop_sequence": None, "usage": {"input_tokens": 50, "output_tokens": 0},
        })

    with pytest.raises(LLMRefusal):
        make_provider(handler).parse(
            feature="copywriter", system="s", messages=[{"role": "user", "content": "x"}],
            schema=SearchIntent, offline=lambda: None, max_tokens=4000, effort="low",
        )
    assert LLMCall.objects.get().status == "refusal"


def test_sanitize_for_echo_after_mid_output_fallback():
    content = [
        {"type": "thinking", "thinking": "", "signature": "a"},
        {"type": "text", "text": "Partial answer"},
        {"type": "tool_use", "id": "toolu_x", "name": "view_cart", "input": {}},
        {"type": "fallback", "from": {"model": "claude-opus-5-5"}, "to": {"model": "claude-opus-5"}},
        {"type": "thinking", "thinking": "", "signature": "b"},
        {"type": "text", "text": "Continued"},
    ]
    assert sanitize_for_echo(content) == [content[1], content[3], content[4], content[5]]
    plain = [{"type": "thinking", "thinking": "", "signature": "a"}, {"type": "text", "text": "hi"}]
    assert sanitize_for_echo(plain) == plain


def test_usage_sums_fallback_attempts_at_each_models_price():
    message = BetaMessage.model_validate({
        "id": "msg_04", "type": "message", "role": "assistant", "model": "claude-opus-5",
        "content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {
            "input_tokens": 100, "output_tokens": 50,
            "iterations": [
                {"type": "message", "input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                {"type": "fallback_message", "model": "claude-opus-5", "input_tokens": 100, "output_tokens": 50,
                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            ],
        },
    })
    usage, fallback_used = _usage_from_response(message, "claude-opus-5-5")
    assert fallback_used is True
    assert (usage.input_tokens, usage.output_tokens) == (200, 60)
    assert usage.cost_usd == pytest.approx((100 * 4 + 10 * 20) / 1e6 + (100 * 5 + 50 * 25) / 1e6)


# ---------------------------------------------------------------------------
# A broken key / outage must degrade to offline mode, never break the app.
# ---------------------------------------------------------------------------

def _resilient_with_status(status_code, error_type):
    from ai.agent.offline_policy import decide_next_turn
    from ai.llm.offline_provider import OfflineProvider
    from ai.llm.resilient import ResilientProvider

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx2.Response(status_code, json={"type": "error", "error": {"type": error_type, "message": "simulated"}})

    return ResilientProvider(make_provider(handler), OfflineProvider(decide_next_turn), cooldown_seconds=60), calls


def test_invalid_api_key_falls_back_to_offline_assistant(user, catalog):
    from ai.agent.assistant import run_turn

    llm, calls = _resilient_with_status(401, "authentication_error")
    events = list(run_turn(user=user, message="show me running shoes", llm=llm))
    done = events[-1]["data"]
    assert done["answered_by"] == "offline" and "error" not in [e["event"] for e in events]
    assert done["products"][0]["name"] == "Stride Runner Road Running Shoes"
    assert llm.degraded and calls["n"] == 1
    # The failed Claude call is visible on the dashboard; later calls skip Claude during the cool-down.
    assert LLMCall.objects.filter(provider="anthropic", status="error").count() == 1
    list(run_turn(user=user, message="what's in my cart", llm=llm))
    assert calls["n"] == 1


def test_out_of_credits_falls_back_for_structured_outputs():
    llm, calls = _resilient_with_status(400, "invalid_request_error")
    expected = SearchIntent(semantic_query="shoes", category_slug=None, min_price=None, max_price=None, in_stock_only=False)
    result = llm.parse(feature="search_parse", system="s", messages=[{"role": "user", "content": "x"}],
                       schema=SearchIntent, offline=lambda: expected, max_tokens=4000, effort="low")
    assert result.value == expected and result.provider == "offline" and llm.degraded


def test_refusal_is_not_masked_by_the_offline_fallback():
    from ai.agent.offline_policy import decide_next_turn
    from ai.llm.offline_provider import OfflineProvider
    from ai.llm.resilient import ResilientProvider

    def handler(request):
        return httpx2.Response(200, json={
            "id": "msg_05", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": [],
            "stop_reason": "refusal", "stop_sequence": None, "usage": {"input_tokens": 5, "output_tokens": 0},
        })

    llm = ResilientProvider(make_provider(handler), OfflineProvider(decide_next_turn))
    with pytest.raises(LLMRefusal):
        llm.parse(feature="copywriter", system="s", messages=[{"role": "user", "content": "x"}],
                  schema=SearchIntent, offline=lambda: None, max_tokens=4000, effort="low")
    assert not llm.degraded


def test_vision_request_is_accepted_by_the_sdk():
    """The photo is sent as a base64 image block next to the text, with structured output."""
    import base64
    import io

    from PIL import Image

    from ai.visual import VisualQuery

    captured = {}
    reply = {"is_product": True, "description": "A kettle", "search_query": "electric kettle", "category_slug": "home-kitchen"}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json={
            "id": "msg_06", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": json.dumps(reply)}],
            "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 900, "output_tokens": 40},
        })

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buf, format="JPEG")
    data = base64.standard_b64encode(buf.getvalue()).decode()
    result = make_provider(handler).parse(
        feature="visual_search", system="s",
        messages=[{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}, {"type": "text", "text": "What is this?"}]}],
        schema=VisualQuery, offline=lambda: None, max_tokens=4000, effort="low",
    )
    sent = captured["body"]["messages"][0]["content"]
    assert sent[0]["type"] == "image" and sent[0]["source"]["data"] == data
    assert result.value.search_query == "electric kettle" and result.provider == "anthropic"
