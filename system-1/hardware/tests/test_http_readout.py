"""http_readout.HttpReadout, fed as rav-server's /readout/<device> feeds it: no thread, no socket."""
import os
import sys
import time

HARDWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HARDWARE, os.path.join(os.path.dirname(HARDWARE), "core")]

import http_readout  # noqa: E402
import pytest  # noqa: E402
from rig import Readout, SafetyStop  # noqa: E402


def test_readout_retains_button_edges_between_polls():
    readout = http_readout.HttpReadout("mc6-01", track_events=False)
    readout.ingest({"btn_time": 0})
    readout.ingest({"btn_time": 1})
    readout.ingest({"btn_time": 1})  # a retry after a lost acknowledgement
    readout.ingest({"btn_time": 0})
    assert readout.snapshot()["button_edges"] == [
        {"seq": 1, "channel": "btn_time", "value": 1},
        {"seq": 2, "channel": "btn_time", "value": 0},
    ]
    assert readout.events == []


def test_no_step_runs_before_the_first_post():
    r = http_readout.HttpReadout("mw1", "http://lab:8780/readout/mw1")
    assert isinstance(r, Readout) and not r.started
    for prop in ("readings", "events"):
        with pytest.raises(SafetyStop, match="no readings yet from device 'mw1'.*http://lab:8780/readout/mw1"):
            getattr(r, prop)


def test_follows_posts_and_logs_int_changes_only():
    r = http_readout.HttpReadout("mw1")
    r.ingest({"BTN1": 0, "FAN": 0.0, "DOOR": 0, "LCD": "READY"})
    r.ingest({"BTN1": 1, "FAN": 0.4})
    r.ingest({"BTN1": 0, "FAN": 0.42, "DOOR": 1, "LCD": "OPEN"})
    r.ingest([1, 2])  # not a snapshot: ignored
    assert r.readings == {"BTN1": 0, "FAN": 0.42, "DOOR": 1} and r.lcd == "OPEN"
    assert [(ch, v) for _, ch, v in r.events] == [("BTN1", 1), ("BTN1", 0), ("DOOR", 1)]


def test_a_quiet_board_stops_the_next_step(monkeypatch):
    r = http_readout.HttpReadout("mw1")
    r.ingest({"BTN1": 0})
    now = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: now + http_readout.STALE_S + 0.1)
    assert not r.snapshot()["fresh"]
    for prop in ("readings", "events"):
        with pytest.raises(SafetyStop, match="nothing from device 'mw1' over WiFi"):
            getattr(r, prop)


def test_closed_ignores_late_posts():
    r = http_readout.HttpReadout("mw1")
    r.ingest({"BTN1": 0})
    r.close()
    r.ingest({"BTN1": 1})
    assert r.snapshot()["readings"] == {"BTN1": 0} and not r.snapshot()["fresh"]
