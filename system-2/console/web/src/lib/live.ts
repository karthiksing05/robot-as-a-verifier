// A real sim run, as it happens, from system-2/console/server/live_sim.py. Events are the same contract as a saved run;
// telemetry (stage, cameras, force) is only for this screen. Nothing here decides or invents a result.
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { RunEvent, Report, Step } from "./contracts";
import type { GraphNode } from "./graph";
import { toRun, type Run } from "./runs";

export const LIVE_URL = "http://127.0.0.1:8765";

export interface Telemetry {
  wall: number;
  sim_t: number;
  stage: string;
  status: string;
  rate: number;
  feeds: string[];
  force: [number, number][];
  paused: boolean;
  step: string | null;
  substage: string | null;
  lcd?: string[];
  probe_n?: number;
}

export interface LiveMeta {
  run_id: string;
  product: string;
  stages: string[];
  route: string;
}

export interface LiveState {
  meta: LiveMeta | null;
  events: RunEvent[];
  tel: Telemetry | null;
  force: [number, number][];
}

export const EMPTY_LIVE: LiveState = { meta: null, events: [], tel: null, force: [] };
const FORCE_KEPT = 500;

export type LiveItem = { name: "reset" } | { name: "meta"; body: LiveMeta } | { name: "run"; body: RunEvent } | { name: "telemetry"; body: Telemetry };

export function liveReducer(state: LiveState, item: LiveItem): LiveState {
  switch (item.name) {
    case "reset": return EMPTY_LIVE;
    case "meta": return { ...state, meta: item.body };
    case "run": return { ...state, events: [...state.events, item.body] };
    case "telemetry": return { ...state, tel: item.body, force: item.body.force.length ? [...state.force, ...item.body.force].slice(-FORCE_KEPT) : state.force };
  }
}

const STUB_REPORT = (id: string, product: string): Report => ({
  run_id: id, product, revision: "A", summary: "", findings: [],
  coverage: { detected: 0, passed: [], failed: [], observed: [], inconclusive: [], skipped: {} },
  reward: { value: 0, control_coverage: 0, pass_rate: 0, formula: "" },
});

/** The events so far as a Run, so live coverage uses the same rules as every saved run. */
export const liveRun = (state: LiveState): Run => {
  const run = toRun(state.events, STUB_REPORT(state.meta?.run_id ?? "", state.meta?.product ?? ""));
  const report = state.events.find((e) => e.type === "report_ready")?.payload as Report | undefined;
  return report ? { ...run, report } : run;
};

const GLYPH: Record<string, string> = { passed: "✓", failed: "✕", observed: "◐", skipped: "⊘", inconclusive: "?" };

/** What's still to run, in order: the plan, as steering has changed it, minus what has started. */
export function stepQueue(events: RunEvent[]): { queue: Step[]; skipped: { step: Step; after: string; by: string; reason: string }[]; moved: Set<string> } {
  let plan: Step[] = [];
  const started = new Set<string>();
  let order: string[] | null = null;
  let last = "approve";
  const skipped: { step: Step; after: string; by: string; reason: string }[] = [];
  const moved = new Set<string>();
  for (const e of events) {
    if (e.type === "plan_ready") plan = e.payload.steps;
    else if (e.type === "step_started") { started.add(e.payload.id); last = e.payload.id; }
    else if (e.type === "steer_applied" && e.payload.queue) {
      const left = plan.filter((s) => !started.has(s.id) && !skipped.some((x) => x.step.id === s.id));
      const kept = new Set<string>(e.payload.queue);
      if (e.payload.kind === "skip") {
        for (const s of left) if (!kept.has(s.id)) skipped.push({ step: s, after: last, by: e.payload.by, reason: e.payload.text ?? "" });
      }
      if (e.payload.kind === "prioritize") for (const s of left) if (s.target === e.payload.target) moved.add(s.id);
      order = e.payload.queue;
    }
  }
  const remaining = plan.filter((s) => !started.has(s.id) && !skipped.some((x) => x.step.id === s.id));
  if (order) {
    const rank = new Map(order.map((id, i) => [id, i]));
    remaining.sort((a, b) => (rank.get(a.id) ?? 999) - (rank.get(b.id) ?? 999));
  }
  return { queue: remaining, skipped, moved };
}

