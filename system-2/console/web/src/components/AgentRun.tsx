import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { AGENT_URL, liveCommand } from "../lib/live";
import { isPaused, pendingApproval, planRows, runOf, stateLine, telemetryOf, timelineOf, type AgentState, type PlanRow, type TimelineItem } from "../lib/agent";
import type { StepTrace, StepVerdict } from "../lib/contracts";
import { useAppSession } from "../lib/context";
import { coverageOf, rewardOf, statusOfControl, type Run } from "../lib/runs";
import type { ToolCall } from "../lib/trace";
import { Feeds } from "./Feeds";
import { ForceChart } from "./ForceChart";
import { TraceSummary } from "./ModelTrace";
import { CountUp, Pill } from "./ui";

export type Send = (path: string, body?: object) => void;

const seconds = (ms: number | null | undefined) => (ms == null ? null : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`);
const argLine = (args: Record<string, unknown>) => Object.entries(args).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join(" ");
const normalize = (points: [number, number][]): [number, number][] => points.map(([t, n]) => [t - points[0][0], n]);
const SPEEDS: [number, string][] = [[1, "1x"], [4, "4x"], [8, "8x"], [0, "Max"]];
const VERDICT_WORD: Record<string, string> = { passed: "Passed", failed: "Failed", intermittent: "Intermittent", observed: "Observed", skipped: "Skipped", inconclusive: "Inconclusive" };

export interface Picked { title: string; verdict?: StepVerdict; trace?: StepTrace; limit?: number }

/** One model run: what it's thinking and doing, on the left; the robot and the plan, on the right. Live and replay are this same view. */
export function AgentRun({ state, send, bar, sim = true, over = false, real = false }: { state: AgentState; send?: Send; bar?: ReactNode; sim?: boolean; over?: boolean; real?: boolean }) {
  const run = useMemo(() => runOf(state), [state.events]); // eslint-disable-line react-hooks/exhaustive-deps
  const items = useMemo(() => timelineOf(state), [state.events, state.deltas]); // eslint-disable-line react-hooks/exhaustive-deps
  const line = stateLine(state);
  const [picked, setPicked] = useState<Picked | null>(null);
  const pending = pendingApproval(items);
  const finished = line.state === "done" || over; // over: the service says the run ended, however it ended
  const telemetry = sim ? telemetryOf(state.meta) : null;
  const openStep = (id: string, seq?: number) => { // a retest has the same id, so a row names its own attempt
    const s = seq === undefined ? run.steps.findLast((r) => r.step.id === id) : run.steps.find((r) => r.startSeq === seq);
    if (s) setPicked({ title: `${s.step.id} ${s.step.skill} ${s.step.target}`, verdict: s.verdict, trace: s.trace, limit: Number(s.step.params.force_limit) || undefined });
  };
  const active = run.steps.findLast((s) => !s.verdict);
  const last = run.steps.findLast((s) => s.verdict);
  return (
    <>
      <div className="liverow">
        <span className={`livechip ${finished ? "ended" : send ? "on" : "paused"}`}><i />{send ? (finished ? "Ended" : "Live") : "Replay"}</span>
        <h1 className="title">{run.product}</h1>
        <span className="mono muted">{[state.meta?.model, run.id].filter(Boolean).join(" / ")}</span>
        <span className="spacer" />
        {telemetry && !finished && state.tel && <div className="seg" role="group" aria-label="Sim speed">{SPEEDS.map(([rate, word]) => <button key={rate} type="button" aria-pressed={state.tel!.rate === rate} onClick={() => void liveCommand("/speed", { rate }, telemetry)}>{word}</button>)}</div>}
        {finished && send && <a className="btn ghost" href={`#/run/${run.id}`}>Open this run</a>}
      </div>
      {bar}
      <div className="agentgrid">
        <section className="panel agentmain" aria-label="What the model is doing">
          <div className={`agentstate ${line.state}`} role="status"><i /><b>{line.label}</b>{line.detail && <span className="muted">{line.detail}</span>}</div>
          <Timeline items={items} send={send} onOpen={setPicked} pendingRef={pending?.ref} />
          {send && !finished && <Composer events={state.events} send={send} />}
        </section>
        <aside className="agentside">
          {telemetry ? <Feeds runId={state.meta?.run_id ?? null} url={telemetry} feeds={state.tel?.feeds ?? []} stage={state.tel?.stage} computing={false} real={real}
            focus={{ target: active?.step.target ?? null, label: active ? `${active.step.target} / ${active.step.skill}` : null, verdict: last?.verdict ? `${last.step.id}:${last.verdict.status}` : null, force: state.tel?.probe_n ?? 0, limit: Number(active?.step.params.force_limit) || 6, lcd: state.tel?.lcd ?? [] }} />
            : <div className="agentnosim note">No sim recording in this run</div>}
          <PlanPanel run={run} send={finished ? undefined : send} onOpen={openStep} finished={finished} />
          <div className="panel">
            <span className="label">This run</span>
            <TraceSummary run={run} nodes={run.steps.map((s) => s.step.id)} onPick={openStep} />
            <p className="mono muted">Stops from System 1: {run.events.filter((e) => e.type === "crossing").length}</p>
          </div>
        </aside>
      </div>
      {picked && <Evidence picked={picked} onClose={() => setPicked(null)} />}
    </>
  );
}

