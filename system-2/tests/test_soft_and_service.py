"""The round-one scenarios, the scorer, the rav-agent service, and two real processes over the network."""
import json
import threading
import time
import urllib.error
import urllib.request

import pytest
from rav_contracts import Control, Frame, Report, StepTrace
from rav_harness.agent import AgentConfig, run_agent, sim_auto_approve
from rav_harness.eval import _truth_map, score, summarize
from rav_harness.launch import Device, System1Process, _env, server_command
from rav_harness.ledger import Budget, Ledger
from rav_harness.model import MODELS, ModelReply, ScriptedModel, call
from rav_harness.runlog import RunLog, read_events
from rav_harness.service import ORIGINS, Hub, Service, at_recording_time, available_models, manual_of, merge_timeline, project_of
from rav_harness.soft import SCENARIOS, format_table, number_png, run_round_one, run_scenario

PLAIN = AgentConfig(max_turns=30, max_tokens=120_000, check_back=False)  # scripted plans here test other rules; check-back has its own tests

CONSOLE = next(iter(ORIGINS))


def by_name(name):
    return next(s for s in SCENARIOS if s.name == name)


def say(*calls, text=""):
    return ModelReply(model="", text=text, calls=list(calls), tokens_in=100, tokens_out=10, latency_ms=5.0)


class Thorough:
    """A generic model that reads every result it's given and does the sensible thing: enough to prove scoring and scenarios work."""

    def __init__(self, summary="ok", ledger=None):
        self.summary, self.model = summary, "thorough"

    def generate(self, system, messages, tools, on_delta=None):
        names = [c.name for m in messages if m.role == "assistant" for c in m.reply.calls]
        last = messages[-1].results[-1].content if messages[-1].results else {}
        if not names:
            return say(call("look_at_device"))
        if last.get("controls"):
            self.controls = [c for c in last["controls"]]
            order = sorted(self.controls, key=lambda c: 0 if c.get("label") == "MAIN" else 1)
            steps = [{"id": f"s{n}", "skill": "observe" if c["kind"] == "display" else "press", "target": c["id"], "params": {} if c["kind"] == "display" else {"force_limit": 5}} for n, c in enumerate(order)]
            for s in steps:
                if next(c for c in order if c["id"] == s["target"]).get("label") == "GO":
                    s["check"] = [{"metric": "reading:RUN", "op": "==", "value": "1", "source": "manual"}]
                    s["requires"] = [{"metric": "reading:MAINS", "op": "==", "value": "1"}]
            self.plan, self.retests = steps, 0
            return say(call("propose_plan", steps=steps))
        if names[-1] == "propose_plan" and last.get("approved"):
            return say(call("run_plan"))
        if "error" in last and names[-1] == "run_plan":
            return say(call("propose_plan", steps=self.plan))
        if last.get("next") == "recover":
            return say(call("recover", action="home"))
        if names[-1] == "recover":
            todo = [i for i, s in last["progress"].items() if s in ("untested", "inconclusive")]
            self.retests += 1
            return say(call("propose_plan", steps=[{"id": f"re{self.retests}-{i}", "skill": "press", "target": i} for i in todo]))
        if last.get("next") == "answer_stop":
            todo = [r for r in last["results"] if r["status"] in ("failed", "inconclusive") and r["target"] not in getattr(self, "again", set())]
            if todo:
                self.again = getattr(self, "again", set()) | {r["target"] for r in todo}
                return say(call("answer_stop", kind="amend", steps=[*[{"id": f"again-{r['step']}", "skill": "press", "target": r["target"]} for r in todo],
                                                                    *[s for s in self.plan if s["id"] in last["remaining"]]]))
            return say(call("answer_stop", kind="continue"))
        progress = last.get("progress") or {}
        if any(s == "inconclusive" for s in progress.values()) and getattr(self, "looped", 0) < 2:
            self.looped = getattr(self, "looped", 0) + 1
            todo = [i for i, s in progress.items() if s == "inconclusive"]
            return say(call("propose_plan", steps=[{"id": f"loop{self.looped}-{i}", "skill": "press", "target": i} for i in todo]))
        return say(call("finish_run", summary=self.summary))


