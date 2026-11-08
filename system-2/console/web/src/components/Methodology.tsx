// Figures for the Methodology page. Each one is HTML or a narrow SVG, so it reflows at phone width instead of scrolling,
// and takes its colors from tokens.css and methodology.css, so it works in both themes.
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { runsFor } from "../lib/context";
import { ReplayClock, ReplaySource } from "../lib/simsource";
import { modelName } from "../lib/wikidata";
import type { SimFocus } from "./Sim3D";
import { RESULTS } from "./WikiSections";

const Sim3D = lazy(() => import("./Sim3D"));

const MODELS = RESULTS.models.length ? RESULTS.models : ["claude-haiku-5-5", "claude-sonnet-5-5", "openai-gpt-5.4", "grok-4.7"];

function Fig({ label, caption, className, children }: { label: string; caption?: React.ReactNode; className?: string; children: React.ReactNode }) {
  return (
    <figure className={`mfig ${className ?? ""}`} aria-label={label}>
      {children}
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

const Arrowhead = ({ id }: { id: string }) => (
  <defs><marker id={id} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8 Z" fill="currentColor" /></marker></defs>
);

// ---- 1. System Architecture --------------------------------------------------------------------------------------

const S1_LAYERS = [
  ["MCP server", "7 tools, no joint tool"],
  ["Routine engine", "explore, run_plan, home; stops"],
  ["Skills", "guarded motion, clamped to limits"],
  ["Perception · force sensing", "camera, touch, servo force"],
] as const;

export function ArchitectureFigure() {
  return (
    <Fig
      className="archfig"
      label="Layers from the frontier model down to the appliance. The model calls System 2's harness: tool belt, plan check, check-back and scorer. The harness crosses the MCP boundary with plans of skills on controls, and gets back checkpoints, evidence and verdicts. The answer key and joint or force commands never cross. Below the boundary, System 1 runs the MCP server's seven tools, the routine engine, skills, perception and force sensing, then the sim arm or the real SO-101, which touches the appliance."
      caption="Plans go down and measurements come up. Two things never cross: a command for a joint, and the answer key."
    >
      <div className="arch">
        <div className="archrow">
          <span className="archtag">Frontier model</span>
          <div className="chips">{MODELS.map((m) => <span key={m} className="chip">{modelName(m)}</span>)}</div>
        </div>
        <div className="archdown" aria-hidden="true"><i />tool calls</div>
        <div className="archsys">
          <div className="archhead"><span className="archtag">System 2 · Harness</span><span className="note">seconds per turn</span></div>
          <div className="archcells">
            <div><b>Tool belt</b><span>the model's only tools</span></div>
            <div><b>Plan check</b><span>refuses before anything moves</span></div>
            <div><b>Check-back</b><span>re-read and closing look</span></div>
            <div><b>Scorer</b><span>plain code, offline</span></div>
          </div>
        </div>
        <div className="archline">
          <span className="archlinelabel">MCP boundary</span>
          <div className="archcross">
            <span className="down">↓ plans of skills on controls</span>
            <span className="up">↑ checkpoints, evidence, verdicts</span>
            <span className="never">✕ never: the answer key, joint or force commands</span>
          </div>
        </div>
        <div className="archsys s1">
          <div className="archhead"><span className="archtag">System 1 · Robot</span><span className="note">50 Hz, needs no network</span></div>
          <ol className="archstack">
            {S1_LAYERS.map(([name, sub], i) => <li key={name} style={{ "--i": i } as React.CSSProperties}><b>{name}</b><span>{sub}</span></li>)}
            <li className="archarms" style={{ "--i": 4 } as React.CSSProperties}><div><b>Sim arm</b><span>MuJoCo</span></div><div><b>Real arm</b><span>SO-101</span></div></li>
          </ol>
        </div>
        <div className="archdown" aria-hidden="true"><i />contact</div>
        <div className="archrow appliance"><span className="archtag">Appliance</span><span className="note">the device under test</span></div>
      </div>
    </Fig>
  );
}

// ---- 3. Sensor-Grounded Verdicts ---------------------------------------------------------------------------------

export function VerdictFigure() {
  const Q = ({ y, text, sub }: { y: number; text: string; sub?: string }) => (
    <g>
      <rect className="q" x="6" y={y} width="200" height="44" rx="4" />
      <text className="t" x="16" y={y + (sub ? 19 : 27)}>{text}</text>
      {sub && <text className="sub" x="16" y={y + 36}>{sub}</text>}
    </g>
  );
  const Out = ({ y, kind, text, sub }: { y: number; kind: "pass" | "fail" | "miss" | "inc"; text: string; sub: string }) => (
    <g className={`out ${kind}`}>
      <rect x="250" y={y} width="166" height="40" rx="2" />
      <text className="v" x="259" y={y + 17}>{text}</text>
      <text className="sub" x="259" y={y + 33}>{sub}</text>
    </g>
  );
  const Side = ({ y, label }: { y: number; label: string }) => (
    <g><line className="a" x1="206" y1={y} x2="248" y2={y} markerEnd="url(#vd-arrow)" /><text className="lab" x="227" y={y - 5} textAnchor="middle">{label}</text></g>
  );
  const Down = ({ y1, y2, label }: { y1: number; y2: number; label: string }) => (
    <g><line className="a" x1="106" y1={y1} x2="106" y2={y2 - 2} markerEnd="url(#vd-arrow)" /><text className="lab" x="114" y={(y1 + y2) / 2 + 4}>{label}</text></g>
  );
  return (
    <Fig
      className="narrow"
      label="How System 1 turns measurements into a verdict. A safety stop gives inconclusive. First contact away from the part gives missed. No reading change after a real push gives fail. A reading that went the wrong way gives fail, one that changed more than the push explains gives missed, and the expected change gives pass. Missed is reported as inconclusive."
      caption="Rules in System 1's skill code, run on what the sensors measured. The model reads the verdict; it can't write one."
    >
      <svg className="mdg" viewBox="0 0 420 432" role="img" aria-labelledby="vd-title">
        <title id="vd-title">Verdict decision rules</title>
        <Arrowhead id="vd-arrow" />
        <rect className="meas" x="6" y="6" width="410" height="34" rx="2" />
        <text className="lab" x="16" y="27">measured: travel, force, contact, readings</text>
        <line className="a" x1="106" y1="40" x2="106" y2="56" markerEnd="url(#vd-arrow)" />
        <Q y={58} text="Safety stop fired?" />
        <Side y={80} label="yes" /><Out y={60} kind="inc" text="INCONCLUSIVE" sub="unsafe; not the device" />
        <Down y1={102} y2={124} label="no" />
        <Q y={124} text="Contact on the part?" sub="within −1.5 to +3.5 mm" />
        <Side y={146} label="no" /><Out y={126} kind="miss" text="MISSED" sub="never really tested" />
        <Down y1={168} y2={190} label="yes" />
        <Q y={190} text="A reading changed?" sub="after a full push or the cap" />
        <Side y={212} label="no" /><Out y={192} kind="fail" text="FAIL" sub="pushed; nothing changed" />
        <Down y1={234} y2={256} label="yes" />
        <Q y={256} text="The expected change?" sub="and as much as pushed?" />
        <Side y={268} label="" /><Out y={248} kind="fail" text="FAIL" sub="moved the wrong way" />
        <path className="a" d="M206 290 H222 V314 H248" markerEnd="url(#vd-arrow)" />
        <Out y={294} kind="miss" text="MISSED" sub="moved more than pushed" />
        <Down y1={300} y2={340} label="yes" />
        <g className="out pass"><rect x="6" y="340" width="200" height="40" rx="2" /><text className="v" x="16" y="357">PASS</text><text className="sub" x="16" y="373">the expected reading</text></g>
        <text className="lab" x="6" y="404">reported up: MISSED → inconclusive</text>
        <text className="lab" x="6" y="422">retests: fail, fail → failed; fail, pass → intermittent</text>
      </svg>
    </Fig>
  );
}

// ---- 4. Hardware as an MCP Server --------------------------------------------------------------------------------

const TOOLS: [string, [string, string][]][] = [
  ["Read", [["system_status", "state, skills, force limit"], ["scene_get", "controls found, fallback plan"], ["evidence_get", "a trace or a frame"]]],
  ["Run", [["routine_start", "explore, run_plan or home"], ["routine_wait", "until the next stop"], ["routine_resume", "continue, amend, skip, abort"], ["routine_stop", "at the next step boundary"]]],
];

const ADVERTISED = ["press", "flip", "turn", "hook_pull", "pick", "place", "reposition", "swing"];

export function McpTreeFigure() {
  return (
    <Fig
      label="The MCP server exposes seven tools: three to read (system_status, scene_get, evidence_get) and four to run routines (routine_start, routine_wait, routine_resume, routine_stop). system_status advertises the skills the rig can do: press, flip, turn, hook_pull, pick, place, reposition and swing. There is no joint, motor or jog tool."
      caption="Skills aren't in the tool list. Each rig publishes its own through system_status, so a new one needs no new tool."
    >
      <div className="mcptree">
        <div className="mcproot"><b>rav-system-1</b><span className="note">MCP server · 7 tools</span></div>
        <div className="mcpgroups">
          {TOOLS.map(([group, tools]) => (
            <div key={group} className="mcpgroup">
              <span className="label">{group}</span>
              <ul>{tools.map(([name, what]) => <li key={name} className={name === "system_status" ? "adv" : undefined}><code>{name}</code><span>{what}</span></li>)}</ul>
            </div>
          ))}
        </div>
        <div className="mcpadv">
          <span className="label">system_status advertises</span>
          <div className="chips">{ADVERTISED.map((s) => <span key={s} className="chip accent">{s}</span>)}</div>
        </div>
        <div className="mcpabsent"><s>joint · motor · jog</s><span className="note">no such tool</span></div>
      </div>
    </Fig>
  );
}

export function McpSwapFigure() {
  return (
    <Fig
      label="Any of four models on one side and either the sim arm or the real SO-101 on the other, with the same seven tools between them."
      caption="Swap the model or the arm and the tools in the middle stay the same. Safety limits and verdicts stay below them."
    >
      <div className="swap">
        <div className="swapcol">
          <span className="label">any model</span>
          {MODELS.map((m) => <span key={m} className="swapitem">{modelName(m)}</span>)}
        </div>
        <span className="swaparrow" aria-hidden="true">⇄</span>
        <div className="swapcol tools">
          <span className="label">the same 7 tools</span>
          <div className="swaptools">{TOOLS.flatMap(([, t]) => t).map(([name]) => <code key={name}>{name}</code>)}</div>
        </div>
        <span className="swaparrow" aria-hidden="true">⇄</span>
        <div className="swapcol">
          <span className="label">any arm</span>
          <span className="swapitem">Sim arm <span className="note">MuJoCo</span></span>
          <span className="swapitem">SO-101 <span className="note">real</span></span>
        </div>
      </div>
    </Fig>
  );
}

// ---- 5. Verification Planning and Check-Back ---------------------------------------------------------------------

const FLOW = [
  ["Scan", "explore: photos and touch"],
  ["Isolate controls", "one part at a time"],
  ["Theory checklist", "device-theory properties"],
  ["Plan", "skills on controls, cited"],
  ["Plan check", "code, before any motion"],
  ["Execute", "routine_start, run_plan"],
  ["Observe outputs", "display, other readings"],
  ["Check back", "re-read; compare looks"],
  ["Restore and report", "what the run changed"],
] as const;

export function PlanningFlowFigure() {
  const X = 30, W = 178, H = 42, STEP = 62, top = (i: number) => 10 + i * STEP, mid = (i: number) => top(i) + H / 2, R = 228;
  return (
    <Fig
      className="narrow"
      label="The verification flow: scan, isolate controls, the device-theory checklist, plan, plan check, execute, observe the outputs, check back, then restore and report. The plan check refuses a plan with an unsourced limit, a change with no output check, or no read-back, and sends it back to planning. A stop during execution escalates to a person or the model. An intermittent result is retested."
      caption="Three loops: a refused plan goes back to planning, a stop escalates, and an intermittent result is tested again."
    >
      <svg className="mdg" viewBox="0 0 420 560" role="img" aria-labelledby="pf-title">
        <title id="pf-title">Verification planning and check-back</title>
        <Arrowhead id="pf-arrow" />
        {FLOW.map(([name, sub], i) => (
          <g key={name}>
            <rect className={i === 4 ? "gate" : i === 7 ? "box em" : "box"} x={X} y={top(i)} width={W} height={H} rx="2" />
            <text className="t" x={X + 9} y={top(i) + 17}>{name}</text>
            <text className="sub" x={X + 9} y={top(i) + 34}>{sub}</text>
            {i < FLOW.length - 1 && <line className="a" x1={X + W / 2} y1={top(i) + H} x2={X + W / 2} y2={top(i + 1) - 2} markerEnd="url(#pf-arrow)" />}
          </g>
        ))}
        <line className="a" x1={X + W} y1={mid(4) + 6} x2={R - 2} y2={mid(4) + 6} markerEnd="url(#pf-arrow)" />
        <g className="refuse">
          <rect x={R} y={top(4) - 28} width="186" height="82" rx="2" />
          <text className="v" x={R + 10} y={top(4) - 10}>REFUSED</text>
          <text className="sub" x={R + 10} y={top(4) + 8}>an unsourced limit</text>
          <text className="sub" x={R + 10} y={top(4) + 25}>a change, no output check</text>
          <text className="sub" x={R + 10} y={top(4) + 42}>no read-back</text>
        </g>
        <path className="a" d={`M${R + 93} ${top(4) - 28} V${mid(3)} H${X + W + 2}`} markerEnd="url(#pf-arrow)" />
        <line className="a" x1={X + W} y1={mid(5) - 6} x2={R - 2} y2={mid(5) - 6} markerEnd="url(#pf-arrow)" />
        <line className="a" x1={R} y1={mid(5) + 10} x2={X + W + 2} y2={mid(5) + 10} markerEnd="url(#pf-arrow)" />
        <g className="esc">
          <rect x={R} y={top(5) - 2} width="186" height="46" rx="2" />
          <text className="v" x={R + 10} y={top(5) + 15}>STOP → ESCALATE</text>
          <text className="sub" x={R + 10} y={top(5) + 33}>amend, skip or resume</text>
        </g>
        <path className="a" d={`M${X} ${mid(6)} H14 V${mid(5)} H${X - 2}`} markerEnd="url(#pf-arrow)" />
        <text className="lab" transform={`translate(9 ${(mid(5) + mid(6)) / 2}) rotate(-90)`} textAnchor="middle">retest</text>
      </svg>
    </Fig>
  );
}

// ---- 6. Exception-Driven Escalation ------------------------------------------------------------------------------

export function EscalationFigure() {
  const LANES = [["Person", 30], ["Model", 82], ["Robot", 134]] as const;
  const sx = (i: number) => 92 + i * 30;
  const retried = new Set([1, 8]);
  return (
    <Fig
      className="narrow"
      label="Ten steps of a plan on the robot's lane. The robot retries steps 2 and 9 itself. At step 5 an inconclusive result stops and rises to the model, which amends the plan. At step 8 a safety abort rises past the model to a person."
      caption="The robot works through the plan and retries on its own. Only a stop reaches the model, and only a safety abort or a patch needs a person."
    >
      <svg className="mdg" viewBox="0 0 420 168" role="img" aria-labelledby="esc-title">
        <title id="esc-title">Exception-driven escalation across ten steps</title>
        <Arrowhead id="esc-arrow" />
        {LANES.map(([name, y]) => <g key={name}><line className="grid" x1="70" x2="412" y1={y} y2={y} /><text className="lab" x="6" y={y + 4}>{name}</text></g>)}
        {Array.from({ length: 11 }, (_, i) => (
          <g key={i}>
            {i < 10 && <line className="a" x1={sx(i) + 6} y1="134" x2={sx(i + 1) - 7} y2="134" />}
            <circle className={i === 7 ? "dot stopfail" : "dot"} cx={sx(i)} cy="134" r="5" />
            {retried.has(i) && <><path className="a" d={`M${sx(i) - 5} 126 A 6 6 0 1 1 ${sx(i) + 5} 126`} /><text className="lab" x={sx(i)} y="112" textAnchor="middle">retry</text></>}
            {i < 10 && <text className="lab" x={sx(i)} y="158" textAnchor="middle">{i + 1}</text>}
          </g>
        ))}
        <line className="a" x1={sx(4)} y1="128" x2={sx(4)} y2="90" markerEnd="url(#esc-arrow)" />
        <rect className="gate" x={sx(4) - 26} y="70" width="52" height="24" rx="2" /><text className="lab" x={sx(4)} y="86" textAnchor="middle">amend</text>
        <path className="a" d={`M${sx(4) + 26} 82 H${sx(5) - 4} V126`} markerEnd="url(#esc-arrow)" />
        <line className="a" x1={sx(7)} y1="128" x2={sx(7)} y2="40" markerEnd="url(#esc-arrow)" />
        <rect className="refusebox" x={sx(7) - 30} y="18" width="60" height="24" rx="2" /><text className="lab" x={sx(7)} y="34" textAnchor="middle">level 3</text>
        <text className="lab" x={sx(4) - 5} y="112" textAnchor="end">stop</text><text className="lab" x={sx(7) - 5} y="112" textAnchor="end">abort</text>
      </svg>
    </Fig>
  );
}

// ---- 9. Simulation Fidelity: the error model and its 5% --------------------------------------------------

const ERRORS = [
  ["Missed aim", "inconclusive, sometimes a plausible fail"],
  ["False alarm", "safety_abort on a healthy arm"],
  ["Stale reading", "a false no_actuation"],
  ["Pipeline fault", "a pipeline_error stop"],
  ["Slow arm", "routine_wait timeouts"],
  ["Device moved", "parts not where the scene says"],
  ["Weak perception", "low confidence, a wrong inventory"],
  ["Dropped frame", "taken again, unseen"],
] as const;

export function ErrorInjectionFigure() {
  const chance = (n: number) => 1 - 0.95 ** n;
  const pts = Array.from({ length: 31 }, (_, n) => `${n === 0 ? "M" : "L"}${30 + n * 8} ${96 - chance(n) * 80}`).join(" ");
  return (
    <Fig
      label="Errors are injected below the MCP boundary by a wrapper around the sim's robot, at 5% per action. Each kind reaches the model only as the message a real fault would give, so the model can't tell it from a real arm. Only the scorer reads the answer key."
      caption="Injected below the boundary, in the sim only. The model sees what a real fault would show, and only the scorer knows which were planted."
    >
      <div className="inject">
        <div className="injtop"><span className="archtag">Model and harness</span><span className="note">can't tell injected from real</span></div>
        <div className="archline"><span className="archlinelabel">MCP boundary</span></div>
        <div className="injbox">
          <div className="archhead"><span className="archtag">Error injector · 5% per action</span><span className="note">refused on the real arm</span></div>
          <ul className="injlist">{ERRORS.map(([kind, seen]) => <li key={kind}><b>{kind}</b><span aria-hidden="true">→</span><span>{seen}</span></li>)}</ul>
          <div className="injkey"><span className="chip">answer key</span><span className="note">→ scorer only, after the run</span></div>
        </div>
        <svg className="mdg injchart" viewBox="0 0 300 124" role="img" aria-labelledby="inj-title">
          <title id="inj-title">Chance of at least one error in a run, by number of actions: 40% at 10 actions, 64% at 20</title>
          <line className="axis" x1="30" y1="96" x2="272" y2="96" /><line className="axis" x1="30" y1="16" x2="30" y2="96" />
          <text className="lab" x="26" y="20" textAnchor="end">100%</text><text className="lab" x="26" y="99" textAnchor="end">0</text>
          <path className="curve" d={pts} />
          {[10, 20].map((n) => (
            <g key={n}>
              <line className="guide" x1={30 + n * 8} y1="96" x2={30 + n * 8} y2={96 - chance(n) * 80} />
              <circle className="dot" cx={30 + n * 8} cy={96 - chance(n) * 80} r="4" />
              <text className="lab" x={30 + n * 8 - 6} y={96 - chance(n) * 80 - 8} textAnchor="end">{Math.round(chance(n) * 100)}%</text>
            </g>
          ))}
          <text className="lab" x="30" y="114">0</text><text className="lab" x="110" y="114" textAnchor="middle">10</text><text className="lab" x="190" y="114" textAnchor="middle">20</text><text className="lab" x="272" y="114" textAnchor="end">30 actions</text>
        </svg>
      </div>
    </Fig>
  );
}

// ---- 9. Simulation Fidelity: one recorded run, replayed in this browser -------------------------------------------

export function ReplayFigure() {
  const run = useMemo(() => runsFor("demo").find((r) => r.recording?.assets), []);
  const box = useRef<HTMLDivElement>(null);
  const [seen, setSeen] = useState(false);
  const [no3D, setNo3D] = useState(false);
  const unavailable = useCallback(() => setNo3D(true), []);
  const timeline = run?.recording?.timeline;
  const clock = useMemo(() => new ReplayClock(timeline?.duration ?? 0), [timeline]);
  const source = useMemo(() => (run?.recording?.assets && timeline ? new ReplaySource(run.recording.assets, clock, timeline.fps) : null), [run, clock, timeline]);
  const [now, setNow] = useState(0);
  const [paused, setPaused] = useState(true);

  // Three.js and the poses load only once the figure scrolls into view.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const watch = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setSeen(true); watch.disconnect(); } }, { rootMargin: "200px" });
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  useEffect(() => {
    if (!seen) return;
    if (!matchMedia("(prefers-reduced-motion: reduce)").matches) void clock.play();
    const tick = window.setInterval(() => { setNow(clock.currentTime); setPaused(clock.paused); }, 150);
    return () => { window.clearInterval(tick); clock.pause(); };
  }, [seen, clock]);

  const focusAt = useMemo(() => {
    if (!run || !timeline || !source) return undefined;
    const at = (seq?: number) => (seq === undefined ? Infinity : timeline.events[String(seq)] ?? Infinity);
    const steps = run.steps.map((s) => ({ s, from: at(s.startSeq), to: at(s.endSeq) }));
    return (): SimFocus => {
      const t = clock.currentTime;
      const active = steps.find(({ from, to }) => t >= from && t < to)?.s;
      const done = [...steps].reverse().find(({ to }) => to <= t)?.s;
      return {
        target: active?.step.target ?? null, label: active ? `${active.step.target} / ${active.step.skill}` : null,
        verdict: done?.verdict ? `${done.step.id}:${done.verdict.status}` : null,
        force: source.force(t), limit: Number(active?.step.params.force_limit) || 6,
        lcd: [...(timeline.lcd ?? [])].reverse().find((l) => l.t <= t)?.lines ?? [],
      };
    };
  }, [run, timeline, source, clock]);

  if (!run || !timeline || !source) return null;
  return (
    <Fig label={`A recorded simulation run of the ${run.product}, replayed in 3D from its saved physics poses.`} caption={<>A recorded sim run of the {run.product}, drawn here from its saved physics poses. <a href={`#/run/${run.id}`}>Open the full run →</a></>}>
      <div className="minireplay" ref={box}>
        {seen && (no3D ? <p className="note simnote">This browser can't draw 3D.</p> : <Suspense fallback={<div className="simloading"><div className="sweep" /></div>}><Sim3D source={source} focusAt={focusAt} onUnavailable={unavailable} /></Suspense>)}
      </div>
      <div className="replaybar">
        <button type="button" className="btn ghost" onClick={() => { if (clock.paused) void clock.play(); else clock.pause(); setPaused(clock.paused); }}>{paused ? "Play" : "Pause"}</button>
        <input type="range" aria-label="Position in the recorded run" min={0} max={timeline.duration} step={0.1} value={now} onChange={(e) => { clock.currentTime = Number(e.target.value); setNow(Number(e.target.value)); }} />
        <span className="mono muted">{now.toFixed(0)} / {timeline.duration.toFixed(0)} s</span>
      </div>
    </Fig>
  );
}

// ---- 10. Compositional Device Theory -----------------------------------------------------------------------------

const PIECES = [
  ["Controls", "press · turn · flip · slide · push_latch · hook_pull · pick/place", "momentary, latching or continuous", ["actuates", "gives_feedback", "respects_range", "returns_to_default", "independent", "reachable", "needs_reposition", "operable_under_rules"]],
  ["Indicators", "text display · light · beeper · flag", "observe", ["message_documented"]],
  ["Mechanisms", "hinge · slide · latch · spring", "a range and a rest", ["mechanism_range"]],
  ["Containers and objects", "well · slot · tray · cradle · hopper", "accepts, fits, sensed", ["accepts_object"]],
  ["State", "domain · default · persists · mode", "what the device remembers", ["default_on_power"]],
] as const;

const RELATIONS = [
  ["enables", "A must be on for B to work", ["enable_holds"]],
  ["requires", "B refuses unless A holds", ["requirement_holds"]],
  ["interlocks", "A blocks B, and says so", ["interlock_holds", "interlock_releases"]],
  ["drives", "A sets B, by a mapping", ["direction_matches", "mapping_matches"]],
  ["displays", "indicator A shows B", ["displays_matches"]],
] as const;

export function TheoryFigure() {
  const Row = ({ name, sub, note, props }: { name: string; sub: string; note: string; props: readonly string[] }) => (
    <li className="thrrow">
      <div className="thrnode"><b>{name}</b><span>{sub}</span>{note && <span className="note">{note}</span>}</div>
      <span className="thrarrow" aria-hidden="true">→</span>
      <div className="chips">{props.map((p) => <span key={p} className="chip">{p}</span>)}</div>
    </li>
  );
  return (
    <Fig
      label="A device is made of pieces (controls, indicators, mechanisms, containers and objects, state), joined by five relations (enables, requires, interlocks, drives, displays), and walked through by procedures. Each piece and relation carries the property templates worth testing on it."
      caption="Every device is a composition of these. Each piece and relation brings its own tests, and a failed precondition blocks the tests behind it rather than passing them."
    >
      <div className="theory">
        <div className="thrroot"><b>Device</b><span className="note">a hypothesis the model writes from the manual and the scan</span></div>
        <div className="thrtier">
          <div className="thrhead"><span className="label">Pieces</span><span className="label">tested by</span></div>
          <ul>{PIECES.map(([n, s, note, p]) => <Row key={n} name={n} sub={s} note={note} props={p} />)}</ul>
        </div>
        <div className="thrtier">
          <div className="thrhead"><span className="label">Relations</span><span className="label">tested by</span></div>
          <ul>{RELATIONS.map(([n, s, p]) => <Row key={n} name={n} sub={s} note="" props={p} />)}</ul>
        </div>
        <div className="thrtier">
          <div className="thrhead"><span className="label">Procedures</span><span className="label">tested by</span></div>
          <ul>
            <Row name="preconditions → step → effects" sub="from the manual" note="" props={["procedure_completes"]} />
            <Row name="any claim" sub="the manual is a claim, not evidence" note="" props={["matches_manual"]} />
          </ul>
        </div>
      </div>
    </Fig>
  );
}
