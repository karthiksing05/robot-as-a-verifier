import { FORE, HAND, Joints, REST, UPPER, forward, sideFor, solve, solveFree, type Point } from "./so101";
import fs from "node:fs";
import path from "node:path";
import { EMPTY_AGENT, agentReducer, isPaused, pendingApproval, planRows, replayItems, stateLine, telemetryOf, timelineOf } from "./agent";
import { controlStatus, evidenceOf, liveProject, projectOf, reviewOf, type Project } from "./projects";
import { ReplayClock, nextDelay } from "./simsource";
import { diagnose, traceFor, traceOf } from "./trace";
import { describe, expect, it } from "vitest";
import type { RunEvent, Status, StepVerdict } from "./contracts";
import { approvalBlock, parsePrompt, type OperatorEdit } from "./edits";
import { EMPTY_LIVE, TELEMETRY_URL, liveFocus, liveNodes, liveReducer, markAt } from "./live";
import { buildGraph, placeNodes, recordOfNode } from "./graph";
import { coverageOf, eventTimes, fixtureRuns, outcomeOf, rewardOf, toRun } from "./runs";
import { OPERATORS, canEnter } from "./session";

const runs = fixtureRuns();
const revA = runs.find((r) => r.id === "sample-revA")!;
const revB = runs.find((r) => r.id === "sample-revB")!;

const edit: OperatorEdit = {
  id: "E9", runId: revA.id, nodeId: "s2", target: "button_2", action: "retry", reason: "cap may rub", params: {},
  by: "Karthik", at: "2026-11-06T00:00:00Z", state: "planned",
};

describe("live flowchart", () => {
  const ev = (seq: number, type: RunEvent["type"], payload: object): RunEvent => ({ seq, t: seq, run_id: "x", type, payload });
  const step = (id: string, target: string) => ({ id, skill: "press", target, params: {} });
  const meta = { run_id: "x", product: "p", stages: ["SURVEY", "PLAN", "TEST", "REPORT"], route: "r" };
  const plan = ev(1, "plan_ready", { plan_id: "p", source: "rules", steps: [step("s1", "a"), step("s2", "b"), step("s3", "c")] });
  const tel = { wall: 0, sim_t: 0, stage: "TEST", status: "", rate: 1, feeds: [], force: [], paused: false, step: null, substage: null };
  const nodes = (events: RunEvent[], stage = "TEST") => liveNodes({ meta, events, tel: { ...tel, stage }, force: [] });
  const byId = (list: ReturnType<typeof nodes>, id: string) => list.find((n) => n.id === id)!;

  it("shows the stages to come before there's a plan", () => {
    const list = nodes([], "SURVEY");
    expect(byId(list, "stage-SURVEY").status).toBe("running");
    expect(byId(list, "stage-TEST").status).toBe("pending");
    expect(byId(list, "stage-REPORT").provenance).toBe("plan");
  });

  it("holds at approval, then turns steps from dashed to running to their verdict", () => {
    expect(byId(nodes([plan]), "approve").status).toBe("running");
    const approved = ev(2, "approved", { kind: "plan", ref: "p", by: "Karthik" });
    const started = ev(3, "step_started", step("s1", "a"));
    const running = nodes([plan, approved, started]);
    expect(byId(running, "s1").status).toBe("running");
    expect(byId(running, "s2").status).toBe("pending");
    expect(liveFocus(running)).toBe("s1");
    const done = ev(4, "step_finished", { trace: { step: "s1", force_trace: [] }, verdict: { step: "s1", target: "a", status: "failed", reason: "stuck", decided_by: "rule" } });
    const finding = ev(5, "finding", { id: "F1", target: "a", label: "stuck", step_ids: ["s1"], event_seqs: [4], severity: "high", what_happened: "" });
    const after = nodes([plan, approved, started, done, finding]);
    expect(byId(after, "s1").status).toBe("failed");
    expect(byId(after, "F1").parents).toEqual(["s1"]);
  });

  it("follows steering: a skip branches off, a prioritized step moves up", () => {
    const approved = ev(2, "approved", { kind: "plan", ref: "p", by: "Karthik" });
    const started = ev(3, "step_started", step("s1", "a"));
    const moved = ev(4, "steer_applied", { kind: "prioritize", target: "c", by: "Karthik", text: "first", queue: ["s3", "s2"] });
    const list = nodes([plan, approved, started, moved]);
    expect(byId(list, "s3").parents).toEqual(["s1"]);
    expect(byId(list, "s2").parents).toEqual(["s3"]);
    const skip = ev(5, "steer_applied", { kind: "skip", target: "b", by: "Karthik", text: "not needed", queue: ["s3"] });
    const skipped = byId(nodes([plan, approved, started, moved, skip]), "s2");
    expect(skipped.status).toBe("skipped");
    expect(skipped.reason).toBe("not needed");
    expect(skipped.parents).toEqual(["s1"]);
  });

  it("finds the node playing at a moment in a run's video", () => {
    const marks = [{ id: "stage-SCAN", t: 2 }, { id: "s1", t: 10 }, { id: "s2", t: 14 }];
    expect(markAt(marks, 0)).toBe("stage-SCAN");
    expect(markAt(marks, 10)).toBe("s1");
    expect(markAt(marks, 99)).toBe("s2");
  });

  it("keeps a reset from leaking the last run", () => {
    const state = liveReducer({ meta, events: [plan], tel, force: [[0, 1]] }, { name: "reset" });
    expect(state).toEqual(EMPTY_LIVE);
  });
});