// --- the timeline ---

function Timeline({ items, send, onOpen, pendingRef }: { items: TimelineItem[]; send?: Send; onOpen: (p: Picked) => void; pendingRef?: string }) {
  const box = useRef<HTMLOListElement>(null);
  const pinned = useRef(true); // follows the newest entry until you scroll up to read
  const size = items.length + items.reduce((n, i) => n + (i.kind === "turn" && i.streaming ? i.thought.length + i.text.length : 0), 0);
  useEffect(() => { if (pinned.current) box.current?.scrollTo({ top: box.current.scrollHeight }); }, [size, pendingRef]);
  return (
    <ol className="timeline" ref={box} aria-live="off" onScroll={(e) => { const b = e.currentTarget; pinned.current = b.scrollHeight - b.scrollTop - b.clientHeight < 60; }}>
      {items.map((item) => <li key={item.key} className={`tl ${item.kind}`}><Entry item={item} send={send} onOpen={onOpen} /></li>)}
    </ol>
  );
}

function Entry({ item, send, onOpen }: { item: TimelineItem; send?: Send; onOpen: (p: Picked) => void }) {
  switch (item.kind) {
    case "turn": return <Turn item={item} />;
    case "tool": return <Tool call={item.call} />;
    case "stop": return <p className="tlline"><span className="tltag">Stop</span>{item.code ?? item.stop}{item.target ? ` on ${item.target}` : ""}<span className="muted"> / {item.routine}</span></p>;
    case "step": return <StepRow item={item} onOpen={onOpen} />;
    case "approval": return <ApprovalRow item={item} send={send} />;
    case "plan": return <details className="tlplan"><summary><span className="tltag">Plan</span>{item.plan.plan_id}, {item.plan.steps.length} steps</summary><ol>{item.plan.steps.map((s) => <li key={s.id} className="mono">{s.id} {s.skill} {s.target}{Object.keys(s.params).length ? ` ${argLine(s.params)}` : ""}{s.quote && <em> “{s.quote}”</em>}</li>)}</ol></details>;
    case "amended": return <p className="tlline"><span className="tltag">Plan changed</span>{item.why || `${item.steps.length} steps left`}<span className="muted"> / level {item.level}{item.by ? `, ${item.by}` : ""}</span></p>;
    case "message":
      if (item.role === "user") return <div className="tloperator"><span className="label">{item.by ?? "Operator"}</span><p>{item.text}</p></div>;
      if (item.asks) return <div className="tlasks"><span className="label">The model asks</span><p>{item.text}</p></div>;
      return <p className={`tlline ${item.role === "model" ? "" : "muted"}`}><span className="tltag">{item.role}</span>{item.text}</p>;
    case "check": return <p className="tlline"><span className="tltag">Check</span><b className="mono">{item.target}</b> {item.failed.map((c) => `${c.metric} ${c.op} ${String(c.value ?? "")}, got ${String(c.actual ?? "nothing")}`).join("; ")}<span className="muted"> / {item.counted ? "counts against it" : `not counted: ${item.why}`}</span></p>;
    case "steer": return <p className="tlline"><span className="tltag">{item.steer}</span>{item.target ? `${item.target}. ` : ""}{item.note}<span className="muted">{item.by ? ` / ${item.by}` : ""}</span></p>;
    case "scene": return <p className="tlline"><span className="tltag">Found</span>{item.scene.controls.length} controls: <span className="mono">{item.scene.controls.map((c) => c.id).join(", ")}</span></p>;
    case "finding": return <p className="tlline tlfinding"><span className="tltag">Finding</span><b>{item.finding.target}</b> {item.finding.what_happened}</p>;
    case "report": return <p className="tlline"><span className="tltag">Report</span>{item.summary}</p>;
    case "end": return <p className="tlline"><span className="tltag">Run {item.status}</span></p>;
  }
}

