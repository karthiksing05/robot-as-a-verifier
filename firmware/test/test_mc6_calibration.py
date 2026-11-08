import hashlib
from pathlib import Path
import tempfile
import unittest

from tools.calibrate_mc6_buttons import apply_mapping, read_source_pins, validate_mapping
from tools.calibrate_mc6_sensors import validate_result


class Mc6CalibrationTests(unittest.TestCase):
    def test_mapping_reserves_toggle_ring_and_sensors(self):
        validate_mapping({"time": 7, "start": 8, "stop": 9})
        validate_mapping({"time": 2, "start": 0, "stop": 1})
        for pin in (5, 6, 13, 14, 15, 16, 17, 18, 19):
            with self.assertRaises(ValueError):
                validate_mapping({"time": pin, "start": 8, "stop": 9})
        with self.assertRaises(ValueError):
            validate_mapping({"time": 7, "start": 7, "stop": 9})

    def test_source_guard_preserves_fixed_toggle(self):
        source = "const uint8_t PIN_START = 2;\nconst uint8_t PIN_STOP = 3;\nconst uint8_t PIN_TIME = 4;\nconst uint8_t PIN_POWER = 5;\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MC6.ino"
            path.write_text(source)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            apply_mapping(path, {"time": 7, "start": 8, "stop": 9}, digest)
            self.assertEqual(read_source_pins(path.read_text()), {"time": 7, "start": 8, "stop": 9})
            self.assertIn("PIN_POWER = 5", path.read_text())
            with self.assertRaises(ValueError):
                apply_mapping(path, {"time": 2, "start": 3, "stop": 4}, digest)

    def test_both_sensors_require_valid_saved_thresholds(self):
        event = {"saved": 1, "lid": {"clear": 700, "shaded": 650, "lo": 670, "hi": 680},
                 "tube": {"clear": 700, "shaded": 640, "lo": 664, "hi": 676}}
        validate_result(event)
        event["tube"]["hi"] = 640
        with self.assertRaises(ValueError):
            validate_result(event)

    def test_lid_only_result_ignores_disabled_tube(self):
        event = {"saved": 1, "tube_required": 0, "tube_saved": 0,
                 "lid": {"clear": 700, "shaded": 650, "lo": 670, "hi": 680},
                 "tube": {"clear": 0, "shaded": 0, "lo": 0, "hi": 0}}
        validate_result(event)
        event["tube_required"] = 1
        with self.assertRaises(ValueError):
            validate_result(event)
