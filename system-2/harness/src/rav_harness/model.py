"""The model, behind one small interface, so the agent loop doesn't know which provider is answering.

    client = make_client("claude-haiku-5-5", run="run-1")  # every call it makes goes on the ledger
    reply = client.generate(system, messages, tools, on_delta)

A provider's reply is kept as it came (ModelReply.raw_message) and sent back unchanged: Claude's thinking blocks carry a
signature the API checks when they come back. Keys come from .env at the repo root, are held only in the client's
request headers, and are never logged, saved with a turn, or passed to System 1.
"""
from __future__ import annotations

import json
import os
import pathlib
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MODEL = "claude-haiku-5-5"
MODELS = ("claude-haiku-5-5", "claude-sonnet-5-5", "openai-gpt-5.4", "grok-4.7")  # all on Snowflake Cortex
REPO = pathlib.Path(__file__).resolve().parents[4]
MIN_INTERVAL_S = 1.0  # between requests: Cortex has no free-tier limit, and 429s still back off
MAX_WAIT_S = 90.0  # a quota that resets later than this isn't worth waiting for: try the next model

Delta = Callable[[str, str], None]  # (kind: "thought" | "text", text)


class ModelError(Exception):
    """kind is a trace error kind: api_error for anything that's ours or the provider's."""

    def __init__(self, message: str, kind: str = "api_error"):
        super().__init__(message)
        self.kind = kind


class Unavailable(ModelError):
    """This model can't answer now: out of quota, or overloaded through every retry. Another one might."""


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})


@dataclass
class ToolRequest:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class ToolResult:
    call: ToolRequest
    content: dict[str, Any]
    is_error: bool = False


@dataclass
class Image:
    mime: str
    data_b64: str
    caption: str = ""


@dataclass
class ModelReply:
    model: str
    text: str = ""
    thinking: str = ""
    calls: list[ToolRequest] = field(default_factory=list)
    stop_reason: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_thinking: int | None = None
    tokens_cached: int | None = None  # input served from the provider's cache
    tokens_cache_write: int | None = None
    latency_ms: float | None = None
    raw_message: Any = None  # the provider's own message, resent unchanged


@dataclass
class Message:
    role: str  # "user" or "assistant"
    text: str = ""
    results: list[ToolResult] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    reply: ModelReply | None = None


class ModelClient(Protocol):
    model: str

    def generate(self, system: str, messages: list[Message], tools: list[ToolSpec], on_delta: Delta | None = None) -> ModelReply: ...


def read_env(name: str, path: pathlib.Path | None = None) -> str | None:
    """A setting from the environment or .env at the repo root. Doesn't touch os.environ, so child processes never get it."""
    if os.environ.get(name):
        return os.environ[name]
    path = path or REPO / ".env"
    if path.is_file():
        for line in path.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip("\"'") or None
    return None


def _retry_after(headers) -> float | None:
    """Seconds from a standard Retry-After header, when the provider sends one."""
    try:
        return float(headers.get("Retry-After")) if headers and headers.get("Retry-After") else None
    except (TypeError, ValueError):
        return None


