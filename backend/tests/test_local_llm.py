"""The local model tier (Ollama): it answers what it can, and every failure falls back to the offline rules."""

import json

import httpx
import pytest
from pydantic import BaseModel

from ai import llm as llm_pkg
from ai.agent.offline_policy import decide_next_turn
from ai.llm import LLMBusy, LLMError
from ai.llm.local_provider import LocalProvider
from ai.llm.offline_provider import OfflineProvider
from ai.llm.resilient import ResilientProvider
from ai.models import LLMCall

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fresh_switch():
    """The on/off switch is re-read from the database at most every 3 s; start every test fresh."""
    from ai.llm import switch

    switch._cached.update(value=True, until=0.0)
    yield
    switch._cached.update(value=True, until=0.0)


class Answer(BaseModel):
    city: str
    days: int


def ollama(reply=None, *, status=200, done_reason="stop", raise_exc=None, seen=None):
    """A fake Ollama /api/chat endpoint."""
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        if raise_exc is not None:
            raise raise_exc
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return httpx.Response(status, json={"message": {"role": "assistant", "content": content}, "done_reason": done_reason,
                                            "prompt_eval_count": 42, "eval_count": 7})
    return httpx.MockTransport(handler)


def chain(transport, features=("delivery",)):
    local = LocalProvider("http://ollama:11434", "qwen2.5:3b", features=features, transport=transport, wait_seconds=0.05)
    return ResilientProvider(primary=local, backup=OfflineProvider(agent_policy=decide_next_turn), cooldown_seconds=60), local


def ask(provider, feature="delivery", messages=None):
    return provider.parse(feature=feature, system="Answer.", messages=messages or [{"role": "user", "content": "Delivery to Pune?"}],
                          schema=Answer, offline=lambda: Answer(city="rules", days=0), max_tokens=500, effort="low")


def test_structured_answer_from_the_local_model():
    seen = []
    provider, _ = chain(ollama({"city": "Pune", "days": 3}, seen=seen))
    result = ask(provider)
    assert result.value == Answer(city="Pune", days=3) and result.provider == "local" and result.model == "qwen2.5:3b"
    body = seen[0]
    assert body["format"] == Answer.model_json_schema() and body["stream"] is False  # decoding constrained to the schema
    assert body["options"]["temperature"] == 0 and body["options"]["num_predict"] == 500
    call = LLMCall.objects.get()
    assert (call.provider, call.status, call.input_tokens, call.output_tokens, float(call.cost_usd)) == ("local", "ok", 42, 7, 0.0)


@pytest.mark.parametrize("transport", [
    ollama(raise_exc=httpx.ConnectError("connection refused")),        # Ollama not running
    ollama({"error": "model not found"}, status=404),                   # model not downloaded yet
    ollama("not json at all"),                                          # garbage output
    ollama({"city": "Pune"}),                                           # wrong shape
    ollama({"city": "Pune", "days": 3}, done_reason="length"),          # cut off
    ollama(raise_exc=httpx.ReadTimeout("too slow")),                    # timeout
])
def test_any_failure_falls_back_to_the_rules_without_an_error(transport):
    provider, _ = chain(transport)
    result = ask(provider)
    assert result.value == Answer(city="rules", days=0) and result.provider == "offline"
    assert provider.degraded  # skipped for the cool-down: the next request doesn't wait on a dead model
    assert LLMCall.objects.filter(provider="local", status="error").count() == 1  # visible on the dashboard


def test_what_it_should_not_answer_goes_straight_to_the_rules():
    seen = []
    provider, _ = chain(ollama({"city": "Pune", "days": 3}, seen=seen))
    assert ask(provider, feature="purchase_check").provider == "offline"  # not in its feature list
    assert ask(provider, feature="eval_judge").provider == "offline"      # never grades itself
    image = [{"role": "user", "content": [{"type": "image", "source": {}}, {"type": "text", "text": "What is this?"}]}]
    assert ask(provider, messages=image).provider == "offline"           # no vision
    assert seen == [] and not provider.degraded                           # not failures, so no cool-down
    assert not provider.supports_vision and not provider.primary.supports_agent


def test_a_busy_model_hands_over_without_a_cool_down():
    provider, local = chain(ollama({"city": "Pune", "days": 3}))
    local._slot.acquire()  # another request is using the model
    try:
        result = ask(provider)
    finally:
        local._slot.release()
    assert result.provider == "offline" and not provider.degraded
    assert not LLMCall.objects.filter(provider="local").exists()  # nothing was sent, nothing to log
    assert ask(provider).provider == "local"  # free again


def test_the_local_provider_raises_typed_errors_on_its_own():
    _, local = chain(ollama(raise_exc=httpx.ConnectError("refused")))
    with pytest.raises(LLMError):
        ask(local)
    local._slot.acquire()
    with pytest.raises(LLMBusy):
        ask(local)
    local._slot.release()


