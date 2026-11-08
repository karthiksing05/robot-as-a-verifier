"""Print MC-6 / MW-1 serial events with timestamps.  pip install pyserial
usage: python monitor.py /dev/tty.usbmodem1101 [--hb]   (--hb also prints the 1 s heartbeats)
Type ping / status / cal / reset and Enter to send a command."""
import sys, json, time, threading
import serial

port = sys.argv[1]
show_hb = "--hb" in sys.argv
s = serial.Serial(port, 115200, timeout=0.2)
time.sleep(2.0)                      # the Uno resets when the port opens
s.write(b"status\n")


def keyboard():
    for line in sys.stdin:
        s.write((line.strip() + "\n").encode())


threading.Thread(target=keyboard, daemon=True).start()
t0 = time.time()
while True:
    raw = s.readline().decode(errors="replace").strip()
    if not raw:
        continue
    try:
        m = json.loads(raw)
    except ValueError:
        print(f"{time.time() - t0:8.3f}  (not json) {raw}")
        continue
    if m.get("ev") == "hb" and not show_hb:
        continue
    ev = m.pop("ev", "?"); dev_t = m.pop("t", None)
    rest = " ".join(f"{k}={v}" for k, v in m.items())
    print(f"{time.time() - t0:8.3f}  dev_ms={dev_t!s:>8}  {ev:<12} {rest}")
