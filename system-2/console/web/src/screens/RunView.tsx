import { ProjectBar } from "../components/ProjectBar";
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { EditForm } from "../components/EditForm";
import { ExplorationGraph } from "../components/ExplorationGraph";
import { ForceChart, type Series } from "../components/ForceChart";
import { ModelTrace, TraceSummary } from "../components/ModelTrace";
import { HBar, Pill, Stat, downloadText, stagger } from "../components/ui";
import { useAppSession, useRuns } from "../lib/context";
import { ACTION_LABEL, useEdits, type OperatorEdit } from "../lib/edits";
import { addEdits, buildGraph, type GraphNode, recordOfNode, stepNodeId } from "../lib/graph";
import { markAt, recordedNodes, videoMarks } from "../lib/live";
import { projectOf, useProjects } from "../lib/projects";
import type { Route } from "../lib/route";
import { ReplayClock, ReplaySource } from "../lib/simsource";
import type { SimFocus } from "../components/Sim3D";
import { coverageOf, describeEvent, nextRevision, statusOfControl, type Run, type StepRecord } from "../lib/runs";

const Sim3D = lazy(() => import("../components/Sim3D"));

const SECTIONS = [["trace", "Diagnosis"], ["bugs", "Bugs"], ["patch", "Patches"], ["report", "Report"], ["decisions", "Decisions"], ["plan", "Plan"], ["log", "Event log"]] as const;

/** One run, one page: click anything and the video and its numbers come to it, with nothing else to open. */
export function RunView({ route }: { route: Route }) {
  const { env } = useAppSession();
  const { runs, ready } = useRuns(env);
  const run = runs.find((r) => r.id === route.parts[1]);
  const allEdits = useEdits(env);

  if (!run) {
    if (!ready) return <div className="sweep" role="status" aria-label="Loading the run" />;
    return <div className="page"><div className="empty"><h2>This run isn't available in {env}</h2><a className="btn ghost" style={{ alignSelf: "flex-start" }} href="#/runs">Back to runs</a></div></div>;
  }
  return <RunPage key={run.id} run={run} runs={runs} edits={allEdits.filter((e) => e.runId === run.id)} route={route} />;
}

