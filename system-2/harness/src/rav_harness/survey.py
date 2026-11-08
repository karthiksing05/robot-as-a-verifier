"""The survey review: explore holds after System 1's survey (EscalationPolicy.review_survey) with the candidate surfaces
it measured drawn on a photo, and a model answers with the manual in hand: which surface is the control panel, what
controls the manual says it has, and where else to look. System 1 compares its scan with that; it never adds a control
from it, so the model still can't write a verdict."""
from __future__ import annotations

import base64
import json
import re

from pydantic import ValidationError

from rav_contracts import Checkpoint, Decision, ExpectedControl, MissedControl, SurveyAnswer, System1

from .commands import Responder, rule_responder
from .manual import Manual
from .model import DEFAULT_MODEL, Image, Message, ModelClient, make_client
from .runlog import RunLog

SYSTEM = ("You help a robot arm find the controls of an appliance on a desk in front of it, before it scans. The photo is "
          "from the arm's wrist camera. Coloured dots are 3D points the robot measured, grouped into flat surfaces, each "
          "outlined and numbered. The robot will next photograph one surface up close to find the controls.")
# Only the numbers: not System 1's pick (told it, the model agreed with it) nor the tilts (it picked a vertical edge by
# its tilt over the panel the photo showed)
ASK = ("The photo shows surfaces {surfaces}. The dots show which points belong to which surface; outlines can "
       "overlap.\n\n{manual}"
       "Answer with JSON only:\n"
       '{{"why": "<one sentence: which surface the manual\'s controls are on, and what in the photo shows it>", '
       '"panel": <the numbered surface that holds the controls, or null if none does>, '
       '"expect": [{{"name": "<each control, as the manual names it>", '
       '"kind": "<button|dial|knob|toggle|slider|display|door|handle|other>"}}], '
       '"also_look": ["<other places on the device with controls the robot should photograph, a few words each>"]}}')


NAME_SYSTEM = ("A robot arm scanned an appliance's control panel. The photo is the panel straight on, with a yellow dot and an "
               "id on each thing the scan thinks may be a control. Magenta ids (cand_1, ...) are things it saw but couldn't "
               "classify: name one only if it clearly is one of the manual's controls.")
NAME_ASK = ("{manual}The ids in the photo: {ids}. For each id, say which control from the manual it is, reading the printed "
            "labels beside the controls. A faint or unreadable label is no reason to leave a control unnamed: name it "
            "from where it sits in the manual's layout (its order along the panel, its colour and shape) next to the "
            "controls you did name. A dot on a switch's lever (a metal bat that may point up or down from its base) is "
            "that switch. Or say it isn't a control (a cable, a latch, the lid, the desk). Then list each control the "
            "manual names (or a lid's lip, a handle) that you can see in the photo but that has no id on it, with the pixel of its centre (the photo "
            "is {size} pixels, x from the left, y from the top), and, if you can judge it, how far its top stands "
            "above the panel. Answer with JSON only: "
            '{{"<id>": {{"control": "<the manual\'s name, or null>", '
            '"kind": "<button|dial|knob|toggle|slider|display|none>", "why": "<a few words>"}}, '
            '"missed": [{{"control": "<the manual\'s name>", "kind": "<button|dial|knob|toggle|slider|handle>", '
            '"x": <pixel>, "y": <pixel>, "height_mm": <number or null>}}]}}')


def part_namer(system1: System1, log: RunLog, manual: Manual) -> Responder:
    """The scan review as rav explore --review runs it, for a model run on the real arm: the default model names the parts."""
    return survey_reviewer(system1, make_client(DEFAULT_MODEL, run=log.run_id), log, "\n\n".join(manual.pages))


