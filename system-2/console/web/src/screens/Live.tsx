import { useEffect, useMemo, useRef, useState, type FormEvent, type RefObject } from "react";
import { ExplorationGraph } from "../components/ExplorationGraph";
import { Feeds } from "../components/Feeds";
import { ForceChart } from "../components/ForceChart";
import { CountUp, Pill, stagger } from "../components/ui";
import { useAppSession } from "../lib/context";
import type { GraphNode } from "../lib/graph";
import { LIVE_URL, liveCommand, liveFocus, liveRun, stepQueue, useLive, type LiveState } from "../lib/live";
import { liveProject, projectOf, useProjects, type Project } from "../lib/projects";
import { ProjectBar } from "../components/ProjectBar";
import type { Route } from "../lib/route";
import { ENVIRONMENTS } from "../lib/session";
import { ModelTrace } from "../components/ModelTrace";
import { useAgentHealth } from "../lib/agent";
import { AgentLive, AgentReplay } from "./AgentLive";
import { coverageOf, rewardOf, statusOfControl, type Run } from "../lib/runs";

/** Watch and steer a real MuJoCo run while it happens. */
export function Live({ route }: { route: Route }) {
  const { env, operator } = useAppSession();
  const projects = useProjects();
  const { state, connected, nodes, lastTelemetry } = useLive();
  const agent = useAgentHealth();
  const [error, setError] = useState<string | null>(null);
  const send = (path: string, body: object = {}) => { void liveCommand(path, body).then(setError); };
  const runProject = useMemo(() => (state.meta ? projectOf(liveRun(state), projects) : undefined), [state.meta, state.events, projects]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!ENVIRONMENTS[env].connected) {
    return <div className="page"><div className="empty"><h2>Real arm and real CAD: not connected yet</h2></div></div>;
  }

  const replay = route.query.get("replay");
  if (replay) return <AgentReplay key={replay} id={replay} />;

  const finished = state.events.find((e) => e.type === "run_finished")?.payload.status as string | undefined;
  const going = !!state.meta && !finished;
  if (agent.up && !going) return <AgentLive route={route} health={agent} />; // the bridge is the fallback when rav-agent isn't running
  const asked = route.query.get("project");
  const selected = liveProject(asked, state.meta ? { project: runProject } : null, projects);
  const physical = selected?.kind === "physical";
  const showFinished = !!state.meta && !!finished && (asked === "none" || runProject?.id === selected?.id); // another project's result isn't this one's
  const waitingFor = going && selected && !physical && selected.id !== runProject?.id ? selected : undefined;
  return (
    <div className="livepage">
      <ProjectBar project={going ? runProject : selected} tab="live" locked={going} />
      {waitingFor && <p className="note" role="status">{waitingFor.name} can start when this run ends.</p>}
      {!going && physical && <NoArm sim={projects.find((p) => p.kind === "sim")} />}
      {!going && !physical && !connected && <Offline />}
      {!going && !physical && connected && <StartPanel key={selected?.id ?? "none"} again={showFinished} judge={operator.role === "judge"} project={selected} onStart={(body) => send("/start", body)} />}
      {error && <p className="error" role="alert">{error}</p>}
      {(going || showFinished) && <Running state={state} nodes={nodes} finished={finished} send={send} lastTelemetry={lastTelemetry} />}
    </div>
  );
}

/** Physical products run on the real arm, so what you can watch today is the sim. */
function NoArm({ sim }: { sim?: Project }) {
  return (
    <div className="empty rise">
      <h2>The real arm isn't connected</h2>
      <div className="row">
        {sim && <a className="btn accent" href={`#/live?project=${sim.id}`}>Run {sim.name}</a>}
        <a className="btn ghost" href="#/run/sample-sim">Watch a recorded run</a>
      </div>
    </div>
  );
}