describe("runs", () => {
  it("loads every fixture run", () => {
    expect(runs.map((r) => r.id)).toEqual(["sample-agent", "sample-revA", "sample-revB", "sample-sim", "sample-trace"]);
  });

  it.each(runs.map((r) => [r.id, r] as const))("recomputes the reward of %s from its events", (_id, run) => {
    const cov = coverageOf(run);
    const { formula: _formula, ...expected } = run.report.reward;
    expect(cov).toEqual(run.report.coverage);
    expect(rewardOf(cov)).toEqual(expected);
  });

  it("builds coverage up to a point in the log", () => {
    const seq = revA.steps[1].endSeq!;
    const cov = coverageOf(revA, seq);
    expect(cov.passed).toEqual(["button_1"]);
    expect(cov.failed).toEqual(["button_2"]);
  });
});

describe("graph", () => {
  const ids = (nodes: { id: string }[]) => nodes.map((n) => n.id);

  it("shows only logged nodes in demo", () => {
    const nodes = buildGraph(revA, revB, []);
    expect(nodes.every((n) => n.provenance === "log")).toBe(true);
    expect(ids(nodes)).toEqual(expect.arrayContaining(["s2", "F1", "F1-cause", "F2-patch", "apply", "retest"]));
  });

  it("joins both patches into one revision, so it's a DAG", () => {
    const apply = buildGraph(revA, revB, []).find((n) => n.id === "apply")!;
    expect(apply.parents).toEqual(["F1-patch", "F2-patch"]);
  });

  it("adds a dashed node for an edit and keeps its reason", () => {
    const node = buildGraph(revA, revB, [edit]).find((n) => n.editId === "E9")!;
    expect(node).toMatchObject({ provenance: "edit", parents: ["s2"], reason: "cap may rub", status: "planned" });
  });

  it("drops withdrawn edits", () => {
    expect(buildGraph(revA, revB, [{ ...edit, state: "withdrawn" }]).some((n) => n.editId === "E9")).toBe(false);
  });

  it("never places two nodes in one cell, and children sit right of their parents", () => {
    const placed = placeNodes(buildGraph(revA, revB, [edit]));
    expect(new Set(placed.map((n) => `${n.rank}:${n.lane}`)).size).toBe(placed.length);
    const byId = new Map(placed.map((n) => [n.id, n]));
    for (const n of placed) for (const p of n.parents) expect(byId.get(p)!.rank).toBeLessThan(n.rank);
  });
});

describe("edits and access", () => {
  const karthik = OPERATORS[0];
  const bayan = OPERATORS.find((o) => o.name === "Bayan")!;
  const judge = OPERATORS.find((o) => o.role === "judge")!;

  it("reads a steering prompt with its reason", () => {
    expect(parsePrompt("Retry button_2 because the cap may rub", ["button_2", "door"])).toEqual({ action: "retry", target: "button_2", reason: "the cap may rub" });
  });

  it("keeps anything else as a note", () => {
    expect(parsePrompt("why did this fail?", ["button_2"]).action).toBe("note");
  });

  it("stops judges approving and stops self-approval of a CAD patch", () => {
    expect(approvalBlock(edit, judge)).toBeTruthy();
    expect(approvalBlock(edit, karthik)).toBeNull();
    const patch = { ...edit, action: "cad_patch" as const };
    expect(approvalBlock(patch, karthik)).toBeTruthy();
    expect(approvalBlock(patch, bayan)).toBeNull();
  });

  it("keeps judges out of prod", () => {
    expect(canEnter(judge, "prod")).toBe(false);
    expect(canEnter(karthik, "prod")).toBe(true);
  });
});

