"""perceive._coarse_panel on synthetic point clouds: which plane it takes as the control panel. Run: uv run pytest sim/tests"""
import pathlib
import sys

import numpy as np
import pytest

SYSTEM_1 = pathlib.Path(__file__).resolve().parents[2]
if str(SYSTEM_1 / "core") not in sys.path:
    sys.path.insert(0, str(SYSTEM_1 / "core"))

perceive = pytest.importorskip("perceive")

CAM = np.array([0.10, 0.0, 0.25])
rng = np.random.default_rng(0)


def plane(centre, u, v, size, n_pts):
    """n_pts points on a size x size patch through centre, spanned by unit u and v."""
    a = rng.uniform(-size / 2, size / 2, (n_pts, 2))
    return np.asarray(centre) + a[:, :1] * np.asarray(u) + a[:, 1:] * np.asarray(v)


TABLE = plane([0.30, 0, 0.0], [1, 0, 0], [0, 1, 0], 0.4, 3000)  # faces straight up: never the panel
UPRIGHT = plane([0.30, 0, 0.08], [0, 1, 0], [0, 0, 1], 0.12, 1500)  # a wall thermostat's face, toward the arm (-x)
s = np.sqrt(0.5)
TILTED = plane([0.27, 0, 0.12], [0, 1, 0], [s, 0, s], 0.08, 800)  # a 45 deg panel facing up and toward the arm


def test_an_upright_face_is_the_panel_when_nothing_tilts():
    T, _ = perceive._coarse_panel(np.vstack([TABLE, UPRIGHT]), CAM)
    n = T[:3, 2]
    assert n @ [-1, 0, 0] > 0.99  # its normal toward the arm
    assert abs(T[0, 3] - 0.30) < 0.003


def test_a_tilted_panel_still_wins_over_a_bigger_upright_face():
    T, _ = perceive._coarse_panel(np.vstack([TABLE, UPRIGHT, TILTED]), CAM)
    n = T[:3, 2]
    assert n @ [-s, 0, s] > 0.99


def test_no_panel_is_a_clear_error_not_a_type_error():
    with pytest.raises(ValueError, match="no control panel"):
        perceive._coarse_panel(TABLE, CAM)