/** The flowchart: the stages, then every step, solid once it's happened and dashed until then. */
export function liveNodes(state: LiveState): GraphNode[] {
  const { meta, events, tel } = state;
  if (!meta) return [];
  const run = liveRun(state);
  const finished = events.some((e) => e.type === "run_finished");
  const stopped = events.find((e) => e.type === "run_finished")?.payload.status !== "completed" && finished;
  const stages = meta.stages;
  const test = stages.indexOf("TEST");
  const current = tel && stages.includes(tel.stage) ? stages.indexOf(tel.stage) : -1;
  const nodes: GraphNode[] = [];
  const planned = events.some((e) => e.type === "plan_ready");
  const approved = run.approvals.find((a) => a.kind === "plan");
  const waiting = planned && !approved;
  const stageState = (i: number): { status?: GraphNode["status"]; provenance: GraphNode["provenance"] } => {
    if (finished && (i <= current)) return { provenance: "log" };
    if (i < current) return { provenance: "log" };
    if (i === current && !finished) return { status: "running", provenance: "log" };
    return { status: "pending", provenance: "plan" };
  };
  const stage = (i: number, parents: string[]) => {
    const name = stages[i];
    const sub = name === "PLAN" && planned ? `${run.plan.steps.length} steps` : name === "MAP" && run.scene.controls.length ? `${run.scene.controls.length} controls` : i === current && tel?.substage && tel.substage !== "done" ? tel.substage : "";
    nodes.push({ id: `stage-${name}`, kind: "input", title: name[0] + name.slice(1).toLowerCase(), sub, parents, flags: [], ...stageState(i) });
    return `stage-${name}`;
  };
  let previous: string[] = [];
  for (let i = 0; i < test; i += 1) previous = [stage(i, previous)];

  // Testing grows out of the plan: first an approval, then the steps.
  if (!planned) {
    nodes.push({ id: "stage-TEST", kind: "step", title: "Test", sub: "waiting for a plan", parents: previous, flags: [], status: "pending", provenance: "plan" });
    previous = ["stage-TEST"];
  } else {
    nodes.push({ id: "approve", kind: "plan", title: approved ? "Approved" : "Approve plan", sub: approved ? `by ${approved.by}` : "needs a person", parents: previous, flags: [], status: waiting && !finished ? "running" : approved ? undefined : "pending", provenance: approved ? "log" : "plan" });
    previous = ["approve"];
    const { queue, skipped, moved } = stepQueue(events);
    for (const s of run.steps) {
      const status = s.verdict?.status;
      nodes.push({ id: s.step.id, kind: "step", title: `${s.step.id}${status ? ` ${GLYPH[status]}` : ""}`, sub: s.step.target, parents: previous, flags: moved.has(s.step.id) ? ["prioritized"] : [], status: status ?? (finished ? "inconclusive" : "running"), provenance: "log", seq: s.endSeq ?? s.startSeq, target: s.step.target });
      previous = [s.step.id];
    }
    for (const s of queue) {
      nodes.push({ id: s.id, kind: "step", title: s.id, sub: s.target, parents: previous, flags: moved.has(s.id) ? ["prioritized"] : [], status: "pending", provenance: "plan", target: s.target });
      previous = [s.id];
    }
    for (const x of skipped) nodes.push({ id: x.step.id, kind: "branch", title: `${x.step.id} ⊘`, sub: `${x.step.target}, skipped`, parents: [x.after], flags: [], status: "skipped", provenance: "edit", target: x.step.target, reason: x.reason, by: x.by });
    for (const f of run.findings) nodes.push({ id: f.id, kind: "finding", title: f.id, sub: f.label, parents: [f.step_ids[0]], flags: [], status: "failed", provenance: "log", seq: f.seq, target: f.target });
  }
  for (let i = test + 1; i < stages.length; i += 1) previous = [stage(i, previous)];
  if (stopped) for (const n of nodes) if (n.status === "pending") n.sub = "didn't run";
  return nodes;
}

/** Where the flowchart should be looking right now. */
export function liveFocus(nodes: GraphNode[]): string | null {
  return nodes.filter((n) => n.status === "running").at(-1)?.id ?? [...nodes].reverse().find((n) => n.provenance === "log")?.id ?? null;
}

