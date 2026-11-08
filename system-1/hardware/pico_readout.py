"""The device's readout from its own Pico over USB serial, for the printed appliance: rig.Readout, as device.DeviceMCU is
in the sim.

    readout = PicoReadout("COM7")               # waits for the Pico's first line
    with real_arm.RealArm(bus, app=readout) as arm:
        ...                                     # the arm's close() closes the readout too

The Pico prints one JSON object per line with its controls' values, {"BTN1": 0, "FAN": 0.42, "DOOR": 0}, and the
display's text as "LCD" if it has one (system-1/subjects/appliance/firmware/README.md has the format). A thread reads the
lines and hands each to snapshot_readout.SnapshotReadout.ingest, which keeps readings and events as DeviceMCU does and
raises SafetyStop once the port fails, as it does when the Pico is unplugged, or goes quiet for STALE_S.
http_readout.HttpReadout is the same readout over WiFi.
"""
import json
import threading
import time

import serial

from snapshot_readout import STALE_S, SnapshotReadout  # noqa: F401  STALE_S: callers and tests read it from here


class PicoReadout(SnapshotReadout):
    hint = ": unplugged, or main.py stopped"

    def __init__(self, port):
        super().__init__()
        self.port, self.source = port, f"the Pico on {port}"
        self.serial = serial.serial_for_url(port, 115200, timeout=0.1)  # USB serial ignores the baud rate
        self._stop = False
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()
        while not self._readings and time.monotonic() - self.last < STALE_S:
            time.sleep(0.01)
        if not self._readings:
            self.close()
            raise RuntimeError(f"no readings from {port} in {STALE_S:g} s: is the Pico's main.py running, and Thonny "
                               "closed?")

    def close(self):
        """Stop the thread, then let the port go. Safe to call again."""
        self._stop = True
        self._thread.join()
        self.serial.close()

    def _read(self):
        rest = b""
        try:
            while not self._stop:
                rest += self.serial.read(self.serial.in_waiting or 1)  # waits up to the timeout for the first byte
                *lines, rest = rest.split(b"\n")  # a line split across reads waits for its end
                for line in lines:
                    try:
                        self.ingest(json.loads(line))
                    except ValueError:
                        continue  # boot messages, a traceback, a half line from before the port opened
        except Exception as e:  # SerialException when unplugged: the next read raises with it
            self.error = e
