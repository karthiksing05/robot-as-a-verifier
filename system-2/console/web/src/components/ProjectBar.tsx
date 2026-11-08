import { useLiveNow } from "../lib/live";
import { useProjects, type Project } from "../lib/projects";
import { go } from "../lib/route";

type Tab = "story" | "live" | "cad";

const pathFor = (tab: Tab, id: string) => (tab === "story" ? `project/${id}` : `${tab}?project=${id}`);

/** One project's screens, one click apart, on every screen that belongs to a project. `locked` holds it on a running run. */
export function ProjectBar({ project, tab, locked = false }: { project?: Project; tab?: Tab; locked?: boolean }) {
  const projects = useProjects();
  const now = useLiveNow();
  const switchTo = (id: string) => {
    if (id === "none") return go("live?project=none");
    const next = projects.find((p) => p.id === id);
    go(pathFor(!tab || (tab === "cad" && !next?.cad) ? "story" : tab, id));
  };
  const tabs: [Tab, string][] = [["story", "Story"], ["live", "Live"], ...(project?.cad ? [["cad", "CAD"] as [Tab, string]] : [])];
  return (
    <nav className="projectbar" aria-label="Project">
      <a className="note" href="#/studies">Studies</a>
      <span className="note" aria-hidden="true">/</span>
      <select className="compact" aria-label="Project" value={project?.id ?? "none"} disabled={locked} onChange={(e) => switchTo(e.target.value)}>
        {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        {(tab === "live" || !project) && <option value="none">No project</option>}
      </select>
      {project && <div className="projecttabs">
        {tabs.map(([t, label]) => (
          <a key={t} href={`#/${pathFor(t, project.id)}`} aria-current={t === tab ? "page" : undefined}>
            {label}{t === "live" && now.running && now.project === project.id && <i className="livedot" role="img" aria-label="running now" />}
          </a>
        ))}
      </div>}
    </nav>
  );
}
