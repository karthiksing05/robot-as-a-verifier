#!/usr/bin/env python3
"""Verify MC-6 physical controls twice and optionally update their pin assignments."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import serial

if __package__:
    from .calibrate_mw1_buttons import PressCapture, save_json
    from .serial_events import SerialEvents, disable_quick_edit
else:
    from calibrate_mw1_buttons import PressCapture, save_json
    from serial_events import SerialEvents, disable_quick_edit

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "MC6_firmware/MC6_firmware.ino"
LABELS = ("time", "start", "stop")
PINS = {0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12}
PROGRESS = ROOT / ".pio/mc6-button-calibration-progress.json"
CANCEL = ROOT / ".pio/mc6-button-calibration.cancel"


def validate_mapping(mapping):
    if set(mapping) != set(LABELS) or len(set(mapping.values())) != 3 or not set(mapping.values()) <= PINS - {5}:
        raise ValueError("Use three distinct pins from D0-D4 or D7-D12; D5 toggle, ring, sensors and I2C are reserved")


def read_source_pins(text):
    if re.findall(r"\bPIN_POWER\s*=\s*(\d+)\b", text) != ["5"]:
        raise ValueError("The confirmed POWER toggle must remain on D5")
    mapping = {}
    for label in LABELS:
        matches = re.findall(r"\bPIN_" + label.upper() + r"\s*=\s*(\d+)\b", text)
        if len(matches) != 1:
            raise ValueError("Expected one numeric assignment for " + label)
        mapping[label] = int(matches[0])
    validate_mapping(mapping)
    return mapping


def apply_mapping(source, mapping, expected_hash):
    validate_mapping(mapping)
    before = source.read_bytes()
    if hashlib.sha256(before).hexdigest() != expected_hash:
        raise ValueError("Firmware changed during measurement; source was not overwritten")
    text = before.decode("utf-8")
    read_source_pins(text)
    for label in LABELS:
        text = re.sub(r"(\bPIN_" + label.upper() + r"\s*=\s*)\d+\b",
                      lambda match: match[1] + str(mapping[label]), text)
    after = text.encode("utf-8")
    if after != before:
        backup = ROOT / f".pio/button-calibration/MC6_firmware.before-{time.time_ns()}.ino"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(before)
        temporary = source.with_suffix(".ino.tmp")
        temporary.write_bytes(after)
        temporary.replace(source)
    return hashlib.sha256(after).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--observe", type=float, default=0, metavar="SECONDS")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()
    if args.timeout <= 0 or args.observe < 0 or args.observe and args.apply:
        parser.error("Use a positive timeout; --observe cannot be combined with --apply")
    disable_quick_edit()
    original = SOURCE.read_bytes()
    source_pins = read_source_pins(original.decode("utf-8"))
    before_hash = hashlib.sha256(original).hexdigest()
    trace = ROOT / ".pio/mc6-button-calibration-events.jsonl"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text("", encoding="utf-8")
    CANCEL.unlink(missing_ok=True)
    save_json(PROGRESS, {"state": "connecting", "port": args.port})
    mapping, captures = {}, []
    try:
        with serial.Serial(args.port, 115200, timeout=0.1, write_timeout=1) as port:
            reader = SerialEvents(port, trace)
            held, heartbeat = set(PINS), time.monotonic()
            connected = False

            def read():
                nonlocal heartbeat, held
                if CANCEL.exists():
                    raise InterruptedError("Calibration cancelled; no unverified mapping was applied")
                if connected and time.monotonic() - heartbeat > 8:
                    raise TimeoutError("USB heartbeats stopped; no mapping was guessed")
                event = reader.read()
                if event and event.get("ev") == "hb":
                    heartbeat = time.monotonic()
                    if connected and event.get("button_test") != 1:
                        raise ValueError("Button-test mode ended unexpectedly")
                    if event.get("button_test") == 1:
                        held = {pin for pin in PINS if event.get("input_mask", 0) & (1 << pin)}
                if event and event.get("ev") == "input":
                    if event.get("pin") not in PINS or event.get("v") not in (0, 1):
                        raise ValueError("Invalid raw input event")
                    if event["v"]:
                        held.add(event["pin"])
                    else:
                        held.discard(event["pin"])
                return event

            try:
                print("Connecting to MC-6. Release all buttons and leave POWER off.", flush=True)
                deadline, request_at, runtime = time.monotonic() + 15, 0, None
                while time.monotonic() < deadline:
                    if time.monotonic() >= request_at:
                        port.write(b"buttons\nstatus\n"); request_at = time.monotonic() + 1
                    event = read()
                    if event and event.get("ev") == "buttons" and event.get("v") == 1:
                        runtime = event.get("pins")
                        expected = {"btn_" + key: value for key, value in source_pins.items()}
                        expected["btn_power"] = 5
                        if runtime != expected or set(event.get("scan_pins", [])) != PINS:
                            raise ValueError("Wrong board or running pin assignments differ; upload current MC-6 firmware")
                    if runtime and event and event.get("ev") == "hb" and event.get("button_test") == 1 and not event.get("calibrating"):
                        connected = True; break
                else:
                    raise TimeoutError("No MC-6 button-test handshake")
                if args.observe:
                    deadline = time.monotonic() + args.observe
                    while time.monotonic() < deadline:
                        event = read()
                        if event and event.get("ev") in ("input", "hb"):
                            print(json.dumps(event), flush=True)
                    return 0
                for round_number in (1, 2):
                    for label in LABELS:
                        while True:
                            deadline = time.monotonic() + args.timeout
                            while held:
                                if time.monotonic() >= deadline:
                                    raise TimeoutError("An input stayed active; release buttons and switch POWER off")
                                read()
                            save_json(PROGRESS, {"state": "waiting", "label": label, "round": round_number, "mapping": mapping})
                            print(f"Round {round_number}/2: press and RELEASE {label.upper()}", flush=True)
                            capture = PressCapture()
                            while time.monotonic() < deadline:
                                event = read()
                                if not event or event.get("ev") != "input":
                                    continue
                                result = capture.feed(event)
                                if result is None:
                                    continue
                                if "error" in result:
                                    print(result["error"], flush=True); break
                                pin = result["pin"]
                                if pin == 5:
                                    print("D5 is the confirmed toggle switch. Leave it OFF and retry the requested button.", flush=True); break
                                if round_number == 1 and pin in mapping.values() or round_number == 2 and pin != mapping[label]:
                                    print("Duplicate/mismatched pin. Retry this label.", flush=True); break
                                mapping[label] = pin
                                captures.append({"label": label, "round": round_number, **result})
                                print(f"Recorded {label.upper()} -> pin {pin}", flush=True)
                                break
                            else:
                                raise TimeoutError("No complete press/release for " + label)
                            if len(captures) == (round_number - 1) * len(LABELS) + LABELS.index(label) + 1:
                                break
                validate_mapping(mapping)
                output = ROOT / "config/mc6_buttons.json"
                record = {"device": "MC-6", "port": args.port, "labels_to_pins": mapping, "captures": captures,
                          "source_sha256_before": before_hash, "applied": False, "trace": str(trace)}
                save_json(output, record)
                if args.apply:
                    record.update(source_sha256_after=apply_mapping(SOURCE, mapping, before_hash), applied=True)
                    save_json(output, record)
                print(f"Verified and saved {output}. Rebuild/upload if source was updated.", flush=True)
                save_json(PROGRESS, {"state": "complete", "mapping": mapping, "applied": record["applied"]})
            finally:
                port.write(b"normal\n")
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    event = reader.read()
                    if event and event.get("ev") == "buttons" and event.get("v") == 0:
                        break
    except (KeyboardInterrupt, serial.SerialException, OSError, ValueError, TimeoutError) as error:
        print("Stopped: " + (str(error) or "cancelled"), flush=True)
        save_json(PROGRESS, {"state": "error", "error": str(error), "mapping": mapping})
        return 1
    return 0


if __name__ == "__main__":
    result = main()
    if "--keep-open" in sys.argv:
        try:
            input("Press Enter to close this window.")
        except (EOFError, KeyboardInterrupt):
            pass
    raise SystemExit(result)