function RunPage({ run, runs, edits, route }: { run: Run; runs: Run[]; edits: OperatorEdit[]; route: Route }) {
  const project = projectOf(run, useProjects());
  const next = nextRevision(runs, run);
  const nodes = useMemo(() => run.recording
    ? addEdits(recordedNodes(run), run.id, edits)
    : buildGraph(run, next, edits), [run, next, edits]);
  const marks = useMemo(() => (run.recording ? videoMarks(run) : []), [run]);
  const video = useRef<Playable | null>(null);
  const stopAt = useRef<number | null>(null); // the end of what someone clicked: it plays once, so it can be read
  const firstFail = run.findings[0]?.step_ids[0];
  const [selected, setSelected] = useState<string | null>(run.recording ? marks[0]?.id ?? null : firstFail ?? run.steps[0]?.step.id ?? null);
  const [at, setAt] = useState(1); // the event the run is showing, for a run with no video
  const [pinned, setPinned] = useState(false); // what someone clicked stays put while the video plays on
  const node = nodes.find((n) => n.id === selected);
  const hasTrace = run.events.some((e) => e.type === "tool_call" || e.type === "model_turn");

  const scrollTo = (id: string) => document.getElementById(`sec-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  const seekVideo = (t: number) => {
    const el = video.current;
    if (!el) return;
    el.currentTime = t;
    void el.play().catch(() => undefined);
  };
  /** Go to an event: the video jumps there, or the event playback does. */
  const seekSeq = (seq: number) => {
    setAt(seq);
    const t = run.recording?.timeline.events[String(seq)];
    if (t !== undefined) seekVideo(t);
    const owner = run.steps.find((s) => s.startSeq <= seq && (s.endSeq ?? Infinity) >= seq);
    if (owner) { setSelected(stepNodeId(run, run.steps.indexOf(owner))); setPinned(true); }
    document.querySelector(".main")?.scrollTo({ top: 0, behavior: "smooth" });
  };
  const pick = (id: string) => {
    setSelected(id);
    setPinned(true);
    const mark = marks.find((m) => m.id === id);
    stopAt.current = mark ? marks[marks.indexOf(mark) + 1]?.t ?? null : null;
    if (mark) seekVideo(mark.t);
    else {
      const seq = nodes.find((n) => n.id === id)?.seq;
      if (seq) { setAt(seq); const t = run.recording?.timeline.events[String(seq)]; if (t !== undefined) seekVideo(t); }
    }
  };

  const pinnedRef = useRef(pinned);
  pinnedRef.current = pinned;
  const follow = useCallback((id: string) => { if (!pinnedRef.current) setSelected(id); }, []);

  // Links from elsewhere, like a bug's event, land on the right spot of this page.
  const wantSeq = Number(route.query.get("seq")) || 0, wantSection = route.parts[2];
  useEffect(() => {
    if (wantSeq) seekSeq(wantSeq);
    else if (SECTIONS.some(([id]) => id === wantSection)) window.setTimeout(() => scrollTo(wantSection), 120);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wantSeq, wantSection]);

  return (
    <div className="runpage">
      {project && <ProjectBar project={project} />}
      <div className="runtop">
        <h1 className="title">{run.product}</h1>
        <span className="mono muted">Rev {run.revision} / {run.id} / {run.status}</span>
        <span className="spacer" style={{ flex: 1 }} />
        {run.events.some((e) => e.type === "model_turn") && <a className="btn ghost" href={`#/live?replay=${run.id}`}>Watch the model</a>}
        <span className="display" style={{ fontSize: 20 }}>REWARD {run.report.reward.value.toFixed(2)}</span>
      </div>

      <div className="workspace">
        {run.recording?.assets
          ? <ReplayPlayer ref_={video} stopAt={stopAt} run={run} marks={marks} selected={selected} onPick={pick} onFollow={follow} />
          : run.recording ? <VideoPlayer ref_={video} stopAt={stopAt} run={run} marks={marks} selected={selected} onPick={pick} onFollow={follow} />
          : <EventPlayer run={run} next={next} at={at} setAt={setAt} onPick={setSelected} />}
        <aside className="inspector" aria-label="Details">
          {node ? <Inspector node={node} run={run} edits={edits.filter((e) => e.nodeId === node.id)} marks={marks} onAdded={(id) => setSelected(`edit-${id}`)} onSeek={seekSeq} onFollow={run.recording && pinned ? () => { setPinned(false); stopAt.current = null; void video.current?.play().catch(() => undefined); } : undefined} /> : <p className="muted">Click a stage or step.</p>}
        </aside>
      </div>

      <ExplorationGraph live={!!run.recording} nodes={nodes} selected={selected} onSelect={pick} />
      <div className="legend">
        <span><i />Happened</span>
        <span><i style={{ borderTopStyle: "dashed", borderTopColor: "var(--accent)" }} />An operator's edit</span>
        <span>Heavy border and ✕: failed</span>
      </div>

      <nav className="jumpbar" aria-label="On this page">
        {SECTIONS.filter(([id]) => (id === "bugs" ? run.findings.length > 0 : id === "patch" ? run.proposed.length > 0 : id === "trace" ? hasTrace : true)).map(([id, label]) => <button key={id} type="button" onClick={() => scrollTo(id)}>{label}</button>)}
      </nav>

      {hasTrace && <section className="runsec" id="sec-trace"><h2>Diagnosis</h2><TraceSummary run={run} nodes={nodes.map((n) => n.id)} onPick={(id) => { pick(id); document.querySelector(".main")?.scrollTo({ top: 0, behavior: "smooth" }); }} /></section>}
      {run.findings.length > 0 && <section className="runsec" id="sec-bugs"><h2>Bugs</h2><Bugs run={run} edits={edits} onSeek={seekSeq} /></section>}
      {run.proposed.length > 0 && <section className="runsec" id="sec-patch"><h2>Patches</h2><Patches run={run} /></section>}
      <section className="runsec" id="sec-report"><h2>Report</h2><ReportBlock run={run} edits={edits} /></section>
      <section className="runsec" id="sec-decisions"><h2>Decisions</h2><Decisions run={run} runs={runs} edits={edits} onSeek={seekSeq} /></section>
      <section className="runsec" id="sec-plan"><h2>Plan</h2><PlanBlock run={run} edits={edits} onSeek={seekSeq} /></section>
      <section className="runsec" id="sec-log"><h2>Event log</h2><EventLog run={run} at={at} onSeek={seekSeq} /></section>
    </div>
  );
}

const RATES = [0.5, 1, 2, 4];