function Turn({ item }: { item: Extract<TimelineItem, { kind: "turn" }> }) {
  const t = item.turn;
  const meta = t ? [t.model, seconds(t.latency_ms), t.tokens_in != null ? `${t.tokens_in} in, ${t.tokens_out ?? 0} out` : null].filter(Boolean).join(" / ") : "";
  return (
    <div className={`tlturn ${t?.error ? "bad" : ""}`}>
      {item.thought && (
        <details open>
          <summary className="label">Reasoning summary</summary>
          <p className="tlthought">{item.thought.trim().split(/\*\*(.+?)\*\*/).map((part, i) => (i % 2 ? <b key={i}>{part}</b> : part))}{item.streaming && !item.text && <i className="tlcaret" />}</p>
        </details>
      )}
      {item.text && <p>{item.text}{item.streaming && <i className="tlcaret" />}</p>}
      {t?.error && <p className="terror">{t.error}</p>}
      {item.calls.map((c) => <Tool key={c.id} call={c} />)}
      {meta && <span className="tmeta">{meta}</span>}
    </div>
  );
}

function Tool({ call: c }: { call: ToolCall }) {
  const args = argLine(c.args);
  const open = !c.ok || undefined;
  return (
    <details className={`tltool ${c.ok ? "" : "bad"}`} open={open}>
      <summary><b className="mono">{c.tool}</b>{args && <span className="mono muted tlargs"> {args}</span>}<span className="tmeta">{[c.ok ? null : c.error_kind, c.caller === "model" ? null : c.caller, seconds(c.duration_ms)].filter(Boolean).join(" / ")}</span></summary>
      {c.error && <p className="terror">{c.error}</p>}
      {Object.keys(c.args).length > 0 && <pre>{JSON.stringify(c.args, null, 2)}</pre>}
      {c.result && <pre>{JSON.stringify(c.result, null, 2)}</pre>}
    </details>
  );
}

function StepRow({ item, onOpen }: { item: Extract<TimelineItem, { kind: "step" }>; onOpen: (p: Picked) => void }) {
  const { step, verdict, trace } = item;
  return (
    <button type="button" className="tlstep" disabled={!trace} onClick={() => onOpen({ title: `${step.id} ${step.skill} ${step.target}`, verdict, trace, limit: Number(step.params.force_limit) || undefined })}>
      <span className="mono">{step.id} {step.skill} {step.target}</span>
      {verdict ? <Pill status={verdict.status}>{VERDICT_WORD[verdict.status]}</Pill> : <Pill status="planned">running</Pill>}
      {verdict && <span className="tlreason">{verdict.reason}</span>}
      {trace && <span className="tlnums mono muted">{[trace.peak_force_n != null ? `${trace.peak_force_n.toFixed(1)} N` : null, trace.travel_mm != null ? `${trace.travel_mm.toFixed(1)} mm` : null].filter(Boolean).join(", ")}</span>}
    </button>
  );
}

function ApprovalRow({ item, send }: { item: Extract<TimelineItem, { kind: "approval" }>; send?: Send }) {
  const { operator } = useAppSession();
  const judge = operator.role === "judge";
  const answer = (ok: boolean) => send?.("/approve", { kind: item.what, ref: item.ref, by: operator.name, ok });
  if (item.state === "approved") return <p className="tlline"><span className="tltag">Approved</span>{item.ref}<span className="muted"> / {item.by}</span></p>;
  if (item.state === "closed") return <p className="tlline"><span className="tltag">Not approved</span>{item.ref}</p>;
  return (
    <div className="approvebar">
      <h2 style={{ flex: "1 1 200px" }}>{item.what === "safety" ? "Resume after this safety stop?" : `Approve this ${item.what}?`}</h2>
      <span className="mono muted">{item.ref}</span>
      {send && item.state === "pending" && <>
        <button className="btn accent" type="button" disabled={judge} title={judge ? "Judges can steer but can't approve" : undefined} onClick={() => answer(true)}>Approve</button>
        <button className="btn danger" type="button" disabled={judge} onClick={() => answer(false)}>Refuse</button>
      </>}
    </div>
  );
}

