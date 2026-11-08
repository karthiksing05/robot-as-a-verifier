"""A yes/no question about a wrist photo, put to Haiku through System 2's model client (rav_harness/model.py: standard
library only, loaded by path, so System 1 needs no new package; it reads SNOWFLAKE_* from the repo's .env).

    held, why = haiku_check.tube_held(wrist.capture())   # True, False, or None when Haiku couldn't say
"""
import base64
import importlib.util
import json
import os
import re
import sys

import cv2

MODEL = "claude-haiku-5-5"
_MODEL_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "system-2", "harness", "src",
                         "rav_harness", "model.py")
_ASK = ("This photo is from a camera on a robot arm's gripper, just after it tried to pick up a small test tube with a "
        "red collar and lift it. The gripper's two white jaws, one with brown tape on its tip, reach in from the left or "
        "bottom of the picture. Is a test tube held between the jaws? Answer with JSON only: "
        '{"held": true or false, "why": "<a few words>"}')


def _model():
    name = "rav_model_for_system1"
    if name not in sys.modules:  # registered first: its dataclasses look themselves up there
        spec = importlib.util.spec_from_file_location(name, os.path.normpath(_MODEL_PY))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


def tube_held(frame):
    """(True, why) if Haiku sees a tube in the jaws in frame (a rig.Frame, BGR), (False, why) if not, (None, why) if it
    couldn't be asked or didn't answer plainly."""
    try:
        m = _model()
        jpg = cv2.imencode(".jpg", frame.rgb, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
        reply = m.MessagesClient(MODEL, max_tokens=200).generate(
            "You check photos from a robot arm's camera and answer in JSON.", [m.Message("user", text=_ASK, images=[m.Image("image/jpeg", base64.b64encode(jpg).decode())])], [])
        found = re.search(r"\{.*\}", reply.text, re.S)
        answer = json.loads(found.group(0)) if found else {}
    except Exception as e:  # noqa: BLE001 - no answer is no reason to stop a pick
        return None, f"Haiku couldn't be asked: {type(e).__name__}: {e}"
    if not isinstance(answer.get("held"), bool):
        return None, f"Haiku's answer wasn't plain: {reply.text[:120]!r}"
    return answer["held"], str(answer.get("why", ""))