describe("the trace", () => {
  const run = runs.find((r) => r.id === "sample-trace")!;
  const nodes = ["scene", "plan", ...run.steps.map((s) => s.step.id)];
  const problems = diagnose(run, nodes);
  const at = (node: string) => problems.filter((p) => p.node === node);

  it("files each failure under the layer that caused it", () => {
    expect(at("plan").map((p) => p.layer)).toEqual(["model"]);
    expect(at("s3").map((p) => p.layer)).toEqual(["pipeline"]);
    expect(at("s5").map((p) => p.layer)).toEqual(["model"]);
  });

  it("catches the model contradicting the sensors, next to the device failure", () => {
    const s2 = at("s2");
    expect(s2.map((p) => p.layer).sort()).toEqual(["device", "model"]);
    expect(s2.find((p) => p.layer === "model")!.what).toContain("The sensors said failed");
  });

  it("calls out the same rejected call sent twice", () => {
    expect(at("s4").some((p) => p.layer === "model" && p.what.startsWith("Sent robot.run_step unchanged"))).toBe(true);
  });

  it("keeps a retry after a timeout from counting as a repeat", () => {
    expect(at("s3").some((p) => p.what.startsWith("Sent"))).toBe(false);
  });

  it("gives a step only its own entries, and runs without a trace nothing", () => {
    expect(traceFor(run, "s1").every((e) => e.step === "s1")).toBe(true);
    expect(traceOf(runs.find((r) => r.id === "sample-revA")!)).toEqual([]);
  });
});

describe("the bundled sim recording", () => {
  const run = runs.find((r) => r.id === "sample-sim")!;
  const folder = path.resolve(import.meta.dirname, "../../../../fixtures/sample_run/sample-sim");
  const scene = JSON.parse(fs.readFileSync(path.join(folder, "scene/scene.json"), "utf8"));

  it("is a whole run that replays with no bridge", () => {
    expect(run.recording?.assets).toBeTruthy();
    expect(run.status).toBe("completed");
    expect(run.steps.length).toBeGreaterThan(0);
    for (const file of ["poses.bin", "cameras.mp4", "scene/scene.json", ...Object.keys(scene.files).map((f) => `scene/${f}`)]) expect(run.recording!.assets!(file), file).toBeTruthy();
  });

  it("has one pose frame for every 30th of a second", () => {
    const stride = 1 + scene.moving.length * 7;
    const floats = fs.statSync(path.join(folder, "poses.bin")).size / 4;
    expect(floats % stride).toBe(0);
    expect(floats / stride / run.recording!.timeline.fps).toBeCloseTo(run.recording!.timeline.duration, 1);
  });

  it("stays small enough to commit", () => {
    const size = (dir: string): number => fs.readdirSync(dir, { withFileTypes: true }).reduce((n, e) => n + (e.isDirectory() ? size(path.join(dir, e.name)) : fs.statSync(path.join(dir, e.name)).size), 0);
    expect(size(folder)).toBeLessThan(6e6);
  });
});

describe("the replay clock", () => {
  it("seeks while paused, and stops at the end", async () => {
    const clock = new ReplayClock(10);
    expect(clock.paused).toBe(true);
    clock.currentTime = 4;
    expect(clock.currentTime).toBe(4);
    clock.currentTime = 99;
    expect(clock.currentTime).toBe(10);
    await clock.play(); // from the end, it starts over
    expect(clock.currentTime).toBeLessThan(0.5);
    clock.currentTime = 9.999;
    await new Promise((r) => setTimeout(r, 10));
    expect(clock.currentTime).toBe(10);
    expect(clock.paused).toBe(true);
  });
});