function Offline() {
  return (
    <div className="empty rise">
      <h2>Nothing to run on yet</h2>
      <div className="row">
        <a className="btn accent" href="#/live?replay=sample-agent">Watch a scripted model run</a>
        <a className="btn ghost" href="#/run/sample-sim">Watch a recorded sim run</a>
      </div>
      <span className="label">The model, with System 1</span>
      <pre className="code">{"cd system-2\nuv run rav-agent"}</pre>
      <span className="label">The sim alone, with rules</span>
      <pre className="code">{"cd system-2\nuv sync --extra live-depth\nuv run python console/server/live_sim.py"}</pre>
    </div>
  );
}

function StartPanel({ again, judge, project, onStart }: { again: boolean; judge: boolean; project?: Project; onStart: (body: object) => void }) {
  const [cameraRoute, setCameraRoute] = useState(true); // the light install has no PyTorch, so it can't run this route
  useEffect(() => { void fetch(`${LIVE_URL}/health`).then((r) => r.json()).then((h) => setCameraRoute(h.camera_route !== false)).catch(() => undefined); }, []);
  const sim = project?.sim;
  const presetC = !!project && (sim?.seed ?? null) === null; // only preset C has the part the planted fault jams
  const [fault, setFault] = useState(sim?.fault ?? "");
  const [seed, setSeed] = useState("");
  const [depth, setDepth] = useState("depth");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onStart({ seed: project ? sim?.seed ?? null : seed.trim(), fault: project ? (presetC ? fault || null : sim?.fault ?? null) : null, depth: depth === "depth", project: project?.id ?? null });
  };
  return (
    <form className="panel rise startpanel" onSubmit={submit}>
      <h2>{again ? "Run again" : "Start a run"}</h2>
      {presetC && <div className="field">
        <label className="label" htmlFor="l-fault">Planted fault</label>
        <select id="l-fault" value={fault} onChange={(e) => setFault(e.target.value)}>
          <option value="stuck_button">button_2 jams</option>
          <option value="">None</option>
        </select>
      </div>}
      {!project && <div className="field">
        <label className="label" htmlFor="l-seed">Device seed</label>
        <input id="l-seed" className="tech" inputMode="numeric" pattern="[0-9]*" required value={seed} placeholder="1401" onChange={(e) => setSeed(e.target.value)} />
      </div>}
      <div className="field">
        <label className="label" htmlFor="l-route">Perception</label>
        <select id="l-route" value={depth} onChange={(e) => setDepth(e.target.value)}>
          <option value="depth">D405 depth camera</option>
          {cameraRoute && <option value="rgb">USB camera, OWLv2 and SAM</option>}
        </select>
      </div>
      <div className="row">
        <button className="btn accent" type="submit" disabled={judge} title={judge ? "Judges can steer but can't start a run" : undefined}>Start run</button>
      </div>
    </form>
  );
}

const SPEEDS = [1, 2, 4, 8];

