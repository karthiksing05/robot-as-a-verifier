import { useState, type FormEvent, type MouseEvent } from "react";
import { Field } from "../components/Field";
import { stagger } from "../components/ui";
import { useAppSession, useRuns } from "../lib/context";
import { galleryOf, splitLabel } from "../lib/gallery";
import { READ_ONLY_CONSOLE, useLiveNow } from "../lib/live";
import { pieceName } from "../lib/wikidata";
import { controlStatus, createProject, projectOf, projectsIn, reviewOf, useProjects, type Project } from "../lib/projects";
import { go } from "../lib/route";
import { ENVIRONMENTS } from "../lib/session";

export function Projects() {
  const { env, operator } = useAppSession();
  const { runs } = useRuns(env);
  const projects = projectsIn(env, useProjects());
  const [adding, setAdding] = useState(false);

  if (!ENVIRONMENTS[env].connected) {
    return <div className="page"><h1 className="title">Studies</h1><div className="empty rise"><h2>Real arm and real CAD: not connected yet</h2></div></div>;
  }
  const unfiled = runs.filter((r) => !projectOf(r, projects)).length;
  const real = ENVIRONMENTS[env].runner === "real arm";

  return (
    <div className="page">
      <section className="hero rise">
        <Field baseX={0.82} reach={0.5} />
        <h1 className="title">Studies</h1>
        <div className="row">
          {!READ_ONLY_CONSOLE && <button className="btn accent" type="button" disabled={operator.role === "judge"} onClick={() => setAdding(!adding)}>{adding ? "Close" : "New project"}</button>}
          <a className="btn ghost" href="#/background">Background</a>
        </div>
        {READ_ONLY_CONSOLE && <p className="note">Hosted demo. Browse the bundled projects and recorded runs.</p>}
      </section>
      {adding && <NewProjectForm />}
      <div className="projectgrid">
        {projects.map((p, i) => <ProjectCard key={p.id} project={p} i={i} real={real} runs={runs.filter((r) => projectOf(r, projects)?.id === p.id)} />)}
      </div>
      {unfiled > 0 && <a className="note" href="#/runs">{unfiled} run{unfiled === 1 ? "" : "s"} not in a project</a>}
    </div>
  );
}

function ProjectCard({ project, runs, i, real }: { project: Project; runs: Parameters<typeof reviewOf>[0]; i: number; real: boolean }) {
  const review = reviewOf(runs);
  const now = useLiveNow();
  const stay = (e: MouseEvent) => e.stopPropagation(); // these links go somewhere other than the card does
  const device = galleryOf(project.id);
  const split = splitLabel(project.split ?? device?.split);
  const about = device?.body.join(" ").trim();
  return (
    <article className="panel projectcard rise" style={stagger(i)} onClick={() => go(`project/${project.id}`)}>
      <div className="row"><span className="tag">{real ? "Real arm" : project.kind === "sim" ? "Sim device" : "Physical product"}</span>{split && <span className="tag">{split}</span>}{review.evidence === "mock" && <span className="tag mock">Mock data</span>}</div>
      <h2><a href={`#/project/${project.id}`}>{project.name}</a></h2>
      {about ? <p>{about}</p> : project.summary && <p>{project.summary}</p>}
      {device && device.theory.length > 0 && <div className="chips" aria-label="Theory pieces">{device.theory.map((x) => <span key={x} className="chip accent" title={x}>{pieceName(x)}</span>)}</div>}
      <span className="spacer" />
      <b className={`headline ${review.open.length ? "bad" : review.latest ? "good" : ""}`}>{review.headline}</b>
      {review.latest && <div className="dots" aria-hidden="true">{review.controls.map((id) => <i key={id} className={controlStatus(review.latest!, id)} />)}</div>}
      <span className="note">{review.revisions.length ? `Rev ${review.revisions.map((r) => r.revision).join(", ")} / ${runs.length} run${runs.length === 1 ? "" : "s"}` : "No runs"}</span>
      <div className="row">
        <a className="btn ghost" href={`#/live?project=${project.id}`} onClick={stay}>{now.running && now.project === project.id ? <>Live now<i className="livedot" aria-hidden="true" /></> : "Live"}</a>
        {project.cad && <a className="btn ghost" href="#/cad" onClick={stay}>CAD</a>}
      </div>
    </article>
  );
}

function NewProjectForm() {
  const [name, setName] = useState("");
  const [summary, setSummary] = useState("");
  const [kind, setKind] = useState<Project["kind"]>("physical");
  const [seed, setSeed] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const sim = kind === "sim" ? { seed: seed.trim() ? Number(seed) : null, fault: null } : undefined;
      const made = await createProject({ name, summary, kind, sim });
      go(`project/${made.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't create the project");
    }
  };
  return (
    <form className="panel rise newproject" onSubmit={(e) => void submit(e)}>
      <div className="field"><label className="label" htmlFor="p-name">Appliance</label><input id="p-name" required value={name} placeholder="Coffee maker" onChange={(e) => setName(e.target.value)} /></div>
      <div className="field"><label className="label" htmlFor="p-summary">What it is</label><input id="p-summary" value={summary} onChange={(e) => setSummary(e.target.value)} /></div>
      <div className="field"><label className="label" htmlFor="p-kind">Tested on</label>
        <select id="p-kind" value={kind} onChange={(e) => setKind(e.target.value as Project["kind"])}><option value="physical">The real arm</option><option value="sim">The sim</option></select>
      </div>
      {kind === "sim" && <div className="field"><label className="label" htmlFor="p-seed">Device seed, blank for preset C</label><input id="p-seed" className="tech" inputMode="numeric" pattern="[0-9]*" value={seed} onChange={(e) => setSeed(e.target.value)} /></div>}
      <div className="row"><button className="btn accent" type="submit">Create project</button></div>
      {error && <p className="error" role="alert">{error}</p>}
    </form>
  );
}