def survey_reviewer(system1: System1, client: ModelClient, log: RunLog, manual: str | None = None,
                    respond: Responder = rule_responder) -> Responder:
    """A Responder for explore: answers survey_review stops with the model, and every other stop with `respond`. A reply
    it can't read keeps System 1's own pick, and says so in the log."""
    def review(stop: Checkpoint) -> Decision:
        e = stop.escalation
        if e is not None and e.code == "scan_review":
            return name_parts(e.measured)
        if e is None or e.code != "survey_review":
            return respond(stop)
        m = e.measured
        surfaces = ", ".join(str(c["k"]) for c in m["candidates"])
        images = [Image("image/jpeg", system1.evidence_frame(ref).data_b64) for ref in m.get("frames", [])]
        for k, image in enumerate(images):  # what the model saw, and below what it said, to check its pick afterwards
            (log.dir / f"survey_review_{k + 1}.jpg").write_bytes(base64.b64decode(image.data_b64))
        text = ASK.format(surfaces=surfaces, picked=m["picked"], manual=f"The appliance's manual:\n\n{manual}\n\n" if manual else "")
        reply = client.generate(SYSTEM, [Message("user", text, images=images)], [])
        (log.dir / "survey_review.txt").write_text(f"{text}\n\n--- {client.model} ---\n{reply.text}\n", encoding="utf-8")
        why = ""
        try:
            said = json.loads(re.search(r"\{.*\}", reply.text, re.S).group(0))
            why = str(said.pop("why", ""))
            answer = SurveyAnswer.model_validate(said)
        except (AttributeError, ValueError, ValidationError) as err:
            log.emit("message", {"role": "harness", "text": f"survey review: couldn't read {client.model}'s answer ({err}), "
                                                            f"so System 1 keeps surface {m['picked']}"})
            return Decision()
        expect = ", ".join(f"{x.name} ({x.kind})" for x in answer.expect) or "nothing"
        log.emit("message", {"role": "harness", "text": f"survey review by {client.model}: panel {answer.panel} (System 1 "
                                                        f"picked {m['picked']}): {why} Expects {expect}; also look at "
                                                        f"{'; '.join(answer.also_look) or 'nothing else'}"})
        return Decision(survey=answer)

    def name_parts(m: dict) -> Decision:
        """scan_review: each part's name and kind from the panel map and the manual, or None for what isn't a control.
        On the real centrifuge it named all seven candidates right, three tries in three."""
        ids = [p["id"] for p in m["parts"]]
        frames = [system1.evidence_frame(ref) for ref in m.get("frames", [])]
        images = [Image("image/jpeg", f.data_b64) for f in frames]
        for k, image in enumerate(images):
            (log.dir / f"scan_review_{k + 1}.jpg").write_bytes(base64.b64decode(image.data_b64))
        text = NAME_ASK.format(manual=f"The appliance's manual:\n\n{manual}\n\n" if manual else "", ids=", ".join(ids),
                               size=f"{frames[0].width}x{frames[0].height}" if frames else "unknown")
        reply = client.generate(NAME_SYSTEM, [Message("user", text, images=images)], [])
        (log.dir / "scan_review.txt").write_text(f"{text}\n\n--- {client.model} ---\n{reply.text}\n", encoding="utf-8")
        try:
            said = json.loads(re.search(r"\{.*\}", reply.text, re.S).group(0))
            labels = {i: None if not said[i].get("control") or said[i].get("kind") in (None, "none") else
                      ExpectedControl(name=str(said[i]["control"]), kind=str(said[i]["kind"])) for i in ids if i in said}
            missed = [MissedControl(name=str(x["control"]), kind=str(x["kind"]), x=x["x"], y=x["y"],
                                    height_mm=x.get("height_mm")) for x in said.get("missed") or [] if x.get("control")]
        except (AttributeError, ValueError, ValidationError, TypeError, KeyError) as err:
            log.emit("message", {"role": "harness", "text": f"scan review: couldn't read {client.model}'s answer ({err}), "
                                                            "so the parts keep the scan's names"})
            return Decision()
        named = ", ".join(f"{i}: {'not a control' if v is None else f'{v.name} ({v.kind})'}" for i, v in labels.items())
        named += "".join(f"; missed {x.name} ({x.kind}) at pixel {x.x:.0f}, {x.y:.0f}" for x in missed)
        log.emit("message", {"role": "harness", "text": f"scan review by {client.model}: {named}"})
        return Decision(labels=labels, missed=missed)
    return review
