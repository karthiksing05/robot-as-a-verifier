"""Interactive SO-101 control demo.

    python demo.py                    viewer + command prompt (Rev B appliance)
    python demo.py --rev A            the faulty revision
    python demo.py --plan plans/coverage_test.json --headless   run a plan, no window
    python demo.py --shuffle 3        appliance fixture dropped at a random spot (seed 3)
    python demo.py --slop             the arm as soft and sloppy as the real servos

Type `help` at the prompt for commands.
"""
import argparse
import json
import os
import queue
import shlex
import sys
import threading
import time

import cv2
import mujoco
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))  # skills.py, rig.py
import appliance  # noqa: E402
import skills  # noqa: E402
import vision  # noqa: E402
from appliance import REVS  # noqa: E402
from robot import WORKSPACE, SafetyStop, SimArm  # noqa: E402

LOOK_PNG = os.path.join("runs", "look.png")

HELP = """commands (positions in mm, arm frame: x forward, y left, z up):
  press <btn1|btn2|btn3> [force=6] [travel=2.5]   guarded press, then verdict
  hold  <btn>  [secs=1] [force=6]                 press and hold
  latch door   [force=6]                          push-to-open latch (Rev B only)
  run <plan.json>                                 run a test plan
  goto <x> <y> <z>                                move the fingertip (e.g. goto 220 0 120)
  follow                                          toggle: arm tracks the green sphere
                                                  (double-click it, then Ctrl+right-drag)
  look                                            find the appliance with the scene camera
                                                  (image with what it saw: runs/look.png)
  shuffle [seed]                                  drop the fixture somewhere else and bump the
                                                  camera; controls are stale until you look
  home | status | controls
  rev <A|B>                                       rebuild with that appliance revision
  reset                                           fresh scene, same revision and placement
  quit"""

ALIASES = {"force": "force_limit", "secs": "hold", "travel": "travel_mm"}
VERBS = {"press": "press", "hold": "press_hold", "latch": "push_latch"}


def parse_step(words):
    verb, target, *rest = words
    params = {}
    for kv in rest:
        k, v = kv.split("=")
        params[ALIASES.get(k, k)] = float(v)
    return {"skill": VERBS[verb.lower()], "target": target, "params": params}


def look(arm, cam):
    """Localize the appliance from the scene camera and give the skills the result."""
    skills.go_home(arm)  # keep the arm out of the picture
    img = cam.grab(arm.d)
    os.makedirs("runs", exist_ok=True)
    try:
        seen = vision.look(img, cam.K, appliance.controls(arm.params))
    except vision.LookFailed as e:
        cv2.imwrite(LOOK_PNG, img)
        print(f"look failed: {e}. Controls unchanged; see {LOOK_PNG}")
        return
    arm.controls = seen["controls"]
    cv2.imwrite(LOOK_PNG, vision.draw(img, seen, cam.K))
    err = vision.errors(arm.controls, arm.true_controls())
    print(f"fixture at {(seen['T_base_fixture'][:2, 3] * 1000).round(1).tolist()} mm, "
          f"heading {np.degrees(np.arctan2(seen['T_base_fixture'][1, 0], seen['T_base_fixture'][0, 0])):.1f} deg  ({LOOK_PNG})")
    for k, c in arm.controls.items():
        chk = seen["checks"].get(k)
        det = "" if chk is None else "  detector: not seen, FLAG" if not chk["seen"] else             f"  detector {chk['off_mm']} mm from CAD" + (", FLAG" if chk["flag"] else "")
        print(f"  {k:<5} at {(c.pos * 1000).round(1).tolist()} mm  (sim truth: off by {err[k][0]} mm sideways, "
              f"{err[k][1]} mm along normal){det}")


def fmt(r):
    keys = ["peak_force_n", "travel_mm", "stop", "contact_offset_mm", "duration_s"]
    extra = "  ".join(f"{k}={r[k]}" for k in keys if k in r)
    col = r.get("collisions")
    if col:
        extra += f"  COLLISIONS={col}"
    return f"{r['verdict']:<8} {r['skill']:<10} {r['target']:<5} {r.get('reason', '')}\n         {extra}"