describe("the mock SO-101", () => {
  const shoulder = { x: 1100, y: 800 }, scale = 2.45;
  // A small fixed generator, so a failure repeats.
  let seed = 12345;
  const random = () => { seed = (seed * 1664525 + 1013904223) % 4294967296; return seed / 4294967296; };
  const targets = Array.from({ length: 5000 }, () => ({ x: random() * 1500 - 50, y: random() * 1000 - 50 }));
  const cross = (a: Point, b: Point, c: Point, d: Point) => {
    const side = (p: Point, q: Point, r: Point) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
    return side(a, b, c) * side(a, b, d) < 0 && side(c, d, a) * side(c, d, b) < 0;
  };
  const turn = (a: number, b: number) => Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b)));

  it("reaches for GO without folding onto itself, wherever it starts", () => {
    for (const t of targets) {
      const pose = solve(shoulder, t, Math.atan2(t.y - shoulder.y, t.x - shoulder.x), scale);
      const { elbow, wrist, tip } = forward(shoulder, pose, scale);
      expect(cross(shoulder, elbow, wrist, tip), `hand crosses the upper arm at ${t.x},${t.y}`).toBe(false);
      expect(Math.PI - turn(pose.fore, pose.upper), "elbow too tight").toBeGreaterThan(1.2);
      expect(turn(pose.hand, pose.fore), "wrist too far").toBeLessThanOrEqual(1.5 + 1e-9);
    }
  });

  it("keeps its elbow above the shoulder, so the pose can't flip", () => {
    for (const t of targets) {
      const { elbow } = forward(shoulder, solve(shoulder, t, Math.PI, scale), scale);
      expect(elbow.y).toBeLessThan(shoulder.y);
    }
  });

  it("goes all the way around in the background, on every side of the shoulder", () => {
    const radius = 170 * scale;
    for (let i = 0; i < 360; i += 5) {
      const angle = (i * Math.PI) / 180, t = { x: shoulder.x + Math.cos(angle) * radius, y: shoulder.y + Math.sin(angle) * radius };
      const pose = solveFree(shoulder, t, scale, sideFor(-1, t, shoulder, scale));
      const { tip } = forward(shoulder, pose, scale);
      expect(Math.hypot(tip.x - t.x, tip.y - t.y), `at ${i} degrees`).toBeLessThan(0.01);
      expect(Math.abs(Math.sin(pose.hand)), "hand off level").toBeLessThanOrEqual(Math.sin(0.28) + 1e-9);
    }
  });

  it("gets back to rest from any pose, the short way round", () => {
    for (const t of targets.slice(0, 200)) {
      const joints = new Joints(solveFree(shoulder, t, scale, sideFor(-1, t, shoulder, scale)));
      for (let i = 0; i < 60; i += 1) joints.follow(REST, 1 / 60, 13); // 1 s
      expect(joints.distanceTo(REST)).toBeLessThan(0.05);
    }
  });

  it("has rigid links, whatever the joints do", () => {
    const { elbow, wrist, tip } = forward(shoulder, { upper: 0.4, fore: 2.2, hand: -1 }, scale);
    expect(Math.hypot(elbow.x - shoulder.x, elbow.y - shoulder.y)).toBeCloseTo(UPPER * scale);
    expect(Math.hypot(wrist.x - elbow.x, wrist.y - elbow.y)).toBeCloseTo(FORE * scale);
    expect(Math.hypot(tip.x - wrist.x, tip.y - wrist.y)).toBeCloseTo(HAND * scale);
  });

  it("reaches a reachable target exactly, and moves smoothly when the target jumps", () => {
    const shoulder = { x: 1302, y: 782 }, scale = 1.94; // where it stands on a 1440 x 900 screen, reaching for GO
    const start = { x: 1100, y: 300 }, end = { x: 756, y: 540 };
    const joints = new Joints(solve(shoulder, start, Math.PI, scale));
    let previous = { ...joints.pose }, worst = 0;
    for (let i = 0; i < 90; i += 1) { // 1.5 s at 60 fps
      const pose = joints.follow(solve(shoulder, end, Math.PI, scale), 1 / 60, 20);
      worst = Math.max(worst, turn(pose.upper, previous.upper), turn(pose.fore, previous.fore), turn(pose.hand, previous.hand));
      previous = { ...pose };
    }
    const { tip } = forward(shoulder, joints.pose, scale);
    expect(Math.hypot(tip.x - end.x, tip.y - end.y)).toBeLessThan(1);
    expect(worst, "biggest joint move in one frame, radians").toBeLessThan(0.2);
  });
});