/** What the run page needs from a player: a video element has all this, and so does a ReplayClock. */
type Playable = Pick<HTMLVideoElement, "currentTime" | "paused" | "playbackRate" | "pause"> & { play(): Promise<void> };
type PlayerProps = { ref_: React.RefObject<Playable | null>; stopAt: React.RefObject<number | null>; run: Run; marks: { id: string; t: number }[]; selected: string | null; onPick: (id: string) => void; onFollow: (id: string) => void };

/** Stops at the end of what someone clicked. timeupdate fires too rarely for a step that lasts under a second. */
function useStopAt(ref_: PlayerProps["ref_"], stopAt: PlayerProps["stopAt"]) {
  useEffect(() => {
    let frame = 0;
    const watch = () => {
      const v = ref_.current, end = stopAt.current;
      if (v && end !== null && !v.paused && v.currentTime >= end) {
        v.pause();
        v.currentTime = Math.max(0, end - 0.05);
        stopAt.current = null;
      }
      frame = requestAnimationFrame(watch);
    };
    frame = requestAnimationFrame(watch);
    return () => cancelAnimationFrame(frame);
  }, [ref_, stopAt]);
}

function Stagebar({ run, marks, selected, onPick }: Pick<PlayerProps, "run" | "marks" | "selected" | "onPick">) {
  const timeline = run.recording!.timeline;
  const bars = marks.filter((m) => m.id.startsWith("stage-") || m.id === "approve");
  const widths = bars.map((m, i) => (bars[i + 1]?.t ?? timeline.duration) - m.t);
  const current = selected && bars.some((b) => b.id === selected) ? selected : recordOfNode(run, selected ?? "") ? "approve" : null;
  return (
    <div className="stagebar" aria-label="Stages">
      {bars.map((m, i) => (
        <button key={m.id} type="button" className={m.id === current ? "now" : ""} style={{ flexGrow: Math.max(widths[i], 1) }} onClick={() => onPick(m.id)}>
          {m.id === "approve" ? "Test" : m.id.slice(6, 7) + m.id.slice(7).toLowerCase()}<span>{m.t.toFixed(0)} s</span>
        </button>
      ))}
    </div>
  );
}

