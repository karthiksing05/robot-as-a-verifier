# A starting point for the appliance's Pico, for Max to change: prints the switches as one JSON line whenever one
# changes, and every 0.2 s otherwise (README.md has the format). The pin numbers are placeholders.
import json
import time

from machine import Pin

PINS = {"BTN1": 2, "BTN2": 3, "BTN3": 4, "DOOR": 5}  # GPn, each switch wired from its pin to ground

pins = {ch: Pin(n, Pin.IN, Pin.PULL_UP) for ch, n in PINS.items()}


def sample():
    # a button reads 0 while pressed; the door's reed switch reads 0 while the magnet holds the door shut
    return {ch: p.value() if ch == "DOOR" else 1 - p.value() for ch, p in pins.items()}


state = last = sample()
sent = time.ticks_ms()
while True:
    now = sample()
    new = {ch: now[ch] if now[ch] == last[ch] else state[ch] for ch in state}  # the same twice, 10 ms apart: settled
    last = now
    if new != state or time.ticks_diff(time.ticks_ms(), sent) >= 200:
        state, sent = new, time.ticks_ms()
        print(json.dumps(state))
    time.sleep_ms(10)