describe("project review", () => {
  const all = fixtureRuns();
  const projects: Project[] = [
    { id: "appliance", name: "Appliance", summary: "", kind: "physical", products: ["Test box"], rules: [], created: "2026-11-07" },
    { id: "sim-preset-c", name: "Preset C", summary: "", kind: "sim", products: ["Sim device preset C"], rules: [], created: "2026-11-07" },
    { id: "sim-14", name: "Seed 14", summary: "", kind: "sim", products: ["Sim device 14"], rules: [], created: "2026-11-07" },
  ];
  const own = (id: string) => all.filter((r) => projectOf(r, projects)?.id === id);

  it("files runs by product, without one name claiming another", () => {
    expect(own("appliance").map((r) => r.id).sort()).toEqual(["sample-revA", "sample-revB", "sample-trace"]);
    expect(own("sim-preset-c").map((r) => r.id)).toEqual(["sample-sim"]);
    expect(projectOf({ ...all[0], product: "Sim device 140", events: [] }, projects)).toBeUndefined();
  });

  it("a run's named project beats its product", () => {
    const events = [{ ...all[0].events[0], type: "run_started" as const, payload: { project: "sim-14" } }];
    expect(projectOf({ ...all[0], events }, projects)?.id).toBe("sim-14");
  });

  it("files a real run that names no project by its id, and calls it real", () => {
    const withRig = [...projects, { ...projects[1], id: "mc6", real: { runs: ["real-"] } }];
    const run = { ...all[0], id: "real-panel-47", product: "Device under test", events: [] };
    expect(projectOf({ ...run, real: true }, withRig)?.id).toBe("mc6");
    expect(projectOf(run, withRig)).toBeUndefined(); // only a run with no sim recording counts
    expect(evidenceOf({ ...run, real: true })).toBe("real");
  });

  it("shows each revision once, and tracks faults across them", () => {
    const review = reviewOf(own("appliance"));
    expect(review.revisions.map((r) => r.revision)).toEqual(["A", "B"]);
    expect(review.open).toEqual([]);
    expect(review.fixed.map((f) => f.revision)).toEqual(["A", "A"]);
    expect(review.headline).toBe("2 faults found and fixed");
    expect(review.evidence).toBe("mock");
  });

  it("calls a recorded run simulated, and keeps its open fault open", () => {
    const review = reviewOf(own("sim-preset-c"));
    expect(review.evidence).toBe("sim");
    expect(review.open.map((f) => f.target)).toEqual(["button_2"]);
    expect(controlStatus(review.latest!, "button_2")).toBe("failed");
    expect(review.headline).toBe("1 open fault");
  });

  it("Live follows the link, then the run on screen, then the first sim device", () => {
    expect(liveProject("appliance", { project: projects[1] }, projects)?.id).toBe("appliance");
    expect(liveProject(null, { project: projects[2] }, projects)?.id).toBe("sim-14");
    expect(liveProject(null, null, projects)?.id).toBe("sim-preset-c");
    expect(liveProject(null, { project: undefined }, projects)).toBeUndefined();
    expect(liveProject("none", { project: projects[1] }, projects)).toBeUndefined();
    expect(liveProject("gone", null, projects)?.id).toBe("sim-preset-c");
  });

  it("has nothing to say about a project with no runs", () => {
    expect(reviewOf([])).toMatchObject({ latest: null, evidence: null, headline: "Not tested yet", revisions: [] });
  });
});

describe("live pose delay", () => {
  const settle = (gap: number) => { let d = 70; for (let i = 0; i < 300; i += 1) d = nextDelay(d, gap); return d; };
  it("stays short when poses arrive at 30 Hz", () => expect(settle(33)).toBeCloseTo(73, 0));
  it("grows when they arrive slowly, so the view doesn't run out", () => expect(settle(100)).toBeCloseTo(220, 0));
  it("isn't fooled by a long pause", () => expect(settle(5000)).toBeLessThanOrEqual(300));
  it("barely moves for a single gap", () => expect(nextDelay(70, 1000)).toBeLessThan(90));
});

