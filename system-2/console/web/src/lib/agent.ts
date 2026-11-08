// The model's run, as it happens or from its log: rav-agent's stream, or a saved run played back through the same reducer.
// Everything shown comes from the run's events. Deltas only preview a turn until its model_turn event arrives.
import { useEffect, useMemo, useRef, useState } from "react";
import type { Finding, Plan, RunEvent, SceneInventory, Status, Step, StepTrace, StepVerdict } from "./contracts";
import { AGENT_URL, EMPTY_LIVE, TELEMETRY_URL, liveReducer, liveRun, type LiveItem, type LiveMeta, type LiveState, type Telemetry } from "./live";
import type { Project } from "./projects";
import type { Run } from "./runs";
import type { ModelTurn, ToolCall } from "./trace";

export interface AgentHealth { up: boolean; running: boolean; project: string | null; run_id: string | null; model: string | null; models: string[] }
const DOWN: AgentHealth = { up: false, running: false, project: null, run_id: null, model: null, models: [] };

export interface Delta { turn: string; kind: "thought" | "text"; text: string }
export interface AgentState extends LiveState { deltas: Record<string, { thought: string; text: string }> }
export type AgentItem = LiveItem | { name: "delta"; body: Delta };
export const EMPTY_AGENT: AgentState = { ...EMPTY_LIVE, deltas: {} };

export function agentReducer(state: AgentState, item: AgentItem): AgentState {
  if (item.name === "delta") {
    const { turn, kind, text } = item.body, now = state.deltas[turn] ?? { thought: "", text: "" };
    return { ...state, deltas: { ...state.deltas, [turn]: { ...now, [kind]: now[kind] + text } } };
  }
  if (item.name === "reset") return EMPTY_AGENT;
  const next = { ...state, ...liveReducer(state, item) };
  return item.name === "run" && item.body.type === "model_turn" ? { ...next, deltas: {} } : next; // the record replaces the preview
}

// --- the timeline ---------------------------------------------------------------------------------------------------

export type TimelineItem =
  | { kind: "turn"; key: string; turn: ModelTurn | null; id: string; thought: string; text: string; streaming: boolean; calls: ToolCall[] }
  | { kind: "tool"; key: string; call: ToolCall }
  | { kind: "stop"; key: string; stop: string; code: string | null; target: string | null; routine: string; verdicts: number }
  | { kind: "step"; key: string; step: Step; verdict?: StepVerdict; trace?: StepTrace }
  | { kind: "approval"; key: string; what: string; ref: string; by: string | null; state: "pending" | "approved" | "closed" }
  | { kind: "plan"; key: string; plan: Plan }
  | { kind: "amended"; key: string; level: number; by: string | null; steps: string[]; why: string }
  | { kind: "message"; key: string; role: string; text: string; by: string | null; asks: boolean }
  | { kind: "check"; key: string; target: string; counted: boolean; why: string; failed: { metric: string; op: string; value: unknown; actual: unknown }[] }
  | { kind: "steer"; key: string; steer: string; note: string; by: string | null; target: string | null }
  | { kind: "scene"; key: string; scene: SceneInventory }
  | { kind: "finding"; key: string; finding: Finding }
  | { kind: "report"; key: string; summary: string }
  | { kind: "end"; key: string; status: string };

