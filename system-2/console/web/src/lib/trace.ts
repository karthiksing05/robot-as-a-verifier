import type { Run } from "./runs";

export type Layer = "model" | "pipeline" | "robot" | "device";
export const LAYERS: Layer[] = ["model", "pipeline", "robot", "device"];
export const LAYER_NAME: Record<Layer, string> = { model: "Model", pipeline: "Pipeline", robot: "Robot", device: "Device" };

export interface ModelTurn {
  kind: "turn"; seq: number; id: string; model: string; stage: string | null; step: string | null; input: string | null; thinking: string | null;
  text: string | null; stop_reason: string | null; tokens_in: number | null; tokens_out: number | null; latency_ms: number | null;
  claims: Record<string, string>; error: string | null; error_kind: string | null; layer: "model" | "pipeline" | null; raw: string | null;
}
export interface ToolCall {
  kind: "tool"; seq: number; id: string; tool: string; args: Record<string, unknown>; caller: "model" | "rules" | "operator"; turn: string | null; stage: string | null;
  step: string | null; ok: boolean; result: Record<string, unknown> | null; error: string | null; error_kind: string | null; layer: "model" | "pipeline" | null; duration_ms: number | null;
}
export type TraceEntry = ModelTurn | ToolCall;
export interface Problem { layer: Layer; what: string; seq: number; node: string }

export function traceOf(run: Run): TraceEntry[] {
  return run.events.flatMap((e): TraceEntry[] => (
    e.type === "model_turn" ? [{ ...e.payload, kind: "turn", seq: e.seq }]
      : e.type === "tool_call" ? [{ ...e.payload, kind: "tool", seq: e.seq }]
        : []));
}

/** The node an entry belongs to: its step, else its stage. Runs without stage nodes call these scene and plan. */
const STAGE_NODE: Record<string, string> = { MAP: "scene", PLAN: "plan" };
const belongs = (e: TraceEntry, node: string) => (e.step ? e.step === node : !!e.stage && (node === `stage-${e.stage}` || node === STAGE_NODE[e.stage]));

export const traceFor = (run: Run, node: string) => traceOf(run).filter((e) => belongs(e, node));

/** Every failure, in the order it happened, with the layer that caused it. A device failing isn't a fault in our
 * system, it's what we're looking for, but it has to be told apart from the rest for the same reason. */
export function diagnose(run: Run, nodes: string[]): Problem[] {
  const entries = traceOf(run);
  const problems: Problem[] = [];
  const nodeOf = (e: TraceEntry) => e.step ?? (e.stage ? (nodes.includes(`stage-${e.stage}`) || !STAGE_NODE[e.stage] ? `stage-${e.stage}` : STAGE_NODE[e.stage]) : "");
  const failed = new Set<string>();
  for (const e of entries) {
    if (e.kind === "tool" && !e.ok) {
      const key = `${e.tool}:${JSON.stringify(e.args)}`;
      const again = failed.has(key);
      if (e.layer === "model") failed.add(key);
      problems.push(again
        ? { layer: "model", what: `Sent ${e.tool} unchanged after the same error: ${e.error}`, seq: e.seq, node: nodeOf(e) }
        : { layer: e.layer ?? "pipeline", what: `${e.tool}: ${e.error}`, seq: e.seq, node: nodeOf(e) });
    } else if (e.kind === "turn") {
      if (e.error) problems.push({ layer: e.layer ?? "model", what: `Turn ended on ${e.error_kind ?? e.stop_reason}: ${e.error}`, seq: e.seq, node: nodeOf(e) });
      for (const [step, said] of Object.entries(e.claims ?? {})) {
        const measured = run.steps.find((s) => s.step.id === step)?.verdict;
        if (measured && measured.status !== said) problems.push({ layer: "model", what: `Said ${step} ${said}. The sensors said ${measured.status}: ${measured.reason}`, seq: e.seq, node: step });
      }
    }
  }
  for (const s of run.steps) {
    if (!s.verdict) continue;
    const seq = s.endSeq ?? s.startSeq;
    if (s.verdict.status === "failed") problems.push({ layer: "device", what: `${s.step.target}: ${s.verdict.reason}`, seq, node: s.step.id });
    else if (s.verdict.status === "inconclusive") problems.push({ layer: "robot", what: `${s.step.target}: ${s.verdict.reason}`, seq, node: s.step.id });
  }
  return problems.sort((a, b) => a.seq - b.seq);
}

export function traceTotals(entries: TraceEntry[]) {
  const turns = entries.filter((e): e is ModelTurn => e.kind === "turn");
  const tools = entries.filter((e): e is ToolCall => e.kind === "tool");
  return {
    turns: turns.length, tools: tools.length,
    tokens: turns.reduce((n, t) => n + (t.tokens_in ?? 0) + (t.tokens_out ?? 0), 0),
    modelSeconds: turns.reduce((n, t) => n + (t.latency_ms ?? 0), 0) / 1000,
    toolSeconds: tools.reduce((n, t) => n + (t.duration_ms ?? 0), 0) / 1000,
  };
}
