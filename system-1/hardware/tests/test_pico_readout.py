"""pico_readout.PicoReadout against a stand-in Pico on a local socket, which pyserial opens as it would a serial port."""
import os
import socket
import sys
import threading
import time

HARDWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HARDWARE, os.path.join(os.path.dirname(HARDWARE), "core")]

import pico_readout  # noqa: E402
from rig import SafetyStop  # noqa: E402


def test_pico_readout_follows_the_device_and_logs_presses():
    server = socket.create_server(("127.0.0.1", 0))
    pico, up = [], threading.Event()

    def plug_in():  # repeats its line, as a real Pico does: pyserial drops what came before the port opened
        pico.append(server.accept()[0])
        while not up.is_set():
            pico[0].sendall(b'{"BTN1": 0, "FAN": 0.0, "LCD": "READY"}\n')
            time.sleep(0.05)

    plugger = threading.Thread(target=plug_in, daemon=True)
    plugger.start()
    r = pico_readout.PicoReadout(f"socket://127.0.0.1:{server.getsockname()[1]}")
    up.set()
    plugger.join()
    seen = []
    for line in (b'{"BTN1": 1, "FAN": 0.0}\n', b"Traceback (most recent call last):\n",
                 b'{"BTN1": 0, "FAN": 0.4', b'2, "LCD": "FAN 42%"}\n'):  # a line split across two writes
        pico[0].sendall(line)
        for _ in range(10):  # the arm's ticks, reading as affordances does mid-step
            seen.append(dict(r.readings))
            time.sleep(0.02)
    assert {"BTN1": 1, "FAN": 0.0} in seen  # the press, seen while it lasted
    assert r.readings == {"BTN1": 0, "FAN": 0.42} and r.lcd == "FAN 42%"
    assert [(ch, v) for _, ch, v in r.events] == [("BTN1", 1), ("BTN1", 0)]  # FAN is a float: no events, as in the sim
    time.sleep(pico_readout.STALE_S + 0.1)  # the Pico goes quiet: the next step must not start
    try:
        r.events
        raise AssertionError("a quiet Pico's events should raise")
    except SafetyStop:
        pass
    pico[0].close()  # unplugged: the thread stops, and readings, which never go stale, raise with the reason
    r._thread.join(1)
    try:
        r.readings
        raise AssertionError("an unplugged Pico's readings should raise")
    except SafetyStop as e:
        assert "disconnected" in str(e), e
    r.close()
    assert not r._thread.is_alive() and not r.serial.is_open
