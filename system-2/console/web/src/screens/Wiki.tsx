import { useEffect, useState } from "react";
import { Boundary, ForceShapes, Parallax, RunFlow, TrustLoop } from "../components/Diagrams";
import type { Route } from "../lib/route";

const SECTIONS = [
  ["overview", "The idea"], ["run", "A run"], ["see", "Seeing"], ["touch", "Touching"], ["judge", "Judging"], ["systems", "Two systems"],
  ["stops", "Staying in touch"], ["trust", "Who signs off"], ["score", "The score"], ["sim", "The sim"], ["state", "What's real"],
] as const;

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

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return <section className="wikisec" id={`wiki-${id}`}><h2>{title}</h2>{children}</section>;
}

/** How the product works. docs/ wins if this page ever disagrees. */
export function Wiki({ route }: { route: Route }) {
  const [active, setActive] = useState<string>(SECTIONS[0][0]);
  const jump = (id: string) => document.getElementById(`wiki-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  const wanted = route.parts[0] === "wiki" ? route.parts[1] : undefined;

  useEffect(() => { if (wanted) jump(wanted); }, [wanted]);
  useEffect(() => {
    const seen = new IntersectionObserver((entries) => {
      const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (top) setActive(top.target.id.replace("wiki-", ""));
    }, { rootMargin: "-10% 0px -75% 0px" });
    document.querySelectorAll(".wikisec").forEach((s) => seen.observe(s));
    return () => seen.disconnect();
  }, []);

  return (
    <div className="wiki">
      <nav className="wikinav" aria-label="On this page">
        {SECTIONS.map(([id, label]) => <button key={id} type="button" aria-current={active === id ? "true" : undefined} onClick={() => jump(id)}>{label}</button>)}
      </nav>
      <div className="wikibody">
        <header className="wikisec" id="wiki-overview">
          <h1 className="title">How it works</h1>
          <p className="wikilede">A low-cost arm explores a product, tests every control it finds, and reports what it measured. The model never grades its own work.</p>
          <TrustLoop />
        </header>

        <Section id="run" title="A run, from start to finish">
          <p>A run is a fixed sequence, and the model does its thinking inside each stage. The robot works on its own between stops, so the model never spends a turn waiting.</p>
          <RunFlow />
        </Section>

        <Section id="see" title="Seeing, with one cheap camera">
          <p>The only camera is a $19 USB module on the wrist, with no depth sensing and nothing stuck on the device. Everything else comes from moving it.</p>
          <ol className="pipeline">{PIPELINE.map(([name, what], i) => <li key={name}><span className="wikistep">{i + 1}</span><b>{name}</b><span>{what}</span></li>)}</ol>
          <Parallax />
          <p>Joint readings alone place the camera too roughly for this. So each photo's pose is refined from features on the device's own printing: bundle adjustment, the method used to build 3D maps from photos. Tested on real photos of a TV remote with 1° and 3 mm of error added to each pose, it brought the median height error down to 0.15 mm.</p>
        </Section>

        <Section id="touch" title="Touching, to correct what it saw">
          <p>Vision gets the arm close, and contact makes it exact. A 12 mm fingertip with a pressure pad taps bare panel to fix the plane, then taps the tops of parts to check their heights. Before each test, one more look corrects the part's position.</p>
          <p>Every motion is guarded: the arm stops on contact or at a force cap. Plans can ask for less force, but never more than the robot's own hard limit of 15 N.</p>
        </Section>

        <Section id="judge" title="Judging, from what sensors measured">
          <ForceShapes />
          <p>A failure needs two things: the arm pushed properly, and the device didn't respond. Separating a broken product from a clumsy robot is what makes a finding worth trusting. A part the fingertip can't work, like a knob that needs a pinch, is refused and reported, never guessed at.</p>
        </Section>

        <Section id="systems" title="Two systems, one narrow channel">
          <Boundary />
          <p>The model can only start named routines from a closed list of skills. No tool moves a joint, and the robot clamps every parameter to its own limits, so no prompt or bad plan can drive the arm directly. If the model goes away, the robot holds safely at the next step boundary and waits.</p>
        </Section>

        <Section id="stops" title="Staying in touch only when it matters">
          <p>Every message to the model costs seconds and tokens, so the robot handles what it can and reports the rest with numbers: "pressed twice, peak 4.8 N, 0.3 mm of travel", never just a score. How often it reports is a setting, and we loosen it only when results hold up.</p>
          <div className="autonomy">
            <div className="autonomyline" aria-hidden="true" />
            {AUTONOMY.map(([name, at, what]) => <div key={name} className="autonomystop" style={{ "--at": at } as React.CSSProperties}><i /><b>{name}</b><span>{what}</span></div>)}
          </div>
          <p>A clean failure and a safety abort always get reported, whatever the setting.</p>
        </Section>

        <Section id="trust" title="Who signs off on a change">
          <p>Plain code compares a changed plan with the approved one and assigns its level, so the model can't grade its own change.</p>
          <ol className="levels">{LEVELS.map(([n, name, what]) => <li key={n} data-level={n}><span className="levelno">{n}</span><b>{name}</b><span>{what}</span></li>)}</ol>
        </Section>

        <Section id="score" title="The score">
          <pre className="formal">{"reward = control coverage × pass rate on covered controls"}</pre>
          <p>It's plain code over the verdicts, so anyone can recompute it from a run's log. It has a known limit: with no observe-only controls, it reduces to controls passed ÷ controls found, so finding a fault and skipping that control score the same. That's why each project's review leads with faults and coverage, not this number.</p>
        </Section>

        <Section id="sim" title="The sim, built from bench measurements">
          <p>The arm runs in MuJoCo, with noise, servo slack and the camera model taken from measurements of the team's real parts. The sim's rules and pipeline are the same ones the real arm will use, and the 3D view on this site replays its real physics poses.</p>
          <div className="statrow">{MEASURED.map(([label, value, note]) => <div key={label} className="stat"><span className="label">{label}</span><span className="value">{value}</span><span className="note">{note}</span></div>)}</div>
        </Section>

        <Section id="state" title="What's real, and what isn't yet">
          <div className="statecols">
            <div><span className="label">Working in simulation</span><ul className="plainlist"><li>The whole pipeline through the two systems, on both camera routes</li><li>A planted fault, caught as stuck</li><li>Approval levels and stop rules</li></ul></div>
            <div><span className="label">Not done yet</span><ul className="plainlist"><li>The frontier model. Rules stand in for it today</li><li>Reading the manual and proposing real CAD patches</li><li>The full pipeline on the real arm</li><li>Any test on Windows, or between two machines</li></ul></div>
          </div>
        </Section>
      </div>
    </div>
  );
}
