import { useMemo } from "react";
import type { Run } from "../lib/runs";
import { LAYERS, LAYER_NAME, diagnose, traceFor, traceOf, traceTotals, type ModelTurn, type Problem, type ToolCall } from "../lib/trace";

const seconds = (ms: number | null) => (ms == null ? null : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`);
const line = (args: Record<string, unknown>) => Object.entries(args).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join(" ");

function More({ label, children }: { label: string; children: string }) {
  return <details className="tmore"><summary>{label}</summary><pre>{children}</pre></details>;
}

function Turn({ t }: { t: ModelTurn }) {
  const meta = [t.model, seconds(t.latency_ms), t.tokens_in != null ? `${t.tokens_in} in, ${t.tokens_out ?? 0} out` : null, t.stop_reason].filter(Boolean).join(" / ");
  return (
    <li className={`tturn ${t.error ? "bad" : ""}`}>
      <span className="tmeta">{meta}</span>
      {t.text && <p>{t.text}</p>}
      {t.error && <p className="terror">{t.error}</p>}
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
      {c.error && <p className="terror">{c.error}</p>}
      {c.result && <More label="Returned">{JSON.stringify(c.result, null, 2)}</More>}
    </li>
  );
}

function ProblemLine({ p }: { p: Problem }) {
  return <><span className={`tlayer ${p.layer}`}>{LAYER_NAME[p.layer]}</span><span>{p.what}</span></>;
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
export function TraceSummary({ run, nodes, onPick }: { run: Run; nodes: string[]; onPick: (node: string) => void }) {
  const entries = useMemo(() => traceOf(run), [run]);
  const problems = useMemo(() => diagnose(run, nodes), [run, nodes]);
  const totals = traceTotals(entries);
  return (
    <div className="stack">
      <div className="tlayers">
        {LAYERS.map((l) => <div key={l} className="tcount"><span className={`tlayer ${l}`}>{LAYER_NAME[l]}</span><b>{problems.filter((p) => p.layer === l).length}</b></div>)}
      </div>
      <p className="mono muted">
        {totals.turns > 0 ? `${totals.turns} model turns, ${totals.tokens.toLocaleString()} tokens, ${totals.modelSeconds.toFixed(1)} s / ` : "No model in this run / "}
        {totals.tools} tool calls, {totals.toolSeconds.toFixed(1)} s
      </p>
      {problems.length > 0 && <ul className="tproblems">{problems.map((p) => <li key={`${p.seq}-${p.what}`}><button type="button" className="tjump" disabled={!nodes.includes(p.node)} onClick={() => onPick(p.node)}><span className="mono muted">{p.node}</span><ProblemLine p={p} /></button></li>)}</ul>}
    </div>
  );
}
