from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from calibrate_mw1_door import validate_result


class DoorCalibrationTests(unittest.TestCase):
    def test_weak_shading_can_be_calibrated_with_measured_points(self):
        validate_result({"open": 700, "closed": 650, "close_below": 670, "open_above": 680, "saved": 1})

    def test_rejects_overlapping_or_unsaved_results(self):
        for result in (
            {"open": 700, "closed": 680, "close_below": 688, "open_above": 692, "saved": 1},
            {"open": 650, "closed": 700, "close_below": 670, "open_above": 680, "saved": 1},
            {"open": 700, "closed": 650, "close_below": 680, "open_above": 670, "saved": 1},
            {"open": 700, "closed": 650, "close_below": 670, "open_above": 680, "saved": 0},
        ):
            with self.assertRaises(ValueError):
                validate_result(result)


if __name__ == "__main__":
    unittest.main()
