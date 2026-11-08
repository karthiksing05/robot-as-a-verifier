"""The MC-6 eight-step demo in the sim (Rev B, stock gripper), filmed with MuJoCo's offscreen renderer at 30 fps of sim time.
Run from system-1/:  uv run --extra sim python <this> OUT_DIR [--still] [--cam lx,ly,lz,dist,az,el]
Reuses sim/tools/verify.py's Bench (System 1's own skills, as the verify.yaml workflow runs them). Edits nothing in the repo."""
import json
import pathlib
import subprocess
import sys
import time

import numpy as np

SYSTEM_1 = pathlib.Path.cwd()
sys.path[:0] = [str(SYSTEM_1 / "sim" / "tools"), str(SYSTEM_1 / "sim")]
import verify  # noqa: E402  (puts core/ and sim/ on the path)
import viz  # noqa: E402
import cv2  # noqa: E402

OUT = pathlib.Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
STILL = "--still" in sys.argv
CAM = [0.20, 0.05, 0.08, 0.75, 200.0, -38.0]
if "--cam" in sys.argv:
    CAM = [float(x) for x in sys.argv[sys.argv.index("--cam") + 1].split(",")]
W, H, FPS = 1920, 1080, 30

SETUP = [
    {"set_joint": {"name": "rack_cover", "deg": 105}},
    {"set_joint": {"name": "lid", "deg": 105}},
]
STEPS = [
    ("s1", "tube_pick", {"skill": "pick", "target": "tube_1"}),
    ("s2", "tube_place (well A)", {"skill": "place", "target": "tube_1", "params": {"into": "well_1", "drop_mm": 30}}),
    ("s3", "lid_close", {"skill": "hook_pull", "target": "handle_1", "params": {"angle": 0}}),
    ("s4", "flip POWER up", {"skill": "flip", "target": "toggle_1"}),
    ("s5", "press TIME+", {"skill": "press", "target": "button_3"}),
    ("s6", "turn SPEED -60", {"skill": "turn", "target": "dial_1", "params": {"angle": -60}}),
    ("s7", "press START", {"skill": "press", "target": "button_1"}),
    ("s8", "press STOP", {"skill": "press", "target": "button_2"}),
]

b = verify.Bench(verify.DEVICES / "centrifuge" / "device.yaml", "B", "stock")
a = b.a
for s in SETUP:
    b.do(s)
for _ in range(25):
    a.tick()
r = viz.renderer(a.m, W, H)
cam = viz.camera(CAM[:3], CAM[3], CAM[4], CAM[5])
if STILL:
    cv2.imwrite(str(OUT / "cam_test.png"), viz.render(r, a.d, cam))
    print("roots:", {k: np.round(a.world.root_T(a.m, a.d, k)[:3, 3], 3).tolist() for k in a.world.cfg["roots"]})
    sys.exit(0)

t0 = a.d.time
ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
                       "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                       str(OUT / "sim_demo.mp4")], stdin=subprocess.PIPE)
state = {"n": 0, "last": None}


def frame(_a=None):
    while a.d.time - t0 >= state["n"] / FPS - 1e-9:
        img = viz.render(r, a.d, cam)
        state["last"] = img
        ff.stdin.write(img.tobytes())
        state["n"] += 1


def hold(sec):
    for _ in range(int(sec * verify.CONTROL_HZ)):
        a.tick()


before = a.on_tick
a.on_tick = lambda arm: (before(arm) if before else None, frame())
frame()
events = []
log = open(OUT / "events.jsonl", "w")


def ev(**k):
    k["t"] = round(a.d.time - t0, 4)
    events.append(k)
    log.write(json.dumps(k) + "\n")
    log.flush()


hold(1.0)  # a beat at home
steps, results = {}, {}
for sid, label, step in STEPS:
    ev(type="step_started", step=sid, label=label, skill=step["skill"], target=step["target"])
    w0 = time.time()
    got = b.do(step)
    ev(type="step_finished", step=sid, verdict=got.get("verdict"), reason=got.get("reason"), changed=got.get("changed"),
       readings=got.get("readings"), lcd=got.get("lcd"), ring=got.get("ring"), state=got.get("state"))
    s0 = next(e["t"] for e in events if e["type"] == "step_started" and e["step"] == sid)
    steps[sid] = [s0, events[-1]["t"]]
    results[sid] = {"label": label, "sim_skill": f"{step['skill']} {step['target']}", "verdict": got.get("verdict"),
                    "reason": got.get("reason"), "changed": got.get("changed"), "state": got.get("state"), "lcd": got.get("lcd"),
                    "ring": got.get("ring"), "readings": got.get("readings")}
    print(sid, label, got.get("verdict"), got.get("state"), repr(got.get("lcd")), got.get("ring"), got.get("changed"),
          f"sim {steps[sid][1]-s0:.1f}s wall {time.time()-w0:.0f}s", (got.get("reason") or "")[:120], flush=True)
    if state["last"] is not None:
        cv2.imwrite(str(OUT / f"{sid}.png"), state["last"])
    hold(0.6)
hold(1.5)
ff.stdin.close()
ff.wait()
json.dump({"steps_sim_s": steps, "results": results, "frames": state["n"], "fps": FPS, "cam": CAM}, open(OUT / "raw.json", "w"), indent=1)
print("frames", state["n"], "sim_s", round(a.d.time - t0, 2))
