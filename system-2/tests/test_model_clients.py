"""The providers' wire formats, against a local fake server. None of this needs a key or a network."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from rav_harness.ledger import Budget, Ledger, LedgeredClient, cost_of, spend_table
from rav_harness.model import (DEFAULT_MODEL, MODELS, SKIP_SIGNATURE, ChatCompletionsClient, FallbackClient, default_fallback, GeminiClient, Http, Image, Message, MessagesClient, ModelError, ModelReply, ScriptedModel, ToolRequest,
                               ToolResult, ToolSpec, Unavailable, make_client, read_env)

TOOL = ToolSpec("add", "Adds", {"type": "object", "properties": {"a": {"type": "number"}}, "required": ["a"]})
SECRET = "SECRET-KEY-VALUE"


class Fake:
    """Answers each POST from a list: (status, body), or a list of SSE event dicts."""

    def __init__(self, answers):
        self.answers, self.requests = list(answers), []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"path": self.path, "body": body, "headers": dict(self.headers)})
                answer = fake.answers.pop(0)
                if isinstance(answer, list):
                    data = "".join(f"data: {json.dumps(e)}\n\n" for e in answer).encode()
                    status = 200
                else:
                    status, data = answer[0], json.dumps(answer[1]).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def quick():
    return Http(min_interval_s=0, sleep=lambda s: None)


def gemini_events():
    return [{"candidates": [{"content": {"parts": [{"text": "Weigh", "thought": True}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "ing it.", "thought": True}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "I'll add."}]}}]},
            {"candidates": [{"content": {"parts": [{"functionCall": {"name": "add", "args": {"a": 1}, "id": "c1"}, "thoughtSignature": "SIG-1"}]}, "finishReason": "STOP"}],
             "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 7, "thoughtsTokenCount": 3, "cachedContentTokenCount": 4}}]


def test_gemini_streams_reasoning_and_sends_the_signature_back():
    fake = Fake([gemini_events(), gemini_events()])
    client = GeminiClient("m", key=SECRET, http=quick(), base_url=fake.url)
    deltas = []
    reply = client.generate("sys", [Message("user", "hi")], [TOOL], lambda kind, text: deltas.append((kind, text)))
    assert reply.thinking == "Weighing it." and reply.text == "I'll add." and reply.calls[0].args == {"a": 1}
    assert deltas[0] == ("thought", "Weigh") and ("text", "I'll add.") in deltas
    assert (reply.tokens_in, reply.tokens_out, reply.tokens_thinking, reply.tokens_cached) == (11, 7, 3, 4)
    messages = [Message("user", "hi"), Message("assistant", reply=reply), Message("user", results=[ToolResult(reply.calls[0], {"sum": 1})], images=[Image("image/png", "QUJD", "a view")])]
    client.generate("sys", messages, [TOOL])
    sent = fake.requests[1]["body"]["contents"]
    assert {"functionCall": {"name": "add", "args": {"a": 1}, "id": "c1"}, "thoughtSignature": "SIG-1"} in sent[1]["parts"]
    assert sent[2]["parts"][0]["functionResponse"] == {"name": "add", "response": {"sum": 1}, "id": "c1"}
    assert {"inlineData": {"mimeType": "image/png", "data": "QUJD"}} in sent[2]["parts"]
    assert fake.requests[0]["body"]["tools"][0]["functionDeclarations"][0]["parameters"]["type"] == "OBJECT"


def test_a_call_from_another_gemini_model_gets_the_skip_value():
    fake = Fake([gemini_events(), gemini_events()])
    first = GeminiClient("one", key=SECRET, http=quick(), base_url=fake.url)
    reply = first.generate("s", [Message("user", "hi")], [TOOL])
    second = GeminiClient("two", key=SECRET, http=quick(), base_url=fake.url)
    second.generate("s", [Message("user", "hi"), Message("assistant", reply=reply), Message("user", results=[ToolResult(reply.calls[0], {})])], [TOOL])
    parts = fake.requests[1]["body"]["contents"][1]["parts"]
    assert any(p.get("thoughtSignature") == SKIP_SIGNATURE for p in parts) and not any(p.get("thought") for p in parts)


def test_overload_is_retried_a_long_quota_isnt_and_a_bad_request_isnt():
    fake = Fake([(503, {"error": {"message": "busy"}}), gemini_events()])
    assert GeminiClient("m", key=SECRET, http=quick(), base_url=fake.url).generate("s", [Message("user", "x")], []).calls
    fake = Fake([(429, {"error": {"message": "out", "details": [{"retryDelay": "44728s"}]}})])
    with pytest.raises(Unavailable, match="out of quota"):
        GeminiClient("m", key=SECRET, http=quick(), base_url=fake.url).generate("s", [Message("user", "x")], [])
    assert len(fake.requests) == 1
    fake = Fake([(400, {"error": {"message": "Function call is missing a thought_signature"}})])
    with pytest.raises(ModelError, match="thought_signature") as e:
        GeminiClient("m", key=SECRET, http=quick(), base_url=fake.url).generate("s", [Message("user", "x")], [])
    assert not isinstance(e.value, Unavailable) and SECRET not in str(e.value)


def test_a_short_rate_limit_waits_as_long_as_it_asks():
    waits = []
    fake = Fake([(429, {"error": {"details": [{"retryDelay": "7s"}]}}), gemini_events()])
    GeminiClient("m", key=SECRET, http=Http(min_interval_s=0, sleep=waits.append), base_url=fake.url).generate("s", [Message("user", "x")], [])
    assert 7.0 in waits


def test_the_key_is_a_header_and_never_in_a_url_or_a_body():
    fake = Fake([gemini_events()])
    GeminiClient("m", key=SECRET, http=quick(), base_url=fake.url).generate("s", [Message("user", "x")], [])
    r = fake.requests[0]
    assert SECRET not in r["path"] and SECRET not in json.dumps(r["body"]) and {k.lower(): v for k, v in r["headers"].items()}["x-goog-api-key"] == SECRET


def chat_answer():
    return (200, {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": "Adding.", "reasoning_content": "Hm.",
                                                                          "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "add", "arguments": "{\"a\": 2}"}}]}}],
                  "usage": {"prompt_tokens": 9, "completion_tokens": 3, "prompt_tokens_details": {"cached_tokens": 2}}})


def test_chat_completions_round_trip_with_its_required_headers():
    fake = Fake([chat_answer(), chat_answer()])
    client = ChatCompletionsClient("openai-x", base_url=fake.url, token=SECRET, http=quick())
    reply = client.generate("sys", [Message("user", "hi")], [TOOL])
    assert reply.calls[0].id == "t1" and reply.calls[0].args == {"a": 2} and reply.thinking == "Hm." and reply.tokens_cached == 2 and reply.stop_reason == "tool_use"
    client.generate("sys", [Message("user", "hi"), Message("assistant", reply=reply), Message("user", results=[ToolResult(reply.calls[0], {"sum": 2})], images=[Image("image/png", "QUJD")])], [TOOL])
    first, second = fake.requests
    assert first["path"] == "/chat/completions" and first["headers"]["Accept"] == "application/json" and first["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert first["body"]["max_completion_tokens"] and first["body"]["tools"][0]["function"]["name"] == "add"
    messages = second["body"]["messages"]
    assert messages[2]["tool_calls"][0]["id"] == "t1" and messages[3] == {"role": "tool", "tool_call_id": "t1", "content": "{\"sum\": 2}"}
    assert messages[4]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def messages_answer():
    return (200, {"content": [{"type": "thinking", "thinking": "Hm.", "signature": "S"}, {"type": "text", "text": "Adding."}, {"type": "tool_use", "id": "u1", "name": "add", "input": {"a": 3}}],
                  "stop_reason": "tool_use", "usage": {"input_tokens": 5, "output_tokens": 4, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 20}})


def test_messages_round_trip_caches_and_counts_cached_input():
    fake = Fake([messages_answer(), messages_answer()])
    client = MessagesClient("claude-x", base_url=fake.url, token=SECRET, http=quick())
    reply = client.generate("sys", [Message("user", "hi")], [TOOL])
    assert reply.calls[0].args == {"a": 3} and reply.thinking == "Hm." and (reply.tokens_in, reply.tokens_cached, reply.tokens_cache_write) == (125, 100, 20)
    client.generate("sys", [Message("user", "hi"), Message("assistant", reply=reply), Message("user", results=[ToolResult(reply.calls[0], {"sum": 3}, True)], images=[Image("image/png", "QUJD", "v")])], [TOOL])
    first, second = fake.requests
    assert first["path"] == "/messages" and first["body"]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["body"]["tools"][0]["input_schema"]["type"] == "object"
    sent = second["body"]["messages"]
    assert sent[1]["content"][0]["signature"] == "S"  # a thinking block goes back as it came
    assert sent[2]["content"][0] == {"type": "tool_result", "tool_use_id": "u1", "content": "{\"sum\": 3}", "is_error": True}
    assert sent[2]["content"][-1]["cache_control"] == {"type": "ephemeral"} and sent[2]["content"][-1]["type"] == "image"


def test_names_route_to_the_right_api_and_google_only_runs_when_named(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_BASE_URL", "http://x")
    monkeypatch.setenv("SNOWFLAKE_PAT", "t")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    api = lambda name: make_client(name).client  # noqa: E731 - each provider sits inside its ledger
    assert isinstance(api("claude-sonnet-5-5"), MessagesClient) and isinstance(api("openai-gpt-5.4"), ChatCompletionsClient) and isinstance(api("grok-4.7"), ChatCompletionsClient)
    assert isinstance(make_client().client, MessagesClient) and make_client().client.wire == DEFAULT_MODEL == "claude-haiku-5-5"
    assert isinstance(api("gemini-3.8-flash"), ChatCompletionsClient)  # a bare name goes to Cortex, never to Google
    assert isinstance(api("gemini-direct:gemini-3.8-flash"), GeminiClient)
    assert all("gemini" not in m for m in MODELS) and default_fallback("claude-haiku-5-5") in MODELS and default_fallback("other") is None
    assert all(isinstance(c.client, (MessagesClient, ChatCompletionsClient)) for c in make_client("claude-haiku-5-5", default_fallback("claude-haiku-5-5")).clients)


def test_reasoning_comes_through_under_either_name_and_absent_is_empty():
    for field in ("reasoning_content", "reasoning"):
        fake = Fake([(200, {"choices": [{"message": {"content": "x", field: "Because."}}]})])
        assert ChatCompletionsClient("x", base_url=fake.url, token=SECRET, http=quick()).generate("s", [Message("user", "x")], []).thinking == "Because."
    fake = Fake([(200, {"choices": [{"message": {"content": "x"}}]})])
    assert ChatCompletionsClient("x", base_url=fake.url, token=SECRET, http=quick()).generate("s", [Message("user", "x")], []).thinking == ""


def test_a_model_with_no_vision_is_told_and_doesnt_crash():
    fake = Fake([(400, {"message": "x is not a multimodal model"}), (200, {"choices": [{"message": {"content": "ok"}}]}), (200, {"choices": [{"message": {"content": "ok"}}]})])
    client = ChatCompletionsClient("x", base_url=fake.url, token=SECRET, http=quick())
    with_image = [Message("user", "see", images=[Image("image/png", "QUJD", "frame:1")])]
    assert client.generate("s", with_image, []).text == "ok" and client.vision is False
    client.generate("s", with_image, [])
    assert len(fake.requests) == 3
    assert "frame:1" in fake.requests[1]["body"]["messages"][1]["content"] and "image_url" not in json.dumps(fake.requests[2]["body"])


def test_settings_come_from_the_env_file_and_stay_out_of_the_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("RAV_TEST_SETTING", raising=False)
    path = tmp_path / ".env"
    path.write_text('RAV_TEST_SETTING="abc"\n')
    assert read_env("RAV_TEST_SETTING", path) == "abc"
    import os
    assert "RAV_TEST_SETTING" not in os.environ


def test_fallback_moves_on_and_remembers():
    switched = []
    one = ScriptedModel([Unavailable("out")], "one")
    two = ScriptedModel([ModelReply(model="", text="a"), ModelReply(model="", text="b")], "two")
    client = FallbackClient([one, two], lambda gone, why: switched.append(gone))
    assert client.generate("s", [], []).model == "two" and client.generate("s", [], []).text == "b"
    assert switched == ["one"] and len(one.requests) == 1 and client.model == "two"
    with pytest.raises(Unavailable):
        FallbackClient([ScriptedModel([Unavailable("x")])]).generate("s", [], [])


# --- the ledger ----------------------------------------------------------------------------------

PRICES = {"m": {"input": 1.0, "output": 10.0, "cached_input": 0.1, "cache_write": 2.0}}


def reply(**kw):
    return ModelReply(model="snowflake:m", tokens_in=1_000_000, tokens_out=100_000, **kw)


def test_every_call_is_on_the_ledger_and_survives_a_restart(tmp_path):
    path = tmp_path / "l.jsonl"
    client = LedgeredClient(ScriptedModel([ModelReply(model="", tokens_in=7, tokens_out=2)], "snowflake:m"), Ledger(path), "run1")
    client.generate("s", [], [])
    rows = Ledger(path).rows()
    assert rows[0]["run"] == "run1" and rows[0]["input"] == 7 and "s" not in rows[0]


def test_cost_uses_each_rate_and_says_when_it_doesnt_know():
    row = {"model": "snowflake:m", "input": 1_000_000, "output": 100_000, "cached": 500_000, "cache_write": 100_000, "thinking": 0}
    assert cost_of(row, PRICES) == pytest.approx(0.4 + 0.05 + 0.2 + 1.0)
    assert cost_of({**row, "model": "other"}, PRICES) is None


def test_the_real_price_table_is_in_credits_with_an_assumed_dollar_rate():
    from rav_harness.ledger import load_prices, run_spend, usd_per_credit
    prices = load_prices()
    assert set(prices) == {"claude-haiku-5-5", "claude-sonnet-5-5", "grok-4.7", "openai-gpt-5.4"} and usd_per_credit() == 2.0
    row = {"model": "snowflake:claude-haiku-5-5", "input": 1_000_000, "cached": 600_000, "cache_write": 100_000, "output": 10_000, "thinking": 0}
    assert cost_of(row, prices) == pytest.approx(0.3 * 0.05 + 0.6 * 0.005 + 0.1 * 0.063 + 0.01 * 0.25)
    grok = {"model": "grok-4.7", "input": 1_000_000, "cached": 0, "cache_write": 0, "output": 0}
    assert run_spend([grok], prices, 2.0) == {"calls": 1, "tokens": 1_000_000, "credits": 1.0, "usd": 2.0, "unpriced_calls": 0}


def test_the_total_prints_and_flags_what_has_no_price(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.record(reply())
    ledger.record(ModelReply(model="other", tokens_in=5))
    text = spend_table(ledger, PRICES, rate=2.0)
    assert "no price" in text and "plus 1 calls with no price" in text and "2.0000 credits, $4.0000 at an assumed $2.00 per credit" in text


def test_a_run_that_could_cross_the_budget_doesnt_start(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    budget = Budget(5.0, ledger, PRICES, margin=1.5, rate=1.0)
    assert budget.refuse("snowflake:m") is None  # 60k tokens at the dearest rate: $0.60 x 1.5
    ledger.record(reply(), "run1")  # $2, and now that's the measured worst run: $3 more is exactly the cap
    assert budget.refuse("m") is None
    ledger.record(reply(), "run2")  # $4 spent, and a run could add $3
    assert "over the $5.00 budget" in budget.refuse("m")
    assert Budget(5.0, ledger, PRICES, rate=1.0).refuse("rules") is None
    assert "over the $5.00 budget" in Budget(5.0, ledger, PRICES, rate=2.0).refuse("m")  # 2 credits a run is $4 at $2 a credit


def test_no_price_is_refused_unless_allowed_and_then_tokens_are_the_cap(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    assert "no price" in Budget(5.0, ledger, {}).refuse("m")
    capped = Budget(5.0, ledger, {}, no_price_ok=True, token_cap=100_000, first_run_tokens=60_000, margin=1.5)
    assert capped.refuse("m") is None
    ledger.record(ModelReply(model="m", tokens_in=20_000, tokens_out=0), "run1")
    assert capped.refuse("m") is None  # 20k used, and the measured worst is 20k: 30k more
    ledger.record(ModelReply(model="m", tokens_in=60_000, tokens_out=0), "run2")
    assert "over the cap" in capped.refuse("m")


def test_a_bad_tool_argument_from_the_provider_doesnt_crash_the_parse():
    bad = (200, {"choices": [{"message": {"content": "", "tool_calls": [{"id": "t", "function": {"name": "add", "arguments": "{not json"}}]}}]})
    fake = Fake([bad])
    got = ChatCompletionsClient("x", base_url=fake.url, token=SECRET, http=quick()).generate("s", [Message("user", "x")], [])
    assert got.calls[0] == ToolRequest("t", "add", {"_unparsed": "{not json"})


def test_claude_reasoning_is_asked_for_only_when_set_and_the_adaptive_way():
    fake = Fake([(200, {"content": [{"type": "thinking", "thinking": "Why."}, {"type": "text", "text": "x"}], "stop_reason": "end_turn"})] * 2)
    plain = MessagesClient("claude-x", base_url=fake.url, token=SECRET, http=quick())
    plain.generate("s", [Message("user", "x")], [])
    assert "thinking" not in fake.requests[0]["body"]
    deep = MessagesClient("claude-x", base_url=fake.url, token=SECRET, http=quick(), effort="low")
    assert deep.generate("s", [Message("user", "x")], []).thinking == "Why."
    assert fake.requests[1]["body"]["thinking"]["type"] == "adaptive" and fake.requests[1]["body"]["output_config"] == {"effort": "low"}


def test_the_results_page_prices_each_run_from_its_own_ledger_rows(tmp_path):
    """Run labels repeat across rounds, so a run's calls are its label inside the span its event log covers."""
    import os
    import time as _t
    from rav_harness.results_page import build
    runs = tmp_path / "runs"
    folder = runs / "eval-a"
    run = folder / "001-claude-haiku-5-5-x-A"
    run.mkdir(parents=True)
    (run / "events.jsonl").write_text(json.dumps({"seq": 1, "t": 1.0, "type": "run_started"}) + "\n" + json.dumps({"seq": 2, "t": 100.0, "type": "run_finished"}) + "\n")
    end = _t.time()
    os.utime(run / "events.jsonl", (end, end))
    (folder / "results.json").write_text(json.dumps({"results": [{"model": "claude-haiku-5-5", "run_id": run.name, "tokens": 1_000_000, "faults_planted": [], "faults_found": []}]}))
    mine = {"run": run.name, "model": "claude-haiku-5-5", "at": end - 50, "input": 1_000_000, "output": 0, "cached": 0, "cache_write": 0}
    earlier_round = {**mine, "at": end - 3600}  # same label, an hour before: another round's run
    config = {"models": ["claude-haiku-5-5"], "baseline": "rules", "rounds": [{"id": "x", "title": "t", "status": "done", "kind": "eval", "folders": ["eval-a"]}]}
    out = build(config, runs, [mine, earlier_round])
    row = out["rounds"][0]["rows"][0]
    assert row["credits"] == pytest.approx(0.05) and row["usd"] == pytest.approx(0.10) and row["per_run"][0]["tokens"] == 1_000_000
    assert out["rounds"][0]["cost"] == {"tokens": 1_000_000, "credits": 0.05, "usd": 0.1}
    assert out["pricing"]["usd_per_credit"] == 2.0 and "assumption" in out["pricing"]["usd_is"]


def test_the_same_run_label_in_two_rounds_is_two_runs_to_the_budget(tmp_path):
    path = tmp_path / "l.jsonl"
    rows = [{"at": at, "run": "001-m-x-A", "model": "m", "input": 500_000, "output": 0} for at in (1000.0, 1010.0, 9000.0)]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    budget = Budget(None, Ledger(path), PRICES, token_cap=10_000_000)
    assert budget._worst_run("m")[1] == 1_000_000  # not 1.5M: the third call is a later round's run with the same label
