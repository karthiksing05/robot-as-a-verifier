import { useEffect, type ReactNode } from "react";
import { ForceShapes, Parallax, TrustLoop } from "../components/Diagrams";
import { ArchitectureFigure, ErrorInjectionFigure, EscalationFigure, McpSwapFigure, McpTreeFigure, PlanningFlowFigure, ReplayFigure, TheoryFigure, VerdictFigure } from "../components/Methodology";
import { DeviceDetail, DeviceList, DeviceTheory, Journey, ModelChart, ModelResults } from "../components/WikiSections";
import { SECTIONS, sectionOf, type SectionId } from "../lib/nav";
import type { Route } from "../lib/route";
import "../styles/methodology.css";
import "../styles/wikisections.css";

const PIPELINE = [
  ["Survey", "Find the panel and which way it faces"],
  ["Scan", "Take photo pairs across the panel"],
  ["Segment", "OWLv2 boxes controls, SAM outlines them"],
  ["Map", "Heights from shift, kinds from shape"],
  ["Touch", "Tap the panel and parts to pin them down"],
  ["Plan", "One or two tests per part, if reachable"],
  ["Test", "Look once more, then press, flip, slide, turn or push"],
] as const;

const AUTONOMY = [
  ["Tethered", 0, "Reports after every step, with no retries"],
  ["Balanced", 50, "Retries twice, reports at the end or when something matters"],
  ["Autonomous", 100, "Retries four times, trusts weaker detections"],
] as const;

const LEVELS = [
  ["0", "Automatic", "Same target and skill, same or lower force. Logged"],
  ["1", "Notify", "Reorder, skip or re-test. Shown, and a person can override"],
  ["2", "Approve", "New target or skill, or higher force. A person first"],
  ["3", "Always a person", "After a safety abort, or printing a patch. No setting lowers this"],
] as const;

const MEASURED = [
  ["Field of view", "75 × 47°", "after undistortion, from the real camera"],
  ["Lens fit", "0.19 px", "error against the bench calibration"],
  ["Servo dead zone", "5 steps", "from the bench servos"],
  ["Reading jitter", "0.95 steps", "1 sigma, at the arm's real gain"],
] as const;