// --- steering ---

function Composer({ events, send }: { events: AgentState["events"]; send: Send }) {
  const { operator } = useAppSession();
  const [text, setText] = useState("");
  const paused = isPaused(events);
  const steer = (kind: string, extra: object = {}) => send("/steer", { kind, by: operator.name, ...extra });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const value = text.trim();
    if (!value) return;
    steer("message", { text: value });
    setText("");
  };
  const onKey = (e: KeyboardEvent) => { if (e.key === "Enter" && !e.shiftKey) submit(e); };
  return (
    <form className="composer" onSubmit={submit}>
      <div className="field">
        <label className="label" htmlFor="agent-message">Message the model</label>
        <textarea id="agent-message" rows={2} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} />
      </div>
      <div className="row">
        <button className="btn accent" type="submit" disabled={!text.trim()}>Send</button>
        <span className="spacer" />
        <button className="btn ghost" type="button" onClick={() => steer(paused ? "resume" : "pause")}>{paused ? "Resume" : "Pause at next step"}</button>
        <button className="btn danger" type="button" onClick={() => steer("stop")}>Stop at next step</button>
      </div>
    </form>
  );
}

function PlanPanel({ run, send, onOpen, finished }: { run: Run; send?: Send; onOpen: (id: string, seq?: number) => void; finished: boolean }) {
  const rows = planRows(run);
  const cov = coverageOf(run);
  const final = finished && run.report.summary ? run.report : null;
  const shown = final?.coverage ?? cov;
  const score = final?.reward.value ?? rewardOf(cov).value;
  return (
    <div className="panel">
      <div className="row"><span className="label" style={{ marginRight: "auto" }}>Plan and coverage</span><span className="display">REWARD <CountUp value={score} /></span></div>
      {run.scene.controls.length > 0 && <div className="chips">{run.scene.controls.map((c) => <Pill key={c.id} status={c.id in shown.skipped && (finished || shown.skipped[c.id] !== "no test ran") ? "skipped" : statusOfControl(shown, c.id)}>{c.id}</Pill>)}</div>}
      {rows.length > 0 && <ol className="planrows">{rows.map((r) => <Row key={r.key} row={r} send={send} onOpen={onOpen} />)}</ol>}
    </div>
  );
}

function Row({ row, send, onOpen }: { row: PlanRow; send?: Send; onOpen: (id: string, seq?: number) => void }) {
  const { operator } = useAppSession();
  const [asking, setAsking] = useState(false);
  const [why, setWhy] = useState("");
  const skip = (e: FormEvent) => {
    e.preventDefault();
    if (!why.trim()) return;
    send?.("/steer", { kind: "skip", target: row.target, text: why.trim(), by: operator.name });
    setAsking(false);
  };
  const done = row.state !== "pending" && row.state !== "running" && row.state !== "skipped";
  return (
    <li className={`planrow ${row.state}`}>
      {done ? <button type="button" className="linkbtn" onClick={() => onOpen(row.id, row.seq)}>{row.id}</button> : <span className="mono">{row.id}</span>}
      <span className="mono muted">{[row.skill, row.target].filter(Boolean).join(" ")}</span>
      <span className="spacer" />
      {row.state === "pending" && send && row.target && !asking && <button type="button" className="linkbtn" onClick={() => setAsking(true)}>Skip</button>}
      {row.state === "running" ? <Pill status="planned">running</Pill> : <Pill status={row.state}>{row.state}</Pill>}
      {asking && (
        <form className="planskip" onSubmit={skip}>
          <input aria-label={`Why skip ${row.id}`} placeholder="Why skip it?" value={why} onChange={(e) => setWhy(e.target.value)} autoFocus />
          <button className="btn ghost" type="submit" disabled={!why.trim()}>Skip</button>
          <button className="linkbtn" type="button" onClick={() => setAsking(false)}>Cancel</button>
        </form>
      )}
    </li>
  );
}