def test_provider_choice(settings):
    settings.AI = {**settings.AI, "LLM_PROVIDER": "auto", "LOCAL_LLM_URL": "http://ollama:11434", "LOCAL_LLM_FEATURES": ["review_summary"]}
    llm_pkg.get_llm.cache_clear()
    llm_pkg.get_agent_llm.cache_clear()
    try:
        assert llm_pkg.resolve_provider_name() == "local"
        chained = llm_pkg.get_llm()
        assert chained.name == "local" and chained.handles("review_summary") and not chained.primary.handles("search_parse")
        assert llm_pkg.get_agent_llm().name == "offline"  # the assistant never runs on the small model
        settings.AI = {**settings.AI, "LOCAL_LLM_URL": ""}
        assert llm_pkg.resolve_provider_name() == "offline"
    finally:
        llm_pkg.get_llm.cache_clear()
        llm_pkg.get_agent_llm.cache_clear()


def test_a_fallback_summary_is_shown_but_not_kept(user, make_user, catalog, monkeypatch):
    from ai import reviews
    from ai.models import ReviewSummary
    from store.models import Review

    product = catalog["headphones"]
    for name, body in [("asha", "Great noise cancellation on flights."), ("ravi", "Noise cancellation is good; battery lasts days.")]:
        Review.objects.create(product=product, user=make_user(name), rating=5, title="", body=body)
    down, _ = chain(ollama(raise_exc=httpx.ConnectError("refused")), features=("review_summary",))
    monkeypatch.setattr(reviews, "get_llm", lambda: down)
    first = reviews.get_review_insights(product)
    assert first["provider"] == "offline" and not ReviewSummary.objects.exists()  # shown, not stored as the model's
    up, _ = chain(ollama({"summary": "Reviewers love the noise cancellation.", "pros": ["ANC"], "cons": [], "sentiment": "positive"}),
                  features=("review_summary",))
    monkeypatch.setattr(reviews, "get_llm", lambda: up)
    second = reviews.get_review_insights(product)
    assert second["provider"] == "local" and second["summary"] == "Reviewers love the noise cancellation."
    assert ReviewSummary.objects.get().provider == "local" and reviews.get_review_insights(product)["cached"] is True


class Flaky(LocalProvider):
    """Fails until told to work: the cache must not keep the stand-in it got while failing."""

    def __init__(self, reply):
        super().__init__("http://x", "flaky-1", features=("all",))
        self.working, self.reply = False, reply

    def _parse(self, **kwargs):
        if not self.working:
            raise LLMError("down")
        return llm_pkg.ParseResult(value=kwargs["schema"].model_validate(self.reply), model=self.model, provider=self.name)


def test_a_stand_in_answer_is_not_cached_as_the_models(make_user, catalog, monkeypatch):
    from ai import listing_check as lc
    from store.models import Review

    product = catalog["speaker"]  # "Portable waterproof speaker..."
    for name, body in [("ana", "It leaked after the pool party."), ("bo", "Water got in after one swim.")]:
        Review.objects.create(product=product, user=make_user(name), rating=2, title="", body=body)
    flaky = Flaky({"claims": [{"claim": "Waterproof", "listing_quote": "waterproof speaker", "supporting": [],
                               "contradicting": [{"review": 1, "quote": "It leaked after the pool party."}]}]})
    chained = ResilientProvider(primary=flaky, backup=OfflineProvider(agent_policy=decide_next_turn), cooldown_seconds=60)
    monkeypatch.setattr(lc, "get_llm", lambda: chained)
    first = lc.check_listing(product)
    assert first["provider"] == "offline" and first["model"] == "rule-based-v1 (fallback)"
    chained.reset()
    flaky.working = True
    second = lc.check_listing(product)  # asks the model again instead of serving the cached stand-in
    assert second["provider"] == "local" and second["findings"][0]["counts"]["contradicting"] == 1


def test_the_readiness_check_never_raises():
    tags = lambda models: httpx.MockTransport(lambda req: httpx.Response(200, json={"models": [{"name": m} for m in models]}))  # noqa: E731
    up = LocalProvider("http://ollama:11434", "qwen2.5:3b", transport=tags(["qwen2.5:3b"]))
    missing = LocalProvider("http://ollama:11434", "qwen2.5:3b", transport=tags(["llama3.2:1b"]))
    down = LocalProvider("http://ollama:11434", "qwen2.5:3b", transport=ollama(raise_exc=httpx.ConnectError("refused")))
    junk = LocalProvider("http://ollama:11434", "qwen2.5:3b", transport=httpx.MockTransport(lambda req: httpx.Response(200, text="<html>")))
    assert up.ready() is True and missing.ready() is False and down.ready() is False and junk.ready() is False


