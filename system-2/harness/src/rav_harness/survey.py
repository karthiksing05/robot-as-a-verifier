"""The survey review: explore holds after System 1's survey (EscalationPolicy.review_survey) with the candidate surfaces
it measured drawn on a photo, and a model answers with the manual in hand: which surface is the control panel, what
controls the manual says it has, and where else to look. System 1 compares its scan with that; it never adds a control
from it, so the model still can't write a verdict."""
from __future__ import annotations

import base64
import json
import re

from pydantic import ValidationError

from rav_contracts import Checkpoint, Decision, SurveyAnswer, System1

from .commands import Responder, rule_responder
from .model import Image, Message, ModelClient
from .runlog import RunLog

SYSTEM = ("You help a robot arm find the controls of an appliance on a desk in front of it, before it scans. The photo is "
          "from the arm's wrist camera. Coloured dots are 3D points the robot measured, grouped into flat surfaces, each "
          "outlined and numbered. The robot will next photograph one surface up close to find the controls.")
ASK = ("Surfaces the robot measured (tilt from flat, points): {surfaces}. The dots show which points belong to which "
       "surface; outlines can overlap.\n\n{manual}"  # not System 1's pick: told it, the model agreed with it
       "Answer with JSON only:\n"
       '{{"why": "<one sentence: which surface the manual\'s controls are on, and what in the photo shows it>", '
       '"panel": <the numbered surface that holds the controls, or null if none does>, '
       '"expect": [{{"name": "<each control, as the manual names it>", '
       '"kind": "<button|dial|knob|toggle|slider|display|door|handle|other>"}}], '
       '"also_look": ["<other places on the device with controls the robot should photograph, a few words each>"]}}')


def survey_reviewer(system1: System1, client: ModelClient, log: RunLog, manual: str | None = None,
                    respond: Responder = rule_responder) -> Responder:
    """A Responder for explore: answers survey_review stops with the model, and every other stop with `respond`. A reply
    it can't read keeps System 1's own pick, and says so in the log."""
    def review(stop: Checkpoint) -> Decision:
        e = stop.escalation
        if e is None or e.code != "survey_review":
            return respond(stop)
        m = e.measured
        surfaces = ", ".join(f"{c['k']}: {c['tilt_deg']} deg, {c['points']}" + ("" if c["faces_arm"] else ", faces away")
                             for c in m["candidates"])
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
    return review
