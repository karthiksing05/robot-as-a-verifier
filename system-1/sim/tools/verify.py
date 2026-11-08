"""Check a test device in the sim, through cad_device.py and System 1's own skills. From system-1/:

    uv run --extra sim python sim/tools/verify.py <id> [--only workflow,F2] [--effector stock|probe] [--shots]

Reads appliances/<id>/verify.yaml (docs/device-authoring.md) and checks, each on a fresh rig:
    load      every revision in device.yaml builds, and its firmware starts
    reach     the controls it lists are reachable from the nominal placement, and the ones it says aren't, aren't
    workflow  the manual's procedure on Rev B: every step meets its expectations
    F<n>      each fault's steps meet every expectation on Rev B, and on the fault's revision first miss one at
              fails_at. So the failure is the physics or the firmware differing, not a scripted verdict.
The effector is verify.yaml's (and a step list's own), unless --effector overrides every one of them, to run the whole
bench on one effector. Writes <id>/build/verify.json (verify.<effector>.json with --effector) and exits non-zero when
anything didn't verify.
"""
import argparse
import json
import math
import pathlib
import re
import sys
import traceback

SYSTEM_1 = pathlib.Path(__file__).resolve().parents[2]
DEVICES = SYSTEM_1.parent / "appliances"  # one folder per device
sys.path[:0] = [str(SYSTEM_1 / "core"), str(SYSTEM_1 / "sim")]

import mujoco  # noqa: E402
import numpy as np  # noqa: E402
import yaml  # noqa: E402

import affordances  # noqa: E402
import cad_device  # noqa: E402
import sim_rig  # noqa: E402
import skills  # noqa: E402
from rig import CONTROL_HZ, SafetyStop  # noqa: E402

REACH_MM = 2.0  # IK position error that still counts as reached