/** A recorded run in the real 3D view, drawn in this browser from its saved poses, beside its wrist camera. */
function ReplayPlayer({ ref_, stopAt, run, marks, selected, onPick, onFollow }: PlayerProps) {
  const { timeline, assets } = run.recording!;
  const clock = useMemo(() => new ReplayClock(timeline.duration), [timeline.duration]);
  const source = useMemo(() => new ReplaySource(assets!, clock, timeline.fps), [assets, clock, timeline.fps]);
  const [rate, setRate] = useState(1);
  const [now, setNow] = useState(0);
  const [paused, setPaused] = useState(false);
  const [no3D, setNo3D] = useState(false);
  const unavailable = useCallback(() => setNo3D(true), []);
  const cameras = useRef<HTMLVideoElement>(null);
  useStopAt(ref_, stopAt);
  useEffect(() => { ref_.current = clock; void clock.play(); return () => { ref_.current = null; clock.pause(); }; }, [clock, ref_]);
  useEffect(() => { clock.playbackRate = rate; }, [clock, rate]);

  // The play head leads: the cameras' video follows it, and so do the graph and the numbers.
  useEffect(() => {
    let last = -1;
    const tick = window.setInterval(() => {
      const t = clock.currentTime, video = cameras.current;
      setPaused(clock.paused);
      if (Math.abs(t - last) > 0.03) { setNow(t); last = t; }
      if (!clock.paused) { const id = markAt(marks, t); if (id) onFollow(id); }
      if (video) {
        video.playbackRate = clock.playbackRate;
        if (Math.abs(video.currentTime - t) > 0.35) video.currentTime = t;
        if (clock.paused && !video.paused) video.pause();
        else if (!clock.paused && video.paused) void video.play().catch(() => undefined);
      }
    }, 120);
    return () => window.clearInterval(tick);
  }, [clock, marks, onFollow]);

  const focusAt = useMemo(() => {
    const at = (seq?: number) => (seq === undefined ? Infinity : timeline.events[String(seq)] ?? Infinity);
    const steps = run.steps.map((s) => ({ s, from: at(s.startSeq), to: at(s.endSeq) }));
    const lcd = timeline.lcd ?? [];
    return (): SimFocus => {
      const t = clock.currentTime;
      const active = steps.find(({ from, to }) => t >= from && t < to)?.s;
      const done = [...steps].reverse().find(({ to }) => to <= t)?.s;
      return {
        target: active?.step.target ?? null, label: active ? `${active.step.target} / ${active.step.skill}` : null,
        verdict: done?.verdict ? `${done.step.id}:${done.verdict.status}` : null,
        force: source.force(t), limit: Number(active?.step.params.force_limit) || 6,
        lcd: [...lcd].reverse().find((l) => l.t <= t)?.lines ?? [],
      };
    };
  }, [clock, run.steps, source, timeline]);

  return (
    <div className="player">
      <div className="replay">
        <div className="replay3d">
          <Suspense fallback={<div className="simloading"><div className="sweep" /></div>}>{no3D ? <p className="note simnote">This browser can't draw 3D. The cameras still play.</p> : <Sim3D source={source} focusAt={focusAt} onUnavailable={unavailable} />}</Suspense>
        </div>
        <div className="wristclip"><video ref={cameras} src={assets!("cameras.mp4")} muted playsInline aria-label="The wrist camera" /></div>
      </div>
      <div className="replaybar">
        <button type="button" className="btn ghost" onClick={() => { if (clock.paused) { stopAt.current = null; void clock.play(); } else clock.pause(); }}>{paused ? "Play" : "Pause"}</button>
        <input type="range" aria-label="Position in the run" min={0} max={timeline.duration} step={0.05} value={now} onChange={(e) => { stopAt.current = null; clock.currentTime = Number(e.target.value); setNow(Number(e.target.value)); }} />
        <span className="mono muted">{now.toFixed(1)} / {timeline.duration.toFixed(1)} s</span>
      </div>
      <Stagebar run={run} marks={marks} selected={selected} onPick={onPick} />
      <div className="playctl">
        <div className="seg" role="group" aria-label="Playback speed">{RATES.map((r) => <button key={r} type="button" aria-pressed={r === rate} onClick={() => setRate(r)}>{r}x</button>)}</div>
        <span className="note">{timeline.meta.route}</span>
      </div>
    </div>
  );
}

/** A recording from before replays were 3D. */
function VideoPlayer({ ref_, stopAt, run, marks, selected, onPick, onFollow }: PlayerProps) {
  const timeline = run.recording!.timeline;
  const [rate, setRate] = useState(1);
  const element = useRef<HTMLVideoElement | null>(null);
  useEffect(() => { if (element.current) element.current.playbackRate = rate; }, [rate]);
  useStopAt(ref_, stopAt);
  return (
    <div className="player">
      <video ref={(v) => { element.current = v; ref_.current = v; }} src={run.recording!.video} controls autoPlay muted playsInline
        onTimeUpdate={(e) => { if (!e.currentTarget.paused) { const id = markAt(marks, e.currentTarget.currentTime); if (id) onFollow(id); } }} />
      <Stagebar run={run} marks={marks} selected={selected} onPick={onPick} />
      <div className="playctl">
        <div className="seg" role="group" aria-label="Playback speed">{RATES.map((r) => <button key={r} type="button" aria-pressed={r === rate} onClick={() => setRate(r)}>{r}x</button>)}</div>
        <span className="note">{timeline.meta.route}</span>
      </div>
    </div>
  );
}

function EventPlayer({ run, next, at, setAt, onPick }: { run: Run; next?: Run; at: number; setAt: (n: number) => void; onPick: (id: string) => void }) {
  const max = run.events.length;
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!playing) return;
    if (at >= max) { setPlaying(false); return; }
    const timer = window.setTimeout(() => {
      const seq = at + 1;
      setAt(seq);
      const step = [...run.steps].reverse().find((s) => s.startSeq <= seq);
      if (step) onPick(stepNodeId(run, run.steps.indexOf(step)));
    }, 420);
    return () => window.clearTimeout(timer);
  }, [playing, at, max, run, setAt, onPick]);
  const cov = coverageOf(run, at);
  const event = run.events[Math.min(at, max) - 1];
  const stages: [string, string, string][] = [
    ["Perceive", `${run.scene.controls.length} controls`, "scene"], ["Plan", `${run.plan.steps.length} steps`, "plan"],
    ["Test", `${run.report.coverage.passed.length} passed, ${run.report.coverage.failed.length} failed`, run.steps[0]?.step.id ?? "plan"],
  ];
  if (run.findings[0]) stages.push(["Report", `${run.findings.length} findings`, run.findings[0].id]);
  if (run.applied.length) stages.push(["Fix", `${run.applied.length} patches`, "apply"]);
  if (next) stages.push(["Retest", `Rev ${next.revision}: ${next.report.reward.value.toFixed(2)}`, "retest"]);
  return (
    <div className="player">
      <div className="stagebar">{stages.map(([name, sub, id]) => <button key={name} type="button" onClick={() => onPick(id)}>{name}<span>{sub}</span></button>)}</div>
      <div className="novideo">
        <div className="row">
          <button className="btn" type="button" onClick={() => { if (at >= max) setAt(1); setPlaying(!playing); }}>{playing ? "Pause" : at >= max ? "Replay from start" : "Play"}</button>
          <span className="mono muted">Event {at} of {max}</span>
        </div>
        <input className="scrub" type="range" min={1} max={max} value={at} aria-label="Event in the run" onChange={(e) => { setPlaying(false); setAt(Number(e.target.value)); }} />
        <p>{describeEvent(event)}</p>
        <div className="chips">{run.scene.controls.map((c) => <Pill key={c.id} status={statusOfControl(cov, c.id)}>{c.id}</Pill>)}</div>
        <p className="note">Mock data, no video.</p>
      </div>
    </div>
  );
}

