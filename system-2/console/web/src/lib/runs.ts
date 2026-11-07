// Turns a run's events.jsonl into what the screens read. The log is the record: nothing here invents a result.
import type {
  CADPatch, Coverage, Finding, Plan, Report, Reward, RootCause, RunEvent, SceneInventory, Status, Step, StepTrace,
  StepVerdict,
} from "./contracts";

const eventFiles = import.meta.glob("@repo/fixtures/sample_run/*/events.jsonl", {
  query: "?raw", import: "default", eager: true,
}) as Record<string, string>;
const reportFiles = import.meta.glob("@repo/fixtures/sample_run/*/report.json", {
  import: "default", eager: true,
}) as Record<string, Report>;

const timelineFiles = import.meta.glob("@repo/fixtures/sample_run/*/timeline.json", { import: "default", eager: true }) as Record<string, Timeline>;
const replayFiles = import.meta.glob(["@repo/fixtures/sample_run/*/poses.bin", "@repo/fixtures/sample_run/*/cameras.mp4", "@repo/fixtures/sample_run/*/scene/**/*"], { query: "?url", import: "default", eager: true }) as Record<string, string>;

export interface StepRecord {
  step: Step;
  trace?: StepTrace;
  verdict?: StepVerdict;
  startSeq: number;
  endSeq?: number;
}

export interface Approval {
  kind: "plan" | "patch";
  ref: string;
  by: string;
  seq: number;
}

export interface Timeline {
  fps: number;
  duration: number;
  meta: { run_id: string; product: string; stages: string[]; route: string };
  stages: { name: string; t: number }[];
  events: Record<string, number>; // event seq -> seconds into the video
  lcd?: { t: number; lines: string[] }[]; // what the device's display showed, from each time on
}

export interface Run {
  recording?: { video?: string; assets?: (path: string) => string; timeline: Timeline }; // assets: a replay in 3D. video: an older recording
  id: string;
  requestId: string;
  product: string;
  revision: string;
  instruction: string;
  manual: string | null;
  events: RunEvent[];
  report: Report;
  scene: SceneInventory;
  plan: Plan;
  steps: StepRecord[];
  findings: (Finding & { seq: number })[];
  causes: (RootCause & { seq: number })[];
  proposed: (CADPatch & { seq: number })[];
  applied: (CADPatch & { seq: number })[];
  approvals: Approval[];
  messages: { role: string; text: string; seq: number }[];
  status: string;
}

export function parseEvents(raw: string): RunEvent[] {
  return raw.split("\n").filter((line) => line.trim()).map((line) => JSON.parse(line) as RunEvent);
}

export function toRun(events: RunEvent[], report: Report): Run {
  const run: Run = {
    id: report.run_id, requestId: "", product: report.product, revision: report.revision, instruction: "", manual: null,
    events, report, scene: { frame: "arm_base", controls: [], unmatched_manual_controls: [], notes: [] },
    plan: { plan_id: "", steps: [], source: "rules" }, steps: [], findings: [], causes: [], proposed: [], applied: [],
    approvals: [], messages: [], status: "unknown",
  };
  for (const e of events) {
    const p = e.payload;
    if (e.type === "run_started") {
      run.requestId = p.request_id;
      run.instruction = p.instruction;
      run.manual = p.manual?.file ?? null;
    } else if (e.type === "scene_ready") run.scene = p;
    else if (e.type === "plan_ready") run.plan = p;
    else if (e.type === "approved") run.approvals.push({ kind: p.kind, ref: p.ref, by: p.by, seq: e.seq });
    else if (e.type === "step_started") run.steps.push({ step: p, startSeq: e.seq });
    else if (e.type === "step_finished") {
      const record = run.steps.find((s) => s.step.id === p.trace.step && s.endSeq === undefined);
      if (record) Object.assign(record, { trace: p.trace, verdict: p.verdict, endSeq: e.seq });
    } else if (e.type === "finding") run.findings.push({ ...p, seq: e.seq });
    else if (e.type === "root_cause") run.causes.push({ ...p, seq: e.seq });
    else if (e.type === "patch_proposed") run.proposed.push({ ...p, seq: e.seq });
    else if (e.type === "patch_applied") run.applied.push({ ...p, seq: e.seq });
    else if (e.type === "message") run.messages.push({ role: p.role, text: p.text, seq: e.seq });
    else if (e.type === "run_finished") run.status = p.status;
  }
  return run;
}