class Bench:
    def __init__(self, device, rev, effector, shots=None):
        self.device, self.rev = device, rev
        self.rig = sim_rig.make_rig(None, slop=True, offsets=0, stiffness=18.0, sensing="current", device=str(device), rev=rev, effector=effector)
        self.a = self.rig.arm
        self.known = {}
        self.shots = shots
        skills.go_home(self.a)

    def parts(self):
        mujoco.mj_forward(self.a.m, self.a.d)
        return self.a.world.truth(self.a.m, self.a.d)

    def snapshot(self):
        app = self.a.app
        return {"readings": dict(app.readings), "lcd": app.lcd, "ring": app.ring, "state": app.state}

    def do(self, step):
        a, app = self.a, self.a.app
        n0 = len(app.events)
        out = {}
        if "skill" in step:
            parts = self.parts()
            try:
                r = affordances.run_step(a, parts, {"skill": step["skill"], "target": step["target"], "params": step.get("params", {})}, self.known)
                out = {"verdict": r.get("verdict"), "reason": (r.get("reason") or "")[:160], "change": r.get("readout_change")}
            except SafetyStop as e:
                out = {"verdict": "SAFETY_STOP", "reason": str(e)[:160]}
                skills.go_home(a)
        elif "wait_s" in step:
            for _ in range(int(step["wait_s"] * CONTROL_HZ)):
                a.tick()
        elif "set_joint" in step:  # the operator sets a part by hand, as a test fixture
            j = step["set_joint"]
            q = math.radians(j["deg"]) if "deg" in j else j["mm"] * 1e-3
            a.d.qpos[a.m.joint(j["name"]).qposadr[0]] = q
            mujoco.mj_forward(a.m, a.d)
            for _ in range(CONTROL_HZ // 5):
                a.tick()
        elif "drop_object" in step:  # the operator lowers an object over a well and lets go: the bore decides where it stops
            o = step["drop_object"]
            w, m, d = a.world, a.m, a.d
            obj = next(x for x in w.cfg["objects"] if x["name"] == o["name"])
            well = next(c for c in w.cfg["controls"] if c["id"] == o["into"])
            T = w.root_T(m, d, well["root"])
            R = T[:3, :3]
            above = T[:3, :3] @ (np.asarray(well["collar"], float) * 1e-3) + T[:3, 3] + [0, 0, o.get("lift_mm", 3) * 1e-3]
            jnt = m.joint(f"{o['name']}_free")
            adr, dof = jnt.qposadr[0], jnt.dofadr[0]
            d.qpos[adr:adr + 3] = above - R @ (np.asarray(obj["collar"], float) * 1e-3)
            d.qpos[adr + 3:adr + 7] = cad_device._quat(R)
            d.qvel[dof:dof + 6] = 0
            mujoco.mj_forward(m, d)
            for _ in range(int(o.get("settle_s", 1.5) * CONTROL_HZ)):
                a.tick()
        elif "move_device" in step:  # the operator moves the device on the bench
            mv = step["move_device"]
            a.world.set_root_pose(a.m, a.d, mv.get("root", next(iter(a.world.cfg["roots"]))), mv.get("dx_mm", 0) * 1e-3, mv.get("dy_mm", 0) * 1e-3, mv.get("yaw_deg", 0))
            skills.go_home(a)
        elif "reach" in step:
            out = {"reach": self.reach(step["reach"])}
        else:
            raise ValueError(f"unknown step {step}")
        out["changed"] = sorted({ch for _, ch, _ in app.events[n0:]})
        out.update(self.snapshot())
        return out

    def reach(self, ids):
        parts = {p.id: p for p in self.parts()}
        got = {}
        for i in ids:
            p = parts[i]
            target = p.meta.get("tip", p.pos) if p.kind == "toggle" else p.pos
            axes = [-np.asarray(p.normal)]
            if p.kind == "handle":  # hook_pull's own first pose: the pad under the lip
                import manipulate
                target, axis = manipulate._hook_poses(self.a, p, p.meta.get("angle", 0.0), p.meta.get("angle", 0.0))[0][0]
                axes = [axis]
            got[i] = False
            for axis in axes:
                q, ok, err, ang = self.a.ik.solve(np.asarray(target), axis / np.linalg.norm(axis), self.a.home_q)
                if err * 1000 <= REACH_MM:
                    got[i] = True
                    break
        return got


def meets(expect, got):
    """The expectations this result misses, in words. Empty: it meets them all."""
    miss = []
    for k, want in (expect or {}).items():
        if k == "verdict":
            ok = got.get("verdict") in (want if isinstance(want, list) else [want])
            have = got.get("verdict")
        elif k == "readings":
            bad = {ch: got["readings"].get(ch) for ch, v in want.items() if got["readings"].get(ch) not in (v if isinstance(v, list) else [v])}
            ok, have = not bad, bad
        elif k == "lcd":
            ok, have = re.fullmatch(str(want), got.get("lcd") or "") is not None, got.get("lcd")
        elif k in ("ring", "state"):
            ok, have = got.get(k) in (want if isinstance(want, list) else [want]), got.get(k)
        elif k == "changed":
            ok, have = set(want) <= set(got["changed"]), got["changed"]
        elif k == "unchanged":
            ok, have = not (set(want) & set(got["changed"])), got["changed"]
        elif k == "reach":
            ok, have = all(got.get("reach", {}).get(i) == v for i, v in want.items()), got.get("reach")
        else:
            raise ValueError(f"unknown expectation {k}")
        if not ok:
            miss.append(f"{k}: wanted {want}, got {have}")
    return miss


def run(device, rev, steps, effector):
    b = Bench(device, rev, effector)
    trail = []
    for i, step in enumerate(steps):
        got = b.do(step)
        miss = meets(step.get("expect"), got)
        trail.append({"i": i, "step": {k: v for k, v in step.items() if k != "expect"}, "miss": miss,
                      **{k: got.get(k) for k in ("verdict", "reason", "lcd", "state", "changed", "reach")}})
        if miss:
            return i, trail
    return None, trail


def rev_for(cfg, fid, spec):
    if spec.get("rev"):
        return spec["rev"]
    return ",".join(f"{f}={'A' if f == fid else 'B'}" for f in cfg.get("faults", {}))


def check(folder, only=None, override=None):
    """override: an effector for every check, over verify.yaml's and each step list's own."""
    device = folder / "device.yaml"
    cfg = yaml.safe_load(device.read_text())
    plan = yaml.safe_load((folder / "verify.yaml").read_text())
    effector = override or plan.get("effector", "stock")
    report = {}

    def want(name):
        return not only or name in only

    if want("load"):
        loaded = {}
        for rev in cfg["revs"]:
            try:
                w = cad_device.build_cad_world(device, rev)
                m = mujoco.MjModel.from_xml_path(w.xml_path)
                d = mujoco.MjData(m)
                fw = w.make_mcu(m)
                fw.update(m, d)
                loaded[rev] = "ok"
            except Exception as e:  # noqa: BLE001  a report, not a crash
                loaded[rev] = f"{type(e).__name__}: {e}"
        report["load"] = {"ok": all(v == "ok" for v in loaded.values()), "revs": loaded}
    if want("reach") and plan.get("reach"):
        # reach: {reachable, unreachable} on Rev B, plus revs: {A: {reachable, unreachable}, ...} for a revision whose
        # geometry differs (a control out of reach on Rev A only)
        r = plan["reach"]
        checks = {"B": r, **(r.get("revs") or {})}
        got_all, bad_all = {}, []
        for rev, rr in checks.items():
            b = Bench(device, rev, effector)
            got = b.reach(list(rr.get("reachable", [])) + list(rr.get("unreachable", [])))
            got_all[rev] = got
            bad_all += [f"{i} (rev {rev})" for i in rr.get("reachable", []) if not got[i]] + \
                       [f"{i} (rev {rev}, listed unreachable)" for i in rr.get("unreachable", []) if got[i]]
        report["reach"] = {"ok": not bad_all, "got": got_all, "wrong": bad_all}
    if want("workflow"):
        wf = plan["workflow"]
        at, trail = run(device, wf.get("rev", "B"), wf["steps"], override or wf.get("effector", effector))
        report["workflow"] = {"ok": at is None, "failed_at": at, "trail": trail}
    for fid, spec in (plan.get("faults") or {}).items():
        if not want(fid):
            continue
        eff = override or spec.get("effector", effector)
        try:
            b_at, b_trail = run(device, spec.get("good_rev", "B"), spec["steps"], eff)
            rev = rev_for(cfg, fid, spec)
            f_at, f_trail = run(device, rev, spec["steps"], eff)
        except Exception:  # noqa: BLE001
            report[fid] = {"ok": False, "error": traceback.format_exc(limit=3)}
            continue
        expected_at = spec.get("fails_at")
        ok = b_at is None and f_at is not None and (expected_at is None or f_at == expected_at)
        report[fid] = {"ok": ok, "rev": rev, "good_passes": b_at is None, "fault_fails_at": f_at, "expected_at": expected_at,
                       "fault_miss": f_trail[-1]["miss"] if f_at is not None else [], "good_trail": b_trail if b_at is not None else None,
                       "fault_trail": f_trail}
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("device", help="a folder name under appliances/")
    ap.add_argument("--only", default=None, help="comma-separated: load, reach, workflow, F1, ...")
    ap.add_argument("--effector", default=None, choices=["stock", "probe"], help="run every check on this effector, over verify.yaml's")
    args = ap.parse_args()
    folder = DEVICES / args.device
    report = check(folder, set(args.only.split(",")) if args.only else None, args.effector)
    (folder / "build").mkdir(exist_ok=True)
    (folder / "build" / (f"verify.{args.effector}.json" if args.effector else "verify.json")).write_text(json.dumps(report, indent=1, default=str) + "\n")
    bad = 0
    for name, r in report.items():
        line = "verified" if r["ok"] else "NOT VERIFIED"
        if name.startswith("F"):
            line += f"  (rev {r.get('rev')}: good passes={r.get('good_passes')}, fault fails at step {r.get('fault_fails_at')}"
            line += f" {r.get('fault_miss')})" if r.get("fault_miss") else ")"
        elif name == "workflow" and not r["ok"]:
            line += f"  at step {r['failed_at']}: {r['trail'][-1]['miss']} ({r['trail'][-1].get('reason')})"
        elif name in ("load", "reach") and not r["ok"]:
            line += f"  {r.get('revs') or r.get('wrong')}"
        print(f"{args.device:16s} {name:9s} {line}")
        bad += not r["ok"]
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
