"""real_arm.RealArm on a simulated bus (tests/fake_bus.py): no hardware, no serial port. Plain asserts, so pytest is
optional:

    python tests/test_real_arm.py              # all of them, a few minutes
    python tests/test_real_arm.py torque       # those whose names contain "torque"
"""
import os
import sys
import tempfile
import time
from dataclasses import replace

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_1 = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.dirname(HERE), HERE, os.path.join(os.path.dirname(HERE), "tools")] + [
    os.path.join(SYSTEM_1, d) for d in ("core", "sim")]  # the sim stands in for the arm, behind fake_bus

import affordances as A  # noqa: E402
import fake_bus  # noqa: E402
import real_arm  # noqa: E402
import real_wrist  # noqa: E402
import rig  # noqa: E402
import robot  # noqa: E402
import sensors  # noqa: E402
import skills  # noqa: E402
import vision  # noqa: E402
import world  # noqa: E402
from robot import ARM_JOINTS, SafetyStop  # noqa: E402

TMP = tempfile.mkdtemp(prefix="real_arm_test_")
ARM_IDS = range(1, len(ARM_JOINTS) + 1)


def _setup(pace=False):
    """Preset C with the arm as SimArm(slop=True, sensing="current"), and a RealArm on it through the fake bus."""
    w = world.build_world(None)
    sim = robot.SimArm(world=w, slop=True, sensing="current")
    bus = fake_bus.make(sim, TMP)
    return w, sim, bus, real_arm.RealArm(bus, app=sim.app, pace=pace)


def _raises(exc, f, *args):
    try:
        f(*args)
    except exc:
        return
    raise AssertionError(f"{f.__name__}{args} did not raise {exc.__name__}")


def test_mapping_round_trips():
    # The fake encodes through real_arm.to_raw, so these tests pass for any SIGN and OFFSET_RAD: only the comparison
    # with LeRobot's own reading below checks the mapping, and only against LeRobot. The team's arm needs arm_check.
    w, sim, bus, arm = _setup()
    with arm:
        assert bus.calibration == fake_bus.calibration(sim)  # make_bus reads the file as LeRobot writes it
        rng = np.random.default_rng(1)
        lo = [bus.calibration[j].range_min for j in ARM_JOINTS]
        hi = [bus.calibration[j].range_max for j in ARM_JOINTS]
        raw = rng.integers(lo, np.add(hi, 1), (2000, 5))
        assert (real_arm.to_raw(real_arm.to_model(raw, arm.mid), arm.mid) == raw).all()
        q = rng.uniform(arm.ik.lo, arm.ik.hi, (2000, 5))
        err = np.abs(real_arm.to_model(real_arm.to_raw(q, arm.mid), arm.mid) - q).max()
        assert err <= robot.TICK_RAD / 2 + 1e-12, err
        # the model angle is LeRobot's own use_degrees reading of the same steps, with SIGN and OFFSET_RAD
        worst = 0.0
        for r in raw[:300]:
            deg = bus._normalize({i: int(v) for i, v in zip(ARM_IDS, r)})
            lerobot = real_arm.SIGN * np.array([deg[i] for i in ARM_IDS]) + np.degrees(real_arm.OFFSET_RAD)
            worst = max(worst, np.abs(np.degrees(real_arm.to_model(r, arm.mid)) - lerobot).max())
        assert worst < 0.05, worst  # LeRobot counts 4095 steps a turn
        print(f"  raw -> model -> raw exact; model -> raw -> model within {np.degrees(err):.3f} deg; "
              f"LeRobot's use_degrees reading within {worst:.3f} deg")


def test_go_home_and_presses_agree_with_sim():
    w, sim, bus, arm = _setup()
    parts = w.truth(sim.m, sim.d)
    steps = [s for s in A.plan_tests(parts) if s["skill"] == "press"]
    with arm:
        arm.enable(confirm=True)
        skills.go_home(arm)
        assert np.allclose(arm.cmd, arm.home_q)
        sag = np.linalg.norm(arm.tip_pose()[0] - arm.ik.fk(arm.home_q)[0])
        real = [A.run_step(arm, parts, s) for s in steps]
    ref = robot.SimArm(world=world.build_world(None), slop=True, sensing="current")
    ref_parts = ref.world.truth(ref.m, ref.d)
    skills.go_home(ref)
    sim_res = [A.run_step(ref, ref_parts, s) for s in steps]
    print(f"  home reached (tip {sag * 1000:.1f} mm below it: soft servos sag); fake bus: collisions "
          f"{sorted(bus.fake.collisions) or 'none'}, true peak force {bus.fake.peak_true_n:.1f} N")
    for s, r, q in zip(steps, real, sim_res):
        print(f"  {s['target']}: RealArm {r['verdict']} peak {r.get('peak_force_n')} N, contact "
              f"{r.get('contact_offset_mm')} mm, {r['duration_s']} s | SimArm {q['verdict']} peak "
              f"{q.get('peak_force_n')} N, contact {q.get('contact_offset_mm')} mm, {q['duration_s']} s | {r['reason']}")
    assert [r["verdict"] for r in real] == ["PASS"] * len(steps)
    assert [r["verdict"] for r in real] == [r["verdict"] for r in sim_res]
    assert [r["channel"] for r in real] == [r["channel"] for r in sim_res]


