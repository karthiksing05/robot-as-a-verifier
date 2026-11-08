import { useMemo } from "react";
import type { Run } from "../lib/runs";
import { LAYERS, LAYER_NAME, diagnose, duration, errorLines, traceFor, traceTotals, type Layer, type ModelTurn, type Problem, type ToolCall } from "../lib/trace";

const seconds = (ms: number | null) => (ms == null ? null : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`);
const line = (args: Record<string, unknown>) => Object.entries(args).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join(" ");

function More({ label, children }: { label: string; children: string }) {
  return <details className="tmore"><summary>{label}</summary><pre>{children}</pre></details>;
}

/** A tool error as its headline, then one line per distinct problem. */
export function ErrorText({ text, className = "terror" }: { text: string; className?: string }) {
  const { head, lines } = errorLines(text);
  return <span className={className}>{head}{lines.map((l) => <span key={l} className="terrline">{l}</span>)}</span>;
}

export const LayerChip = ({ layer }: { layer: Layer }) => <span className={`tlayer l-${layer}`}>{LAYER_NAME[layer]}</span>;

function Turn({ t }: { t: ModelTurn }) {
  const meta = [t.model, seconds(t.latency_ms), t.tokens_in != null ? `${t.tokens_in} in, ${t.tokens_out ?? 0} out` : null, t.stop_reason].filter(Boolean).join(" / ");
  return (
    <li className={`tturn ${t.error ? "bad" : ""}`}>
      <span className="tmeta">{meta}</span>
      {t.text && <p>{t.text}</p>}
      {t.error && <ErrorText text={t.error} />}
      {t.input && <More label="Told">{t.input}</More>}
      {t.thinking && <More label="Thinking">{t.thinking}</More>}
      {t.raw && <span className="tmeta">{t.raw}</span>}
    </li>
  );
}

function Tool({ c }: { c: ToolCall }) {
  return (
    <li className={`ttool ${c.ok ? "" : "bad"} ${c.turn ? "child" : ""}`}>
      <span className="tcall"><b>{c.tool}</b>{" "}{line(c.args)}</span>
      <span className="tmeta">{[c.ok ? "ok" : c.error_kind, c.caller === "model" ? null : c.caller, seconds(c.duration_ms)].filter(Boolean).join(" / ")}</span>
      {c.error && <ErrorText text={c.error} />}
      {c.result && <More label="Returned">{JSON.stringify(c.result, null, 2)}</More>}
    </li>
  );
}

function ProblemLine({ p }: { p: Problem }) {
  return <><LayerChip layer={p.layer} /><ErrorText text={p.what} className="tprob" /></>;
}

/** What the model and the pipeline did for one stage or step, in order, with whichever layer failed first on top. */
export function ModelTrace({ run, node }: { run: Run; node: string }) {
  const entries = useMemo(() => traceFor(run, node), [run, node]);
  if (!entries.length) return null;
  const problems = diagnose(run, [node]).filter((p) => p.node === node);
  return (
    <div className="trace">
      <span className="label">Trace</span>
      {problems.length > 0 && <ul className="tproblems">{problems.map((p) => <li key={`${p.seq}-${p.what}`}><ProblemLine p={p} /></li>)}</ul>}
      <ol className="tlist">{entries.map((e) => (e.kind === "turn" ? <Turn key={e.id} t={e} /> : <Tool key={e.id} c={e} />))}</ol>
    </div>
  );
}

/** Every failure in the run by the layer that caused it. A line goes to its step. */
export function TraceSummary({ run, nodes, onPick, stops }: { run: Run; nodes: string[]; onPick: (node: string) => void; stops?: number }) {
  const problems = useMemo(() => diagnose(run, nodes), [run, nodes]);
  const totals = useMemo(() => traceTotals(run), [run]);
  return (
    <div className="stack">
      <div className="tlayers">
        {LAYERS.map((l) => { const n = problems.filter((p) => p.layer === l).length; return <div key={l} className={`tcount ${n ? "" : "zero"}`}><LayerChip layer={l} /><b>{n}</b></div>; })}
      </div>
      <p className="mono muted tstats">
        <span>{totals.turns > 0 ? `${totals.turns} model turns, ${totals.tokens.toLocaleString()} tokens, ${duration(totals.modelSeconds)}` : "No model in this run"}</span>
        <span>{totals.tools} tool calls, {duration(totals.toolSeconds)}{totals.waitSeconds >= 1 && `, plus ${duration(totals.waitSeconds)} waiting for approval`}</span>
        {stops != null && <span>{stops} stops from System 1</span>}
      </p>
      {problems.length > 0 && <ul className="tproblems">{problems.map((p) => <li key={`${p.seq}-${p.what}`}><button type="button" className="tjump" disabled={!nodes.includes(p.node)} onClick={() => onPick(p.node)}><span className="mono muted">{p.node}</span><ProblemLine p={p} /></button></li>)}</ul>}
    </div>
  );
}
