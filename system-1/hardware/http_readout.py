"""The device's readout over WiFi: the board POSTs the same snapshots the Pico prints over USB to rav-server's
/readout/<device> (the server's device_api.py), which hands each to ingest. rig.Readout, as pico_readout.PicoReadout is.

    readout = HttpReadout("mw1")                # waits for nothing: the server isn't listening yet
    rig = hw_rig.make_rig("COM5", "makecu.json", app=readout)

Before the first POST, readings and events raise SafetyStop, so no step runs blind while the board is still joining the
WiFi. After it, they behave as PicoReadout's do: events raises once nothing has come for STALE_S. The board sends a
snapshot on every change and at least every 0.5 s, as over USB.
"""
import time

from safety import SafetyStop
from snapshot_readout import STALE_S, SnapshotReadout  # noqa: F401


class HttpReadout(SnapshotReadout):
    hint = ": off the WiFi, or its sketch stopped"

    def __init__(self, device, url=None, *, track_events=True):
        """device is the name in the URL. url, where the board should POST, goes in the waiting error."""
        super().__init__()
        self.device, self.source, self.closed = device, f"device '{device}' over WiFi", False
        self.url = url or f"/readout/{device}"
        self.track_events = track_events

    @property
    def started(self):
        return bool(self._readings)

    def ingest(self, new, *, replace=False):
        if not self.closed:
            super().ingest(new, track_events=self.track_events, replace=replace)

    def snapshot(self):
        with self._lock:
            age = time.monotonic() - self.last if self.started else None
            return {"device_id": self.device, "readings": dict(self._readings), "lcd": self.lcd,
                    "age_s": round(age, 3) if age is not None else None,
                    "fresh": age is not None and age <= STALE_S and not self.closed}

    def close(self):
        self.closed = True

    def _alive(self):
        super()._alive()
        if not self._readings:
            raise SafetyStop(f"no readings yet from device '{self.device}': is it on the WiFi and posting to {self.url}?")
        if self.closed:
            raise SafetyStop(f"device readout closed: {self.source}")
        quiet = time.monotonic() - self.last
        if quiet > STALE_S:
            raise SafetyStop(f"device readout lost: nothing from {self.source} for {quiet:.1f} s" + self.hint)
