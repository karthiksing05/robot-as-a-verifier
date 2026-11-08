"""The survey review: the model's answer reaches System 1 as a SurveyAnswer, and an answer it can't read keeps System 1's
own pick."""
from rav_contracts import Checkpoint, Escalation, Frame
from rav_harness.model import ModelReply, ScriptedModel
from rav_harness.runlog import RunLog, read_events
from rav_harness.survey import survey_reviewer


class Frames:
    def evidence_frame(self, ref):
        return Frame(ref=ref, data_b64="QUJD", width=2, height=2, caption="the survey")


STOP = Checkpoint(routine_id="r1", stop="escalation", status="paused", escalation=Escalation(
    code="survey_review", measured={"candidates": [{"k": 1, "tilt_deg": 2.0, "points": 300, "faces_arm": True},
                                                   {"k": 2, "tilt_deg": 45.0, "points": 200, "faces_arm": True}],
                                    "picked": 1, "frames": ["frame:1"]}))


def test_the_answer_reaches_system_1_and_a_bad_one_keeps_its_pick(tmp_path):
    good = ('Surface 2. {"panel": 2, "expect": [{"name": "START", "kind": "button"}], "also_look": ["the lid"]}')
    client = ScriptedModel([ModelReply(model="", text=good), ModelReply(model="", text="I can't tell")])
    log = RunLog("r", tmp_path)
    review = survey_reviewer(Frames(), client, log, manual="START starts the spin.")
    answer = review(STOP).survey
    assert answer.panel == 2 and answer.expect[0].name == "START" and answer.also_look == ["the lid"]
    assert "START starts the spin." in client.requests[0]["messages"][0].text
    assert review(STOP).survey is None
    assert "keeps surface 1" in read_events(log.path)[-1].payload["text"]
