"""A free local model served by Ollama, used between Claude and the offline rules.

Structured outputs only. Every `parse()` call sends the Pydantic model's JSON schema as Ollama's
`format`, which constrains decoding so the model can only produce JSON of that shape, and the reply
is validated again with Pydantic. Anything that goes wrong (Ollama not running, the model not
downloaded yet, a timeout, output cut off or not matching the schema) raises `LLMError`; the
`ResilientProvider` in front of this provider then answers with the offline rules and skips the
local model for a short cool-down, so the website never shows an error and never waits on a dead
model twice.

What it leaves to the next provider in line, on purpose:
- images: there is no vision model, so photo search uses CLIP only;
- the shopping assistant's multi-step tool use: small models are unreliable at it and slow on a CPU;
- any feature not listed in `AI["LOCAL_LLM_FEATURES"]`, which were chosen by running the eval
  suites with the local model and the offline rules side by side (see the README).
"""

from __future__ import annotations

import json
import threading
from typing import Iterable

import httpx
from pydantic import ValidationError

from .base import LLMBusy, LLMError, LLMProvider, ParseResult, Usage

JSON_INSTRUCTION = "\n\nReply with one JSON object only, matching this JSON schema:\n"


class LocalProvider(LLMProvider):
    name = "local"
    is_live = True
    supports_vision = False
    supports_agent = False

    def __init__(self, url: str, model: str, *, timeout_seconds: float = 45.0, max_tokens: int = 1024,
                 features: Iterable[str] = (), context_tokens: int = 8192, wait_seconds: float = 1.0,
                 transport: httpx.BaseTransport | None = None):
        self.url = url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.context_tokens = context_tokens
        self.features = frozenset(features)
        self._timeout = httpx.Timeout(timeout_seconds, connect=2.0)
        self._transport = transport  # tests pass an httpx.MockTransport
        self._client: httpx.Client | None = None
        self._lock = threading.Lock()
        # One call at a time per server process: a CPU model answers one request at a time anyway,
        # so a second request gets the offline rules at once instead of queueing behind the first.
        self._slot = threading.Semaphore(1)
        self._wait = wait_seconds

    def ready(self) -> bool:
        """Whether Ollama is up and has the model (a quick check for the status badge). Never raises:
        anything unexpected just means "not ready"."""
        try:
            response = self._http().get(f"{self.url}/api/tags", timeout=1.0)
            names = {m.get("name") for m in response.json().get("models", [])}
        except Exception:
            return False
        return self.model in names or f"{self.model}:latest" in names

    def handles(self, feature: str) -> bool:
        if feature == "eval_judge":  # the eval judge is always Claude: a small model grading itself proves nothing
            return False
        if not ("all" in self.features or feature in self.features):
            return False
        from .switch import local_switch_on

        return local_switch_on()  # staff can turn the local model off from the AI admin page

    def _http(self) -> httpx.Client:
        with self._lock:
            if self._client is None:
                self._client = httpx.Client(timeout=self._timeout, transport=self._transport)
            return self._client

    @staticmethod
    def _messages(system: str, messages: list[dict], schema_json: dict) -> list[dict]:
        out = [{"role": "system", "content": system + JSON_INSTRUCTION + json.dumps(schema_json, ensure_ascii=False)}]
        for message in messages:
            content = message["content"]
            if isinstance(content, list):
                if any(block.get("type") == "image" for block in content):
                    raise LLMError("The local model can't read images.")
                content = "\n".join(block.get("text", "") for block in content if block.get("type") == "text")
            out.append({"role": message["role"], "content": content})
        return out

    def _parse(self, *, system, messages, schema, offline, max_tokens, effort, model) -> ParseResult:
        schema_json = schema.model_json_schema()
        body = {
            "model": self.model,
            "messages": self._messages(system, messages, schema_json),
            "format": schema_json,
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": 0, "num_predict": min(max_tokens, self.max_tokens), "num_ctx": self.context_tokens},
        }
        if not self._slot.acquire(timeout=self._wait):
            raise LLMBusy("The local model is busy with another request.")
        try:
            response = self._http().post(f"{self.url}/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise LLMError(f"Local model unreachable: {type(exc).__name__}: {exc}") from exc
        finally:
            self._slot.release()
        if response.status_code != 200:
            raise LLMError(f"Local model returned HTTP {response.status_code}: {response.text[:200]}")
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("Local model sent a response that isn't JSON.") from exc
        if data.get("done_reason") == "length":
            raise LLMError("Local model output was cut off at the token limit.")
        text = (data.get("message") or {}).get("content") or ""
        try:
            value = schema.model_validate_json(text)
        except ValidationError as exc:
            raise LLMError(f"Local model output didn't match the schema: {exc.errors()[:2]}") from exc
        usage = Usage(input_tokens=int(data.get("prompt_eval_count") or 0), output_tokens=int(data.get("eval_count") or 0), cost_usd=0.0)
        return ParseResult(value=value, model=self.model, usage=usage, provider=self.name)

    def _stream_turn(self, **kwargs):
        raise LLMError("The local model isn't used for the shopping assistant.")
