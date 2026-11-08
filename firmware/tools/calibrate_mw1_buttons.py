#!/usr/bin/env python3
"""Prompt for physical MW-1 buttons, verify their pins twice, and optionally update the sketch."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import serial

if __package__:
    from .serial_events import SerialEvents, disable_quick_edit
else:
    from serial_events import SerialEvents, disable_quick_edit

ROOT = Path(__file__).resolve().parents[1]
LABELS = ("time", "30s", "power", "start", "stop")
PRINTED = {"time": "TIME", "30s": "+30s", "power": "POWER", "start": "START", "stop": "STOP"}
CONSTANTS = {label: "PIN_" + label.upper() for label in LABELS}
EVENTS = {"btn_" + label: label for label in LABELS}
PINS = set(range(2, 13)) | {16, 17}
CANCEL_FILE = ROOT / ".pio/button-calibration.cancel"


def pin_name(pin):
    return f"A{pin - 14}" if pin in (16, 17) else f"D{pin}"


def read_source_pins(text):
    result = {}
    for label, constant in CONSTANTS.items():
        matches = re.findall(r"\b" + constant + r"\s*=\s*(\d+)\b", text)
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one numeric assignment for {constant}")
        result[label] = int(matches[0])
    validate_mapping(result)
    return result


def validate_mapping(mapping):
    if (set(mapping) != set(LABELS) or len(set(mapping.values())) != 5 or
            not set(mapping.values()) <= PINS):
        raise ValueError("The mapping must use five distinct pins from D2-D12 or A2/A3")


def apply_mapping(source, mapping, expected_hash):
    validate_mapping(mapping)
    before = source.read_bytes()
    if hashlib.sha256(before).hexdigest() != expected_hash:
        raise ValueError("Firmware changed during calibration; mapping was saved, but source was not overwritten")
    text = before.decode("utf-8")
    read_source_pins(text)
    for label, constant in CONSTANTS.items():
        pattern = r"(\b" + constant + r"\s*=\s*)\d+\b"
        text, count = re.subn(pattern, lambda m: m[1] + str(mapping[label]), text)
        if count != 1:
            raise ValueError(f"Could not update {constant} uniquely")
    after = text.encode("utf-8")
    if after != before:
        backups = ROOT / ".pio/button-calibration"
        backups.mkdir(parents=True, exist_ok=True)
        (backups / f"MW1_firmware.before-{time.time_ns()}.ino").write_bytes(before)
        temporary = source.with_suffix(source.suffix + ".tmp")
        temporary.write_bytes(after)
        temporary.replace(source)
    return hashlib.sha256(after).hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class PressCapture:
    """Accept exactly one debounced press followed by its release; reject chords."""
    def __init__(self):
        self.pin = None
        self.down = set()
        self.press = None
        self.invalid = False

    def feed(self, event):
        pin = event["pin"]
        if event["v"] == 1:
            self.down.add(pin)
            if self.pin is None:
                self.pin, self.press = pin, event
            elif pin != self.pin:
                self.invalid = True
        else:
            self.down.discard(pin)
            if self.pin is not None and not self.down:
                if self.invalid or pin != self.pin:
                    return {"error": "More than one input changed; press only the requested button"}
                return {"pin": pin, "press": self.press, "release": event}
        return None


class Wizard:
    def __init__(self, port, args, source_pins):
        self.port, self.args = port, args
        self.held = {pin: None for pin in PINS}
        self.runtime_pins = None
        self.last_button = time.monotonic()
        self.source_pins = source_pins
        self.mapping = {}
        self.captures = []
        self.progress_state = {}
        self.last_heartbeat = None
        self.watchdog = False
        self.last_input = None
        self.reader = SerialEvents(port, args.trace)
        self.last_status_print = time.monotonic()

    def progress(self, state, **fields):
        self.progress_state = {"state": state, **fields}
        self.save_progress()

    def save_progress(self):
        save_json(self.args.progress, {**self.progress_state, "mapping": self.mapping,
                                     "last_heartbeat_host": self.last_heartbeat,
                                     "last_input": self.last_input,
                                     "held_pins": sorted(pin for pin, v in self.held.items() if v == 1)})

    def read(self):
        if CANCEL_FILE.exists():
            raise InterruptedError("Calibration cancelled; no unverified mapping was applied")
        if self.watchdog and self.last_heartbeat is not None and time.monotonic() - self.last_heartbeat > 8:
            raise TimeoutError("USB heartbeats stopped for 8 seconds; mapping stopped without guessing. Check USB/power and button wiring")
        event = self.reader.read()
        if event is None:
            return None
        name = event.get("ev")
        if name == "buttons" and event.get("v") == 1:
            runtime = event.get("pins", {})
            scan_pins = event.get("scan_pins", [])
            if (set(runtime) != set(EVENTS) or len(set(runtime.values())) != 5 or
                    not set(runtime.values()) <= PINS or set(scan_pins) != PINS):
                raise ValueError("Firmware did not report all five unique physical pins; upload the current sketch first")
            self.runtime_pins = runtime
            if {EVENTS[k]: v for k, v in runtime.items()} != self.source_pins:
                raise ValueError("Running firmware pin assignments differ from this source; upload the current sketch first")
        if name == "hb":
            self.last_heartbeat = time.monotonic()
            if event.get("button_test") == 1 and isinstance(event.get("input_mask"), int):
                for pin in PINS:
                    self.held[pin] = 1 if event["input_mask"] & (1 << pin) else 0
            self.save_progress()
            if (self.progress_state.get("state") in ("waiting", "release_wait") and
                    time.monotonic() - self.last_status_print >= 5):
                label = self.progress_state.get("printed_label", "button release")
                held = ", ".join(pin_name(pin) for pin, value in self.held.items() if value == 1) or "none"
                print(f"Waiting for {label}. USB alive; held inputs: {held}.", flush=True)
                self.last_status_print = time.monotonic()
        if name == "input":
            pin, value = event.get("pin"), event.get("v")
            if pin not in PINS or value not in (0, 1):
                raise ValueError("Button event lacks a valid raw pin/value; upload the current sketch first")
            self.held[pin] = value
            self.last_button = time.monotonic()
            self.last_input = event
            self.save_progress()
        return event

    def connect(self):
        print("Connecting to MW-1 button-test mode. Release every button.", flush=True)
        deadline, next_request = time.monotonic() + 15, 0
        while time.monotonic() < deadline:
            if time.monotonic() >= next_request:
                self.port.write(b"buttons\nstatus\n")
                next_request = time.monotonic() + 1
            event = self.read()
            if (event and event.get("ev") == "hb" and event.get("button_test") == 1 and
                    not event.get("calibrating") and self.runtime_pins):
                self.watchdog = True
                return
        raise TimeoutError("No button-test handshake. Upload the current MW-1 sketch and close other serial monitors")

    def released(self, deadline):
        reported = None
        while time.monotonic() < deadline:
            if all(v == 0 for v in self.held.values()) and time.monotonic() - self.last_button >= 0.3:
                return
            held_pins = sorted(pin for pin, value in self.held.items() if value == 1)
            if held_pins and held_pins != reported:
                print("Waiting for release: " + ", ".join(pin_name(pin) for pin in held_pins), flush=True)
                self.progress("release_wait", held_pins=held_pins)
                reported = held_pins
            self.read()
        raise TimeoutError("An input stayed pressed or did not report release; no mapping was guessed")

    def capture(self, label, round_number):
        while True:
            deadline = time.monotonic() + self.args.timeout
            self.released(deadline)
            self.progress("waiting", label=label, printed_label=PRINTED[label], round=round_number)
            print(f"\nRound {round_number}/2: press and RELEASE [{PRINTED[label]}]. Hold for about half a second.",
                  flush=True)
            capture = PressCapture()
            while time.monotonic() < deadline:
                event = self.read()
                if not event:
                    continue
                if event.get("ev") == "hb" and event.get("button_test") != 1:
                    raise ValueError("Button-test mode ended unexpectedly; calibration stopped")
                if event.get("ev") != "input":
                    continue
                result = capture.feed(event)
                if result is None:
                    if event["v"] == 1 and capture.press is event:
                        print(f"Detected {pin_name(event['pin'])}; release the button.", flush=True)
                        self.progress("release_wait", label=label, printed_label=PRINTED[label],
                                      round=round_number, held_pins=[event["pin"]])
                    continue
                if "error" in result:
                    print(result["error"], flush=True)
                    break
                pin = result["pin"]
                if round_number == 1 and pin in self.mapping.values():
                    previous = next(k for k, v in self.mapping.items() if v == pin)
                    print(f"{pin_name(pin)} was already recorded for {PRINTED[previous]}. Retry {PRINTED[label]}.", flush=True)
                    break
                if round_number == 2 and pin != self.mapping[label]:
                    print(f"Mismatch: round 1 was {pin_name(self.mapping[label])}, this press was {pin_name(pin)}. Retry.", flush=True)
                    break
                self.captures.append({"label": label, "round": round_number, **result})
                self.mapping[label] = pin
                print(f"Recorded {PRINTED[label]} -> {pin_name(pin)} (press and release verified).", flush=True)
                return
            else:
                raise TimeoutError(f"Timed out waiting for {PRINTED[label]} press/release")

    def run(self):
        self.connect()
        for round_number in (1, 2):
            for label in LABELS:
                self.capture(label, round_number)
        self.released(time.monotonic() + self.args.timeout)
        validate_mapping(self.mapping)

    def observe(self, duration):
        self.connect()
        self.progress("observing")
        print("\nRAW INPUT MONITOR: press and release each physical button, one at a time.", flush=True)
        print("This mode records every input change and heartbeat; it does not assign labels or edit firmware.", flush=True)
        deadline, next_status = time.monotonic() + duration, 0
        while time.monotonic() < deadline:
            event = self.read()
            if not event:
                continue
            if event.get("ev") == "input":
                print(f"{pin_name(event['pin'])}: {'PRESSED' if event['v'] else 'RELEASED'}", flush=True)
            if event.get("ev") == "hb" and time.monotonic() >= next_status:
                held = ", ".join(pin_name(pin) for pin, value in self.held.items() if value == 1) or "none"
                print(f"USB alive. Held inputs: {held}. Device time: {event.get('t')} ms", flush=True)
                next_status = time.monotonic() + 2
        self.progress("observed", trace=str(self.args.trace))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="MW-1 USB serial port, for example COM6")
    parser.add_argument("--apply", action="store_true", help="Update the five firmware pin constants after both rounds agree")
    parser.add_argument("--source", type=Path, default=ROOT / "MW1_firmware/MW1_firmware.ino")
    parser.add_argument("--output", type=Path, default=ROOT / "config/mw1_buttons.json")
    parser.add_argument("--progress", type=Path, default=ROOT / ".pio/button-calibration-progress.json")
    parser.add_argument("--trace", type=Path, default=ROOT / ".pio/button-calibration-events.jsonl")
    parser.add_argument("--observe", type=float, default=0, metavar="SECONDS",
                        help="Only monitor raw inputs for this many seconds; do not assign labels or edit source")
    parser.add_argument("--timeout", type=float, default=180, help="Seconds allowed per requested press/release")
    parser.add_argument("--keep-open", action="store_true", help="Wait for Enter before closing this console")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.observe < 0 or (args.observe and args.apply):
        parser.error("--observe must be nonnegative and cannot be combined with --apply")
    disable_quick_edit()
    wizard = None
    result_code = 1
    try:
        CANCEL_FILE.unlink(missing_ok=True)
        source_bytes = args.source.read_bytes()
        before_hash = hashlib.sha256(source_bytes).hexdigest()
        source_pins = read_source_pins(source_bytes.decode("utf-8"))
        args.trace.parent.mkdir(parents=True, exist_ok=True)
        args.trace.write_text("", encoding="utf-8")
        with serial.Serial(args.port, 115200, timeout=0.1, write_timeout=1) as port:
            wizard = Wizard(port, args, source_pins)
            wizard.progress("connecting")
            try:
                if args.observe:
                    wizard.observe(args.observe)
                    result_code = 0
                else:
                    wizard.run()
                    record = {"schema": 1, "device": "MW-1", "port": args.port,
                              "recorded_at": datetime.now(timezone.utc).isoformat(),
                              "labels_to_pins": wizard.mapping, "previous_labels_to_pins": source_pins,
                              "source_sha256_before": before_hash, "captures": wizard.captures, "applied": False}
                    save_json(args.output, record)
                    if args.apply:
                        record["source_sha256_after"] = apply_mapping(args.source, wizard.mapping, before_hash)
                        record["applied"] = True
                        save_json(args.output, record)
                    print("\nVerified mapping:", flush=True)
                    for label in LABELS:
                        print(f"  {PRINTED[label]:5s} -> {pin_name(wizard.mapping[label])}", flush=True)
                    print(f"Saved {args.output}", flush=True)
                    print("Firmware pin constants updated; build and upload are still required." if args.apply else
                          "Firmware unchanged. Run with --apply to update it after a new verified session.", flush=True)
                    wizard.progress("complete", applied=record["applied"], output=str(args.output))
                    result_code = 0
            finally:
                wizard.watchdog = False
                # Restore normal operation even after Ctrl+C; inputs must release naturally.
                port.write(b"normal\n")
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    if CANCEL_FILE.exists():
                        CANCEL_FILE.unlink()
                    event = wizard.read()
                    if event and event.get("ev") == "buttons" and event.get("v") == 0:
                        break
    except (KeyboardInterrupt, serial.SerialException, OSError, ValueError, TimeoutError) as error:
        message = str(error) or "Calibration cancelled"
        print(f"\nStopped: {message}", file=sys.stderr, flush=True)
        save_json(args.progress, {"state": "error", "error": message,
                                 "mapping": wizard.mapping if wizard else {}})
    if args.keep_open:
        try:
            input("\nPress Enter to close this window.")
        except (EOFError, KeyboardInterrupt):
            pass
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