export function timelineOf(state: Pick<AgentState, "events" | "deltas">): TimelineItem[] {
  const items: TimelineItem[] = [];
  const finished = state.events.some((e) => e.type === "run_finished");
  const turns = new Map<string, Extract<TimelineItem, { kind: "turn" }>>();
  for (const e of state.events) {
    const p = e.payload, key = String(e.seq);
    switch (e.type) {
      case "model_turn": {
        const item = { kind: "turn" as const, key, turn: { ...p, kind: "turn", seq: e.seq } as ModelTurn, id: p.id as string, thought: p.thinking ?? "", text: p.text ?? "", streaming: false, calls: [] };
        turns.set(p.id, item);
        items.push(item);
        break;
      }
      case "tool_call": {
        const call = { ...p, kind: "tool", seq: e.seq } as ToolCall, parent = call.turn ? turns.get(call.turn) : undefined;
        if (call.caller === "rules" && call.ok) break; // the harness's own calls under the model's tool; run totals still count them
        if (parent) parent.calls.push(call);
        else items.push({ kind: "tool", key, call });
        break;
      }
      case "crossing": items.push({ kind: "stop", key, stop: p.stop, code: p.code ?? null, target: p.target ?? null, routine: p.routine, verdicts: p.verdicts ?? 0 }); break;
      case "step_started": items.push({ kind: "step", key, step: p }); break;
      case "step_finished": {
        const open = items.findLast((i): i is Extract<TimelineItem, { kind: "step" }> => i.kind === "step" && i.step.id === p.trace.step && !i.verdict);
        if (open) Object.assign(open, { verdict: p.verdict, trace: p.trace });
        break;
      }
      case "approval_needed": items.push({ kind: "approval", key, what: p.kind, ref: p.ref, by: null, state: finished ? "closed" : "pending" }); break;
      case "approved": {
        const open = items.findLast((i): i is Extract<TimelineItem, { kind: "approval" }> => i.kind === "approval" && i.ref === p.ref && !i.by);
        if (open) Object.assign(open, { by: p.by, state: "approved" });
        break;
      }
      case "plan_ready": items.push({ kind: "plan", key, plan: p }); break;
      case "plan_amended": items.push({ kind: "amended", key, level: p.level, by: p.by ?? null, steps: p.steps ?? [], why: p.why ?? "" }); break;
      case "message": items.push({ kind: "message", key, role: p.role, text: p.text, by: p.by ?? null, asks: !!p.asks }); break;
      case "check_judged": items.push({ kind: "check", key, target: p.target, counted: !!p.counted, why: p.why ?? "", failed: p.failed ?? [] }); break;
      case "steer_applied": if (p.kind !== "message") items.push({ kind: "steer", key, steer: p.kind, note: p.note ?? "", by: p.by ?? null, target: p.target ?? null }); break;
      case "scene_ready": items.push({ kind: "scene", key, scene: p }); break;
      case "finding": items.push({ kind: "finding", key, finding: p }); break;
      case "report_ready": items.push({ kind: "report", key, summary: p.summary }); break;
      case "run_finished": items.push({ kind: "end", key, status: p.status }); break;
    }
  }
  // A refusal logs no event of its own, so an approval is over once the run has moved on from it.
  for (const item of items) {
    if (item.kind !== "approval" || item.state !== "pending") continue;
    const seq = Number(item.key);
    if (state.events.some((e) => e.seq > seq && (e.type === "model_turn" || e.type === "tool_call" || e.type === "step_started"))) item.state = "closed";
  }
  for (const [id, d] of Object.entries(state.deltas)) items.push({ kind: "turn", key: `live-${id}`, turn: null, id, thought: d.thought, text: d.text, streaming: true, calls: [] });
  return items;
}

export const pendingApproval = (items: TimelineItem[]) => items.findLast((i): i is Extract<TimelineItem, { kind: "approval" }> => i.kind === "approval" && i.state === "pending");

const STATE_LABEL: Record<string, string> = { thinking: "Thinking", calling: "Calling a tool", arm: "Waiting on the arm", waiting_person: "Waiting on you", idle: "Idle", done: "Done" };

/** What's happening now. An open approval or a finished run says so whatever the last agent_state was. */
export function stateLine(state: Pick<AgentState, "events" | "deltas" | "meta">): { state: string; label: string; detail: string } {
  const items = timelineOf(state);
  const end = items.findLast((i) => i.kind === "end");
  if (end?.kind === "end") return { state: "done", label: STATE_LABEL.done, detail: end.status === "completed" ? "" : end.status };
  if (pendingApproval(items)) return { state: "waiting_person", label: STATE_LABEL.waiting_person, detail: "" };
  if (Object.keys(state.deltas).length) return { state: "thinking", label: STATE_LABEL.thinking, detail: "" };
  const last = state.events.findLast((e) => e.type === "agent_state")?.payload;
  if (!last) return { state: "idle", label: state.meta || state.events.length ? "Starting" : STATE_LABEL.idle, detail: "" };
  return { state: last.state, label: STATE_LABEL[last.state] ?? last.state, detail: last.detail ?? "" };
}

export const isPaused = (events: RunEvent[]) => events.findLast((e) => e.type === "steer_applied" && (e.payload.kind === "pause" || e.payload.kind === "resume"))?.payload.kind === "pause";

// --- the plan --------------------------------------------------------------------------------------------------------

