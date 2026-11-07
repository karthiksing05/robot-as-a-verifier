"""The device's readout from its own Pico over USB serial, for the printed appliance: rig.Readout, as device.DeviceMCU is
in the sim.

    readout = PicoReadout("COM7")               # waits for the Pico's first line
    with real_arm.RealArm(bus, app=readout) as arm:
        ...                                     # the arm's close() closes the readout too

The Pico prints one JSON object per line with its controls' values, {"BTN1": 0, "FAN": 0.42, "DOOR": 0}, and the
display's text as "LCD" if it has one (system-1/subjects/appliance/firmware/README.md has the format). A thread reads the
lines and keeps what DeviceMCU keeps: readings, each channel's latest value, and events, (time, channel, value) each
time an int channel changes after its first line. Floats are continuous, like the sim's FAN, and log no events. time is
the laptop's time.monotonic(), which nothing reads. Reading readings every tick costs nothing: the thread swaps in a new
dict, so a reader never sees one half updated. Once the port fails, as it does when the Pico is unplugged, the thread
stops and the next read of either raises SafetyStop with the port's error, so a step mid-push stops and the arm goes
home. events is read when a step starts and ends, and also raises once no line has come for STALE_S,
so a crashed Pico stops the next step instead of failing every part.
"""
import json
import threading
import time

import serial

from rig import SafetyStop

STALE_S = 2.0  # the Pico sends a line at least every 0.5 s; this long without one, it's gone


class PicoReadout:
    def __init__(self, port):
        self.port, self._readings, self.lcd, self._events, self.error = port, {}, None, [], None
        self.serial = serial.serial_for_url(port, 115200, timeout=0.1)  # USB serial ignores the baud rate
        self.last, self._stop = time.monotonic(), False
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()
        while not self._readings and time.monotonic() - self.last < STALE_S:
            time.sleep(0.01)
        if not self._readings:
            self.close()
            raise RuntimeError(f"no readings from {port} in {STALE_S:g} s: is the Pico's main.py running, and Thonny "
                               "closed?")

    @property
    def readings(self):
        self._alive()
        return self._readings

    @property
    def events(self):
        self._alive()
        quiet = time.monotonic() - self.last
        if quiet > STALE_S:
            raise SafetyStop(f"device readout lost: no line from the Pico on {self.port} for {quiet:.1f} s: unplugged, "
                             "or main.py stopped")
        return self._events

    def close(self):
        """Stop the thread, then let the port go. Safe to call again."""
        self._stop = True
        self._thread.join()
        self.serial.close()

    def _alive(self):
        if self.error:
            raise SafetyStop(f"device readout lost: Pico on {self.port} stopped reading: {self.error}") from self.error

    def _read(self):
        rest = b""
        try:
            while not self._stop:
                rest += self.serial.read(self.serial.in_waiting or 1)  # waits up to the timeout for the first byte
                *lines, rest = rest.split(b"\n")  # a line split across reads waits for its end
                for line in lines:
                    try:
                        new = json.loads(line)
                    except ValueError:
                        continue  # boot messages, a traceback, a half line from before the port opened
                    if not isinstance(new, dict):
                        continue
                    t = time.monotonic()
                    self.lcd = new.pop("LCD", self.lcd)
                    old = self._readings
                    self._events.extend((t, ch, v) for ch, v in new.items()
                                        if isinstance(v, int) and ch in old and old[ch] != v)
                    self._readings = {**old, **new}
                    self.last = t
        except Exception as e:  # SerialException when unplugged: the next read raises with it
            self.error = e
