"""A device from a device file on real physics: the canonical centrifuge in appliances/centrifuge.
Run: uv run --extra sim pytest sim/tests/test_cad_device.py"""
import math
import pathlib
import sys

import numpy as np
import pytest

SYSTEM_1 = pathlib.Path(__file__).resolve().parents[2]
for d in (SYSTEM_1 / "core", SYSTEM_1 / "sim"):
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))
DEVICE = SYSTEM_1.parent / "appliances" / "centrifuge" / "device.yaml"

pytestmark = [pytest.mark.sim, pytest.mark.skipif(not DEVICE.exists(), reason="no appliances/centrifuge")]


@pytest.fixture(scope="module")
def mods():
    pytest.importorskip("mujoco")
    import affordances
    import cad_device
    import inventory
    import sim_rig
    return sim_rig, cad_device, inventory, affordances


def _rig(sim_rig, rev="B", **kw):
    kw.setdefault("effector", "probe")  # the pad's tactile sensing: the stock gripper has no pad
    return sim_rig.make_rig(0, slop=True, offsets=0, stiffness=18.0, sensing="tactile", device=str(DEVICE), rev=rev, **kw)


def test_fault_choices_parse(mods):
    _, cad_device, _, _ = mods
    assert cad_device.parse_rev("F1=B,F2=B,F3=A") == {"F1": "B", "F2": "B", "F3": "A"}
    assert cad_device.parse_rev("A") is None


def test_the_robots_cad_inventory_is_where_the_sim_puts_the_parts(mods):
    sim_rig, _, inventory, _ = mods
    rig = _rig(sim_rig)
    inv = inventory.Inventory(DEVICE, "B")
    truth = {p.id: p for p in rig.arm.world.truth(rig.arm.m, rig.arm.d)}
    for p in inv.parts():
        assert np.linalg.norm(p.pos - truth[p.id].pos) < 2e-4, p.id
        assert p.meta["source"] == "cad"


def test_registration_fits_a_shift_from_face_offsets_and_matched_parts(mods):
    _, _, inventory, _ = mods
    inv = inventory.Inventory(DEVICE, "B")
    T0 = inv.Ts["centrifuge"]
    true = inventory._T(inventory._yaw(4.0) @ T0[:3, :3], T0[:3, 3] + [0.012, -0.008, 0.0])
    faces = inv.cfg["registration"]["centrifuge"]["touches"]
    got = [(k, true[:3, :3] @ (np.asarray(f["at"]) * 1e-3) + true[:3, 3]) for k, f in enumerate(faces)]
    pairs = [(true[:3, :3] @ (np.asarray(c["top"]) * 1e-3) + true[:3, 3], np.asarray(c["top"], float))
             for c in inv.cfg["controls"] if c["kind"] == "button"]
    T, res, seen = inventory.fit(inv, "centrifuge", T0, got, pairs)
    assert np.linalg.norm(T[:2, 3] - true[:2, 3]) < 5e-4
    assert abs(math.degrees(math.atan2(T[1, 0], T[0, 0]) - math.atan2(true[1, 0], true[0, 0]))) < 0.1
    assert max(abs(r) for r in res) < 5e-4 and set(seen) >= {"x", "y"}


def test_matching_survives_a_guess_off_by_more_than_half_the_part_spacing(mods):
    _, _, inventory, _ = mods
    from dataclasses import replace

    inv = inventory.Inventory(DEVICE, "B")
    buttons = [p for p in inv.parts() if p.kind == "button"]
    shift = np.array([0.004, 0.025, 0.0])  # the buttons are 23 mm apart along y
    scanned = [replace(p, T=np.r_[np.c_[p.T[:3, :3], p.pos + shift], [[0, 0, 0, 1]]]) for p in buttons]
    pairs = inv.matches(scanned)["centrifuge"]
    by_point = {tuple(np.round(cad, 2)): s for s, cad in pairs}
    for p in buttons:
        c = next(c for c in inv.cfg["controls"] if c["id"] == p.id)
        assert np.allclose(by_point[tuple(np.round(c["top"], 2))], p.pos + shift)


def test_push_refuses_a_clamped_root_and_a_direction_it_cant_push(mods):
    sim_rig, _, inventory, _ = mods
    rig = _rig(sim_rig)
    inv = inventory.Inventory(DEVICE, "B")
    assert "clamped" in inventory.push(rig.arm, inv, "centrifuge", 10, 0, 0, "clamped")["reason"]
    assert "only push" in inventory.push(rig.arm, inv, "centrifuge", -10, 0, 0, "free")["reason"]
    assert "bounds" in inventory.push(rig.arm, inv, "centrifuge", 0, 0, 5, "free")["reason"]  # the file allows no turn


def test_rev_a_lid_is_refused_for_its_pinch_fin(mods):
    sim_rig, _, _, affordances = mods
    rig = _rig(sim_rig, "A")
    parts = rig.arm.world.truth(rig.arm.m, rig.arm.d)
    r = affordances.run_step(rig.arm, parts, {"skill": "hook_pull", "target": "handle_1", "params": {"angle": 100}}, {})
    assert r["verdict"] == "REFUSED" and "pinch" in r["reason"]


@pytest.mark.parametrize("rev, seated", [("F2=B,F3=B", True), ("F2=B,F3=A", False)])
def test_well_a_insert_decides_whether_the_tube_seats(mods, rev, seated):
    """F3 is contact physics: the tube's taper against the insert's bore, not a flag."""
    import mujoco

    sim_rig, _, _, _ = mods
    rig = _rig(sim_rig, rev)
    m, d, w = rig.arm.m, rig.arm.d, rig.arm.world
    d.qpos[m.joint("lid").qposadr[0]] = math.radians(105)
    o, adr = w.cfg["objects"][0], m.joint("tube_1_free").qposadr[0]
    well = next(p for p in w.truth(m, d) if p.id == "well_1")
    T, collar = w.root_T(m, d, "centrifuge"), np.asarray(o["collar"]) * 1e-3
    d.qpos[adr:adr + 3] = well.meta["collar"] + [0, 0, 0.012] - T[:3, :3] @ collar
    mujoco.mju_mat2Quat(d.qpos[adr + 3:adr + 7], T[:3, :3].ravel())
    for _ in range(1500):
        mujoco.mj_step(m, d)
        rig.arm.app.update(m, d)
    assert rig.arm.app.readings["tube_raw_1"] == int(seated)  # the light under well A; the firmware judges it only in READY


def test_hook_pull_opens_and_closes_the_lid(mods):
    sim_rig, _, _, affordances = mods
    import skills

    rig = _rig(sim_rig)
    skills.go_home(rig.arm)
    parts = rig.arm.world.truth(rig.arm.m, rig.arm.d)
    for angle, lid in ((100, [1, 0]), (0, [0, 1])):
        r = affordances.run_step(rig.arm, parts, {"skill": "hook_pull", "target": "handle_1", "params": {"angle": angle}}, {})
        assert r["verdict"] == "PASS" and r["readout_change"]["lid"] == lid, r["reason"]