function traceSeries(record: StepRecord, tone: Series["tone"]): Series | null {
  const points = record.trace?.force_trace;
  if (!points?.length) return null;
  return { name: record.step.target, points: points.map(([t, n]) => [t - points[0][0], n] as [number, number]), tone };
}

function EditList({ edits }: { edits: OperatorEdit[] }) {
  if (!edits.length) return null;
  return (
    <>
      {edits.map((e) => (
        <div key={e.id} className={`editrow rise ${e.state === "withdrawn" ? "withdrawn" : ""}`}>
          <div className="row"><span className="label">{e.id} / {ACTION_LABEL[e.action]} / {e.by}</span><Pill status={e.state}>{e.state}</Pill></div>
          <span>“{e.reason}”</span>
        </div>
      ))}
    </>
  );
}

/** Everything known about whatever was clicked. */
function Inspector({ node, run, edits, marks, onAdded, onSeek, onFollow }: { node: GraphNode; run: Run; edits: OperatorEdit[]; marks: { id: string; t: number }[]; onAdded: (id: string) => void; onSeek: (seq: number) => void; onFollow?: () => void }) {
  const record = recordOfNode(run, node.id);
  const finding = run.findings.find((f) => f.id === node.id);
  const cause = finding ? run.causes.find((c) => c.finding === finding.id) : undefined;
  const series = record ? traceSeries(record, record.verdict?.status === "failed" ? "fail" : "pass") : null;
  const editable = !!node.target && node.provenance === "log";
  const times = run.recording?.timeline.events;
  const index = marks.findIndex((m) => m.id === node.id);
  // What the sim said while this was happening.
  const lines = useMemo(() => {
    if (!times || index < 0) return [];
    const from = marks[index].t, to = marks[index + 1]?.t ?? Infinity;
    return run.events.filter((e) => e.type === "message" && (times[String(e.seq)] ?? -1) >= from && (times[String(e.seq)] ?? -1) < to);
  }, [run, times, marks, index]);
  const seconds = index >= 0 && run.recording ? (marks[index + 1]?.t ?? run.recording.timeline.duration) - marks[index].t : null;

  return (
    <div className="stack rise" key={node.id}>
      <div className="row">
        <h2 style={{ marginRight: "auto" }}>{node.title}</h2>
        {node.status && node.status !== "pending" && node.status !== "running" && <Pill status={node.status} />}
        {onFollow && <button className="linkbtn" type="button" onClick={onFollow}>Follow the video</button>}
      </div>
      <dl className="kv">
        {node.tier && <><dt>Fix tier</dt><dd>{node.tier}</dd></>}
        {node.target && <><dt>Control</dt><dd className="mono">{node.target}</dd></>}
        {record && <><dt>Skill</dt><dd className="mono">{record.step.skill}</dd></>}
        {record?.verdict && <><dt>Result</dt><dd>{record.verdict.reason}</dd><dt>Decided by</dt><dd>{record.verdict.decided_by}, not a person or the planner</dd></>}
        {record?.trace?.peak_force_n != null && <><dt>Measured</dt><dd className="mono">{record.trace.peak_force_n.toFixed(1)} N peak{record.trace.travel_mm != null ? `, ${record.trace.travel_mm.toFixed(1)} mm travel` : ""}{record.trace.stop_reason ? `, stopped on ${record.trace.stop_reason}` : ""}</dd></>}
        {record?.trace?.duration_s != null && <><dt>Took</dt><dd className="mono">{record.trace.duration_s.toFixed(1)} s of sim time</dd></>}
        {!record && !finding && node.sub && <><dt>Detail</dt><dd>{node.sub}</dd></>}
        {seconds !== null && <><dt>In the video</dt><dd className="mono">{marks[index].t.toFixed(1)} s, for {seconds.toFixed(1)} s</dd></>}
        {finding && <><dt>What happened</dt><dd>{finding.what_happened}</dd><dt>Severity</dt><dd className="mono">{finding.severity}</dd></>}
        {cause && <><dt>Root cause</dt><dd>{cause.root_cause}</dd></>}
        {node.reason && <><dt>Reason</dt><dd>“{node.reason}”{node.by ? `, ${node.by}` : ""}</dd></>}
        {node.id === "stage-REPORT" && <><dt>Summary</dt><dd>{run.report.summary}</dd></>}
        {node.linkRun && <><dt>Run</dt><dd><a href={`#/run/${node.linkRun}`}>Open {node.linkRun}</a></dd></>}
      </dl>
      <ModelTrace run={run} node={node.id} />
      {series
        ? <ForceChart key={node.id} series={[series]} limit={Number(record?.step.params.force_limit) || undefined} />
        : record && <p className="note">This step logged no force samples.</p>}
      {node.id.endsWith("PLAN") && run.plan.steps.length > 0 && <ol className="minilog">{run.plan.steps.map((s) => <li key={s.id}>{s.id} {s.skill} {s.target}</li>)}</ol>}
      {(node.id === "stage-MAP" || node.id === "scene") && run.scene.controls.length > 0 && <div className="chips">{run.scene.controls.map((c) => <Pill key={c.id} status={statusOfControl(run.report.coverage, c.id)}>{c.id}</Pill>)}</div>}
      {lines.length > 0 && <><span className="label">What the sim logged</span><ol className="minilog">{lines.map((e) => <li key={e.seq}>{e.payload.text}</li>)}</ol></>}
      {!run.recording && node.seq && <button className="linkbtn" type="button" style={{ alignSelf: "flex-start" }} onClick={() => onSeek(node.seq!)}>Show event {node.seq}</button>}
      {edits.length > 0 && <EditList edits={edits} />}
      {editable && <EditForm runId={run.id} nodeId={node.id} target={node.target ?? null} skill={record?.step.skill} onAdded={onAdded} />}
    </div>
  );
}

