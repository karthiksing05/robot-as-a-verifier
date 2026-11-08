#!/usr/bin/env python3
"""Continuously display the MC-6 A1 ADC value over USB serial."""
import argparse
import csv
from datetime import datetime
from pathlib import Path
import sys
import time

import serial

if __package__:
    from .serial_events import SerialEvents, disable_quick_edit
else:
    from serial_events import SerialEvents, disable_quick_edit

ROOT = Path(__file__).resolve().parents[1]
CANCEL = ROOT / ".pio/mc6-a1-monitor.cancel"


def a1_value(event):
    if event.get("ev") != "raw":
        return None
    value = event.get("a1")
    if type(value) is not int or not 0 <= value <= 1023:
        raise ValueError("Firmware returned an invalid A1 ADC value")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", default="COM7", help="MC-6 USB port (default: COM7)")
    parser.add_argument("--interval", type=float, default=0.25, help="Seconds between readings (minimum 0.1)")
    parser.add_argument("--seconds", type=float, default=0, help="Stop after this duration; 0 runs until Ctrl+C")
    parser.add_argument("--csv", type=Path, default=ROOT / ".pio/mc6-a1-readings.csv", help="CSV recording path")
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--all", action="store_true", help="Also display and record A0/A2/A3 for wiring diagnosis")
    args = parser.parse_args()
    if args.interval < 0.1 or args.seconds < 0:
        parser.error("--interval must be at least 0.1 and --seconds must be nonnegative")
    disable_quick_edit()
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    trace = ROOT / ".pio/mc6-a1-events.jsonl"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text("", encoding="utf-8")
    CANCEL.unlink(missing_ok=True)
    count, minimum, maximum = 0, 1023, 0
    try:
        with serial.Serial(args.port, 115200, timeout=0.1, write_timeout=1) as port, args.csv.open("w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow(("host_time", "device_ms", "a0", "a1", "a2", "a3") if args.all else ("host_time", "device_ms", "a1"))
            output.flush()
            reader = SerialEvents(port, trace)
            started = last_reading = time.monotonic()
            next_request = 0
            print(f"Monitoring MC-6 A1 on {args.port} (0-1023; eight-sample firmware average).", flush=True)
            print("Cover/uncover the sensor or move it between light and shade. Ctrl+C stops. Close other serial monitors.", flush=True)
            print(f"Saving readings to {args.csv}\n", flush=True)
            while not CANCEL.exists():
                now = time.monotonic()
                if args.seconds and now - started >= args.seconds:
                    break
                if now - last_reading > 8:
                    raise TimeoutError("No A1 reply for eight seconds. Check USB/port and upload current MC-6 firmware with the raw command")
                if now >= next_request:
                    port.write(b"raw\n")
                    next_request = now + args.interval
                event = reader.read()
                if not event:
                    continue
                if event.get("ev") == "error":
                    raise ValueError("MC-6 raw command was rejected; upload the current MC-6 firmware")
                value = a1_value(event)
                if value is None:
                    continue
                last_reading = time.monotonic()
                minimum, maximum = min(minimum, value), max(maximum, value)
                count += 1
                stamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
                if args.all:
                    if not all(type(event.get(key)) is int and 0 <= event[key] <= 1023 for key in ("a0", "a2", "a3")):
                        raise ValueError("Firmware returned an invalid analog reading")
                    writer.writerow((stamp, event.get("t"), event["a0"], value, event["a2"], event["a3"]))
                else:
                    writer.writerow((stamp, event.get("t"), value))
                output.flush()
                others = f"  A0: {event['a0']:4d}  A2: {event['a2']:4d}  A3: {event['a3']:4d}" if args.all else ""
                print(f"{stamp}  A1: {value:4d}  min: {minimum:4d}  max: {maximum:4d}" + others, flush=True)
        if not count:
            raise TimeoutError("No A1 readings received")
        print(f"Stopped. {count} readings; range {minimum}-{maximum}.", flush=True)
    except KeyboardInterrupt:
        print(f"\nStopped. {count} readings recorded.", flush=True)
    except (serial.SerialException, OSError, ValueError, TimeoutError) as error:
        print(f"Monitor stopped: {error}", file=sys.stderr, flush=True)
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
