#!/usr/bin/env python3
"""Guide MC-6 lid/tube light calibration and record EEPROM-confirmed thresholds."""
import argparse
import json
from pathlib import Path
import sys
import time

import serial

if __package__:
    from .calibrate_mw1_buttons import save_json
    from .serial_events import SerialEvents, disable_quick_edit
else:
    from calibrate_mw1_buttons import save_json
    from serial_events import SerialEvents, disable_quick_edit

ROOT = Path(__file__).resolve().parents[1]
PROGRESS = ROOT / ".pio/mc6-sensor-calibration-progress.json"
CANCEL = ROOT / ".pio/mc6-sensor-calibration.cancel"
PROMPTS = {
    "open": "1. OPEN the lid and REMOVE the tube. Press/release START; hold still while measuring.",
    "closed": "2. Leave the well EMPTY and CLOSE the lid. Press/release START; hold still.",
    "tube": "3. INSERT the tube and CLOSE the lid again. Press/release START; hold still.",
    "measuring": "Measuring under the steady white ring; keep the setup still.",
}


def validate_result(event):
    if event.get("saved") != 1:
        raise ValueError("Firmware did not confirm saved calibration")
    names = ("lid",) if event.get("tube_required", 1) == 0 else ("lid", "tube")
    for name in names:
        sensor = event.get(name, {})
        if not all(isinstance(sensor.get(key), int) and 0 <= sensor[key] <= 1023 for key in ("clear", "shaded", "lo", "hi")):
            raise ValueError("Invalid " + name + " calibration")
        if sensor["clear"] - sensor["shaded"] < 40 or not sensor["shaded"] < sensor["lo"] < sensor["hi"] < sensor["clear"]:
            raise ValueError("Unseparated " + name + " thresholds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    disable_quick_edit()
    trace = ROOT / ".pio/mc6-sensor-calibration-events.jsonl"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text("", encoding="utf-8")
    CANCEL.unlink(missing_ok=True)
    save_json(PROGRESS, {"state": "connecting", "port": args.port})
    complete, identified = False, False
    try:
        with serial.Serial(args.port, 115200, timeout=0.1, write_timeout=1) as port:
            reader = SerialEvents(port, trace)
            try:
                deadline, request_at = time.monotonic() + 15, 0
                while time.monotonic() < deadline:
                    if time.monotonic() >= request_at:
                        port.write(b"calstatus\n"); request_at = time.monotonic() + 1
                    event = reader.read()
                    if event and event.get("ev") == "lightcal" and "lid" in event and "tube" in event:
                        identified = True
                        lid_only = event.get("tube_required", 1) == 0
                        if lid_only:
                            print("Tube sensor disabled. Only OPEN and CLOSED lid measurements are required.", flush=True)
                        break
                else:
                    raise TimeoutError("No MC-6 calibration handshake; upload current MC-6 firmware and check the port")
                port.write(b"normal\ncalstop\ncal\n")
                deadline, heartbeat, started, previous = time.monotonic() + args.timeout, time.monotonic(), False, None
                while time.monotonic() < deadline:
                    if CANCEL.exists():
                        raise InterruptedError("Calibration cancelled")
                    if time.monotonic() - heartbeat > 8:
                        raise TimeoutError("USB heartbeats stopped; calibration was not assumed successful")
                    event = reader.read()
                    if not event:
                        continue
                    if event.get("ev") == "hb":
                        heartbeat = time.monotonic()
                    if event.get("ev") == "error":
                        raise ValueError(event.get("msg", "Firmware command failed"))
                    if event.get("ev") == "cal_error":
                        retry = "with the lid OPEN" if lid_only else "from OPEN/EMPTY"
                        print("Rejected: " + json.dumps(event) + f". Check shading/lighting and retry {retry}, or STOP to cancel.", flush=True)
                    if event.get("ev") != "lightcal":
                        continue
                    stage = event.get("stage")
                    if stage == "open":
                        started = True
                    if not started:
                        continue
                    save_json(PROGRESS, {"state": stage, "calibration": event, "port": args.port})
                    if stage == "cancelled":
                        raise InterruptedError("Calibration cancelled with STOP")
                    if stage != previous and stage in PROMPTS:
                        prompt = PROMPTS[stage]
                        if lid_only and stage in ("open", "closed"):
                            prompt = ("1. OPEN the lid." if stage == "open" else "2. CLOSE the lid.") + " Press/release START; hold still while measuring."
                        print(prompt, flush=True)
                    previous = stage
                    if stage == "saved":
                        validate_result(event)
                        output = ROOT / "config/mc6_sensors.json"
                        record = {"device": "MC-6", "port": args.port, "pins": {"lid": "A2"} if lid_only else {"lid": "A2", "tube": "A1"},
                                  "scope": "lid_only" if lid_only else "lid_and_tube", "ignored_pins": ["A1"] if lid_only else [],
                                  "result": event, "storage": "board EEPROM", "trace": str(trace), "complete": True}
                        save_json(output, record)
                        save_json(PROGRESS, {"state": "complete", "calibration": event})
                        print(f"SAVED {output}. Thresholds load automatically after restart.", flush=True)
                        complete = True; return 0
                raise TimeoutError("Calibration timed out; no successful result was assumed")
            finally:
                if identified and not complete:
                    port.write(b"calstop\n")
    except (KeyboardInterrupt, serial.SerialException, OSError, ValueError, TimeoutError) as error:
        print("Stopped: " + (str(error) or "cancelled"), flush=True)
        save_json(PROGRESS, {"state": "error", "error": str(error)})
        return 1


if __name__ == "__main__":
    result = main()
    if "--keep-open" in sys.argv:
        try:
            input("Press Enter to close this window.")
        except (EOFError, KeyboardInterrupt):
            pass
    raise SystemExit(result)
