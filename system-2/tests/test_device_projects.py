"""Every sim device in system-1's registry can be started from the Console: its project, revisions, effector and manual."""
import json
import threading
import time
import urllib.request

import pytest
from rav_harness.agent import AgentConfig
from rav_harness.launch import Device, server_command
from rav_harness.model import ModelReply, ScriptedModel, call
from rav_harness.service import ORIGINS, REPO, Service, config_for, manual_of, project_of

REGISTRY = json.loads((REPO / "appliances/registry.json").read_text())
CONSOLE = next(iter(ORIGINS))


def test_the_registry_has_the_centrifuge_and_ten_more():
    ids = {d["id"] for d in REGISTRY}
    assert len(ids) == 11 and "centrifuge" in ids
    assert {d["id"] for d in REGISTRY if d["split"] == "held_out"} == {"coffee-grinder", "hotplate-stirrer"}


@pytest.mark.parametrize("entry", REGISTRY, ids=lambda d: d["id"])
def test_each_device_has_a_project_that_matches_the_registry(entry):
    project = project_of(entry["project"])
    assert project["kind"] == "sim" and project["split"] == entry["split"]
    assert project["sim"]["path"] == entry["device"] and project["sim"]["revs"] == entry["revs"]
    assert project["sim"]["rev"] in entry["revs"] and project["manual"] == entry["manual"]
    manual = manual_of(project)  # the model reads this, as it does the centrifuge's
    assert manual is not None and manual.path == (REPO / entry["manual"]).resolve() and manual.read()["pages"] >= 1
    assert "build" not in manual.path.parts and "answer_key" not in manual.path.name


@pytest.mark.parametrize("entry", REGISTRY, ids=lambda d: d["id"])
def test_any_revision_of_any_device_makes_its_server_command(entry, tmp_path):
    project = project_of(entry["project"])
    for rev in entry["revs"]:
        device = Device.from_request({"device": {**project["sim"], "rev": rev}})
        cmd = server_command(device, 9000, 9001, tmp_path / "answer_key.json", None, None)
        assert cmd[cmd.index("--device") + 1] == str(REPO / entry["device"]) and cmd[cmd.index("--rev") + 1] == rev
        assert (REPO / entry["device"]).is_file()  # the server runs in system-1, so a repo-relative path wouldn't reach it
        assert cmd[cmd.index("--effector") + 1] == "stock"  # the real arm's only effector
        assert cmd[cmd.index("--answer-key") + 1] == str(tmp_path / "answer_key.json")  # written for scoring; no tool reads it
        assert "--fault" not in cmd  # a device file's faults are its revision's


def test_the_effector_is_the_gripper_unless_the_sim_probe_is_asked_for():
    sim = {"path": "x/device.yaml", "rev": "A", "revs": ["A", "B"]}
    assert Device.from_request({"device": {**sim, "effector": "probe"}}).effector == "probe"
    assert Device.from_request({"device": {**sim, "effector": None}}).effector == "stock"
    with pytest.raises(ValueError, match="effector"):
        Device.from_request({"device": {**sim, "effector": "claw"}})


def test_a_revision_has_to_be_the_devices_or_fault_choices():
    sim = {"path": "x/device.yaml", "revs": ["A", "B", "M1"]}
    assert Device.from_request({"device": {**sim, "rev": "M1"}}).rev == "M1"
    assert Device.from_request({"device": {**sim, "rev": "F1=B,F2=A"}}).rev == "F1=B,F2=A"
    for bad in ("M7", "--answer-key", "A B", 3):
        with pytest.raises(ValueError, match="revision"):
            Device.from_request({"device": {**sim, "rev": bad}})


def test_a_run_can_ask_for_fewer_turns_never_more():
    assert config_for({}, None).max_turns == AgentConfig().max_turns
    assert config_for({"max_turns": 15}, None).max_turns == 15
    assert config_for({"max_turns": 10_000}, AgentConfig(max_turns=40)).max_turns == 40
    for bad in (0, -3, 2.5, "15", True):
        with pytest.raises(ValueError):
            config_for({"max_turns": bad}, None)


def test_a_device_project_runs_from_the_console_and_stops_at_its_turn_limit(tmp_path):
    def make(model, fallback=None, on_switch=None, **_):
        return ScriptedModel(lambda messages, tools: ModelReply(model="", text="", calls=[call("get_status")], tokens_in=1, tokens_out=1, latency_ms=1.0), "scripted")
    service = Service(tmp_path, port=0, make=make)
    threading.Thread(target=service.serve, daemon=True).start()
    try:
        body = {"project": "wall-thermostat", "device": {"robot": "mock", "rev": "M1", "effector": "probe"}, "model": "claude-haiku-5-5",
                "max_turns": 2, "auto_approve": True}
        request = urllib.request.Request(f"http://127.0.0.1:{service.port}/start", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "Origin": CONSOLE})
        with urllib.request.urlopen(request, timeout=5) as r:
            assert json.load(r)["ok"]
        end = time.monotonic() + 30
        while (service.hub.running or service.hub.run_id is None) and time.monotonic() < end:
            time.sleep(0.05)
        events = [json.loads(line) for line in (tmp_path / service.hub.run_id / "events.jsonl").read_text().splitlines()]
        assert sum(e["type"] == "model_turn" for e in events) == 2
        assert any("turn limit" in str(e["payload"]) for e in events if e["type"] == "message")
        started = next(e for e in events if e["type"] == "run_started")["payload"]
        assert started["project"] == "wall-thermostat" and started["revision"] == "M1"
        assert "F1" not in json.dumps(started)  # nothing planted is in the request
    finally:
        service.server.shutdown()


def test_the_wiki_never_carries_a_held_out_devices_faults():
    from rav_harness.results_page import DOCS, held_out_safe
    md = "\n".join(["# Devices", "## Dev", "### Kettle (`kettle`)", "**Split:** dev.", "**Faults:** F1 lid.",
                    "## Held-out", "### Grinder (`grinder`)", "**Split:** held-out.", "Grinds.", "**Faults:** F1 burrs jam."])
    out = held_out_safe(md)
    assert "F1 lid" in out and "burrs" not in out and "Grinds." in out
    devices = held_out_safe((DOCS / "devices.md").read_text())
    for entry in (d for d in REGISTRY if d["split"] == "held_out"):
        section = devices.split(f"(`{entry['id']}`)")[1].split("\n### ")[0]
        assert "fault" not in section.lower() and "**Theory pieces:**" in section
