import { useEffect, useState } from "react";
import { ForceShapes, Parallax, TrustLoop } from "../components/Diagrams";
import { ArchitectureFigure, ErrorInjectionFigure, EscalationFigure, McpSwapFigure, McpTreeFigure, PlanningFlowFigure, ReplayFigure, TheoryFigure, VerdictFigure } from "../components/Methodology";
import { DeviceTheory, Devices, Journey, ModelChart, ModelResults } from "../components/WikiSections";
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

const NUMBER = Object.fromEntries(SECTIONS.map(([id], i) => [id, i + 1])) as Record<SectionId, number>;
const TITLE = Object.fromEntries(SECTIONS.map(([id, , title]) => [id, title])) as Record<SectionId, string>;

function Section({ id, children }: { id: SectionId; children: React.ReactNode }) {
  return <section className="wikisec" id={`wiki-${id}`}><h2><span className="secno">{NUMBER[id]}</span>{TITLE[id]}</h2>{children}</section>;
}

/** Methodology: how the product works, laid out like a paper. docs/ wins if this page ever disagrees. */
export function Wiki({ route }: { route: Route }) {
  const [active, setActive] = useState<string>(SECTIONS[0][0]);
  const jump = (id: string) => document.getElementById(`wiki-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  const wanted = route.parts[0] === "systems" ? "architecture" : sectionOf(route.parts[1]);

  useEffect(() => { if (wanted) jump(wanted); }, [wanted]);
  useEffect(() => {
    const seen = new IntersectionObserver((entries) => {
      const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (top) setActive(top.target.id.replace("wiki-", ""));
    }, { rootMargin: "-10% 0px -75% 0px" });
    document.querySelectorAll(".wikisec[id]").forEach((s) => seen.observe(s));
    return () => seen.disconnect();
  }, []);

  return (
    <div className="wiki">
      <nav className="wikinav" aria-label="On this page">
        {SECTIONS.map(([id, short], i) => <button key={id} type="button" aria-current={active === id ? "true" : undefined} onClick={() => jump(id)}><span className="secno">{i + 1}</span>{short}</button>)}
      </nav>
      <div className="wikibody">
        <header className="wikisec">
          <h1 className="title">Methodology</h1>
          <p className="wikilede">A low-cost arm explores a product, tests every control it finds, and reports what it measured. The model never grades its own work.</p>
          <TrustLoop />
        </header>

        <Section id="architecture">
          <ArchitectureFigure />
          <p>The robot clamps every parameter to its own limits. If the model goes away, it holds at the next step boundary and waits.</p>
        </Section>

        <Section id="perception">
          <ol className="pipeline">{PIPELINE.map(([name, what], i) => <li key={name}><span className="wikistep">{i + 1}</span><b>{name}</b><span>{what}</span></li>)}</ol>
          <Parallax />
          <p>One $19 USB camera on the wrist, with no depth sensor. Each photo's pose is refined by bundle adjustment on the device's own printing: on real photos of a TV remote with 1° and 3 mm of pose error added, median height error fell to 0.15 mm.</p>
          <p>Contact makes it exact. A 12 mm fingertip taps bare panel to fix the plane and tops of parts to check their heights, and every motion stops on contact or at a force cap. Plans can ask for less force, never more than the robot's hard limit of 15 N.</p>
        </Section>

        <Section id="verdicts">
          <VerdictFigure />
          <ForceShapes />
          <p>A part the fingertip can't work, like a knob that needs a pinch, is refused and reported, never guessed at.</p>
        </Section>

        <Section id="mcp">
          <McpTreeFigure />
          <McpSwapFigure />
        </Section>

        <Section id="planning">
          <PlanningFlowFigure />
        </Section>

        <Section id="escalation">
          <EscalationFigure />
          <div className="autonomy">
            <div className="autonomyline" aria-hidden="true" />
            {AUTONOMY.map(([name, at, what]) => <div key={name} className="autonomystop" style={{ "--at": at } as React.CSSProperties}><i /><b>{name}</b><span>{what}</span></div>)}
          </div>
          <p>Stops carry numbers ("pressed twice, peak 4.8 N, 0.3 mm of travel"), never just a score. A clean failure and a safety abort are always reported, whatever the setting.</p>
        </Section>

        <Section id="authorization">
          <ol className="levels">{LEVELS.map(([n, name, what]) => <li key={n} data-level={n}><span className="levelno">{n}</span><b>{name}</b><span>{what}</span></li>)}</ol>
          <p>Plain code compares a changed plan with the approved one and assigns its level, so the model can't grade its own change.</p>
        </Section>

        <Section id="metric">
          <pre className="formal">{"reward = control coverage × pass rate on covered controls"}</pre>
          <p>Plain code over the verdicts, recomputable from any run's log. Its known limit: with no observe-only controls it reduces to controls passed ÷ controls found, so finding a fault and skipping that control score the same. That's why each study's review leads with faults and coverage.</p>
        </Section>

        <Section id="simulation">
          <ReplayFigure />
          <div className="statrow">{MEASURED.map(([label, value, note]) => <div key={label} className="stat"><span className="label">{label}</span><span className="value">{value}</span><span className="note">{note}</span></div>)}</div>
          <p>MuJoCo, with noise, servo slack and the camera model measured from the team's real parts. The rules and pipeline are the ones the real arm will use.</p>
          <ErrorInjectionFigure />
        </Section>

        <Section id="theory">
          <TheoryFigure />
          <details className="misses">
            <summary className="note">The full vocabulary</summary>
            <div className="stack"><DeviceTheory /></div>
          </details>
        </Section>

        <Section id="devices">
          <Devices />
        </Section>

        <Section id="models">
          <p>The same harness, prompts and tools for every model, and a rule-based baseline on the same tests. Sensors decide every verdict, so a model is scored on what it chose to test and how it read the results.</p>
          <ModelChart />
          <ModelResults />
        </Section>

        <Section id="evolution">
          <Journey />
        </Section>

        <Section id="limitations">
          <div className="statecols">
            <div><span className="label">Working in simulation</span><ul className="plainlist"><li>The whole pipeline through the two systems, on both camera routes</li><li>Frontier models running a verification through the harness's tools</li><li>Random planted faults, injected arm errors and an answer key only the scorer reads</li><li>Approval levels and stop rules</li></ul></div>
            <div><span className="label">Not done yet</span><ul className="plainlist"><li>A model comparison hard enough to rank them</li><li>Proposing real CAD patches from a run</li><li>The full pipeline on the real arm</li><li>Any test on Windows, or between two machines</li></ul></div>
          </div>
        </Section>
      </div>
    </div>
  );
}