export interface PlanRow { id: string; target: string | null; skill: string | null; quote: string | null; state: Status | "running" | "pending" | "skipped"; key: string; seq?: number }

/** Everything run so far, then what's still to come as the latest plan, amendments and steering leave it. */
export function planRows(run: Run): PlanRow[] {
  const rows: PlanRow[] = run.steps.map((s) => ({ id: s.step.id, target: s.step.target, skill: s.step.skill, quote: s.step.quote ?? null, state: s.verdict?.status ?? "running", key: `run-${s.startSeq}`, seq: s.startSeq }));
  const known = new Map<string, Step>();
  let queue: Step[] = [];
  const skipped: Step[] = [];
  const started = new Set<string>();
  for (const e of run.events) {
    const p = e.payload;
    if (e.type === "plan_ready") {
      for (const s of p.steps as Step[]) known.set(s.id, s);
      queue = (p.steps as Step[]).filter((s) => !started.has(s.id));
    } else if (e.type === "step_started") {
      started.add(p.id);
      known.set(p.id, p);
      queue = queue.filter((s) => s.id !== p.id);
    } else if (e.type === "plan_amended") {
      queue = (p.steps as string[]).map((id) => known.get(id) ?? { id, skill: "", target: "", params: {}, quote: null, expected: null, why: null });
    } else if (e.type === "steer_applied" && p.target) {
      const mine = queue.filter((s) => s.target === p.target), rest = queue.filter((s) => s.target !== p.target);
      if (p.kind === "skip") { skipped.push(...mine); queue = rest; }
      if (p.kind === "prioritize") queue = [...mine, ...rest];
    }
  }
  const later = (s: Step, state: PlanRow["state"]): PlanRow => ({ id: s.id, target: s.target || null, skill: s.skill || null, quote: s.quote ?? null, state, key: `${state}-${s.id}` });
  return [...rows, ...queue.map((s) => later(s, "pending")), ...skipped.map((s) => later(s, "skipped"))];
}

// --- replay ----------------------------------------------------------------------------------------------------------

export interface ReplayItem { wait: number; item: AgentItem }
const CHUNKS = 14;

function pieces(text: string): string[] {
  const size = Math.max(1, Math.ceil(text.length / CHUNKS));
  return Array.from({ length: Math.ceil(text.length / size) }, (_, i) => text.slice(i * size, (i + 1) * size));
}

/** A saved run as the stream it would have been. Long pauses are shortened, and a turn's text is shown as it was written. */
export function replayItems(run: Run): ReplayItem[] {
  const meta: LiveMeta = { run_id: run.id, product: run.product, stages: [], route: "" };
  const items: ReplayItem[] = [{ wait: 0, item: { name: "meta", body: meta } }];
  let before = run.events[0]?.t ?? 0;
  for (const e of run.events) {
    const wait = Math.min(900, Math.max(80, (e.t - before) * 1000));
    before = e.t;
    if (e.type === "model_turn" && (e.payload.thinking || e.payload.text)) {
      const parts = [...pieces(e.payload.thinking ?? "").map((text) => ({ kind: "thought" as const, text })), ...pieces(e.payload.text ?? "").map((text) => ({ kind: "text" as const, text }))];
      for (const { kind, text } of parts) items.push({ wait: 45, item: { name: "delta", body: { turn: e.payload.id, kind, text } } });
      items.push({ wait: 120, item: { name: "run", body: e } });
    } else items.push({ wait, item: { name: "run", body: e } });
  }
  return items;
}

export function useReplay(run: Run | undefined) {
  const items = useMemo(() => (run ? replayItems(run) : []), [run]);
  const [at, setAt] = useState(items.length ? 1 : 0);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  useEffect(() => { setAt(items.length ? 1 : 0); setPlaying(true); }, [items]);
  useEffect(() => {
    if (!playing || at >= items.length) return;
    const timer = window.setTimeout(() => setAt((n) => n + 1), items[at].wait / speed);
    return () => window.clearTimeout(timer);
  }, [playing, at, items, speed]);
  const state = useMemo(() => items.slice(0, at).reduce((s, r) => agentReducer(s, r.item), EMPTY_AGENT), [items, at]);
  return { state, at, total: items.length, playing, speed, setSpeed, setPlaying, seek: setAt };
}

// --- starting a run ------------------------------------------------------------------------------------------------

export const MAX_TURNS = 80; // rav-agent's own limit: a run can ask for fewer

