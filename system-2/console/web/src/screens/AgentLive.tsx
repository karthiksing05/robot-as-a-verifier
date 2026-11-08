import { useEffect, useMemo, useState, type FormEvent } from "react";
import { AgentRun, postAgent, type Send } from "../components/AgentRun";
import { ProjectBar } from "../components/ProjectBar";
import { MAX_TURNS, revisionsOf, startBody, useAgentStream, useReplay, type AgentHealth, type AgentState } from "../lib/agent";
import { useAppSession, useRuns } from "../lib/context";
import { liveRun } from "../lib/live";
import { liveProject, projectOf, useProjects, type Project } from "../lib/projects";
import type { Route } from "../lib/route";

const DEFAULT_MODEL = "claude-haiku-5-5";


/** The model's run, through rav-agent: start it, watch it and steer it. */
export function AgentLive({ route, health }: { route: Route; health: AgentHealth }) {
  const { operator } = useAppSession();
  const projects = useProjects();
  const state = useAgentStream(true);
  const [error, setError] = useState<string | null>(null);
  const post = useMemo(() => postAgent(setError), []);
  const [starting, setStarting] = useState(false); // health is polled, so it says "running" a moment after a start
  useEffect(() => {
    if (health.running || !starting) { setStarting(false); return; }
    const timer = window.setTimeout(() => setStarting(false), 8000); // it refused, or it's over already
    return () => window.clearTimeout(timer);
  }, [health.running, starting]);
  const send: Send = (path, body) => { if (path === "/start") { setStarting(true); setError(null); } post(path, body); };
  const finished = state.events.some((e) => e.type === "run_finished");
  const going = starting || (!!state.meta && !finished && health.running);
  const runProject = useMemo(() => (state.meta ? projects.find((p) => p.id === state.meta?.project) ?? projectOf(liveRun(state), projects) : undefined), [state.meta, state.events, projects]); // eslint-disable-line react-hooks/exhaustive-deps
  const selected = liveProject(route.query.get("project"), state.meta ? { project: runProject } : null, projects);
  const runnable = !selected || selected.kind === "sim" || !!selected.sim;
  return (
    <div className="livepage">
      <ProjectBar project={going ? runProject : selected} tab="live" locked={going} />
      {!going && !runnable && <NoSim sim={projects.find((p) => p.kind === "sim")} />}
      {!going && runnable && !finished && <StartForm key={selected?.id ?? "none"} project={selected} health={health} again={false} judge={operator.role === "judge"} send={send} />}
      {!going && runnable && finished && (
        <details className="runagain">
          <summary className="btn ghost">Run again</summary>
          <StartForm key={selected?.id ?? "none"} project={selected} health={health} again judge={operator.role === "judge"} send={send} />
        </details>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {!state.meta && state.events.filter((e) => e.type === "message").map((e) => <p key={e.t} className="error" role="alert">{e.payload.text}</p>)}
      {state.meta && <AgentRun key={state.meta.run_id} state={state} send={send} over={!going} />}
    </div>
  );
}

function NoSim({ sim }: { sim?: Project }) {
  return (
    <div className="empty rise">
      <h2>This project has no sim device</h2>
      {sim && <a className="btn accent" href={`#/live?project=${sim.id}`}>Run {sim.name}</a>}
    </div>
  );
}

function StartForm({ project, health, again, judge, send }: { project?: Project; health: AgentHealth; again: boolean; judge: boolean; send: Send }) {
  const sim = project?.sim;
  const [seed, setSeed] = useState("");
  const [fault, setFault] = useState(sim?.fault ?? "");
  const revs = revisionsOf(project);
  const [rev, setRev] = useState(sim?.rev ?? revs[0] ?? "");
  const [effector, setEffector] = useState("stock");
  const [placement, setPlacement] = useState("nominal");
  const [model, setModel] = useState(health.models.includes(DEFAULT_MODEL) ? DEFAULT_MODEL : health.models[0] ?? "");
  const [maxTurns, setMaxTurns] = useState(String(MAX_TURNS));
  const [errorRate, setErrorRate] = useState("5");
  const [errorSeed, setErrorSeed] = useState("");
  const [auto, setAuto] = useState(false);
  const [speed, setSpeed] = useState("4");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    send("/start", startBody(project, { seed, fault, rev, effector, placement, route: "rgb", model, speed, maxTurns, errorRate, errorSeed, auto }));
  };
  return (
    <form className="panel rise startpanel" onSubmit={submit}>
      <h2>{again ? "Run again" : "Start a run"}</h2>
      {!project && <div className="field">
        <label className="label" htmlFor="a-seed">Device seed</label>
        <input id="a-seed" className="tech" inputMode="numeric" pattern="[0-9]*" required value={seed} placeholder="1401" onChange={(e) => setSeed(e.target.value)} />
      </div>}
      {sim?.path && <div className="field">
        <label className="label" htmlFor="a-rev">Revision</label>
        <select id="a-rev" value={rev} onChange={(e) => setRev(e.target.value)}>{revs.map((r) => <option key={r} value={r}>{r}</option>)}</select>
      </div>}
      {sim?.path && <div className="field">
        <label className="label" htmlFor="a-effector">Effector</label>
        <select id="a-effector" value={effector} onChange={(e) => setEffector(e.target.value)}><option value="stock">SO-101 gripper</option><option value="probe">Probe (sim only)</option></select>
      </div>}
      {!sim?.path && <div className="field">
        <label className="label" htmlFor="a-fault">Planted fault</label>
        <input id="a-fault" className="tech" value={fault} placeholder="None" onChange={(e) => setFault(e.target.value)} />
      </div>}
      <div className="field">
        <label className="label" htmlFor="a-place">Placement</label>
        <select id="a-place" value={placement} onChange={(e) => setPlacement(e.target.value)}><option value="nominal">Nominal</option><option value="random">Random</option></select>
      </div>
      <div className="field">
        <label className="label" htmlFor="a-model">Model</label>
        <select id="a-model" value={model} onChange={(e) => setModel(e.target.value)}>{health.models.map((m) => <option key={m} value={m}>{m}</option>)}</select>
      </div>
      <div className="field">
        <label className="label" htmlFor="a-turns">Turn limit</label>
        <input id="a-turns" className="tech" type="number" min="1" max={MAX_TURNS} step="1" required value={maxTurns} onChange={(e) => setMaxTurns(e.target.value)} />
      </div>
      <div className="field">
        <label className="label" htmlFor="a-rate">Arm error rate, %</label>
        <input id="a-rate" className="tech" type="number" min="0" max="100" step="1" required value={errorRate} onChange={(e) => setErrorRate(e.target.value)} />
      </div>
      <div className="field">
        <label className="label" htmlFor="a-eseed">Error seed</label>
        <input id="a-eseed" className="tech" inputMode="numeric" pattern="[0-9]*" value={errorSeed} placeholder="Random" onChange={(e) => setErrorSeed(e.target.value)} />
      </div>
      <div className="field">
        <label className="label" htmlFor="a-speed">Sim speed</label>
        <select id="a-speed" value={speed} onChange={(e) => setSpeed(e.target.value)}><option value="1">1x</option><option value="4">4x</option><option value="8">8x</option><option value="0">As fast as it goes</option></select>
      </div>
      <label className="agentcheck"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Auto-approve plans</label>
      <div className="row">
        <button className="btn accent" type="submit" disabled={judge} title={judge ? "Judges can steer but can't start a run" : undefined}>Start run</button>
      </div>
    </form>
  );
}

/** A saved model run, through the same view as a live one. */
export function AgentReplay({ id }: { id: string }) {
  const { env } = useAppSession();
  const { runs, ready } = useRuns(env);
  const run = runs.find((r) => r.id === id);
  const replay = useReplay(run);
  if (!run) return <div className="page"><div className="empty"><h2>{ready ? `No run called ${id}` : "Loading"}</h2></div></div>;
  return (
    <div className="livepage">
      <AgentRun state={replay.state as AgentState} sim={false} bar={(
        <div className="replaybar agentreplay">
          <button className="btn ghost" type="button" onClick={() => { if (replay.at >= replay.total) replay.seek(1); replay.setPlaying(!replay.playing || replay.at >= replay.total); }}>{replay.playing && replay.at < replay.total ? "Pause" : "Play"}</button>
          <input type="range" aria-label="Position in the run" min={1} max={replay.total} value={replay.at} onChange={(e) => { replay.setPlaying(false); replay.seek(Number(e.target.value)); }} />
          <div className="seg" role="group" aria-label="Speed">{[1, 2, 4].map((r) => <button key={r} type="button" aria-pressed={replay.speed === r} onClick={() => replay.setSpeed(r)}>{r}x</button>)}</div>
        </div>
      )} />
    </div>
  );
}
