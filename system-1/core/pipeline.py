"""System 1's routine on a device, one call per stage, on any rig (rig.Rig: an arm and its cameras). explore.py films
these stages and the tool server runs them. A touch stage that fails hands back what the scan found and the exception,
so the caller can say so and go on; a SafetyStop is raised instead, since the arm stopped. Finer exploration steps, such
as scanning one area of the panel, belong here too.

    scene = scan_device(arm, None, wrist)              # None: the wrist camera surveys too
    plane, touched, err = touch_plane(arm, scene)      # err: the touch-offs failed, and plane is the scan's
    parts, err = touch_parts(arm, scene, plane)        # err: the touches failed, and parts are the scan's
    results = affordances.run_plan(arm, parts, affordances.plan_tests(parts), refine=last_look(wrist, plane))
"""
import traceback
from dataclasses import replace

import perceive
import rgbperceive
import rig
import touch


def scan_device(arm, phone, wrist, depth=False, on_stage=None, on_frame=None, on_survey=None):
    """The device's parts from the cameras: rgbperceive.perceive_rgb (on_survey runs after its wrist survey), or
    perceive.perceive with a depth camera."""
    if depth:
        return perceive.perceive(arm, phone, wrist, on_stage=on_stage, on_frame=on_frame)
    return rgbperceive.perceive_rgb(arm, phone, wrist, on_stage=on_stage, on_frame=on_frame, on_survey=on_survey)


def touch_plane(arm, scene):
    """(the panel plane in the probe's frame, the touch-off points, None), or (the scan's plane, [], the exception)."""
    try:
        return (*touch.touch_plane(arm, scene), None)
    except rig.SafetyStop:  # the arm stopped on a force or workspace limit: not a scan to fall back on
        raise
    except Exception as e:
        return scene.plane[0], [], e


def touch_parts(arm, scene, plane):
    """(the parts with touched heights, None), or (the scanned parts, the exception)."""
    try:
        return touch.touch_parts(arm, scene, scene.parts, plane), None
    except rig.SafetyStop:
        raise
    except Exception as e:
        return scene.parts, e


def last_look(wrist, plane, depth=False, sam=None):
    """refine(arm, part) for affordances.run_step: the wrist camera's look at each step's approach pose. A look that
    raises keeps the part as scanned, with the reason in meta["refine_why"], and the step goes on."""
    look = (lambda arm, p: perceive.refine(arm, wrist, p)) if depth else touch.make_refine(wrist, plane, sam=sam)

    def refine(arm, p):
        try:
            return look(arm, p)
        except rig.SafetyStop:
            raise
        except Exception as e:
            traceback.print_exc()
            why = f"{type(e).__name__}: {e}"
            return replace(p, meta={**p.meta, "refined": False, "refine_shift": 0.0, "refine_why": why})

    return refine