class Http:
    """Pacing and backoff, shared by the providers. RAV_MODEL_MIN_INTERVAL_S sets the gap between requests (default 1 s; it
    was 4.5 s through round 3c)."""

    def __init__(self, min_interval_s: float | None = None, retries: int = 5, sleep: Callable[[float], None] = time.sleep,
                 timeout_s: float = 180.0):
        self.min_interval_s = float(read_env("RAV_MODEL_MIN_INTERVAL_S") or MIN_INTERVAL_S) if min_interval_s is None else min_interval_s
        self.retries, self.sleep, self.timeout_s = retries, sleep, timeout_s
        self.last = 0.0

    def open(self, url: str, body: dict, headers: dict[str, str], name: str):
        """The open response, after waiting out 429s and 5xxs as far as is worth it."""
        data = json.dumps(body).encode()
        delay = 2.0
        for attempt in range(self.retries + 1):
            wait = self.min_interval_s - (time.monotonic() - self.last)
            if wait > 0:
                self.sleep(wait)
            self.last = time.monotonic()
            request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
            try:
                return urllib.request.urlopen(request, timeout=self.timeout_s)
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "replace")
                short = _short_error(text)
                if e.code == 429:
                    asked = _retry_after(e.headers)
                    if asked is not None and asked > MAX_WAIT_S:
                        raise Unavailable(f"{name}: out of quota, resets in {asked:.0f} s") from None
                    if attempt == self.retries:
                        raise Unavailable(f"{name}: rate limited: {short}") from None
                    self.sleep(asked if asked is not None else delay)
                elif e.code >= 500:
                    if attempt == self.retries:
                        raise Unavailable(f"{name}: HTTP {e.code}: {short}") from None
                    self.sleep(delay + random.random())
                else:
                    raise ModelError(f"{name}: HTTP {e.code}: {short}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == self.retries:
                    raise Unavailable(f"{name}: {type(e).__name__}: {e}") from None
                self.sleep(delay)
            delay = min(delay * 2, 30.0)
        raise Unavailable(f"{name}: no answer")


def _short_error(text: str) -> str:
    try:
        return json.loads(text)["error"]["message"][:300]
    except (ValueError, KeyError, TypeError):
        return text[:300]


# --- OpenAI-compatible: Snowflake Cortex's Chat Completions --------------------------------------------

def _without_images(m: Message) -> Message:
    if not m.images:
        return m
    note = "This model can't view images, so these weren't shown: " + ", ".join(i.caption or "an image" for i in m.images)
    return Message(m.role, f"{m.text}\n{note}".strip(), m.results, [], m.reply)


class ChatCompletionsClient:
    """Chat Completions with tool calls, as Snowflake Cortex documents them. Answers arrive whole: no streaming yet."""

    def __init__(self, model: str, base_url: str | None = None, token: str | None = None, http: Http | None = None, max_tokens: int = 8192):
        self.model, self.wire, self.max_tokens, self.vision = model, model, max_tokens, True
        self.base_url = (base_url or read_env("SNOWFLAKE_BASE_URL") or "").rstrip("/")
        self._token = token or read_env("SNOWFLAKE_PAT")
        if not self.base_url or not self._token:
            raise ModelError("SNOWFLAKE_BASE_URL and SNOWFLAKE_PAT must be set (.env at the repo root)")
        self.http = http or Http(min_interval_s=0.0)

    def _post(self, system: str, messages: list[Message], tools: list[ToolSpec]):
        return self.http.open(f"{self.base_url}/chat/completions", self.request_body(system, messages, tools),
                              {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}, self.model)  # Cortex refuses a request without Accept

    def request_body(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> dict:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "assistant":
                out.append(m.reply.raw_message)
                continue
            for r in m.results:
                out.append({"role": "tool", "tool_call_id": r.call.id, "content": json.dumps(r.content, default=str)})
            if m.text or m.images:
                content: list[dict] = [{"type": "text", "text": m.text or "See the images."}]
                for image in m.images:
                    content.append({"type": "image_url", "image_url": {"url": f"data:{image.mime};base64,{image.data_b64}"}})
                out.append({"role": "user", "content": content if m.images else m.text})
        body: dict[str, Any] = {"model": self.wire, "messages": out, "max_completion_tokens": self.max_tokens}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}} for t in tools]
        return body

    def generate(self, system: str, messages: list[Message], tools: list[ToolSpec], on_delta: Delta | None = None) -> ModelReply:
        start = time.monotonic()
        if not self.vision:
            messages = [_without_images(m) for m in messages]
        try:
            response = self._post(system, messages, tools)
        except ModelError as e:
            if not any(m.images for m in messages) or "multimodal" not in str(e).lower():
                raise
            self.vision = False  # found out once, then the model is told the frames can't be shown
            response = self._post(system, [_without_images(m) for m in messages], tools)
        with response:
            data = json.load(response)
        choice = data["choices"][0]
        message = choice["message"]
        calls = []
        for c in message.get("tool_calls") or []:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except ValueError:
                args = {"_unparsed": c["function"].get("arguments")}
            calls.append(ToolRequest(c["id"], c["function"]["name"], args))
        text = message.get("content") or ""
        thinking = message.get("reasoning_content") or message.get("reasoning") or ""  # providers name it differently, and many send none
        if on_delta:
            if thinking:
                on_delta("thought", thinking)
            if text:
                on_delta("text", text)
        usage = data.get("usage") or {}
        finish = choice.get("finish_reason")
        return ModelReply(model=self.model, text=text, thinking=thinking, calls=calls,
                          stop_reason={"length": "max_tokens", "tool_calls": "tool_use", "stop": "stop"}.get(finish, finish),
                          tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens"),
                          tokens_cached=(usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                          latency_ms=round((time.monotonic() - start) * 1000, 1), raw_message=message)


# --- Anthropic Messages: Claude on Snowflake Cortex ----------------------------------------------------

class MessagesClient:
    """The Messages API, which is how Cortex serves Claude. It caches the system prompt and tools, then the latest turn."""

    def __init__(self, model: str, base_url: str | None = None, token: str | None = None, http: Http | None = None, max_tokens: int = 8192,
                 effort: str | None = None):
        self.model, self.wire, self.max_tokens, self.effort = model, model, max_tokens, effort
        self.base_url = (base_url or read_env("SNOWFLAKE_BASE_URL") or "").rstrip("/")
        self._token = token or read_env("SNOWFLAKE_PAT")
        if not self.base_url or not self._token:
            raise ModelError("SNOWFLAKE_BASE_URL and SNOWFLAKE_PAT must be set (.env at the repo root)")
        self.http = http or Http(min_interval_s=0.0)

    def request_body(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> dict:
        out: list[dict] = []
        for m in messages:
            if m.role == "assistant":
                out.append({"role": "assistant", "content": m.reply.raw_message["content"]})
                continue
            content: list[dict] = [{"type": "tool_result", "tool_use_id": r.call.id, "content": json.dumps(r.content, default=str), "is_error": r.is_error} for r in m.results]
            for image in m.images:
                if image.caption:
                    content.append({"type": "text", "text": image.caption})
                content.append({"type": "image", "source": {"type": "base64", "media_type": image.mime, "data": image.data_b64}})
            if m.text:
                content.append({"type": "text", "text": m.text})
            out.append({"role": "user", "content": content})
        if out and out[-1]["role"] == "user" and out[-1]["content"]:  # the whole conversation so far is the next turn's cheap prefix
            out[-1] = {"role": "user", "content": [*out[-1]["content"][:-1], {**out[-1]["content"][-1], "cache_control": {"type": "ephemeral"}}]}
        body: dict[str, Any] = {"model": self.wire, "max_tokens": self.max_tokens, "messages": out,
                                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]}
        if tools:
            body["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]
        if self.effort:  # these models refuse a fixed thinking budget; summarized, or the text comes back empty
            body["thinking"] = {"type": "adaptive", "display": "summarized"}
            body["output_config"] = {"effort": self.effort}
        return body

    def generate(self, system: str, messages: list[Message], tools: list[ToolSpec], on_delta: Delta | None = None) -> ModelReply:
        start = time.monotonic()
        response = self.http.open(f"{self.base_url}/messages", self.request_body(system, messages, tools),
                                  {"Authorization": f"Bearer {self._token}", "Accept": "application/json", "anthropic-version": "2023-06-01"}, self.model)
        with response:
            data = json.load(response)
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        thinking = "".join(b.get("thinking", "") for b in blocks if b.get("type") == "thinking")
        calls = [ToolRequest(b["id"], b["name"], b.get("input") or {}) for b in blocks if b.get("type") == "tool_use"]
        if on_delta:
            if thinking:
                on_delta("thought", thinking)
            if text:
                on_delta("text", text)
        usage = data.get("usage") or {}
        finish = data.get("stop_reason")
        cached, wrote = usage.get("cache_read_input_tokens"), usage.get("cache_creation_input_tokens")
        return ModelReply(model=self.model, text=text, thinking=thinking, calls=calls, stop_reason="max_tokens" if finish == "max_tokens" else finish,
                          tokens_in=(usage.get("input_tokens") or 0) + (cached or 0) + (wrote or 0), tokens_out=usage.get("output_tokens"),
                          tokens_cached=cached, tokens_cache_write=wrote, latency_ms=round((time.monotonic() - start) * 1000, 1),
                          raw_message={"role": "assistant", "content": blocks})


# --- what it all costs ---------------------------------------------------------------------------------

class LedgeredClient:
    """Records every call's tokens to the ledger before anything else can go wrong, and a call that failed as a row with
    no tokens. make_client wraps each provider in one, so no route skips it. Wrapping a client that already records
    only re-labels it, so nothing is counted twice."""

    def __init__(self, client: ModelClient, ledger=None, run: str | None = None):
        self.client, self.ledger, self.run = client, ledger, run
        self.inner_records = _relabel(client, ledger, run)

    @property
    def model(self) -> str:
        return self.client.model

    def generate(self, system: str, messages: list[Message], tools: list[ToolSpec], on_delta: Delta | None = None) -> ModelReply:
        if self.inner_records:
            return self.client.generate(system, messages, tools, on_delta)
        if self.ledger is None:
            from .ledger import Ledger
            self.ledger = Ledger()
        try:
            reply = self.client.generate(system, messages, tools, on_delta)
        except Exception as e:
            self.ledger.record(ModelReply(model=getattr(self.client, "model", "?")), self.run, error=f"{type(e).__name__}: {e}"[:200])
            raise
        self.ledger.record(reply, self.run)
        return reply


def _relabel(client: Any, ledger, run: str | None) -> bool:
    """True when every call through `client` is already recorded. Points those records at this ledger and run."""
    if isinstance(client, LedgeredClient):
        client.ledger, client.run = ledger if ledger is not None else client.ledger, run if run is not None else client.run
        return True
    if isinstance(client, FallbackClient):
        return all([_relabel(c, ledger, run) for c in client.clients])
    return False


# --- several models, and no model ----------------------------------------------------------------------

class FallbackClient:
    """The first model that can answer. Once one is out it stays out for this run, so each turn doesn't pay for finding out."""

    def __init__(self, clients: list[ModelClient], on_switch: Callable[[str, str], None] | None = None):
        self.clients, self.on_switch = list(clients), on_switch

    @property
    def model(self) -> str:
        return self.clients[0].model

    def generate(self, system: str, messages: list[Message], tools: list[ToolSpec], on_delta: Delta | None = None) -> ModelReply:
        while True:
            try:
                return self.clients[0].generate(system, messages, tools, on_delta)
            except Unavailable as e:
                if len(self.clients) == 1:
                    raise
                gone = self.clients.pop(0)
                if self.on_switch:
                    self.on_switch(gone.model, str(e))


class ScriptedModel:
    """For tests: script(messages, tools) returns a ModelReply, or one comes from a list. No network, no key."""

    def __init__(self, script: list[ModelReply | Exception] | Callable[..., ModelReply], model: str = "scripted"):
        self.script, self.model, self.requests = script, model, []

    def generate(self, system: str, messages: list[Message], tools: list[ToolSpec], on_delta: Delta | None = None) -> ModelReply:
        self.requests.append({"system": system, "messages": list(messages), "tools": [t.name for t in tools]})
        item = self.script(messages, tools) if callable(self.script) else self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        item.model = self.model
        if on_delta:
            if item.thinking:
                on_delta("thought", item.thinking)
            if item.text:
                on_delta("text", item.text)
        return item


def call(name: str, id_: str = "", **args: Any) -> ToolRequest:
    return ToolRequest(id_ or f"c-{name}", name, args)


def default_fallback(model: str) -> str | None:
    """The next cheapest of the compared models, or none for a model outside them."""
    return next((m for m in MODELS if m != model), None) if model in MODELS else None


def make_client(model: str = DEFAULT_MODEL, fallback: str | None = None, on_switch: Callable[[str, str], None] | None = None,
                effort: str | None = None, ledger=None, run: str | None = None) -> ModelClient:
    """A client for a model name, on Snowflake Cortex by the API that serves it: Messages for Claude, Chat Completions for
    the rest."""
    def one(name: str) -> ModelClient:
        wire = name.removeprefix("snowflake:")
        if wire.startswith("claude"):
            return MessagesClient(wire, effort=effort)
        return ChatCompletionsClient(wire)
    names = [model] + ([fallback] if fallback and fallback != model else [])
    clients: list[ModelClient] = [LedgeredClient(one(n), ledger, run) for n in names]  # every provider call, whatever the route
    return clients[0] if len(clients) == 1 else FallbackClient(clients, on_switch)


