"""Bounded newline-JSON framing shared by the MW-1 operator tools."""
from datetime import datetime, timezone
import json
import os
import sys


class SerialEvents:
    def __init__(self, port, trace):
        self.port, self.trace = port, trace
        self.pending = bytearray()

    def read(self):
        if b"\n" not in self.pending:
            self.pending.extend(self.port.read(min(2048, max(1, self.port.in_waiting))))
        if len(self.pending) > 8192:
            raise ValueError("Serial data exceeded 8192 bytes without a valid line boundary; check connection/baud")
        if b"\n" not in self.pending:
            return None
        line, _, self.pending = self.pending.partition(b"\n")
        if not line.strip():
            return None
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(event, dict):
            return None
        event["host_at"] = datetime.now(timezone.utc).isoformat()
        with self.trace.open("a", encoding="utf-8") as trace:
            trace.write(json.dumps(event) + "\n")
        return event


def disable_quick_edit():
    if os.name != "nt" or not sys.stdin.isatty():
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    handle, mode = kernel.GetStdHandle(-10), wintypes.DWORD()
    if kernel.GetConsoleMode(handle, ctypes.byref(mode)):
        kernel.SetConsoleMode(handle, (mode.value | 0x0080) & ~0x0040)