function Bugs({ run, edits, onSeek }: { run: Run; edits: OperatorEdit[]; onSeek: (seq: number) => void }) {
  const kind = (id: string) => run.scene.controls.find((c) => c.id === id)?.kind;
  return (
    <div className="grid2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(420px, 100%), 1fr))" }}>
      {run.findings.map((f, i) => {
        const record = run.steps.find((s) => s.step.id === f.step_ids[0]);
        const sibling = run.steps.find((s) => s.verdict?.status === "passed" && kind(s.step.target) === kind(f.target));
        const series = [record && traceSeries(record, "fail"), sibling && traceSeries(sibling, "pass")].filter(Boolean) as Series[];
        const cause = run.causes.find((c) => c.finding === f.id);
        const patch = cause ? run.proposed[run.causes.indexOf(cause)] : undefined;
        const related = edits.filter((e) => e.target === f.target);
        return (
          <article className="panel rise" key={f.id} style={stagger(i)}>
            <div className="row"><span className="label" style={{ marginRight: "auto" }}>{f.id} / {f.target} / {f.label}</span><Pill status="failed">{f.severity}</Pill></div>
            <h3 className="sentence">{f.what_happened}</h3>
            <dl className="kv">
              {f.manual_says && <><dt>Manual says</dt><dd>{f.manual_says}</dd></>}
              {record?.trace && <><dt>Measured</dt><dd className="mono">{record.trace.peak_force_n} N peak, {record.trace.travel_mm} mm travel, stopped on {record.trace.stop_reason}</dd></>}
              {record?.verdict && <><dt>Decided by</dt><dd>{record.verdict.decided_by}</dd></>}
              <dt>Evidence</dt><dd className="mono">{f.evidence.join(", ") || "–"}</dd>
            </dl>
            <div className="row"><button className="btn accent" type="button" onClick={() => onSeek(f.event_seqs[0])}>Go to the failure</button></div>
            {series.length
              ? <ForceChart key={f.id} series={series} limit={Number(record?.step.params.force_limit) || undefined} />
              : <p className="note">This step logged no force samples, only its peak of {record?.trace?.peak_force_n} N.</p>}
            {cause && <>
              <h3>Root cause</h3>
              <p>{cause.root_cause}</p>
              {patch && patch.changes.map((c) => <p className="mono" key={c.param}>{c.param}: <span className="old">{String(c.from_value)}</span> → {String(c.to_value)}{c.unit ? ` ${c.unit}` : ""}. Predicted: {c.predicted}</p>)}
            </>}
            {related.length > 0 && <><h3>Operator edits on {f.target}</h3><EditList edits={related} /></>}
          </article>
        );
      })}
    </div>
  );
}