/** The flowchart for a run that's over, from its saved log. */
export function recordedNodes(run: Run): GraphNode[] {
  const t = run.recording!.timeline;
  const stage = t.stages.at(-1)?.name ?? "";
  return liveNodes({ meta: t.meta, events: run.events, force: [], tel: { wall: 0, sim_t: 0, stage, status: "", rate: 1, feeds: [], force: [], paused: false, step: null, substage: null } });
}

/** When each node starts in a run's video, in order. */
export function videoMarks(run: Run): { id: string; t: number }[] {
  const t = run.recording!.timeline;
  const at = (seq?: number) => (seq === undefined ? undefined : t.events[String(seq)]);
  const marks = t.stages.filter((s) => t.meta.stages.includes(s.name) && s.name !== "TEST").map((s) => ({ id: `stage-${s.name}`, t: s.t }));
  const approved = run.approvals.find((a) => a.kind === "plan");
  if (approved) marks.push({ id: "approve", t: at(approved.seq) ?? 0 });
  for (const s of run.steps) marks.push({ id: s.step.id, t: at(s.startSeq) ?? 0 });
  return marks.sort((a, b) => a.t - b.t);
}

export function markAt(marks: { id: string; t: number }[], now: number): string | null {
  return [...marks].reverse().find((m) => m.t <= now + 0.02)?.id ?? marks[0]?.id ?? null;
}

export async function liveCommand(path: string, body: object): Promise<string | null> {
  try {
    const res = await fetch(`${LIVE_URL}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (res.ok) return null;
    const reply = await res.json().catch(() => ({}));
    return reply.error ?? `The bridge answered ${res.status}.`;
  } catch {
    return "The bridge isn't reachable.";
  }
}

export interface LiveNow { running: boolean; project: string | null }
const IDLE: LiveNow = { running: false, project: null };
let liveNow = IDLE;
let nowTimer = 0;
const nowWatchers = new Set<() => void>();

async function pollNow() {
  let next = IDLE, wait = 15000; // no bridge is the usual case on a laptop, so ask rarely
  try {
    const health = await (await fetch(`${LIVE_URL}/health`)).json();
    next = { running: !!health.running, project: health.project ?? null };
    wait = 3000;
  } catch {
    // the bridge isn't running, so neither is a run
  }
  if (next.running !== liveNow.running || next.project !== liveNow.project) {
    liveNow = next;
    nowWatchers.forEach((fn) => fn());
  }
  window.clearTimeout(nowTimer);
  if (nowWatchers.size) nowTimer = window.setTimeout(() => void pollNow(), wait);
}

/** Whether a run is going, and for which project, for screens other than Live. */
export function useLiveNow() {
  return useSyncExternalStore((fn) => {
    nowWatchers.add(fn);
    if (nowWatchers.size === 1) void pollNow();
    return () => {
      nowWatchers.delete(fn);
      if (!nowWatchers.size) window.clearTimeout(nowTimer);
    };
  }, () => liveNow);
}

/** Follows the bridge's stream while the screen is open, and reconnects by itself if the bridge restarts. */
export function useLive() {
  const [state, setState] = useState<LiveState>(EMPTY_LIVE);
  const [connected, setConnected] = useState(false);
  const lastTelemetry = useRef(0);
  const pending = useRef<LiveItem[]>([]);
  useEffect(() => {
    let timer = 0;
    const flush = () => {
      timer = 0;
      const items = pending.current;
      pending.current = [];
      setState((s) => items.reduce(liveReducer, s));
    };
    const push = (item: LiveItem) => {
      pending.current.push(item);
      if (!timer) timer = window.setTimeout(flush, 50); // batched: a page opening mid-run gets the history at once
    };
    const source = new EventSource(`${LIVE_URL}/stream`);
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.addEventListener("reset", () => push({ name: "reset" }));
    source.addEventListener("meta", (e) => push({ name: "meta", body: JSON.parse((e as MessageEvent).data) }));
    source.addEventListener("run", (e) => push({ name: "run", body: JSON.parse((e as MessageEvent).data) }));
    source.addEventListener("telemetry", (e) => { lastTelemetry.current = performance.now(); push({ name: "telemetry", body: JSON.parse((e as MessageEvent).data) }); });
    return () => {
      source.close();
      window.clearTimeout(timer);
    };
  }, []);
  const nodes = useMemo(() => liveNodes(state), [state.meta, state.events, state.tel?.stage, state.tel?.substage]); // eslint-disable-line react-hooks/exhaustive-deps
  return { state, connected, nodes, lastTelemetry };
}
