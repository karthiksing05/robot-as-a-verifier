import type { ReactNode } from "react";
import { ProjectBar } from "../components/ProjectBar";
import { Pill, Stat, stagger } from "../components/ui";
import type { Route } from "../lib/route";
import { useAppSession, useRuns } from "../lib/context";
import { galleryOf, splitLabel } from "../lib/gallery";
import { previewOf } from "../lib/previews";
import { controlStatus, projectOf, projectsIn, reviewOf, useProjects, type Project as ProjectData, type Review } from "../lib/projects";
import { ENVIRONMENTS } from "../lib/session";
import type { DeviceCard } from "../lib/wikidata";

function Chapter({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="chapter rise" style={stagger(n)}>
      <span className="chapterno" aria-hidden="true">{n}</span>
      <div className="chapterbody"><h2>{title}</h2>{children}</div>
    </section>
  );
}

const EVIDENCE = {
  mock: "Mock data: this shows how an appliance's story reads. No robot or sim produced it.",
  sim: "Simulated: none of this has run on the real arm.",
  real: "Recorded on the real arm.",
};

export function Project({ route }: { route: Route }) {
  const { env, operator } = useAppSession();
  const { runs, ready } = useRuns(env);
  const projects = projectsIn(env, useProjects());
  const project = projects.find((p) => p.id === route.parts[1]);

  if (!project) {
    if (!ready) return <div className="sweep" role="status" aria-label="Loading the project" />;
    return <div className="page"><div className="empty"><h2>No project called {route.parts[1]}</h2><a className="btn ghost" href="#/studies">All studies</a></div></div>;
  }
  const own = runs.filter((r) => projectOf(r, projects)?.id === project.id);
  const review = reviewOf(own);
  const canRun = project.kind === "sim" && operator.role !== "judge";
  const device = galleryOf(project.id);
  const split = splitLabel(project.split ?? device?.split);
  // The plain description only: the device notes after it (source notes, firmware quirks) live further down.
  const about = device?.body.join(" ").split("**")[0].replace(/`/g, "").trim();
  const picture = previewOf(project.id);

  return (
    <div className="page projectpage">
      <ProjectBar project={project} tab="story" />
      <header className={`projecthero rise ${picture ? "withpic" : ""}`}>
        <div className="herotext">
          <div className="row"><span className="tag">{ENVIRONMENTS[env].runner === "real arm" ? "Real arm" : project.kind === "sim" ? "Sim device" : "Physical product"}</span>{split && <span className="tag">{split}</span>}{review.revisions.length > 0 && <span className="tag">Rev {review.revisions.at(-1)!.revision}</span>}</div>
          <h1 className="title">{project.name}</h1>
          {about ? <p className="wikilede">{about}</p> : project.summary && <p className="wikilede">{project.summary}</p>}
          <b className={`headline big ${review.open.length ? "bad" : review.latest ? "good" : ""}`}>{review.headline}</b>
          {canRun && <div className="row"><a className="btn accent" href={`#/live?project=${project.id}`}>{review.latest ? "Run it again" : "Start the first run"}</a></div>}
          {review.evidence && <p className={`evidence ${review.evidence}`}>{EVIDENCE[review.evidence]}</p>}
        </div>
        {picture && <img className="heropic" src={picture} alt={`${project.name}, rendered from its CAD`} />}
      </header>
      <Story project={project} review={review} />
    </div>
  );
}

