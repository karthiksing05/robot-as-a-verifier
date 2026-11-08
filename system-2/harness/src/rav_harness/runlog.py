"""One folder per run: events.jsonl plus report.json. The log is the record: nothing else is authoritative."""
from __future__ import annotations

import json
import pathlib
import threading
import time
from collections.abc import Callable

from pydantic import BaseModel

from rav_contracts import PAYLOADS, Report, RunEvent, StepOutcome

Subscriber = Callable[[RunEvent], None]


class RunLog:
    def __init__(self, run_id: str, root: str | pathlib.Path = "runs", on_event: Subscriber | None = None):
        self.run_id, self.dir = run_id, pathlib.Path(root) / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "events.jsonl"
        self.path.write_text("")
        self.seq, self.t0, self.on_event = 0, time.monotonic(), on_event
        self.wall0 = time.time()
        self._lock = threading.Lock()       # analysts may run in parallel and log to the same run

    def emit(self, type_: str, payload: BaseModel | dict) -> RunEvent:
        expected = PAYLOADS[type_]
        if expected is not None and not isinstance(payload, expected):
            raise TypeError(f"{type_} needs a {expected.__name__}, got {type(payload).__name__}")
        if type_ == "step_finished" and not isinstance(payload, StepOutcome):
            raise TypeError("step_finished needs a StepOutcome")
        body = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        with self._lock:
            self.seq += 1
            event = RunEvent(seq=self.seq, t=round(time.monotonic() - self.t0, 3), run_id=self.run_id, type=type_, payload=body)
            with self.path.open("a") as f:
                f.write(event.model_dump_json() + "\n")
        if self.on_event:
            self.on_event(event)
        return event

    def write_report(self, report: Report) -> None:
        (self.dir / "report.json").write_text(report.model_dump_json(indent=2) + "\n")


def read_events(path: str | pathlib.Path) -> list[RunEvent]:
    return [RunEvent(**json.loads(line)) for line in pathlib.Path(path).read_text().splitlines() if line.strip()]