export function fixtureRuns(): Run[] {
  const runs: Run[] = [];
  for (const [file, raw] of Object.entries(eventFiles)) {
    const report = reportFiles[file.replace("events.jsonl", "report.json")];
    if (!report) continue;
    const run = toRun(parseEvents(raw), report);
    const folder = file.replace("events.jsonl", ""), timeline = timelineFiles[`${folder}timeline.json`];
    if (timeline) run.recording = { timeline, assets: (path) => replayFiles[folder + path] };
    runs.push(run);
  }
  return runs.sort((a, b) => a.id.localeCompare(b.id));
}

// The same rules as system-2/harness/src/rav_harness/reward.py. tests check them against report.json.
const RANK: Record<Status, number> = { failed: 4, inconclusive: 3, skipped: 2, passed: 1, observed: 0 };

export function coverageOf(run: Run, uptoSeq = Infinity): Coverage {
  const worst = new Map<string, StepVerdict>();
  for (const s of run.steps) {
    if (!s.verdict || (s.endSeq ?? Infinity) > uptoSeq) continue;
    const current = worst.get(s.verdict.target);
    if (!current || RANK[s.verdict.status] > RANK[current.status]) worst.set(s.verdict.target, s.verdict);
  }
  const cov: Coverage = { detected: run.scene.controls.length, passed: [], failed: [], observed: [], inconclusive: [], skipped: {} };
  for (const c of run.scene.controls) {
    const v = worst.get(c.id);
    if (!v) cov.skipped[c.id] = "no test ran";
    else if (v.status === "skipped") cov.skipped[c.id] = v.reason;
    else cov[v.status].push(c.id);
  }
  return cov;
}

export function rewardOf(cov: Coverage): Omit<Reward, "formula"> {
  const covered = cov.passed.length + cov.failed.length + cov.observed.length;
  const judged = cov.passed.length + cov.failed.length;
  const control_coverage = cov.detected ? covered / cov.detected : 0;
  const pass_rate = judged ? cov.passed.length / judged : 0;
  const round = (n: number) => Math.round(n * 10000) / 10000;
  return { value: round(control_coverage * pass_rate), control_coverage: round(control_coverage), pass_rate: round(pass_rate) };
}

export function statusOfControl(cov: Coverage, id: string): Status | "pending" {
  if (cov.passed.includes(id)) return "passed";
  if (cov.failed.includes(id)) return "failed";
  if (cov.observed.includes(id)) return "observed";
  if (cov.inconclusive.includes(id)) return "inconclusive";
  return "pending";
}

export function nextRevision(runs: Run[], run: Run): Run | undefined {
  const later = run.applied[0]?.revision_to;
  return later ? runs.find((r) => r.requestId === run.requestId && r.revision === later) : undefined;
}

export function describeEvent(e: RunEvent): string {
  const p = e.payload;
  switch (e.type) {
    case "run_started": return `Run started on ${p.product}, Rev ${p.revision}`;
    case "scene_ready": return `Scene ready: ${p.controls.length} controls found`;
    case "plan_ready": return `Plan ${p.plan_id} ready: ${p.steps.length} steps, source ${p.source}`;
    case "approval_needed": return `Approval needed for ${p.kind} ${p.ref}`;
    case "approved": return `${p.kind === "plan" ? "Plan" : "Patch"} approved by ${p.by}`;
    case "step_started": return `${p.id} started: ${p.skill} on ${p.target}`;
    case "step_finished": return `${p.trace.step} ${p.verdict.status}: ${p.verdict.reason}`;
    case "finding": return `Finding ${p.id} (${p.severity}): ${p.what_happened}`;
    case "root_cause": return `Root cause for ${p.finding}: ${p.root_cause}`;
    case "patch_proposed": return `Patch proposed: ${p.changes.map((c: { param: string }) => c.param).join(", ")}`;
    case "patch_applied": return `Patch applied: ${p.changes.map((c: { param: string }) => c.param).join(", ")}`;
    case "steer_applied": return `Steering applied: ${p.kind}. ${p.note ?? ""}`;
    case "message": return `${p.role}: ${p.text}`;
    case "report_ready": return `Report ready: ${p.summary}`;
    case "run_finished": return `Run finished: ${p.status}`;
    case "model_turn": return `${p.model}: ${p.error ?? p.text ?? p.stop_reason ?? "a turn"}`;
    case "crossing": return `System 1 stopped: ${p.code ?? p.stop}${p.target ? ` on ${p.target}` : ""}`;
    case "plan_amended": return `Plan amended, level ${p.level}${p.by ? `, approved by ${p.by}` : ""}`;
    case "tool_call": return `${p.tool} ${p.ok ? "ok" : `failed: ${p.error}`}`;
  }
}