function Patches({ run }: { run: Run }) {
  return (
    <div className="grid2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(420px, 100%), 1fr))" }}>
      {run.proposed.map((p, i) => {
        const cause = run.causes[i];
        const applied = run.applied.some((a) => a.changes[0]?.param === p.changes[0]?.param);
        return (
          <article className="panel rise" key={p.seq} style={stagger(i)}>
            <div className="row"><h3 style={{ marginRight: "auto" }}>Patch for {cause?.finding}</h3><Pill status={applied ? "approved" : "planned"}>{applied ? "Applied" : "Proposed"}</Pill></div>
            {cause && <p>{cause.root_cause}</p>}
            {p.changes.map((c) => <p className="mono" key={c.param}>{c.param}: <span className="old">{String(c.from_value)}</span> → {String(c.to_value)}{c.unit ? ` ${c.unit}` : ""}</p>)}
            <dl className="kv">
              <dt>Predicted</dt><dd>{p.changes[0]?.predicted}</dd>
              <dt>Rerun</dt><dd className="mono">{p.verify_with.join(", ")}</dd>
              <dt>Approved by</dt><dd>{run.approvals.find((a) => a.kind === "patch" && a.seq > p.seq)?.by ?? "No one yet"}</dd>
              <dt>Cost</dt><dd>A reprint takes about 15 to 40 minutes (docs/product.md).</dd>
              <dt>Backend</dt><dd className="mono">{p.backend}</dd>
            </dl>
            <div className="row"><a className="btn ghost" href="#/design-analysis">Open in Design Analysis</a></div>
          </article>
        );
      })}
    </div>
  );
}

function ReportBlock({ run, edits }: { run: Run; edits: OperatorEdit[] }) {
  const { env } = useAppSession();
  const cov = run.report.coverage;
  const live = edits.filter((e) => e.state !== "withdrawn");
  const exportReport = () => downloadText(`${run.id}-report.json`, JSON.stringify({ ...run.report, operator_edits: live, environment: env }, null, 2));
  return (
    <>
      <div className="row"><p style={{ marginRight: "auto", fontSize: 19 }}>{run.report.summary}</p><button className="btn ghost" type="button" onClick={exportReport}>Export JSON</button></div>
      <div className="stats">
        <Stat label="Reward" value={run.report.reward.value} i={0} />
        <Stat label="Coverage" value={run.report.reward.control_coverage} i={1} />
        <Stat label="Pass rate" value={run.report.reward.pass_rate} i={2} />
        <Stat label="Controls" value={cov.detected} digits={0} i={3} />
        <Stat label="Crossings" value={run.events.filter((e) => e.type === "crossing").length} digits={0} i={4} />
      </div>
      <div className="grid2">
        <div className="panel rise" style={stagger(4)}>
          <div className="scrollx"><table>
            <thead><tr><th>Control</th><th>Kind</th><th>Result</th><th>Finding</th><th>Edits</th></tr></thead>
            <tbody>{run.scene.controls.map((c) => {
              const finding = run.findings.find((f) => f.target === c.id);
              const related = live.filter((e) => e.target === c.id);
              return <tr key={c.id}><td className="n">{c.id}</td><td className="n">{c.kind}</td><td><Pill status={c.id in cov.skipped ? "skipped" : statusOfControl(cov, c.id)} /></td><td className="n">{finding?.id ?? "–"}</td><td className="n">{related.map((e) => e.id).join(" ") || "–"}</td></tr>;
            })}</tbody>
          </table></div>
        </div>
        <div className="stack">
          <div className="panel rise" style={stagger(6)}>
            <span className="note">{run.report.reward.formula}</span>
            <h3>Operator edits</h3>
            <EditList edits={live} />
          </div>
        </div>
      </div>
    </>
  );
}