/** Each section's page. `sub` is the part after the section in the address, used by Devices for one device. */
const BODY: Record<SectionId, (sub?: string) => ReactNode> = {
  architecture: () => <>
    <ArchitectureFigure />
    <p>The robot clamps every parameter to its own limits. If the model goes away, it holds at the next step boundary and waits.</p>
  </>,
  perception: () => <>
    <ol className="pipeline">{PIPELINE.map(([name, what], i) => <li key={name}><span className="wikistep">{i + 1}</span><b>{name}</b><span>{what}</span></li>)}</ol>
    <Parallax />
    <p>One $19 USB camera on the wrist, with no depth sensor. Each photo's pose is refined by bundle adjustment on the device's own printing: on real photos of a TV remote with 1° and 3 mm of pose error added, median height error fell to 0.15 mm.</p>
    <p>Contact makes it exact. A 12 mm fingertip taps bare panel to fix the plane and tops of parts to check their heights, and every motion stops on contact or at a force cap. Plans can ask for less force, never more than the robot's hard limit of 15 N.</p>
  </>,
  verdicts: () => <>
    <VerdictFigure />
    <ForceShapes />
    <p>A part the fingertip can't work, like a knob that needs a pinch, is refused and reported, never guessed at.</p>
  </>,
  mcp: () => <><McpTreeFigure /><McpSwapFigure /></>,
  planning: () => <PlanningFlowFigure />,
  escalation: () => <>
    <EscalationFigure />
    <div className="autonomy">
      <div className="autonomyline" aria-hidden="true" />
      {AUTONOMY.map(([name, at, what]) => <div key={name} className="autonomystop" style={{ "--at": at } as React.CSSProperties}><i /><b>{name}</b><span>{what}</span></div>)}
    </div>
    <p>Stops carry numbers ("pressed twice, peak 4.8 N, 0.3 mm of travel"), never just a score. A clean failure and a safety abort are always reported, whatever the setting.</p>
  </>,
  authorization: () => <>
    <ol className="levels">{LEVELS.map(([n, name, what]) => <li key={n} data-level={n}><span className="levelno">{n}</span><b>{name}</b><span>{what}</span></li>)}</ol>
    <p>Plain code compares a changed plan with the approved one and assigns its level, so the model can't grade its own change.</p>
  </>,
  metric: () => <>
    <pre className="formal">{"reward = control coverage × pass rate on covered controls"}</pre>
    <p>Plain code over the verdicts, recomputable from any run's log. Its known limit: with no observe-only controls it reduces to controls passed ÷ controls found, so finding a fault and skipping that control score the same. That's why each study's review leads with faults and coverage.</p>
  </>,
  simulation: () => <>
    <ReplayFigure />
    <div className="statrow">{MEASURED.map(([label, value, note]) => <div key={label} className="stat"><span className="label">{label}</span><span className="value">{value}</span><span className="note">{note}</span></div>)}</div>
    <p>MuJoCo, with noise, servo slack and the camera model measured from the team's real parts. The rules and pipeline are the ones the real arm will use.</p>
    <ErrorInjectionFigure />
  </>,
  theory: () => <>
    <TheoryFigure />
    <details className="misses">
      <summary className="note">The full vocabulary</summary>
      <div className="stack"><DeviceTheory /></div>
    </details>
  </>,
  devices: (sub) => (sub ? <DeviceDetail id={sub} /> : <DeviceList />),
  models: () => <>
    <p>The same harness, prompts and tools for every model, and a rule-based baseline on the same tests. Sensors decide every verdict, so a model is scored on what it chose to test and how it read the results.</p>
    <ModelChart />
    <ModelResults />
  </>,
  evolution: () => <Journey />,
  limitations: () => (
    <div className="statecols">
      <div><span className="label">Working in simulation</span><ul className="plainlist"><li>The whole pipeline through the two systems, on both camera routes</li><li>Frontier models running a verification through the harness's tools</li><li>Random planted faults, injected arm errors and an answer key only the scorer reads</li><li>Approval levels and stop rules</li></ul></div>
      <div><span className="label">Not done yet</span><ul className="plainlist"><li>A model comparison hard enough to rank them</li><li>Proposing real CAD patches from a run</li><li>The full pipeline on the real arm</li><li>Any test on Windows, or between two machines</li></ul></div>
    </div>
  ),
};

const href = (id: SectionId | null) => (id ? `#/methodology/${id}` : "#/methodology");

/** Methodology: how the product works, one section per page, in the order of a paper. docs/ wins if this page ever disagrees. */
export function Wiki({ route }: { route: Route }) {
  const id = route.parts[0] === "systems" ? "architecture" : sectionOf(route.parts[1]);
  const sub = id === "devices" ? route.parts[2] : undefined;
  const at = id ? SECTIONS.findIndex(([s]) => s === id) : -1;
  const prev = at > 0 ? SECTIONS[at - 1] : null;
  const next = SECTIONS[at + 1] ?? null;

  useEffect(() => { window.scrollTo({ top: 0 }); }, [id, sub]);

  return (
    <div className="wiki">
      <nav className="wikinav" aria-label="Methodology">
        <a href={href(null)} aria-current={!id ? "page" : undefined}><span className="secno" />Overview</a>
        {SECTIONS.map(([s, short], i) => <a key={s} href={href(s)} aria-current={s === id ? "page" : undefined}><span className="secno">{i + 1}</span>{short}</a>)}
      </nav>
      <div className="wikibody" key={`${id}-${sub ?? ""}`}>
        {id ? (
          <section className="wikisec rise">
            <h2><span className="secno">{at + 1}</span>{SECTIONS[at][2]}</h2>
            {BODY[id](sub)}
          </section>
        ) : (
          <header className="wikisec rise">
            <h1 className="title">Methodology</h1>
            <p className="wikilede">A low-cost arm explores a product, tests every control it finds, and reports what it measured. The model never grades its own work.</p>
            <TrustLoop />
          </header>
        )}
        <nav className="pager" aria-label="Pages">
          {at >= 0 ? <a href={href(prev?.[0] ?? null)}><span className="label">Previous</span>{prev ? prev[2] : "Overview"}</a> : <span />}
          {next && <a className="next" href={href(next[0])}><span className="label">Next</span>{next[2]}</a>}
        </nav>
      </div>
    </div>
  );
}