describe("the model's run", () => {
  const agent = runs.find((r) => r.id === "sample-agent")!;
  const verdict = (status: Status, n = 1): StepVerdict => ({ step: `s${n}`, target: "c", attempt: n, status, label: null, reason: status, channel: null, decided_by: "rule", evidence: [] });
  const finalState = replayItems(agent).reduce((s, r) => agentReducer(s, r.item), EMPTY_AGENT);

  it("adds up a control's attempts the way verdicts.py does", () => {
    const of = (...s: Status[]) => outcomeOf(s.map((x, i) => verdict(x, i)))?.status;
    expect(of("failed", "failed")).toBe("failed");
    expect(of("failed")).toBe("failed");
    expect(of("failed", "passed")).toBe("intermittent");
    expect(of("passed", "failed")).toBe("intermittent");
    expect(of("failed", "passed", "failed")).toBe("intermittent");
    expect(of("failed", "inconclusive", "failed")).toBe("failed");
    expect(of("inconclusive", "passed")).toBe("passed");
    expect(of("inconclusive", "skipped")).toBe("inconclusive");
    expect(of("observed")).toBe("observed");
    expect(of()).toBeUndefined();
  });

  it("gives a retest its own graph node, so a retried step can't make a cycle", () => {
    const placed = placeNodes(buildGraph(agent, undefined, []));
    expect(placed.filter((n) => n.kind === "step" && n.target === "dial_1").map((n) => n.id)).toEqual(["s4", "s4-2"]);
    expect(recordOfNode(agent, "s4-2")!.trace!.attempt).toBe(2);
  });

  it("previews a turn from deltas until its record arrives, and then only shows the record", () => {
    let s = agentReducer(EMPTY_AGENT, { name: "delta", body: { turn: "turn-1", kind: "thought", text: "Hm" } });
    s = agentReducer(s, { name: "delta", body: { turn: "turn-1", kind: "thought", text: "m." } });
    s = agentReducer(s, { name: "delta", body: { turn: "turn-1", kind: "text", text: "Go" } });
    expect(timelineOf(s)).toMatchObject([{ kind: "turn", streaming: true, thought: "Hmm.", text: "Go" }]);
    expect(stateLine(s).state).toBe("thinking");
    const turn = agent.events.find((e) => e.type === "model_turn")!;
    s = agentReducer(s, { name: "run", body: turn });
    const items = timelineOf(s);
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ kind: "turn", streaming: false, thought: turn.payload.thinking });
    expect(agentReducer(s, { name: "reset" })).toEqual(EMPTY_AGENT);
  });

  it("puts a turn's tool calls inside it, and fills each step with its result", () => {
    const items = timelineOf(finalState);
    const rejected = items.flatMap((i) => (i.kind === "turn" ? i.calls : [])).find((c) => !c.ok)!;
    expect(rejected.tool).toBe("propose_plan");
    const steps = items.filter((i) => i.kind === "step");
    expect(steps.every((i) => i.kind === "step" && !!i.verdict)).toBe(true);
    expect(steps.filter((i) => i.kind === "step" && i.step.id === "s4").map((i) => i.kind === "step" && i.trace?.attempt)).toEqual([1, 2]);
  });

  it("says who it's waiting on, and an open approval beats the last state", () => {
    const upto = (type: string) => agent.events.slice(0, agent.events.findIndex((e) => e.type === type) + 1);
    const asked = agentReducer(EMPTY_AGENT, { name: "meta", body: { run_id: "x", product: "x", stages: [], route: "" } });
    const waiting = { ...asked, events: upto("approval_needed") };
    expect(stateLine(waiting).state).toBe("waiting_person");
    expect(pendingApproval(timelineOf(waiting))?.ref).toBe("plan-1");
    expect(pendingApproval(timelineOf({ ...asked, events: upto("approved") }))).toBeUndefined();
    expect(stateLine(finalState).state).toBe("done");
    expect(stateLine(EMPTY_AGENT).label).toBe("Idle");
  });

  it("closes an approval the run has moved on from, since a refusal logs no event", () => {
    const at = agent.events.findIndex((e) => e.type === "approval_needed");
    const refused = [...agent.events.slice(0, at + 1), { ...agent.events[at], seq: 9000, type: "model_turn" as const, payload: { id: "x", model: "m" } }];
    const items = timelineOf({ events: refused, deltas: {} });
    expect(items.find((i) => i.kind === "approval")).toMatchObject({ state: "closed" });
    expect(pendingApproval(items)).toBeUndefined();
  });

  it("uses the telemetry a run names, and none if it says none", () => {
    const meta = { run_id: "x", product: "x", stages: [], route: "" };
    expect(telemetryOf({ ...meta, telemetry: "http://127.0.0.1:9" })).toBe("http://127.0.0.1:9");
    expect(telemetryOf({ ...meta, telemetry: null })).toBeNull();
    expect(telemetryOf(meta)).toBe(TELEMETRY_URL);
  });

  it("knows the plan as amendments and steering leave it", () => {
    const upto = (n: number) => ({ ...agent, events: agent.events.slice(0, n) });
    const at = agent.events.findIndex((e) => e.type === "plan_amended" && e.payload.level === 1);
    const live = toRun(upto(at + 1).events, agent.report);
    const pending = planRows(live).filter((r) => r.state === "pending").map((r) => r.id);
    expect(pending).toEqual(["s4", "s3", "s5", "s6", "s7"]);
    const run = toRun(agent.events, agent.report);
    expect(planRows(run).filter((r) => r.state === "pending")).toEqual([]);
    const steer = { seq: 9999, t: 0, run_id: "x", type: "steer_applied" as const, payload: { kind: "skip", target: "dial_1", by: "op", note: "" } };
    const skipped = planRows(toRun([...upto(at + 1).events, steer], agent.report));
    expect(skipped.find((r) => r.state === "skipped")?.target).toBe("dial_1");
    expect(skipped.filter((r) => r.state === "pending").map((r) => r.id)).toEqual(["s3", "s5", "s6", "s7"]);
  });

  it("tracks pause and resume from what was applied, not what was asked", () => {
    const steer = (kind: string, seq: number) => ({ seq, t: 0, run_id: "x", type: "steer_applied" as const, payload: { kind } });
    expect(isPaused([])).toBe(false);
    expect(isPaused([steer("pause", 1)])).toBe(true);
    expect(isPaused([steer("pause", 1), steer("resume", 2)])).toBe(false);
  });

  it("shows a turn with no reasoning as just what it did", () => {
    const silent = agent.events.filter((e) => e.type === "model_turn" && !e.payload.thinking);
    expect(silent.length).toBeGreaterThan(1);
    const turns = timelineOf(finalState).filter((i) => i.kind === "turn");
    const toolOnly = turns.find((i) => !i.thought && !i.text);
    expect(toolOnly).toBeTruthy();
    expect(toolOnly!.calls.length).toBeGreaterThan(0);
    for (const t of turns) if (silent.some((e) => e.payload.id === t.id)) expect(t.thought).toBe("");
  });

  it("leaves the harness's own successful calls out of the timeline but not the totals", () => {
    const call = (seq: number, caller: string, ok: boolean) => ({ seq, t: seq, run_id: "r", type: "tool_call" as const, payload: { id: `c${seq}`, tool: "system1.routine_start", args: {}, caller, turn: null, stage: null, ok } });
    const shown = timelineOf({ events: [call(1, "rules", true), call(2, "rules", false), call(3, "model", true)] as never, deltas: {} }).filter((i) => i.kind === "tool");
    expect(shown.map((i) => i.call.seq)).toEqual([2, 3]);
  });

  it("lines a System 1 recording up with the run's events by step", () => {
    const e = (seq: number, type: string, payload: object) => ({ seq, t: seq, run_id: "r", type, payload }) as never;
    const events = [e(1, "model_turn", {}), e(2, "step_started", { id: "s1" }), e(3, "step_finished", {}), e(4, "model_turn", {}), e(5, "step_started", { id: "s1" }), e(6, "step_finished", {})];
    const timeline = { fps: 30, duration: 9, meta: {} as never, stages: [], events: {}, steps: [{ id: "s1", t: 2, end: 3 }, { id: "s1", t: 6, end: 7 }] };
    expect(eventTimes(events, timeline)).toEqual({ 1: 2, 2: 2, 3: 3, 4: 3, 5: 6, 6: 7 });
    expect(eventTimes(events, { ...timeline, events: { 1: 5 } })).toEqual({ 1: 5 });
  });

  it("labels the scripted run as not real", () => {
    expect(evidenceOf(agent)).toBe("mock");
    expect(agent.events.filter((e) => e.type === "model_turn").every((e) => e.payload.model.includes("not a real model"))).toBe(true);
  });
});