function Running({ state, nodes, finished, send, lastTelemetry }: { state: LiveState; nodes: GraphNode[]; finished?: string; send: (path: string, body?: object) => void; lastTelemetry: RefObject<number> }) {
  const { operator } = useAppSession();
  const { meta, tel, events } = state;
  const run = useMemo(() => liveRun(state), [state.events]); // eslint-disable-line react-hooks/exhaustive-deps
  const [picked, setPicked] = useState<string | null>(null);
  const focus = useMemo(() => liveFocus(nodes), [nodes]);
  const needed = events.find((e) => e.type === "approval_needed");
  const waiting = !!needed && !run.approvals.some((a) => a.kind === "plan") && !finished;
  const cov = coverageOf(run);
  const score = rewardOf(cov);
  const steer = (kind: string, extra: object = {}) => send("/steer", { kind, by: operator.name, ...extra });
  const active = tel?.step ? run.steps.find((s) => s.step.id === tel.step) : undefined;
  const limit = Number(active?.step.params.force_limit) || undefined;
  const lastDone = [...run.steps].reverse().find((s) => s.verdict);
  const selected = nodes.find((n) => n.id === (picked ?? focus));
  // The models and the fuse step block the sim, so no frames come. Say so, instead of looking frozen.
  const [computing, setComputing] = useState(false);
  useEffect(() => {
    const timer = window.setInterval(() => setComputing(!finished && !waiting && !tel?.paused && performance.now() - lastTelemetry.current > 1500), 400);
    return () => window.clearInterval(timer);
  }, [finished, waiting, tel?.paused, lastTelemetry]);

  return (
    <>
      <div className="liverow">
        <span className={`livechip ${finished ? "ended" : tel?.paused ? "paused" : "on"}`}><i />{finished ? finished : tel?.paused ? "Paused" : "Live"}</span>
        <h1 className="title">{meta!.product}</h1>
        <span className="mono muted">MuJoCo sim / {meta!.route} / {meta!.run_id}</span>
        <span className="spacer" />
        {tel && <span className="mono muted">{tel.status}</span>}
        {tel && <span className="mono">t = {tel.sim_t.toFixed(1)} s</span>}
        {!finished && <div className="seg" role="group" aria-label="Speed">{SPEEDS.map((r) => <button key={r} type="button" aria-pressed={tel?.rate === r} onClick={() => send("/speed", { rate: r })}>{r}x</button>)}</div>}
        {finished && <a className="btn accent" href={`#/run/${meta!.run_id}`}>Open this run</a>}
        {!finished && <>
          <button className="btn ghost" type="button" onClick={() => steer(tel?.paused ? "resume" : "pause")}>{tel?.paused ? "Resume" : "Pause at next step"}</button>
          <button className="btn danger" type="button" onClick={() => steer("stop")}>Stop at next step</button>
        </>}
      </div>

      <div className="strip" aria-label="Stages">
        {meta!.stages.map((name) => {
          const at = meta!.stages.indexOf(tel?.stage ?? "");
          const i = meta!.stages.indexOf(name);
          const state = (finished ? i <= at : i < at) ? "done" : i === at ? "now" : "";
          return <div key={name} className={state}><b>{name[0] + name.slice(1).toLowerCase()}</b><span className="muted">{i === at && !finished ? tel?.substage && tel.substage !== "done" ? tel.substage : "running" : state === "done" ? "done" : "to do"}</span></div>;
        })}
      </div>

      {waiting && (
        <div className="approvebar rise" role="alert">
          <h2 style={{ flex: "1 1 200px" }}>Plan ready</h2>
          <button className="btn accent" type="button" disabled={operator.role === "judge"} title={operator.role === "judge" ? "Judges can steer but can't approve" : undefined} onClick={() => send("/approve", { by: operator.name })}>Approve plan</button>
          <button className="btn danger" type="button" onClick={() => send("/reject")}>Reject</button>
        </div>
      )}

      <Feeds runId={meta!.run_id} feeds={tel?.feeds ?? []} stage={tel?.stage} computing={computing}
        focus={{ target: active && !active.verdict ? active.step.target : null, label: active && !active.verdict ? `${active.step.target} / ${active.step.skill}` : null, verdict: lastDone?.verdict ? `${lastDone.step.id}:${lastDone.verdict.status}` : null, force: tel?.probe_n ?? 0, limit: limit ?? 6, lcd: tel?.lcd ?? [] }} />

      <section className="stack" aria-label="Flowchart">
        <div className="row"><span className="label" style={{ marginRight: "auto" }}>Flowchart, live</span><span className="legend"><span><i />Happened</span><span><i style={{ borderTopStyle: "dashed", borderTopColor: "var(--muted)" }} />Still to come</span><span><i style={{ borderTopColor: "var(--accent)" }} />Running now</span></span></div>
        <ExplorationGraph live nodes={nodes} selected={selected?.id ?? null} focus={focus} onSelect={setPicked} />
      </section>

      <div className="grid3">
        <div className="panel rise" style={stagger(1)}>
          <span className="label">Probe contact force</span>
          <LiveForce points={state.force} limit={limit} now={tel?.sim_t ?? 0} label={active ? `${active.step.id} ${active.step.skill} ${active.step.target}` : "between steps"} />
        </div>
        <div className="panel rise" style={stagger(2)}>
          {selected && <NodeDetail key={selected.id} node={selected} run={run} finished={!!finished} events={events} onSteer={steer} following={!picked} onFollow={() => setPicked(null)} />}
        </div>
        <div className="stack rise" style={stagger(3)}>
          <div className="panel">
            <span className="label">{finished ? "Final" : "So far"}</span>
            <div className="liveproof"><span className="display" style={{ fontSize: 24 }}>REWARD <CountUp value={finished && run.report.summary ? run.report.reward.value : score.value} /></span></div>
            {run.scene.controls.length > 0
              ? <div className="chips">{run.scene.controls.map((c) => <Pill key={c.id} status={finished && c.id in cov.skipped ? "skipped" : statusOfControl(cov, c.id)}>{c.id}</Pill>)}</div>
              : null}
            {finished && run.report.summary && <p>{run.report.summary}</p>}
          </div>
          <LogPanel state={state} />
        </div>
      </div>
    </>
  );
}

