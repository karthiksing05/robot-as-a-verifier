"""What every real device readout keeps, however its lines arrive: rig.Readout, as device.DeviceMCU is in the sim.

The device sends flat snapshots, one JSON object per message, {"BTN1": 0, "FAN": 0.42, "DOOR": 0, "LCD": "READY"}
(system-1/subjects/appliance/firmware/README.md has the format). ingest() keeps what DeviceMCU keeps: readings, each
channel's latest value, and events, (time, channel, value) each time an int channel changes after its first snapshot.
Floats are continuous, like the sim's FAN, and log no events. time is the laptop's time.monotonic(), which nothing reads.
ingest swaps in a new dict, so a reader of readings never sees one half updated.

Subclasses feed ingest: pico_readout.PicoReadout from a USB serial thread, http_readout.HttpReadout from the server's
POST /readout/<device>. Once the transport fails (error set), readings and events raise SafetyStop with the reason, so
a step mid-push stops and the arm goes home. events, read when a step starts and ends, also raises once nothing has come
for STALE_S, so a crashed device stops the next step instead of failing every part.
"""
import threading
import time

from rig import SafetyStop

STALE_S = 2.0  # the device sends at least every 0.5 s; this long without one, it's gone


class SnapshotReadout:
    source = "the device"  # how errors name it: "the Pico on COM7", "device 'mw1' over WiFi"
    hint = ""              # what to check, after the error

    def __init__(self):
        self._readings, self.lcd, self._events, self.error = {}, None, [], None
        self.last = time.monotonic()
        self._lock = threading.Lock()  # a serial thread, or the server's request handlers, may ingest at once

    @property
    def readings(self):
        self._alive()
        return self._readings

    @property
    def events(self):
        self._alive()
        quiet = time.monotonic() - self.last
        if quiet > STALE_S:
            raise SafetyStop(f"device readout lost: nothing from {self.source} for {quiet:.1f} s" + self.hint)
        return self._events

    def ingest(self, new):
        """One snapshot, already parsed. Not a dict: ignored."""
        if not isinstance(new, dict):
            return
        new = dict(new)
        with self._lock:
            t = time.monotonic()
            self.lcd = new.pop("LCD", self.lcd)
            old = self._readings
            self._events.extend((t, ch, v) for ch, v in new.items()
                                if isinstance(v, int) and ch in old and old[ch] != v)
            self._readings = {**old, **new}
            self.last = t

    def _alive(self):
        if self.error:
            raise SafetyStop(f"device readout lost: {self.source} stopped: {self.error}") from self.error