def test_the_status_badge_checks_the_local_model(anon_client, settings, monkeypatch):
    from ai.llm import local_provider

    settings.AI = {**settings.AI, "LLM_PROVIDER": "local", "LOCAL_LLM_URL": "http://ollama:11434"}
    llm_pkg.get_llm.cache_clear()
    try:
        # the real readiness check, against an Ollama that refuses connections
        monkeypatch.setattr(local_provider.LocalProvider, "_http", lambda self: httpx.Client(transport=ollama(raise_exc=httpx.ConnectError("refused"))))
        r = anon_client.get("/api/ai/status/")
        assert r.status_code == 200
        assert r.data["llm"]["provider"] == "local" and r.data["llm"]["degraded"] is True and r.data["llm"]["is_live"] is False
    finally:
        llm_pkg.get_llm.cache_clear()


def test_staff_can_turn_the_local_model_off_and_on(user, admin_user, client_for, settings, monkeypatch):
    from ai.llm import switch

    sent = []
    monkeypatch.setattr(switch, "_ollama", lambda payload, timeout: sent.append(payload) or "")
    monkeypatch.setattr(switch.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda self: target(*args)})())
    settings.AI = {**settings.AI, "LLM_PROVIDER": "local", "LOCAL_LLM_URL": "http://ollama:11434", "LOCAL_LLM_FEATURES": ["product_qa"]}
    llm_pkg.get_llm.cache_clear()
    staff = client_for(admin_user)
    try:
        assert client_for(user).post("/api/ai/local-model/", {"on": False}, format="json").status_code == 403  # shoppers can't
        r = staff.post("/api/ai/local-model/", {"on": False}, format="json")
        assert r.status_code == 200 and r.data["on"] is False and r.data["configured"] is True
        assert sent[-1] == {"model": "qwen2.5:3b", "keep_alive": 0}  # Ollama is asked to free the memory
        status = staff.get("/api/ai/status/").data
        assert status["llm"]["provider"] == "offline" and status["local_model"]["on"] is False  # the badge says Offline AI
        assert llm_pkg.get_llm().handles("product_qa") is False  # every request now goes to the rules
        switch._cached.update(value=True, until=10**12)  # another server process, still holding "on" in memory...
        assert switch.local_switch_on() is True
        assert switch.local_switch_on(fresh=True) is False  # ...but the badge and the card read the saved switch
        assert staff.get("/api/ai/status/").data["local_model"]["on"] is False
        switch._cached.update(until=0.0)
        assert switch.local_switch_on() is False  # and requests pick it up within a few seconds
        r = staff.post("/api/ai/local-model/", {"on": True}, format="json")
        assert r.data["on"] is True and sent[-1] == {"model": "qwen2.5:3b", "keep_alive": "30m"}  # loaded ahead of the first answer
        assert llm_pkg.get_llm().handles("product_qa") is True
    finally:
        llm_pkg.get_llm.cache_clear()


def test_the_switch_needs_a_local_model(admin_user, client_for):
    r = client_for(admin_user).post("/api/ai/local-model/", {"on": True}, format="json")
    assert r.status_code == 400 and "No local model is set up" in r.data["detail"]
    assert client_for(admin_user).get("/api/ai/local-model/").data == {"configured": False, "on": False, "ready": False, "model": None, "features": [], "note": ""}


def test_the_rules_answer_is_cached_when_the_rules_are_meant_to_answer(make_user, catalog, monkeypatch):
    """With a local model that doesn't do listing checks, the rules' result is the intended one: keep it."""
    from django.core.cache import cache

    from ai import listing_check as lc
    from store.models import Review

    product = catalog["speaker"]
    Review.objects.create(product=product, user=make_user("ana"), rating=2, title="", body="It leaked after the pool party.")
    seen = []
    chained, _ = chain(ollama({"claims": []}, seen=seen), features=("product_qa",))  # local model on, but not for this
    monkeypatch.setattr(lc, "get_llm", lambda: chained)
    first = lc.check_listing(product)
    assert first["provider"] == "offline" and first["model"] == "rule-based-v1" and seen == []  # the rules, as intended
    monkeypatch.setattr(lc, "_offline", lambda *a: (_ for _ in ()).throw(AssertionError("should come from the cache")))
    assert lc.check_listing(product) == first


def test_a_failed_judge_call_is_skipped_not_counted_as_wrong(knowledge, settings, monkeypatch):
    from ai.evals import runner

    class FailingJudge(LocalProvider):  # stands in for Claude: handles everything, fails on the judge
        name = "anthropic"

        def handles(self, feature):
            return True

        def _parse(self, **kwargs):
            if kwargs["schema"].__name__ == "JudgeVerdict":
                raise LLMError("Claude timed out")
            return llm_pkg.ParseResult(value=kwargs["offline"](), model=self.model, provider=self.name)

    judge = ResilientProvider(primary=FailingJudge("http://x", "claude-test"), backup=OfflineProvider(agent_policy=decide_next_turn), cooldown_seconds=0)
    monkeypatch.setattr(runner, "get_llm", lambda: judge)
    monkeypatch.setattr("ai.rag.get_llm", lambda: judge)
    report = runner.run_rag_eval()
    assert "judge_correct" not in report["metrics"] or report["metrics"]["judge_correct"] is None  # no fake "wrong" verdicts