def test_torque_off_after_exit_exception_and_ctrl_c():
    for exc in (None, ValueError, KeyboardInterrupt):
        w, sim, bus, arm = _setup()
        try:
            with arm:
                arm.enable(confirm=True)
                for _ in range(5):
                    arm.send(arm.cmd)
                    arm.tick()
                assert all(bus.fake.torque[i] for i in ARM_IDS) and not bus.fake.torque[6]  # the gripper is left off
                if exc:
                    raise exc("test")
        except (ValueError, KeyboardInterrupt) as e:
            assert type(e) is exc
        assert not any(bus.fake.torque.values()) and not bus.fake.open, (exc, bus.fake.torque)
    print("  torque off and the port closed after a normal exit, an exception and Ctrl+C")


def test_refuses_torque_without_confirmation():
    w, sim, bus, arm = _setup()
    with arm:
        for bad in ((), (False,), ("yes",), (1,)):
            _raises(RuntimeError, arm.enable, *bad)
        _raises(RuntimeError, arm.send, arm.cmd)
        arm.tick()  # reads, writes nothing
        assert not any(bus.fake.torque.values()) and not bus.fake.goal
        # moved by hand after the last reading, with no tick since: enable() must read again
        q = sim.d.qpos[sim.qadr[1]]
        sim.d.qpos[sim.qadr[1]] = sim.ik.lo[1] - 0.05  # shoulder_lift past its limit, as if resting on its stop
        _raises(SafetyStop, arm.enable, True)
        assert not any(bus.fake.torque.values())
        sim.d.qpos[sim.qadr[1]], sim.d.qpos[sim.qadr[2]] = q, sim.d.qpos[sim.qadr[2]] - np.radians(20)
        now = bus.fake.sync_read_register_with_error(ARM_IDS, "present_position")
        arm.enable(True)  # holds the elbow where it is now, not 20 deg back
        jump = np.abs(arm.goal - [v for v, _ in now]).max()
        assert jump <= 3, jump  # encoder jitter only
        assert bus.fake.p == dict.fromkeys(ARM_IDS, real_arm.SERVO_P), bus.fake.p  # LeRobot's P=16 raised, gripper untouched
    print(f"  enable() after a 20 deg move by hand: goal within {jump} steps of the arm")
    # motors that don't hold the file's calibration: no connection
    bus = fake_bus.make(sim, TMP)
    c = bus.fake.cal["elbow_flex"]
    bus.fake.cal = {**bus.fake.cal, "elbow_flex": replace(c, homing_offset=c.homing_offset + 100)}
    _raises(RuntimeError, real_arm.RealArm, bus)
    assert not bus.fake.open and not any(bus.fake.torque.values())
    print("  enable() refused without confirm=True and with a joint past its limit; send() refused with torque off; "
          "a calibration mismatch refused at connect")


def test_hard_cap_stops_a_push():
    w, sim, bus, arm = _setup()
    p = next(p for p in w.truth(sim.m, sim.d) if p.id == "button_1")
    with arm:
        arm.enable(confirm=True)
        skills.go_home(arm)
        q, bias = A._approach(arm, p.pos + skills.APPROACH_M * p.normal, -p.normal, "cap test")
        arm.tare()
        try:  # 15 mm past the cap's top at 5 mm/s: the button bottoms out and the panel holds the probe
            skills.move_line(arm, p.pos - 0.015 * p.normal, -p.normal, 0.005)
            raise AssertionError("no safety stop")
        except SafetyStop as e:
            stop = str(e)
        assert "hard cap" in stop, stop
        backed = (arm.tip_pose()[0] - p.pos) @ p.normal
    print(f"  {stop}; true peak {bus.fake.peak_true_n:.1f} N; tip then {backed * 1000:+.1f} mm off the cap's top")