// --- evidence ---

function Evidence({ picked, onClose }: { picked: Picked; onClose: () => void }) {
  const { title, verdict, trace, limit } = picked;
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    close.current?.focus();
    const onKey = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [onClose]);
  const measures = Object.entries(trace?.measures ?? {});
  const readings = Object.entries(trace?.readout_change ?? {});
  return (
    <div className="evidencewrap" onClick={onClose}>
      <aside className="evpanel panel" role="dialog" aria-modal="true" aria-label={`Evidence for ${title}`} onClick={(e) => e.stopPropagation()}>
        <div className="row"><h2 className="mono" style={{ marginRight: "auto", fontSize: 14 }}>{title}</h2><button ref={close} className="btn ghost" type="button" onClick={onClose}>Close</button></div>
        {verdict && <div className="stack"><Pill status={verdict.status}>{VERDICT_WORD[verdict.status]}</Pill><p>{verdict.reason}</p><span className="note">Decided by {verdict.decided_by}{trace ? `, attempt ${trace.attempt}` : ""}</span></div>}
        {trace && trace.force_trace.length > 1 && <div className="stack"><span className="label">Force</span><ForceChart series={[{ name: verdict?.target ?? "force", points: normalize(trace.force_trace), tone: verdict?.status === "failed" ? "fail" : "pass" }]} limit={limit} /></div>}
        {trace && <div className="stack"><span className="label">Measured</span><dl className="kv mono">
          {trace.peak_force_n != null && <><dt>Peak</dt><dd>{trace.peak_force_n.toFixed(2)} N</dd></>}
          {trace.travel_mm != null && <><dt>Travel</dt><dd>{trace.travel_mm.toFixed(2)} mm</dd></>}
          {trace.stop_reason && <><dt>Stopped on</dt><dd>{trace.stop_reason}</dd></>}
          {trace.duration_s != null && <><dt>Took</dt><dd>{trace.duration_s.toFixed(1)} s</dd></>}
          {measures.map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{typeof v === "string" ? v : JSON.stringify(v)}</dd></div>)}
        </dl></div>}
        {readings.length > 0 && <div className="stack"><span className="label">Device readings</span><dl className="kv mono">{readings.map(([ch, seq]) => <div key={ch} style={{ display: "contents" }}><dt>{ch}</dt><dd>{seq.map(String).join(" → ")}</dd></div>)}</dl></div>}
        {(trace?.checks?.length ?? 0) > 0 && <div className="stack"><span className="label">Checks</span><ul className="planrows">{trace!.checks!.map((c, i) => <li key={i} className="planrow"><span className="mono">{c.metric} {c.op} {String(c.value ?? "")}</span><span className="spacer" /><span className="mono muted">{String(c.actual ?? "not measured")}</span><Pill status={c.passed === null ? "skipped" : c.passed ? "passed" : "failed"}>{c.passed === null ? "n/a" : c.passed ? "met" : "not met"}</Pill></li>)}</ul></div>}
        {(trace?.frames.length ?? 0) > 0 && <div className="stack"><span className="label">Frames</span><div className="evframes">{trace!.frames.map((ref) => <FrameImage key={ref} refId={ref} />)}</div></div>}
      </aside>
    </div>
  );
}

/** A camera frame, fetched only when someone opens the evidence. */
function FrameImage({ refId }: { refId: string }) {
  const [frame, setFrame] = useState<{ mime: string; data_b64: string; caption?: string } | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let gone = false;
    fetch(`${AGENT_URL}/evidence?ref=${encodeURIComponent(refId)}`).then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((f) => { if (!gone) setFrame(f); }).catch(() => { if (!gone) setFailed(true); });
    return () => { gone = true; };
  }, [refId]);
  if (failed) return <span className="note">{refId} isn't available</span>;
  if (!frame) return <div className="sweep" role="status" aria-label={`Loading ${refId}`} />;
  return <figure><img src={`data:${frame.mime};base64,${frame.data_b64}`} alt={frame.caption || refId} /><figcaption className="note">{frame.caption || refId}</figcaption></figure>;
}

export const postAgent = (setError: (e: string | null) => void): Send => (path, body = {}) => { void liveCommand(path, body, AGENT_URL).then(setError); };