@pytest.mark.parametrize("scenario", [s.name for s in SCENARIOS if s.name != "image_read"])
def test_a_sensible_model_scores_full_marks(tmp_path, scenario):
    record = run_scenario(by_name(scenario), "thorough", tmp_path, Ledger(tmp_path / "l.jsonl"), PLAIN, make=lambda m: Thorough())
    assert record["score"] == 1.0, record


def test_reading_the_image_is_needed_for_full_marks(tmp_path):
    def run(summary):
        return run_scenario(by_name("image_read"), "thorough", tmp_path, Ledger(tmp_path / "l.jsonl"), PLAIN, make=lambda m: Thorough(summary))
    assert run("The display shows 4729.")["score"] == 1.0
    assert run("I couldn't read it.")["checks"]["read_the_number"] is False


def test_the_scenario_image_is_a_real_png_of_the_number():
    data = number_png("4729")
    assert data.startswith(b"\x89PNG") and len(data) > 100


def test_a_careless_model_loses_marks(tmp_path):
    """Presses GO before MAIN, with a check that doesn't declare what it needs: its own bad order turns into a false finding."""
    script = [say(call("look_at_device")),
              say(call("propose_plan", steps=[{"id": "a", "skill": "press", "target": "p1", "check": [{"metric": "reading:RUN", "op": "==", "value": "1", "source": "manual"}]},
                                              {"id": "b", "skill": "press", "target": "p2"}, {"id": "c", "skill": "press", "target": "p3"}])), say(call("run_plan")),
              say(call("answer_stop", kind="continue")), say(call("finish_run", summary="x"))]
    record = run_scenario(by_name("plan_from_manual"), "careless", tmp_path, Ledger(tmp_path / "l.jsonl"), PLAIN, make=lambda m: ScriptedModel(script))
    assert record["checks"]["no_false_findings"] is False and record["score"] < 1.0


def test_a_provider_that_breaks_scores_zero_and_the_round_goes_on(tmp_path):
    def make(model):
        if model == "broken":
            raise RuntimeError("no such model")
        return Thorough()
    done = run_round_one(["broken", "thorough"], tmp_path, make=make, ledger=Ledger(tmp_path / "l.jsonl"), scenarios=[by_name("false_alarm")], config=PLAIN)
    rows = {r["model"]: r for r in done["summary"]}
    assert rows["broken"]["crashes"] == 1 and rows["thorough"]["score"] == 1.0 and "thorough" in format_table(done["summary"])
    assert json.loads((tmp_path / done["folder"] / "results.json").read_text())["summary"]