/** A rolling trace of the last few seconds. The newest sample is labeled; the whole trace is in the event log. */
function LiveForce({ points, limit, now, label }: { points: [number, number][]; limit?: number; now: number; label: string }) {
  const W = 420, H = 150, L = 34, R = 10, T = 8, B = 20, SPAN = 24;
  const shown = points.filter(([t]) => t >= now - SPAN);
  const top = Math.max(4, Math.ceil(Math.max(limit ?? 0, ...shown.map(([, n]) => n))));
  const x = (t: number) => L + ((t - (now - SPAN)) / SPAN) * (W - L - R);
  const y = (n: number) => H - B - (Math.min(n, top) / top) * (H - T - B);
  const last = shown.at(-1);
  return (
    <div className="stack">
      <div className="row"><span className="mono muted" style={{ marginRight: "auto" }}>{label}</span><span className="mono">{last ? `${last[1].toFixed(1)} N` : "0.0 N"}</span></div>
      <div className="chart"><svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Contact force over the last ${SPAN} simulated seconds, ${last ? last[1].toFixed(1) : 0} newtons now`}>
        {[0, top / 2, top].map((n) => <g key={n}><line className="grid" x1={L} x2={W - R} y1={y(n)} y2={y(n)} /><text x={L - 6} y={y(n) + 4} textAnchor="end">{Number.isInteger(n) ? n : n.toFixed(1)}{n === top ? " N" : ""}</text></g>)}
        <text x={L} y={H - 5}>-{SPAN} s</text><text x={W - R} y={H - 5} textAnchor="end">now</text>
        {limit !== undefined && <><line className="limit" x1={L} x2={W - R} y1={y(limit)} y2={y(limit)} strokeDasharray="4 3" /><text x={W - R} y={y(limit) - 4} textAnchor="end">step limit</text></>}
        {shown.length > 1 && <polyline className="ser" style={{ stroke: "var(--accent)" }} points={shown.map(([t, n]) => `${x(t).toFixed(1)},${y(n).toFixed(1)}`).join(" ")} />}
      </svg></div>
    </div>
  );
}

function NodeDetail({ node, run, finished, events, onSteer, following, onFollow }: { node: GraphNode; run: Run; finished: boolean; events: LiveState["events"]; onSteer: (kind: string, extra: object) => void; following: boolean; onFollow: () => void }) {
  const [reason, setReason] = useState("");
  const [tried, setTried] = useState(false);
  const record = run.steps.find((s) => s.step.id === node.id);
  const planned = run.plan.steps.find((s) => s.id === node.id);
  const step = record?.step ?? planned;
  const canSteer = !finished && node.status === "pending" && !!node.target && stepQueue(events).queue.some((s) => s.id === node.id);
  const act = (kind: "prioritize" | "skip") => {
    if (!reason.trim()) { setTried(true); return; }
    onSteer(kind, { target: node.target, text: reason.trim() });
    setReason("");
    setTried(false);
  };
  return (
    <>
      <div className="row">
        <h2 style={{ marginRight: "auto" }}>{node.title}</h2>
        {node.status && <Pill status={node.status === "running" ? "planned" : node.status}>{node.status === "running" ? "running" : node.status}</Pill>}
        {!following && <button className="linkbtn" type="button" onClick={onFollow}>Follow the run</button>}
      </div>
      <dl className="kv">
        {node.target && <><dt>Control</dt><dd className="mono">{node.target}</dd></>}
        {step && <><dt>Skill</dt><dd className="mono">{step.skill}</dd></>}
        {step?.why && <><dt>Why</dt><dd>{step.why}</dd></>}
        {!step && node.sub && <><dt>Detail</dt><dd>{node.sub}</dd></>}
        {node.id === "stage-REPORT" && run.report.summary && <><dt>Summary</dt><dd>{run.report.summary}</dd></>}
        {!step && !node.sub && node.id !== "stage-REPORT" && <><dt>State</dt><dd>{node.status === "pending" ? "Still to come" : node.status === "running" ? "Running now" : "Done"}</dd></>}
        {record?.verdict && <><dt>Result</dt><dd>{record.verdict.reason}</dd><dt>Decided by</dt><dd>{record.verdict.decided_by}</dd></>}
        {record?.trace?.peak_force_n != null && <><dt>Measured</dt><dd className="mono">{record.trace.peak_force_n.toFixed(1)} N peak{record.trace.travel_mm != null ? `, ${record.trace.travel_mm.toFixed(1)} mm travel` : ""}</dd></>}
        {node.reason && <><dt>Reason</dt><dd>“{node.reason}”{node.by ? `, ${node.by}` : ""}</dd></>}
      </dl>
      <ModelTrace run={run} node={node.id} />
      {record?.trace?.force_trace.length ? <ForceChart key={record.step.id} series={[{ name: record.step.target, points: normalize(record.trace.force_trace), tone: record.verdict?.status === "failed" ? "fail" : "pass" }]} limit={Number(record.step.params.force_limit) || undefined} /> : null}
      {canSteer && (
        <div className="stack">
          <div className="field">
            <label className="label" htmlFor="l-reason">Reason</label>
            <input id="l-reason" value={reason} placeholder="Check this first, the cap may rub" onChange={(e) => setReason(e.target.value)} aria-invalid={tried && !reason.trim()} />
          </div>
          {tried && !reason.trim() && <p className="error">Say why, so the run's log records it.</p>}
          <div className="row">
            <button className="btn ghost" type="button" onClick={() => act("prioritize")}>Test next</button>
            <button className="btn ghost" type="button" onClick={() => act("skip")}>Skip</button>
          </div>
        </div>
      )}
    </>
  );
}

// Sim traces use sim time from the start of the run; the chart reads from zero.
const normalize = (points: [number, number][]): [number, number][] => points.map(([t, n]) => [t - points[0][0], n]);

function LogPanel({ state }: { state: LiveState }) {
  const log = useRef<HTMLOListElement>(null);
  const lines = useMemo(() => state.events.filter((e) => e.type === "message").slice(-200), [state.events]);
  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight }); }, [lines.length]);
  return (
    <div className="panel">
      <span className="label">Sim log</span>
      <ol className="livelog" ref={log}>
        {lines.map((e) => <li key={e.seq}><span className="seq">{e.payload.sim_t?.toFixed(1) ?? ""}</span><span>{e.payload.text}</span></li>)}
      </ol>
    </div>
  );
}