def test_arm_check_reads_and_moves_one_joint():
    import arm_check
    sim = robot.SimArm(world=world.build_world(None), slop=True, sensing="current")
    bus = fake_bus.make(sim, TMP)
    arm_check.main(["FAKE", "cal.json", "--rows", "2"], bus=bus, ask=lambda prompt: "")
    assert not bus.fake.qs and not bus.fake.open  # read-only: nothing driven
    bus = fake_bus.make(sim, TMP)
    arm_check.main(["FAKE", "cal.json", "--move", "elbow_flex"], bus=bus, ask=lambda prompt: "no")
    assert not bus.fake.qs and not any(bus.fake.torque.values())
    bus = fake_bus.make(sim, TMP)
    arm_check.main(["FAKE", "cal.json", "--move", "elbow_flex"], bus=bus, ask=lambda prompt: "yes")
    moved = np.degrees(np.array(bus.fake.qs) - bus.fake.qs[0])
    assert abs(moved[:, 2].max() - 5) < 0.1 and np.abs(np.delete(moved, 2, axis=1)).max() < 0.1, moved
    assert abs(moved[-1, 2]) < 0.1 and not any(bus.fake.torque.values()) and not bus.fake.open
    print(f"  read-only drove nothing; 'no' drove nothing; 'yes' took elbow_flex to {moved[:, 2].max():+.2f} deg and "
          f"back to {moved[-1, 2]:+.2f}, others within {np.abs(np.delete(moved, 2, axis=1)).max():.3f} deg")


def test_hand_eye_solve_finds_a_moved_camera():
    # tools/hand_eye.solve on the board's corners as seen from a camera turned 1 deg and moved 2 mm off the model's
    # wrist_cam, with exact joint angles and 0.2 px of noise. tests/hand_eye_check.py runs the whole tool on the sim.
    import hand_eye
    import hand_eye_check as hc
    arm, K, corners = hc.clean_arm(), sensors.USB_CAL_K, vision.BOARD.getChessboardCorners()
    rng, views = np.random.default_rng(0), []
    for q in hc.board_poses(arm, K, sensors.USB_RES, 15, rng):
        p = (np.linalg.inv(hand_eye.fk(arm, q) @ hc.T_MOUNT) @ vision.T_BASE_BOARD @ np.c_[corners, np.ones(24)].T)[:3]
        img = (K @ (p / p[2]))[:2].T + rng.normal(0, 0.2, (24, 2))
        _, r, t = cv2.solvePnP(corners, img, K, None, flags=cv2.SOLVEPNP_IPPE)
        board = vision._T(cv2.Rodrigues(r)[0], t.ravel())
        views.append(dict(hand=hand_eye.fk(arm, q), board=board, obj=corners, img=img))
    deg, mm = hc.off_by(hand_eye.solve(views, K)[0], hc.T_MOUNT)
    assert deg < 0.03 and mm < 0.1, (deg, mm)
    print(f"  found the 1 deg, 2 mm move to within {deg:.3f} deg and {mm:.3f} mm")


def test_tick_paced_at_control_hz():
    w, sim, bus, arm = _setup(pace=True)
    with arm:
        t = time.perf_counter()
        for _ in range(25):
            arm.tick()
        dt = time.perf_counter() - t
    assert 0.48 <= dt < 0.75, dt
    print(f"  25 ticks in {dt:.3f} s")


def test_operator_readout_judges_presses():
    w, sim, bus, arm = _setup()
    answers, asked = ["BTN1", ""], []
    arm.app = real_arm.OperatorReadout(arm, ask=lambda prompt: asked.append(prompt) or answers[len(asked) - 1])
    parts = w.truth(sim.m, sim.d)
    step = {"skill": "press", "target": "button_1"}
    with arm:
        arm.enable(confirm=True)
        skills.go_home(arm)
        said = A.run_step(arm, parts, step)
        skills.go_home(arm)  # motion between steps: not asked about
        silent = A.run_step(arm, parts, step)
    assert len(asked) == 2, asked  # once per step, after it
    assert said["verdict"] == "PASS" and said["channel"] == "BTN1", said["reason"]
    assert silent["verdict"] == "FAIL", silent["reason"]
    print(f"  'BTN1': {said['verdict']} ({said['reason']}); nothing: {silent['verdict']} ({silent['reason']})")


def test_both_rigs_have_what_the_pipeline_calls():
    w, sim, bus, arm = _setup()
    stream, real_wrist.Capture = real_wrist.Capture, lambda size: None  # no camera here: its stream isn't opened
    try:
        with arm:
            sim_cam, real_cam = sensors.WristCamera(sim, usb=True), real_wrist.WristCamera(arm)
            assert isinstance(sim, rig.Arm) and isinstance(arm, rig.Arm)
            assert isinstance(sim_cam, rig.Camera) and isinstance(real_cam, rig.Camera)
            assert isinstance(sim.app, rig.Readout) and isinstance(arm.app, rig.Readout)
            sim_cam.close()
    finally:
        real_wrist.Capture = stream
    print("  SimArm and RealArm fit rig.Arm, both wrist cameras rig.Camera, both readouts rig.Readout")


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    for name, f in list(globals().items()):
        if name.startswith("test_") and only in name:
            t = time.time()
            print(name)
            f()
            print(f"  ok, {time.time() - t:.0f} s")