/** What /start gets from the form. A device file's faults are its revision's, so it never takes a planted fault. */
export function startBody(project: Project | undefined, form: {
  seed: string; fault: string; rev: string; effector: string; placement: string; route: string; model: string; speed: string;
  maxTurns: string; errorRate: string; errorSeed: string; auto: boolean;
}) {
  const sim = project?.sim;
  const where = sim?.path ? { path: sim.path, rev: form.rev || null, effector: form.effector || "stock" }
    : project ? (sim?.seed != null ? { seed: sim.seed } : { preset: "C" }) : { seed: Number(form.seed) };
  return {
    project: project?.id ?? null, device: { ...where, fault: sim?.path ? null : form.fault.trim() || null, placement: form.placement, route: form.route },
    model: form.model || null, speed: Number(form.speed), max_turns: form.maxTurns.trim() ? Number(form.maxTurns) : null,
    error_rate: Number(form.errorRate) / 100, error_seed: form.errorSeed.trim() ? Number(form.errorSeed) : null, auto_approve: form.auto,
  };
}

/** A device file's revisions: Rev A, its fixes, and the mixed ones that unmask a fault. */
export const revisionsOf = (project: Project | undefined) => (project?.sim?.path ? project.sim.revs ?? ["A", "B"] : []);

// --- the live connection ---------------------------------------------------------------------------------------------

export function useAgentHealth(): AgentHealth {
  const [health, setHealth] = useState(DOWN);
  useEffect(() => {
    let timer = 0, gone = false;
    const ask = async () => {
      let next = DOWN;
      try {
        const h = await (await fetch(`${AGENT_URL}/health`)).json();
        next = { up: !!h.ok, running: !!h.running, project: h.project ?? null, run_id: h.run_id ?? null, model: h.model ?? null, models: h.models ?? [] };
      } catch {
        // rav-agent isn't running
      }
      if (gone) return;
      setHealth((was) => (JSON.stringify(was) === JSON.stringify(next) ? was : next));
      timer = window.setTimeout(() => void ask(), next.up ? 3000 : 6000);
    };
    void ask();
    return () => { gone = true; window.clearTimeout(timer); };
  }, []);
  return health;
}

/** Follows rav-agent's events and System 1's telemetry, and reconnects by itself if either restarts. */
export function useAgentStream(enabled: boolean) {
  const [state, setState] = useState(EMPTY_AGENT);
  const pending = useRef<AgentItem[]>([]);
  useEffect(() => {
    if (!enabled) return;
    let timer = 0;
    const flush = () => {
      timer = 0;
      const items = pending.current;
      pending.current = [];
      setState((s) => items.reduce(agentReducer, s));
    };
    const push = (item: AgentItem) => {
      pending.current.push(item);
      if (!timer) timer = window.setTimeout(flush, 50); // batched: a page opening mid-run gets the history at once
    };
    const data = (e: Event) => JSON.parse((e as MessageEvent).data);
    const events = new EventSource(`${AGENT_URL}/events`);
    events.addEventListener("reset", () => push({ name: "reset" }));
    events.addEventListener("meta", (e) => push({ name: "meta", body: data(e) as LiveMeta }));
    events.addEventListener("run", (e) => push({ name: "run", body: data(e) as RunEvent }));
    events.addEventListener("delta", (e) => push({ name: "delta", body: data(e) as Delta }));
    return () => {
      events.close();
      window.clearTimeout(timer);
    };
  }, [enabled]);
  const telemetryUrl = telemetryOf(state.meta);
  useEffect(() => {
    if (!enabled || !state.meta || !telemetryUrl) return;
    const telemetry = new EventSource(`${telemetryUrl}/telemetry`);
    telemetry.addEventListener("telemetry", (e) => setState((s) => agentReducer(s, { name: "telemetry", body: JSON.parse((e as MessageEvent).data) as Telemetry })));
    return () => telemetry.close();
  }, [enabled, !state.meta, telemetryUrl]); // eslint-disable-line react-hooks/exhaustive-deps
  return state;
}

/** Each run's System 1 gets its own ports, and rav-agent says which. null: this run has no telemetry. */
export const telemetryOf = (meta: LiveMeta | null): string | null => (meta?.telemetry === undefined ? TELEMETRY_URL : meta.telemetry);

export const runOf = (state: AgentState): Run => liveRun(state);