/** What the device is, from its gallery entry. A held-out device's entry has no faults in it. */
function DeviceFacts({ device }: { device: DeviceCard }) {
  return (
    <dl className="facts devicefacts">
      {device.controls.length > 0 && <div><dt>Controls</dt><dd><div className="chips">{device.controls.map((x) => <span key={x} className="chip">{x}</span>)}</div></dd></div>}
      {device.theory.length > 0 && <div><dt>Theory pieces</dt><dd><ul className="plainlist">{device.theory.map((x) => <li key={x}>{x}</li>)}</ul></dd></div>}
      {device.planted && <div><dt>Planted faults</dt><dd>{device.planted.replace(/`/g, "")}</dd></div>}
    </dl>
  );
}

function Story({ project, review }: { project: ProjectData; review: Review }) {
  const { latest } = review;
  const device = galleryOf(project.id);
  const instruction = latest?.instruction;
  const kinds = new Map<string, number>();
  latest?.scene.controls.forEach((c) => kinds.set(c.kind, (kinds.get(c.kind) ?? 0) + 1));
  const findings = review.revisions.flatMap(({ revision, run }) => run.report.findings.map((f) => ({ f, revision, run })));
  return (
    <div className="story">
      <Chapter n={1} title="The brief">
        {instruction && <blockquote>{instruction}</blockquote>}
        <dl className="facts">
          <div><dt>Manual</dt><dd>{latest?.manual ?? project.manual?.split("/").at(-1) ?? "None yet"}</dd></div>
          <div><dt>Rules</dt><dd>{project.rules.length ? project.rules.join(", ") : "None yet"}</dd></div>
          {project.sim?.revs && <div><dt>Revisions</dt><dd>{project.sim.revs.join(", ")}</dd></div>}
          {latest?.plan.steps.length ? <div><dt>Plan</dt><dd>{latest.plan.steps.length} steps, written by {latest.plan.source === "model" ? "the model" : latest.plan.source === "rules" ? "rules" : "a script"}</dd></div> : null}
        </dl>
        {device && <DeviceFacts device={device} />}
      </Chapter>
      {!latest && <Chapter n={2} title="Nothing tested yet"><p>{project.kind === "sim" ? "Start a run to see what the robot finds on this device." : "This story starts once the arm can run it."}</p></Chapter>}
      {latest && <>
        <Chapter n={2} title="What the robot found">
          <p>{latest.scene.controls.length} controls.</p>
          <div className="row">{[...kinds.entries()].map(([kind, n]) => <span key={kind} className="tag">{n} {kind}{n === 1 ? "" : "s"}</span>)}</div>
        </Chapter>
        <Chapter n={3} title="What it tested">
          <div className="scrollx">
            <table className="matrix">
              <thead><tr><th>Control</th>{review.revisions.map(({ revision, run }) => <th key={revision}><a href={`#/run/${run.id}`}>Rev {revision}</a></th>)}</tr></thead>
              <tbody>{review.controls.map((id) => (
                <tr key={id}><td className="n">{id}</td>{review.revisions.map(({ revision, run }) => {
                  const status = controlStatus(run, id);
                  return <td key={revision}><Pill status={status === "pending" ? "skipped" : status}>{status === "pending" ? "not found" : status}</Pill></td>;
                })}</tr>
              ))}</tbody>
            </table>
          </div>
        </Chapter>
        <Chapter n={4} title={findings.length ? "What went wrong" : "No faults found"}>
          {findings.map(({ f, revision, run }) => {
            const fixed = review.fixed.some((x) => x.id === f.id && x.revision === revision);
            const cause = run.causes.find((c) => c.finding === f.id);
            return (
              <article key={`${revision}-${f.id}`} className={`faultcard ${fixed ? "fixed" : ""}`}>
                <div className="row"><b className="n">{f.target}</b><span className="tag">{f.label}</span><span className="tag">Rev {revision}</span><span className="spacer" /><Pill status={fixed ? "passed" : "failed"}>{fixed ? "Fixed" : "Open"}</Pill></div>
                <p>{f.what_happened}</p>
                {f.manual_says && <p className="muted">The manual says: {f.manual_says}</p>}
                {cause && <p><b>Why:</b> {cause.root_cause}</p>}
                <a className="note" href={`#/run/${run.id}?seq=${f.event_seqs[0] ?? ""}`}>See the evidence</a>
              </article>
            );
          })}
        </Chapter>
        {(review.patches.length > 0 || review.open.length > 0) && <Chapter n={5} title="The fix">
          {review.patches.length === 0 && <p>No fix has been proposed yet.</p>}
          {review.patches.map((p) => (
            <div key={`${p.from}-${p.param}`} className="patchline">
              <span className="n">{p.param}</span>
              <span className="n"><s>{String(p.from_value)}</s> → <b>{String(p.to_value)}</b>{p.unit ? ` ${p.unit}` : ""}</span>
              <span className="note">Rev {p.from} → Rev {p.to}</span>
              {p.predicted && <p>{p.predicted}</p>}
            </div>
          ))}
        </Chapter>}
        <Chapter n={review.patches.length > 0 || review.open.length > 0 ? 6 : 5} title="The review">
          <div className="statrow">
            <Stat label="Controls covered" text={`${latest.report.coverage.passed.length + latest.report.coverage.failed.length + latest.report.coverage.observed.length} of ${latest.report.coverage.detected}`} />
            <Stat label="Faults found" text={String(findings.length)} i={1} />
            <Stat label="Fixed" text={String(review.fixed.length)} i={2} />
            <Stat label="Still open" text={String(review.open.length)} i={3} />
          </div>
          {review.untested.length > 0 && <>
            <h3>Not proven</h3>
            <ul className="plainlist">{review.untested.map((u) => <li key={u.id}><b className="n">{u.id}</b> {u.why}</li>)}</ul>
          </>}
          <h3>Every run</h3>
          <ul className="plainlist">{review.runs.map((r) => <li key={r.id}><a href={`#/run/${r.id}`}>{r.id}</a> <span className="muted">Rev {r.revision} / {r.status}</span></li>)}</ul>
        </Chapter>
      </>}
    </div>
  );
}
