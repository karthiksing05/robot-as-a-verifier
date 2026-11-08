import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from calibrate_mw1_buttons import PressCapture, Wizard, apply_mapping, read_source_pins, validate_mapping


class ButtonCalibrationTests(unittest.TestCase):
    def test_requires_release(self):
        capture = PressCapture()
        self.assertIsNone(capture.feed({"pin": 4, "v": 1, "t": 10}))
        result = capture.feed({"pin": 4, "v": 0, "t": 600})
        self.assertEqual(result["pin"], 4)
        self.assertEqual(result["press"]["t"], 10)
        self.assertEqual(result["release"]["t"], 600)

    def test_chord_rejected(self):
        capture = PressCapture()
        for pin, value in [(2, 1), (3, 1), (2, 0)]:
            self.assertIsNone(capture.feed({"pin": pin, "v": value}))
        self.assertIn("error", capture.feed({"pin": 3, "v": 0}))

    def test_duplicate_mapping_rejected(self):
        with self.assertRaises(ValueError):
            validate_mapping(dict(time=2, **{"30s": 2}, power=4, start=5, stop=6))

    def test_extended_inputs_allowed_and_reserved_pins_rejected(self):
        validate_mapping({"time": 6, "30s": 8, "power": 10, "start": 16, "stop": 17})
        for reserved in (0, 1, 13, 14, 15, 18, 19):
            with self.assertRaises(ValueError):
                validate_mapping({"time": 6, "30s": 8, "power": 10, "start": 2, "stop": reserved})

    def test_pin_update_and_concurrent_edit_guard(self):
        text = ("const uint8_t PIN_START = 2, PIN_STOP = 3, PIN_TIME = 4, PIN_POWER = 5, PIN_30S = 6;\n"
                "const uint8_t PIN_SOFT_SDA = A4;\n")
        mapping = {"time": 2, "30s": 3, "power": 4, "start": 5, "stop": 6}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "test.ino"
            source.write_bytes(text.encode())
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            after = apply_mapping(source, mapping, before)
            self.assertEqual(read_source_pins(source.read_text()), mapping)
            self.assertIn("PIN_SOFT_SDA = A4", source.read_text())
            self.assertEqual(after, hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(apply_mapping(source, mapping, after), after)
            source.write_text(source.read_text() + "// concurrent edit\n")
            with self.assertRaises(ValueError):
                apply_mapping(source, mapping, after)
            self.assertIn("concurrent edit", source.read_text())

    def test_raw_trace_and_connection_watchdog(self):
        class Port:
            def __init__(self, events):
                self.lines = [json.dumps(event).encode() + b"\n" for event in events]

            @property
            def in_waiting(self):
                return len(self.lines[0]) if self.lines else 0

            def read(self, size):
                if not self.lines:
                    return b""
                chunk = self.lines.pop(0)
                if len(chunk) > size:
                    self.lines.insert(0, chunk[size:])
                return chunk[:size]

        events = [{"ev": "hb", "button_test": 1, "input_mask": 0, "t": 100},
                  {"ev": "input", "pin": 8, "v": 1, "t": 200},
                  {"ev": "input", "pin": 8, "v": 0, "t": 600}]
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(progress=Path(directory) / "progress.json",
                                   trace=Path(directory) / "trace.jsonl")
            wizard = Wizard(Port(events), args, {})
            wizard.progress("waiting", label="30s")
            wizard.read()
            wizard.watchdog = True
            wizard.read()
            progress = json.loads(args.progress.read_text())
            self.assertEqual(progress["held_pins"], [8])
            self.assertEqual(progress["last_input"]["pin"], 8)
            wizard.read()
            self.assertEqual(json.loads(args.progress.read_text())["held_pins"], [])
            self.assertEqual(len(args.trace.read_text().splitlines()), 3)
            wizard.last_heartbeat = time.monotonic() - 9
            with self.assertRaises(TimeoutError):
                wizard.read()
            self.assertEqual(wizard.mapping, {})

    def test_partial_serial_lines_are_preserved(self):
        class Port:
            def __init__(self):
                self.chunks = [b'{"ev":"hb","button_test":1,',
                               b'"input_mask":0,"t":100}\n{"ev":"input",',
                               b'"pin":8,"v":1,"t":200}\n']

            @property
            def in_waiting(self):
                return len(self.chunks[0]) if self.chunks else 0

            def read(self, size):
                return self.chunks.pop(0) if self.chunks else b""

        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(progress=Path(directory) / "progress.json",
                                   trace=Path(directory) / "trace.jsonl")
            wizard = Wizard(Port(), args, {})
            self.assertIsNone(wizard.read())
            self.assertEqual(wizard.read()["ev"], "hb")
            self.assertEqual(wizard.read()["pin"], 8)
            self.assertEqual(json.loads(args.progress.read_text())["held_pins"], [8])
            self.assertEqual(len(args.trace.read_text().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
