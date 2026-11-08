#!/usr/bin/env python3
"""Guide MW-1 open/closed light calibration using the physical START button."""
import argparse
import json
from pathlib import Path
import sys
import time

import serial

if __package__:
    from .serial_events import SerialEvents, disable_quick_edit
else:
    from serial_events import SerialEvents, disable_quick_edit

ROOT = Path(__file__).resolve().parents[1]
CANCEL_FILE = ROOT / ".pio/door-calibration.cancel"


def save_progress(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_result(result):
    required = ("open", "closed", "close_below", "open_above")
    if not all(isinstance(result.get(k), int) and 0 <= result[k] <= 1023 for k in required):
        raise ValueError("Firmware returned invalid calibration values")
    if (result.get("saved") != 1 or result["open"] - result["closed"] < 40 or
            not result["closed"] < result["close_below"] < result["open_above"] < result["open"]):
        raise ValueError("Firmware did not confirm valid, saved and separated door thresholds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="MW-1 serial port, for example COM6")
    parser.add_argument("--timeout", type=float, default=600, help="Seconds allowed for the guided procedure")
    parser.add_argument("--output", type=Path, default=ROOT / "config/mw1_door.json")
    parser.add_argument("--trace", type=Path, default=ROOT / ".pio/door-calibration-events.jsonl")
    parser.add_argument("--progress", type=Path, default=ROOT / ".pio/door-calibration-progress.json")
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    disable_quick_edit()
    finished = False
    result_code = 1
    for path in (args.output, args.trace, args.progress):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.trace.write_text("", encoding="utf-8")
    CANCEL_FILE.unlink(missing_ok=True)
    state = {"state": "connecting", "port": args.port, "door_raw": None}
    save_progress(args.progress, state)
    try:
        with serial.Serial(args.port, 115200, timeout=0.1, write_timeout=1) as port:
            reader = SerialEvents(port, args.trace)
            last_heartbeat = time.monotonic()
            try:
                print("Connecting. Calibration will use OPEN and CLOSED readings; START confirms each position.", flush=True)
                deadline, next_request = time.monotonic() + 15, 0
                while time.monotonic() < deadline:
                    if time.monotonic() >= next_request:
                        port.write(b"calstop\nnormal\nstatus\n")
                        next_request = time.monotonic() + 1
                    event = reader.read()
                    if event and event.get("ev") == "hb" and not event.get("calibrating") and not event.get("button_test"):
                        last_heartbeat = time.monotonic()
                        break
                else:
                    raise TimeoutError("No ready heartbeat. Check the port and upload MW-1 firmware 1.1")
                port.write(b"doorcal\n")
                deadline = time.monotonic() + args.timeout
                previous_stage, next_status = None, 0
                while time.monotonic() < deadline:
                    if CANCEL_FILE.exists():
                        raise InterruptedError("Door calibration cancelled")
                    if time.monotonic() - last_heartbeat > 8:
                        raise TimeoutError("USB heartbeats stopped; calibration was not assumed successful")
                    event = reader.read()
                    if event is None:
                        continue
                    name = event.get("ev")
                    if name == "hb":
                        last_heartbeat = time.monotonic()
                        state.update(door_raw=event.get("door_raw"), last_heartbeat_host=last_heartbeat)
                        save_progress(args.progress, state)
                        if time.monotonic() >= next_status:
                            print(f"USB alive. Light reading: {event.get('door_raw')}", flush=True)
                            next_status = time.monotonic() + 5
                    if name == "error":
                        raise ValueError(event.get("msg", "Firmware command error; firmware 1.1 is required"))
                    if name == "cal_error":
                        state["last_error"] = event
                        print("Calibration rejected: " + json.dumps(event), flush=True)
                        print("Ensure the door shades the sensor when closed and the two positions give distinct readings."
                              " Retry with the door fully open, then press START; STOP cancels.", flush=True)
                    if name != "doorcal":
                        continue
                    stage = event.get("stage")
                    state.update(state=stage, calibration=event)
                    save_progress(args.progress, state)
                    if stage == "cancelled":
                        raise InterruptedError("Calibration cancelled with STOP or calstop")
                    if stage != previous_stage:
                        if stage == "open":
                            print("\n1. OPEN the door fully. Keep it still and press/release the physical START button.", flush=True)
                        elif stage == "closed":
                            print("\n2. CLOSE the door fully. Keep it still and press/release the physical START button.", flush=True)
                        elif stage in ("measure_open", "measure_closed"):
                            print("Measuring; hold the door still.", flush=True)
                        previous_stage = stage
                    if stage == "saved":
                        validate_result(event)
                        record = {"device": "MW-1", "pin": "A0", "port": args.port, "result": event,
                                  "trace": str(args.trace), "storage": "board EEPROM", "complete": True}
                        save_progress(args.output, record)
                        state["state"] = "complete"
                        save_progress(args.progress, state)
                        print("\nSAVED: " + json.dumps(event), flush=True)
                        print("Door thresholds are stored on the board and will load after restart.", flush=True)
                        print("Open/close the door again to verify its serial door state; rerun if lighting changes.", flush=True)
                        finished = True
                        result_code = 0
                        break
                else:
                    raise TimeoutError("Door calibration timed out; no new successful calibration was assumed")
            finally:
                if not finished:
                    port.write(b"calstop\n")
    except (KeyboardInterrupt, serial.SerialException, OSError, ValueError, TimeoutError) as error:
        message = str(error) or "Door calibration cancelled"
        state.update(state="error", error=message)
        save_progress(args.progress, state)
        print(f"Stopped: {message}", file=sys.stderr, flush=True)
    if args.keep_open:
        try:
            input("\nPress Enter to close this window.")
        except (EOFError, KeyboardInterrupt):
            pass
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
