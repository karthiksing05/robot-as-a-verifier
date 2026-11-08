"""Press one part from scan_check's last scan with the pipeline's own press (affordances.run_step), the last look on:
from the approach pose it re-finds the part in a fresh photo first. Contact is by stall. You say what changed on the
device after the press (the operator readout), which gives the verdict. The arm returns to where it rested limp before
torque goes off. Don't move the device between scan_check and this.

    python tools/press_part.py COM11 CAL.json button_1
    python tools/press_part.py COM11 CAL.json button_1 --no-look
"""
import logging
import os
import pickle
import sys

import numpy as np

logging.getLogger("torch.distributed.elastic.multiprocessing.redirects").setLevel(logging.ERROR)  # Windows noise

HARDWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HARDWARE, os.path.join(HARDWARE, "..", "core")]
import affordances  # noqa: E402
import hw_rig  # noqa: E402
import pipeline  # noqa: E402
import skills  # noqa: E402


def main(argv=None, ask=input):
    args = argv or sys.argv[1:]
    port, cal, target = args[:3]
    scene = pickle.load(open(os.path.join(os.getcwd(), "scan_check", "scene.pkl"), "rb"))
    part = next((p for p in scene.parts if p.id == target), None)
    if part is None:
        print(f"No {target} in the last scan: it has {[p.id for p in scene.parts]}")
        return
    print(f"{target}: {part.kind} at {np.round(part.pos * 1000)} mm")
    rig = hw_rig.make_rig(port, cal)
    arm = rig.arm
    try:
        arm.tick()
        rest = arm.read_q()
        if ask(f"The arm will go home, look at {target} from close up, press it until it stalls (a few N), back off and "
               f"come back here. Is it clear? Type yes to go: ").strip() != "yes":
            print("Not moved.")
            return
        arm.enable(confirm=True)
        try:
            skills.go_home(arm)
            look = None if "--no-look" in args else pipeline.last_look(rig.wrist, scene.plane[0])
            r = affordances.run_step(arm, scene.parts, {"skill": "press", "target": target}, None, look)
            for k in ("verdict", "reason", "stop", "contact_offset_mm", "travel_mm", "refined", "duration_s"):
                print(f"  {k}: {r.get(k)}")
            print(f"  last look: {({k: v for k, v in part.meta.items() if 'refine' in k}) or 'not used'}")
            skills.go_home(arm)
        except (Exception, KeyboardInterrupt) as e:  # torque stays on, so the arm holds
            print(f"Stopped: {type(e).__name__}: {e or 'Ctrl+C'}")
        skills.move_joints(arm, rest)
        ask("Hold the arm, then press Enter: torque goes off. ")
    finally:
        rig.close()


if __name__ == "__main__":
    main()
