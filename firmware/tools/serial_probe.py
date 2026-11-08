#!/usr/bin/env python3
"""Request status and print newline-delimited firmware events until Ctrl+C."""
import argparse
from datetime import datetime
import json
import sys
import time

import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="COM5, /dev/ttyACM0, etc.")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()
    try:
        with serial.Serial(args.port, args.baud, timeout=0.2, write_timeout=1) as port:
            # Opening an Uno port resets it. Keep the boot log while it restarts.
            status_at = time.monotonic() + 2
            pending = bytearray()
            while True:
                if status_at is not None and time.monotonic() >= status_at:
                    port.write(b"status\n")
                    status_at = None
                pending.extend(port.read(max(1, port.in_waiting)))
                while b"\n" in pending:
                    line, _, pending = pending.partition(b"\n")
                    stamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            raise ValueError("expected a JSON object")
                    except (ValueError, UnicodeDecodeError) as error:
                        print(f"{stamp} invalid event: {line!r} ({error})", file=sys.stderr)
                        continue
                    print(f"{stamp} device_ms={event.get('t', '?')} "
                          f"{json.dumps(event, ensure_ascii=False)}", flush=True)
                if len(pending) > 4096:
                    print("Discarding oversized unterminated serial line", file=sys.stderr)
                    pending.clear()
    except KeyboardInterrupt:
        return 0
    except (serial.SerialException, OSError) as error:
        print(f"Serial error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