def run_plan(arm, path):
    with open(path) as f:
        plan = json.load(f)
    steps = plan["steps"] if isinstance(plan, dict) else plan
    results = []
    for i, step in enumerate(steps, 1):
        print(f"[{i}/{len(steps)}] {step['skill']} {step['target']}", flush=True)
        r = skills.run_step(arm, step)
        print(fmt(r), flush=True)
        results.append(r)
    skills.go_home(arm)
    counts = {v: sum(r["verdict"] == v for r in results) for v in ("PASS", "FAIL", "MISSED", "REFUSED", "ABORTED")}
    print("summary: " + ", ".join(f"{n} {v}" for v, n in counts.items() if n), flush=True)
    return results


def save_run(arm, results, plan_path):
    """results.json plus a force plot per step, under runs/<plan>_rev<X>/."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = os.path.join("runs", f"{os.path.splitext(os.path.basename(plan_path))[0]}_rev{arm.rev}")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "results.json"), "w") as f:
        json.dump([{k: v for k, v in r.items() if k != "force_trace"} for r in results], f, indent=1)
    traced = [r for r in results if r.get("force_trace")]
    if not traced:
        print(f"saved {out}/results.json (no steps moved, so no force plot)")
        return
    fig, axes = plt.subplots(len(traced), 1, figsize=(7, 1.9 * len(traced)), squeeze=False)
    for ax, r in zip(axes[:, 0], traced):
        t, f = np.array(r["force_trace"]).T
        ax.plot(t - t[0], f, lw=1.2)
        ax.axhline(r["force_limit_n"], color="r", ls="--", lw=0.8)
        ax.set_title(f"{r['skill']} {r['target']}: {r['verdict']} ({r['reason']})", fontsize=8, loc="left")
        ax.set_ylabel("N")
    axes[-1, 0].set_xlabel("s")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "force.png"), dpi=110)
    print(f"saved {out}/results.json and force.png")


class Overlay:
    """Status text and a live tip-force plot drawn in the viewer."""

    def __init__(self, viewer):
        self.v = viewer
        self.fig = mujoco.MjvFigure()
        mujoco.mjv_defaultFigure(self.fig)
        self.fig.title = "tip force (N)"
        self.fig.flg_extend = 1
        self.fig.range[1] = [0, 8]
        self.fig.figurergba[3] = 0.6
        self.fig.linename[0] = "force"
        self.n = 0

    def __call__(self, arm):
        if not self.v.is_running():
            return
        tip, _ = arm.tip_pose()
        log = arm.force_log[-250:]  # last 5 s
        f_now = log[-1][1] if log else 0.0
        n = len(log)
        if n:
            t0 = log[-1][0]
            data = np.array([(t - t0, f) for t, f in log], dtype=np.float32).ravel()
            self.fig.linedata[0][: 2 * n] = data
            self.fig.linepnt[0] = n
            self.fig.range[1] = [0, max(8, max(f for _, f in log) * 1.2)]
        vp = self.v.viewport
        if vp is not None:
            w, h = 420, 220
            self.v.set_figures((mujoco.MjrRect(vp.width - w, 0, w, h), self.fig))
        left = "rev\nskill\ntip force\ntip (mm)\nappliance"
        right = (f"{arm.rev}\n{arm.status}\n{f_now:5.2f} N\n"
                 f"{(tip * 1000).round(0).astype(int).tolist()}\n{arm.app.summary()}")
        self.v.set_texts((mujoco.mjtFontScale.mjFONTSCALE_150, mujoco.mjtGridPos.mjGRID_TOPLEFT, left, right))
        self.v.sync()


def interactive(rev, plan=None, placement=None, slop=False):
    import mujoco.viewer

    cmds = queue.Queue()
    if plan:
        cmds.put(f"run {plan}")

    def reader():
        print(HELP)
        while True:
            try:
                cmds.put(input("> "))
            except EOFError:
                cmds.put("quit")
                return

    threading.Thread(target=reader, daemon=True).start()

    auto_look = True
    while True:
        arm = SimArm(rev, realtime=True, placement=placement, slop=slop)
        viewer = mujoco.viewer.launch_passive(arm.m, arm.d, show_left_ui=False, show_right_ui=False)
        viewer.cam.azimuth, viewer.cam.elevation, viewer.cam.distance = 300, -25, 0.7
        viewer.cam.lookat[:] = [0.2, 0, 0.03]
        arm.on_tick = Overlay(viewer)
        cam = vision.Camera(arm.m)
        if auto_look:
            look(arm, cam)
        else:
            print("fixture moved; the controls still point at the old spot until you run look")
        auto_look = True
        target_mocap = arm.m.body("target").mocapid[0]
        follow = False
        next_rev = None
        while viewer.is_running() and next_rev is None:
            try:
                line = cmds.get_nowait()
            except queue.Empty:
                if follow:
                    target = np.clip(arm.d.mocap_pos[target_mocap], WORKSPACE[:, 0], WORKSPACE[:, 1])
                    q, *_ = arm.ik.solve(target, np.array([0.7, 0, -0.7]), arm.cmd, iters=20)
                    arm.send(q)
                else:
                    arm.send(arm.cmd)
                try:
                    arm.tick()
                except SafetyStop as e:
                    print(f"SAFETY STOP: {e}", flush=True)
                    follow = False
                continue
            try:
                words = shlex.split(line)
                if not words:
                    continue
                verb = words[0].lower()
                if verb in VERBS:
                    print(fmt(skills.run_step(arm, parse_step(words))), flush=True)
                elif verb == "run":
                    run_plan(arm, words[1])
                elif verb == "goto":
                    if len(words) != 4:
                        raise ValueError("goto needs x y z in mm")
                    x, y, z = (float(w) / 1000 for w in words[1:4])
                    ang = skills.goto(arm, [x, y, z])
                    print(f"at {arm.tip_pose()[0].round(3).tolist()} (probe {ang:.1f} deg off the 45 deg axis)")
                elif verb == "follow":
                    follow = not follow
                    if follow:
                        arm.d.mocap_pos[target_mocap] = arm.tip_pose()[0]
                    print("follow", "on: double-click the green sphere, Ctrl+right-drag it" if follow else "off")
                elif verb == "home":
                    skills.go_home(arm)
                elif verb == "look":
                    look(arm, cam)
                elif verb == "shuffle":
                    seed = int(words[1]) if len(words) > 1 else None
                    placement = appliance.random_placement(np.random.default_rng(seed))
                    next_rev, auto_look = rev, False
                elif verb == "status":
                    print(f"q (rad) = {arm.read_q().round(3).tolist()}\ntip = {arm.tip_pose()[0].round(4).tolist()}\n{arm.app.summary()}")
                elif verb == "controls":
                    for c in arm.controls.values():
                        print(f"  {c.name:<5} at {(c.pos * 1000).round(0).astype(int).tolist()} mm  skills={list(c.skills) or 'none (needs ' + c.requires + ')'}")
                elif verb == "rev":
                    if words[1].upper() not in REVS:
                        raise ValueError(f"revisions are {', '.join(REVS)}")
                    next_rev = words[1].upper()
                elif verb == "reset":
                    next_rev = rev
                elif verb in ("quit", "exit"):
                    viewer.close()
                    return
                elif verb == "help":
                    print(HELP)
                else:
                    print(f"unknown command '{verb}', type help")
            except SafetyStop as e:
                print(f"SAFETY STOP: {e}")
            except (ValueError, IndexError, KeyError, TypeError, FileNotFoundError) as e:
                print(f"bad command ({e}); type help")
        cam.close()
        viewer.close()
        if next_rev is None:  # window closed
            return
        rev = next_rev
        time.sleep(0.3)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rev", default="B", choices=["A", "B"])
    ap.add_argument("--plan", help="run this plan JSON")
    ap.add_argument("--headless", action="store_true", help="no viewer; needs --plan")
    ap.add_argument("--shuffle", type=int, metavar="SEED", help="random fixture placement")
    ap.add_argument("--slop", action="store_true", help="real-servo softness, dead band and gear play (robot.SERVO_NM_PER_RAD)")
    args = ap.parse_args()
    placement = None if args.shuffle is None else appliance.random_placement(np.random.default_rng(args.shuffle))
    if args.headless:
        if not args.plan:
            ap.error("--headless needs --plan")
        arm = SimArm(args.rev, placement=placement, slop=args.slop)
        look(arm, vision.Camera(arm.m))
        save_run(arm, run_plan(arm, args.plan), args.plan)
    else:
        interactive(args.rev, args.plan, placement, args.slop)


if __name__ == "__main__":
    main()
