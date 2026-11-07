"""The light install has no sim, so the tests that need one aren't collected. `uv sync --extra sim` brings them back,
and `--extra arm` adds the two that need LeRobot's bus code and pyserial."""
import importlib.util


def _has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


if not _has("mujoco"):
    collect_ignore_glob = ["tests/test_real_cameras.py", "hardware/tests/*"]
elif not _has("draccus"):
    collect_ignore_glob = ["hardware/tests/test_real_arm.py", "hardware/tests/test_pico_readout.py"]