function Decisions({ run, runs, edits, onSeek }: { run: Run; runs: Run[]; edits: OperatorEdit[]; onSeek: (seq: number) => void }) {
  const rows = [
    ...run.approvals.map((a) => ({ seq: a.seq, what: `Approve ${a.kind}`, who: a.by, why: a.ref })),
    ...run.steps.filter((s) => s.verdict).map((s) => ({ seq: s.endSeq!, what: `${s.step.id} ${s.verdict!.status}`, who: s.verdict!.decided_by, why: s.verdict!.reason })),
    ...run.causes.map((c) => ({ seq: c.seq, what: `Root cause for ${c.finding}`, who: "analyst (scripted mock)", why: c.root_cause })),
    ...(run.recording ? [] : run.messages.map((m) => ({ seq: m.seq, what: "Keep or roll back", who: m.role, why: m.text }))),
  ].sort((a, b) => a.seq - b.seq);
  void runs; void edits;
  return (
    <div className="decisiongrid">
      <div className="panel rise">
        <div className="scrollx"><table className="decisions">
          <thead><tr><th>Event</th><th>Decision</th><th>Decided by</th><th>Basis</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.seq} className="link" onClick={() => onSeek(r.seq)}><td className="n">{r.seq}</td><td className="n">{r.what}</td><td className="n">{r.who}</td><td>{r.why}</td></tr>)}</tbody>
        </table></div>
      </div>
      <div className="stack">
        {run.causes.map((c, i) => (
          <div className="panel rise" key={c.finding} style={stagger(i)}>
            <h3>Hypotheses for {c.finding}</h3>
            {c.hypotheses.map((h, n) => <HBar key={h.cause} label={<>{h.cause}{h.ruled_out && <span className="muted">, ruled out</span>}</>} value={h.p} i={n} />)}
          </div>
        ))}
      </div>
    </div>
  );
}

function PlanBlock({ run, edits, onSeek }: { run: Run; edits: OperatorEdit[]; onSeek: (seq: number) => void }) {
  const approval = run.approvals.find((a) => a.kind === "plan");
  return (
    <>
      <div className="row"><span className="mono muted" style={{ marginRight: "auto" }}>{run.plan.plan_id}, source: {run.plan.source}</span><Pill status="approved">Approved by {approval?.by ?? "no one"}</Pill></div>
      <div className="panel rise"><div className="scrollx"><table>
        <thead><tr><th>Step</th><th>Skill</th><th>Control</th><th>Limit</th><th>Expected</th><th>Manual says</th><th>Result</th><th>Edits</th></tr></thead>
        <tbody>{run.plan.steps.map((s) => {
          const done = run.steps.find((r) => r.step.id === s.id);
          const stepEdits = edits.filter((e) => e.target === s.target && e.state !== "withdrawn");
          return (
            <tr key={s.id} className="link" onClick={() => { if (done) onSeek(done.startSeq); }}>
              <td className="n">{s.id}</td><td className="n">{s.skill}</td><td className="n">{s.target}</td><td className="n">{String(s.params.force_limit ?? "–")} N</td>
              <td>{s.expected ?? "–"}</td><td className="muted">{s.quote ?? "–"}</td>
              <td>{done?.verdict ? <Pill status={done.verdict.status} /> : <Pill status="skipped">didn't run</Pill>}</td><td className="n">{stepEdits.map((e) => e.id).join(" ") || "–"}</td>
            </tr>
          );
        })}</tbody>
      </table></div></div>
      {run.scene.notes.length > 0 && <p className="note">Scene notes: {run.scene.notes.join("; ")}</p>}
    </>
  );
}

function EventLog({ run, at, onSeek }: { run: Run; at: number; onSeek: (seq: number) => void }) {
  return (
    <div className="panel rise">
      <ol className="eventlist">
        {run.events.map((e) => (
          <li key={e.seq} className={e.seq === at ? "now" : ""} onClick={() => onSeek(e.seq)}>
            <span className="seq">{e.seq}</span><span>{describeEvent(e)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
