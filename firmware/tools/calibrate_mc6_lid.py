#!/usr/bin/env python3
"""Guide lid-only A2 calibration and preserve any saved A1 tube thresholds."""

if __package__:
    from .calibrate_mc6_sensors import run_cli
else:
    from calibrate_mc6_sensors import run_cli


if __name__ == "__main__":
    run_cli(lid_only_mode=True)
