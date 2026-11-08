#!/usr/bin/env python3
"""Check MW-1 software-I2C detection and completed LCD writes over USB serial."""
import argparse
import json
from pathlib import Path
import sys
import time

import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="MW-1 USB serial port, for example COM6")
    parser.add_argument("--reinitialize", type=int, default=0,
                        help="Repeat manual LCD initialization (0-20); leaves appliance settings unchanged")
    parser.add_argument("--output", type=Path, help="Save received device events as JSONL")
    parser.add_argument("--startup-timeout", type=float, default=10,
                        help="Seconds allowed for USB startup and boot calibration")
    args = parser.parse_args()
    if not 0 <= args.reinitialize <= 20:
        parser.error("--reinitialize must be between 0 and 20")
    if args.startup_timeout <= 0:
        parser.error("--startup-timeout must be positive")
    events = []
    failures = []
    try:
        with serial.Serial(args.port, 115200, timeout=0.1, write_timeout=1) as port:
            def collect(duration):
                batch = []
                deadline = time.monotonic() + duration
                while time.monotonic() < deadline:
                    line = port.readline().strip()
                    if not line:
                        continue
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError("received JSON that is not an object")
                    events.append(event)
                    batch.append(event)
                return batch

            deadline = time.monotonic() + args.startup_timeout
            next_request = 0
            while time.monotonic() < deadline:
                if time.monotonic() >= next_request:
                    port.write(b"ping\nstatus\ni2c\n")
                    next_request = time.monotonic() + 1
                collect(0.25)
                snapshots = [e for e in events if e.get("ev") == "hb"]
                if (snapshots and not snapshots[-1].get("calibrating") and
                        any(e.get("ev") == "pong" for e in events) and
                        any(e.get("ev") == "i2c" for e in events)):
                    break
            initial = [e for e in events if e.get("ev") == "hb"]
            if not initial or not all(initial[-1].get(k) for k in ("lcd_present", "rgb_present")):
                failures.append("LCD/backlight not both initialized before the manual checks")
            for attempt in range(args.reinitialize):
                port.write(b"lcd\n")
                batch = collect(0.8)
                replies = [e for e in batch if e.get("ev") == "lcd"]
                if (not replies or not replies[-1].get("lcd_present") or
                        not replies[-1].get("rgb_present") or
                        not any(e.get("ev") == "lcd_sync" for e in batch)):
                    failures.append(f"LCD reinitialization {attempt + 1} did not complete")
            port.write(b"status\n")
            collect(0.5)
    except (serial.SerialException, OSError, ValueError) as error:
        print(f"Check failed: {error}", file=sys.stderr)
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    snapshots = [e for e in events if e.get("ev") == "hb"]
    scans = [e for e in events if e.get("ev") == "i2c"]
    if not snapshots or not scans:
        failures.append("missing heartbeat or I2C scan reply")
    else:
        status, scan = snapshots[-1], scans[-1]
        if (status.get("i2c") != "software" or not status.get("lcd_present") or
                not status.get("rgb_present") or status.get("lcd_pending") != 0):
            failures.append("final status does not confirm completed software-I2C output")
        addresses = scan.get("addresses", [])
        if 0x3E not in addresses or status.get("rgb_addr") not in addresses:
            failures.append("text/backlight address not acknowledged in scan")
        print(f"Transport: {status.get('i2c')}, phase delay: {status.get('i2c_us')} us")
        print("Acknowledged addresses: " + ", ".join(f"0x{a:02X}" for a in addresses))
        print(f"LCD: {status.get('lcd_present')}, backlight: {status.get('rgb_present')}, "
              f"pending text: {status.get('lcd_pending')}")
    if not any(e.get("ev") == "pong" for e in events):
        failures.append("no ping reply")
    if any(e.get("ev") == "warning" and "io_error" in e for e in events):
        failures.append("a display I2C error occurred during the check; inspect saved events")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"PASS: display writes acknowledged; {args.reinitialize} manual reinitializations completed")
    print("This checks controller acknowledgements; inspect the physical screen to confirm appearance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