def test_the_budget_stops_a_round_before_it_starts_a_run(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    budget = Budget(0.0, ledger, {"thorough": {"input": 1.0, "output": 1.0}})
    done = run_round_one(["thorough"], tmp_path, budget=budget, make=lambda m: Thorough(), ledger=ledger, scenarios=[by_name("false_alarm")], config=PLAIN)
    assert not done["results"] and "budget" in done["stopped"]


def test_the_rule_baseline_runs_free(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    record = run_scenario(by_name("false_alarm"), "rules", tmp_path, ledger)
    assert "score" in record and not ledger.rows() and record["checks"]["not_called_broken"] is False


# --- the scorer ----------------------------------------------------------------------------------

def test_controls_match_truth_by_place_when_their_ids_differ():
    scene = [{"id": "a", "pos_mm": [1, 0, 0]}, {"id": "b", "pos_mm": [40, 0, 0]}, {"id": "ghost", "pos_mm": [400, 0, 0]}]
    truth = [{"id": "t2", "pos_mm": [41, 0, 0]}, {"id": "t1", "pos_mm": [0, 0, 0]}]
    assert _truth_map(scene, truth) == {"a": "t1", "b": "t2"}


def test_the_score_separates_found_missed_false_and_noise(tmp_path):
    controls = [Control(id=i, kind="button", pos_mm=(n * 50.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0)) for n, i in enumerate("abcd")]
    log = RunLog("r", tmp_path)
    log.emit("scene_ready", {"controls": []} and __import__("rav_contracts").SceneInventory(controls=controls))
    log.emit("run_finished", {"status": "completed"})
    from rav_contracts import Coverage, Finding, Reward
    finding = lambda t, label: Finding(id="F", severity="high", target=t, label=label, what_happened="x", step_ids=["s"])  # noqa: E731
    report = Report(run_id="r", product="p", revision="A", summary="", findings=[finding("a", "stuck"), finding("b", "stuck"), finding("c", "intermittent")],
                    coverage=Coverage(detected=4, passed=["d"], failed=["a", "b"], observed=[], inconclusive=[], skipped={}, intermittent=["c"]), reward=Reward(value=0, control_coverage=1, pass_rate=0))
    key = {"controls": [{"id": c.id, "pos_mm": list(c.pos_mm)} for c in controls], "faults": [{"part": "a"}, {"part": "d"}], "errors": [{"kind": "x"}]}
    s = score(report, read_events(log.path), key)
    assert s["faults_found"] == ["a"] and s["faults_missed"] == ["d"] and s["false_findings"] == ["b"] and s["noise_flags"] == ["c"] and s["errors_injected"] == 1
    assert summarize([{"model": "m", **s}])["m"]["faults_found"] == 1


def test_a_workflow_in_the_key_is_scored_from_readings(tmp_path):
    from rav_contracts import Coverage, Reward, StepOutcome, StepTrace, StepVerdict
    log = RunLog("r", tmp_path)
    log.emit("step_finished", StepOutcome(trace=StepTrace(step="s", readout_change={"RUN": [0, 1]}), verdict=StepVerdict(step="s", target="a", status="passed", reason="")))
    report = Report(run_id="r", product="p", revision="A", summary="", findings=[], coverage=Coverage(detected=0, passed=[], failed=[], observed=[], inconclusive=[], skipped={}), reward=Reward(value=0, control_coverage=0, pass_rate=0))
    events = read_events(log.path)
    assert score(report, events, {"expected": {"workflow": [{"channel": "RUN", "value": 1}]}})["workflow_done"] is True
    assert score(report, events, {"expected": {"workflow": [{"channel": "RUN", "value": 2}]}})["workflow_done"] is False


# --- the process boundary ------------------------------------------------------------------------

def test_the_server_command_passes_only_what_was_asked_and_no_secrets():
    device = Device(seed=7, faults=["stuck_button"], error_rate=0.05, error_seed=3, placement="random")
    cmd = server_command(device, 9000, 9001, None, None, None)
    assert cmd[cmd.index("--seed") + 1] == "7" and "--error-rate" in cmd and "--depth" not in cmd and "--answer-key" not in cmd
    assert "--seed" not in server_command(Device(robot="mock"), 9000, 9001, None, None, None)


def test_two_real_processes_over_the_network(tmp_path):
    """The agent, then rav-server --robot mock as its own process. Then the server dying mid-run still leaves a report."""
    process = System1Process(Device(robot="mock"), tmp_path / "server", telemetry_port=0)
    system1 = process.start()
    try:
        script = [say(call("get_status")), say(call("look_at_device")),
                  say(call("propose_plan", steps=[{"id": "x", "skill": "press", "target": "nope"}])),
                  say(call("propose_plan", steps=[{"id": f"s{n}", "skill": "press", "target": f"button_{n}"} for n in (1, 2, 3)])),
                  say(call("run_plan")), say(call("finish_run", summary="fine"))]
        client = ScriptedModel(script)
        log = RunLog("two", tmp_path)
        report = run_agent(system1, __import__("rav_contracts").TestRequest(request_id="two", product="p"), log, client, approve=sim_auto_approve, config=PLAIN)
        assert report.coverage.passed == ["button_1", "button_2", "button_3"]
        events = read_events(log.path)
        told = [r.content.get("error", "") for m in client.requests[3]["messages"] for r in m.results]
        assert any("nope" in t for t in told)
        assert any(e.type == "tool_call" and e.payload["tool"] == "system1.routine_start" for e in events)
    finally:
        system1.close()
        process.stop()
    assert process.process.poll() is not None

    process = System1Process(Device(robot="mock"), tmp_path / "server2", telemetry_port=0)
    system1 = process.start()
    def die_then(messages, tools):
        process.stop()
        return say(call("look_at_device"))
    answers = [die_then, lambda m, t: say(call("finish_run", summary="the robot went away"))]
    client = ScriptedModel(lambda m, t: answers.pop(0)(m, t) if len(answers) > 1 else say(call("get_scene")))
    log = RunLog("gone", tmp_path)
    try:
        from rav_harness.agent import AgentConfig
        report = run_agent(system1, __import__("rav_contracts").TestRequest(request_id="gone", product="p"), log, client, approve=sim_auto_approve, config=AgentConfig(max_turns=4, check_back=False))
        assert (tmp_path / "gone/report.json").is_file() and isinstance(report, Report)
        bad = [e.payload for e in read_events(log.path) if e.type == "tool_call" and not e.payload["ok"]]
        assert bad and bad[0]["layer"] == "pipeline"
    finally:
        try:
            system1.close()
        except Exception:  # noqa: BLE001, S110 - the far end is gone, which is the test
            pass


def post(service, path, body, origin=CONSOLE):
    request = urllib.request.Request(f"http://127.0.0.1:{service.port}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **({"Origin": origin} if origin else {})})
    try:
        with urllib.request.urlopen(request, timeout=5) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


@pytest.fixture
def service(tmp_path):
    made = {}
    def make(model, fallback=None, on_switch=None, **_):
        client = ScriptedModel(made["script"], "scripted")
        made["client"] = client
        return client
    s = Service(tmp_path, port=0, make=make, config=PLAIN)
    s.made = made
    threading.Thread(target=s.serve, daemon=True).start()
    yield s
    s.server.shutdown()


def listen(service):
    """Collects the SSE stream into a list, on a thread."""
    got = []
    def run():
        request = urllib.request.Request(f"http://127.0.0.1:{service.port}/events")
        with urllib.request.urlopen(request, timeout=30) as r:
            name = None
            for line in r:
                line = line.decode().strip()
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    got.append((name, json.loads(line[5:])))
    threading.Thread(target=run, daemon=True).start()
    return got


def until(fn, seconds=30):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(0.05)
    return False


def test_only_the_console_can_send_commands(service):
    assert post(service, "/start", {}, origin="http://evil.example")[0] == 403
    assert post(service, "/start", {}, origin=None)[0] == 403
    assert post(service, "/steer", {"kind": "stop"})[0] == 409
    assert post(service, "/approve", {"kind": "plan", "ref": "x"})[0] == 409


def test_a_whole_run_from_the_console_with_a_person_approving_and_steering(service):
    plan = [{"id": f"s{n}", "skill": "press", "target": f"button_{n}"} for n in (1, 2, 3)]
    service.made["script"] = [say(call("look_at_device"), text="Looking."), say(call("propose_plan", steps=plan)), say(call("run_plan")), say(call("finish_run", summary="done"), text="Finished.")]
    got = listen(service)
    status, body = post(service, "/start", {"device": {"robot": "mock"}, "model": "claude-haiku-5-5"})
    assert status == 200 and body["ok"]
    assert post(service, "/start", {"device": {"robot": "mock"}})[0] == 409
    with urllib.request.urlopen(f"http://127.0.0.1:{service.port}/health") as r:
        health = json.load(r)
    assert health["running"] and health["model"] == "claude-haiku-5-5" and "claude-haiku-5-5" in health["models"]
    assert until(lambda: any(n == "run" and e["type"] == "approval_needed" for n, e in got)), got[-3:]
    assert post(service, "/steer", {"kind": "message", "text": "Careful with button_2.", "by": "Ada"})[0] == 200
    assert post(service, "/steer", {"kind": "nonsense"})[0] == 400
    assert post(service, "/approve", {"kind": "plan", "ref": "wrong"})[0] == 409
    assert post(service, "/approve", {"kind": "plan", "ref": "plan-1", "by": "Ada", "ok": True})[0] == 200
    assert until(lambda: any(n == "run" and e["type"] == "run_finished" for n, e in got)), got[-3:]
    types = [e["type"] for n, e in got if n == "run"]
    assert "model_turn" in types and "tool_call" in types and "agent_state" in types and "report_ready" in types
    assert any(n == "meta" and e["stages"] for n, e in got) and any(n == "delta" and e["text"] == "Looking." for n, e in got)
    approved = next(e["payload"] for n, e in got if n == "run" and e["type"] == "approved")
    assert approved["by"] == "Ada"
    assert until(lambda: not service.hub.running)
    late = listen(service)  # someone opening the page afterwards gets the run, without the deltas
    assert until(lambda: any(n == "run" and e["type"] == "run_finished" for n, e in late))
    assert not any(n == "delta" for n, e in late)
    run_id = next(e["run_id"] for n, e in got if n == "meta")
    assert (service.runs_root / run_id / "report.json").is_file()


def test_auto_approval_is_recorded_on_the_run(service):
    plan = [{"id": f"s{n}", "skill": "press", "target": f"button_{n}"} for n in (1, 2, 3)]
    service.made["script"] = [say(call("look_at_device")), say(call("propose_plan", steps=plan)), say(call("run_plan")), say(call("finish_run", summary="done"))]
    got = listen(service)
    post(service, "/start", {"device": {"robot": "mock"}, "auto_approve": True})
    assert until(lambda: any(n == "run" and e["type"] == "run_finished" for n, e in got)), got[-3:]
    assert any(n == "run" and e["type"] == "approved" and e["payload"]["by"] == "auto (sim)" for n, e in got)


def test_a_project_has_to_exist_and_a_manual_comes_from_its_folder(tmp_path):
    (tmp_path / "p/manual").mkdir(parents=True)
    (tmp_path / "p/manual/guide.txt").write_text("Press it.")
    (tmp_path / "p/project.json").write_text('{"id": "p", "name": "P"}')
    project = project_of("p", tmp_path)
    assert manual_of(project, tmp_path).read()["text"] == "Press it." and project_of(None) == {}
    with pytest.raises(ValueError):
        project_of("../secrets", tmp_path)
    assert manual_of({"id": "none"}, tmp_path) is None


def test_listeners_get_history_first_and_deltas_dont_stick():
    hub = Hub()
    hub.publish("run", {"a": 1})
    q = hub.listen()
    hub.publish("delta", {"b": 2}, keep=False)
    assert [q.get_nowait()[0] for _ in range(3)] == ["reset", "run", "delta"] and len(hub.history) == 1


def test_only_the_compared_models_are_offered():
    assert "claude-haiku-5-5" in available_models() and set(available_models()) <= {*MODELS, "rules"}


def test_the_server_gets_no_model_keys_but_keeps_its_path(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_PAT", "x")
    monkeypatch.setenv("OTHER_API_KEY", "x")
    monkeypatch.setenv("RAV_TOKEN", "t")
    env = _env()
    assert "PATH" in env and "SNOWFLAKE_PAT" not in env and "OTHER_API_KEY" not in env and env["RAV_TOKEN"] == "t"


def test_a_recording_gets_its_events_on_its_own_clock(tmp_path):
    log = RunLog("r", tmp_path)
    log.wall0 = 1000.0
    event = log.emit("message", {"role": "harness", "text": "x"})
    (log.dir / "timeline.json").write_text(json.dumps({"anchors": [[1000.0, 0.0], [1010.0, 5.0]], "events": {}, "meta": {"product": "rig"}}))
    merge_timeline(log, "A product")
    timeline = json.loads((log.dir / "timeline.json").read_text())
    assert timeline["meta"]["product"] == "A product" and str(event.seq) in timeline["events"]
    assert at_recording_time(1005.0, [[1000.0, 0.0], [1010.0, 5.0]]) == 2.5 and at_recording_time(9.0, []) == 0.0 and at_recording_time(2000.0, [[1000.0, 3.0]]) == 3.0
    merge_timeline(RunLog("no-recording", tmp_path), "x")  # nothing to do, and no complaint


# --- what the Console's real run found ------------------------------------------------------------------

def get(service, path, origin=CONSOLE):
    request = urllib.request.Request(f"http://127.0.0.1:{service.port}{path}", headers={"Origin": origin} if origin else {})
    try:
        with urllib.request.urlopen(request, timeout=5) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


class Evidence:
    def evidence_get(self, ref):
        if ref != "trace:r1:s1:1":
            raise KeyError(ref)
        return StepTrace(step="s1", attempt=1)

    def evidence_frame(self, ref):
        return Frame(ref=ref, mime="image/png", data_b64="QUJD", width=2, height=2, caption="before")


def test_evidence_and_frames_come_from_the_live_run_for_the_console_only(service):
    assert get(service, "/evidence?ref=frame:6")[0] == 409  # nothing live
    service.hub.system1 = Evidence()
    status, body = get(service, "/evidence?ref=frame:6")
    assert status == 200 and body["frame"]["data_b64"] == "QUJD"
    assert get(service, "/evidence?ref=trace:r1:s1:1")[1]["trace"]["step"] == "s1"
    assert get(service, "/evidence?ref=trace:nope")[0] == 404 and get(service, "/evidence")[0] == 400
    assert get(service, "/evidence?ref=frame:6", origin="http://evil.example")[0] == 403 and get(service, "/evidence?ref=frame:6", origin=None)[0] == 403


def _sleeper(tmp_path):
    """A process group whose command line says rav-server, like the real one under uv."""
    import subprocess
    import sys
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "rav-server"], start_new_session=True)


def test_servers_go_down_with_the_service_and_a_crashed_ones_are_reaped(tmp_path):
    from rav_harness import launch
    live = System1Process(Device(robot="mock"), tmp_path / "a")
    live.process = _sleeper(tmp_path)
    launch.LIVE.add(live)
    launch._register(live.process.pid, {"port": 1, "run_id": "a"})
    launch.stop_all()  # what SIGINT, SIGTERM and atexit run
    assert live.process.poll() is not None and str(live.process.pid) not in launch._registered()
    left = _sleeper(tmp_path)  # one a crash left behind, still registered
    launch._register(left.pid, {"port": 2, "run_id": "b"})
    said = launch.reap_stale_servers()
    left.wait(10)
    assert left.returncode is not None and "b" in said[0] and not launch._registered()


def test_a_busy_port_is_said_plainly(tmp_path):
    import socket
    from rav_harness import service as svc
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        with pytest.raises(SystemExit, match="is taken"):
            svc.main(["--port", str(held.getsockname()[1]), "--runs", str(tmp_path)])


def test_random_faults_vary_by_repeat_and_are_recorded():
    cmd = server_command(Device(seed=3, faults=["random"], fault_seed=3001), 1, 2, None, None, None)
    assert cmd[cmd.index("--fault-seed") + 1] == "3001"
    assert "--fault-seed" not in server_command(Device(seed=3), 1, 2, None, None, None)
    assert Device.from_request({"device": {"seed": 3, "fault": "random", "fault_seed": 9}}).fault_seed == 9


def test_every_provider_call_is_ledgered_whatever_the_route(tmp_path, monkeypatch):
    from rav_harness.model import FallbackClient, LedgeredClient, Unavailable, make_client
    monkeypatch.setenv("SNOWFLAKE_BASE_URL", "http://x")
    monkeypatch.setenv("SNOWFLAKE_PAT", "t")
    made = make_client("claude-haiku-5-5", "openai-gpt-5.4")
    assert isinstance(made, FallbackClient) and all(isinstance(c, LedgeredClient) for c in made.clients)
    assert isinstance(make_client("grok-4.7"), LedgeredClient) and isinstance(make_client("claude-sonnet-5-5"), LedgeredClient)
    ledger = Ledger(tmp_path / "l.jsonl")
    inner = LedgeredClient(ScriptedModel([ModelReply(model="m", tokens_in=5, tokens_out=1), RuntimeError("boom")], "m"))
    outer = LedgeredClient(inner, ledger, "run-1")  # what eval and the service add: re-labels, doesn't count twice
    outer.generate("s", [], [])
    with pytest.raises(RuntimeError):
        outer.generate("s", [], [])
    rows = ledger.rows()
    assert [(r["run"], r["input"]) for r in rows] == [("run-1", 5), ("run-1", 0)] and "boom" in rows[1]["error"]
    switching = FallbackClient([LedgeredClient(ScriptedModel([Unavailable("down")], "a")), LedgeredClient(ScriptedModel([ModelReply(model="b", tokens_in=3)], "b"))])
    LedgeredClient(switching, ledger, "run-2").generate("s", [], [])
    assert [(r["run"], r["model"], r["input"]) for r in ledger.rows()[2:]] == [("run-2", "a", 0), ("run-2", "b", 3)]


def test_the_services_model_calls_reach_the_ledger(service):
    plan = [{"id": "s1", "skill": "press", "target": "button_1"}]
    service.made["script"] = [say(call("look_at_device")), say(call("propose_plan", steps=plan)), say(call("run_plan")), say(call("finish_run", summary="done"))]
    before = len(Ledger().rows())
    assert post(service, "/start", {"device": {"robot": "mock"}, "auto_approve": True})[0] == 200
    assert until(lambda: not service.hub.running)
    rows = Ledger().rows()[before:]
    assert len(rows) >= 4 and all(r["run"].startswith("agent-mock") for r in rows) and rows[0]["input"] > 0


def test_a_stop_ends_the_run_while_the_model_waits_on_a_question(service):
    service.made["script"] = [say(call("look_at_device")), say(call("ask_operator", question="Which one first?")), say(call("finish_run", summary="x"))]
    got = listen(service)
    assert post(service, "/start", {"device": {"robot": "mock"}})[0] == 200
    assert until(lambda: any(n == "run" and e["type"] == "message" and e["payload"].get("asks") for n, e in got))
    assert post(service, "/steer", {"kind": "stop", "by": "Ada"})[0] == 200
    assert until(lambda: not service.hub.running, 10)
    finished = [e["payload"]["status"] for n, e in got if n == "run" and e["type"] == "run_finished"]
    assert finished == ["stopped"] and sum(e["type"] == "model_turn" for n, e in got if n == "run") == 2


def test_a_stop_ends_the_run_while_it_waits_on_an_approval(service):
    plan = [{"id": "s1", "skill": "press", "target": "button_1"}]
    service.made["script"] = [say(call("look_at_device")), say(call("propose_plan", steps=plan)), say(call("run_plan")), say(call("finish_run", summary="x"))]
    got = listen(service)
    assert post(service, "/start", {"device": {"robot": "mock"}})[0] == 200
    assert until(lambda: any(n == "run" and e["type"] == "approval_needed" for n, e in got))
    assert post(service, "/steer", {"kind": "stop", "by": "Ada"})[0] == 200
    assert until(lambda: not service.hub.running, 10)
    assert [e["payload"]["status"] for n, e in got if n == "run" and e["type"] == "run_finished"] == ["stopped"]


# --- authored devices ---------------------------------------------------------------------------------------

BUILD = {"faults": [{"id": "F1", "piece": "button_1", "property": "actuates"}, {"id": "F2", "piece": "button_2", "property": "procedure_completes"},
                    {"id": "F3", "piece": "well_1", "property": "accepts_object"}, {"id": "F4", "piece": "display_1", "property": "displays_matches"}],
         "revs": {"A": {"choices": {"F1": "A", "F2": "A", "F3": "A", "F4": "A"}, "observable": ["F1", "F2", "F3"], "masked": ["F4"]},
                  "B": {"choices": {"F1": "B", "F2": "B", "F3": "B", "F4": "B"}, "observable": [], "masked": []}}}


def _authored_run(tmp_path, findings, passed):
    from rav_contracts import Coverage, Finding, Reward
    log = RunLog("r", tmp_path)
    controls = [Control(id=i, kind="button", pos_mm=[n * 30.0, 0, 0], normal=[0, 0, 1]) for n, i in enumerate(["button_1", "button_2", "well_1", "display_1", "dial_1"])]
    from rav_contracts import SceneInventory
    log.emit("scene_ready", SceneInventory(controls=controls))
    report = Report(run_id="r", product="p", revision="A", findings=[Finding(id=f"F{n}", severity="high", target=t, label=l, what_happened="x", step_ids=["s1"]) for n, (t, l) in enumerate(findings)],
                    coverage=Coverage(detected=5, passed=passed, failed=[], observed=[], inconclusive=[], skipped={}), reward=Reward(value=0, control_coverage=0, pass_rate=0, formula="x"), summary="")
    key = {"device": {"rev": BUILD["revs"]["A"]["choices"]}, "controls": [{"id": c.id, "pos_mm": c.pos_mm} for c in controls], "errors": []}
    return score(report, read_events(log.path), key, BUILD)


def test_an_authored_device_is_scored_by_its_revisions_observable_faults(tmp_path):
    s = _authored_run(tmp_path / "a", [("button_1", "stuck"), ("dial_1", "stuck")], [])
    assert s["revision"] == "A" and s["faults_found"] == ["F1"] and s["faults_missed"] == ["F2"] and s["false_findings"] == ["dial_1"]
    assert s["faults_untestable_ok"] == ["F3"] and s["faults_planted"] == ["F1", "F2"]  # can't place an object: handled by not calling it passed
    masked = _authored_run(tmp_path / "b", [("display_1", "wrong_feedback")], ["well_1", "display_1"])
    assert not masked["false_findings"] and masked["masked_found"] == ["F4"]  # a masked fault found counts neither way
    assert masked["faults_called_passed"] == ["F3", "F4"] and masked["faults_untestable_ok"] == [] and "F3" in masked["faults_missed"]


def test_held_out_devices_are_never_run(tmp_path):
    from rav_harness.eval import find_authored
    (tmp_path / "appliances").mkdir()
    (tmp_path / "appliances" / "registry.json").write_text(json.dumps([{"id": "kept", "split": "held_out", "device": "appliances/kept/device.yaml"},
                                                                     {"id": "open", "split": "dev", "device": "appliances/open/device.yaml"}]))
    with pytest.raises(ValueError, match="held out"):
        find_authored("kept", tmp_path)
    assert find_authored("open", tmp_path)["build_key"].name == "answer_key.json"


def test_a_fault_reported_as_intermittent_counts_as_found_with_a_note(tmp_path):
    s = _authored_run(tmp_path, [("button_2", "intermittent")], [])
    assert s["faults_found"] == ["F2"] and s["found_as_intermittent"] == ["F2"] and not s["noise_flags"]


def test_a_finding_that_reads_a_faults_symptom_counts_for_it_wherever_its_check_sat(tmp_path):
    from rav_contracts import Coverage, Finding, Reward, SceneInventory, StepOutcome, StepVerdict
    from rav_contracts import CheckResult
    log = RunLog("r", tmp_path)
    controls = [Control(id=i, kind="button", pos_mm=[n * 30.0, 0, 0], normal=[0, 0, 1]) for n, i in enumerate(["button_1", "button_2", "well_1", "display_1", "toggle_1"])]
    log.emit("scene_ready", SceneInventory(controls=controls))
    from rav_contracts import Check, Plan, Step
    log.emit("plan_ready", Plan(plan_id="p", source="model", steps=[
        Step(id="on", skill="flip", target="toggle_1", quote="Shows 100 at power-on", check=[Check(metric="lcd", op="==", value="100")]),
        Step(id="made_up", skill="flip", target="toggle_1", check=[Check(metric="lcd", op="==", value="100")])]))
    for sid, actual in (("on", "60"), ("made_up", "60")):
        log.emit("step_finished", StepOutcome(trace=StepTrace(step=sid, checks=[CheckResult(metric="lcd", op="==", value="100", actual=actual, passed=False)]),
                                              verdict=StepVerdict(step=sid, target="toggle_1", status="failed", label="wrong_feedback", reason="x")))
    key = {"device": {"rev": BUILD["revs"]["A"]["choices"]}, "controls": [{"id": c.id, "pos_mm": c.pos_mm} for c in controls], "errors": []}
    cov = Coverage(detected=5, passed=[], failed=["toggle_1"], observed=[], inconclusive=[], skipped={})
    def run(step_ids, symptom):
        report = Report(run_id="r", product="p", revision="A", findings=[Finding(id="F1", severity="high", target="toggle_1", label="wrong_feedback", what_happened="x", step_ids=step_ids)],
                        coverage=cov, reward=Reward(value=0, control_coverage=0, pass_rate=0, formula="x"), summary="")
        return score(report, read_events(log.path), key, BUILD, symptom)
    shows = {"F2": {"on": "toggle_1", "reads": {"lcd", "state"}}}
    s = run(["on"], shows)
    assert "F2" in s["faults_found"] and s["found_by_symptom"] == {"F2": "toggle_1"} and not s["false_findings"]
    assert run(["made_up"], shows)["false_findings"] == ["toggle_1"]  # no quote: a number of its own, not the manual's promise
    assert run(["on"], {"F2": {"on": "button_2", "reads": {"lcd"}}})["false_findings"] == ["toggle_1"]  # the fault shows on another control's step
    assert run(["on"], {"F4": {"on": "toggle_1", "reads": {"lcd"}}})["false_findings"] == ["toggle_1"]  # a masked fault can't show
