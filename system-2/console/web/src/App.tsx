import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { ChatDock } from "./components/ChatDock";
import { SettingsMenu } from "./components/SettingsMenu";
import { SessionContext, runsFor } from "./lib/context";
import { useEdits } from "./lib/edits";
import { useLiveNow } from "./lib/live";
import { useProjects } from "./lib/projects";
import { NAV, isCurrent, screenOf } from "./lib/nav";
import { useRoute, withTransition } from "./lib/route";
import { useSession } from "./lib/session";
import { Approvals } from "./screens/Approvals";
import { EditLog } from "./screens/EditLog";
import { Live } from "./screens/Live";
import { Login } from "./screens/Login";
import { Motivation } from "./screens/Motivation";
import { Project } from "./screens/Project";
import { Projects } from "./screens/Projects";
import { RunView } from "./screens/RunView";
import { Runs } from "./screens/Runs";
import { Wiki } from "./screens/Wiki";

const loadCad = () => import("./screens/CadBench");
const CadBench = lazy(() => loadCad().then((m) => ({ default: m.CadBench })));

function readPref(key: string, fallback: string) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function useTheme() {
  const key = "rav.theme";
  const [value, setValue] = useState(() => readPref(key, "dark"));
  const set = (next: string) => {
    withTransition(() => {
      setValue(next);
      document.documentElement.dataset.theme = next;
    });
    try {
      localStorage.setItem(key, next);
    } catch {
      // the choice then lasts only for this page
    }
  };
  return [value, set] as const;
}

export function App() {
  const session = useSession();
  const route = useRoute();
  const [theme, setTheme] = useTheme();
  const edits = useEdits(session?.env ?? "demo");
  const projects = useProjects();
  const live = useLiveNow();
  const lastProject = useRef<string | null>(null); // Live opens on the project you were just looking at

  // Load the 3D bench while idle, so opening it never shows a wait.
  useEffect(() => {
    if (!session) return;
    const idle = window.requestIdleCallback ?? ((fn: () => void) => window.setTimeout(fn, 400));
    idle(() => void loadCad());
  }, [session]);

  if (!session) return <Login />;

  const section = screenOf(route.parts[0]);
  const pending = edits.filter((e) => e.state === "planned").length;
  const runId = section === "run" ? route.parts[1] : null;
  const here = section === "project" ? route.parts[1] : section === "live" ? route.query.get("project") : section === "cad" ? route.query.get("project") ?? projects.find((p) => p.cad)?.id : null;
  if (here) lastProject.current = here;
  const hrefFor = (path: string) => (path === "live" && lastProject.current ? `#/live?project=${lastProject.current}` : `#/${path}`);

  return (
    <SessionContext.Provider value={session}>
      <div className="app">
        <header className="top">
          <span className="topstatic" aria-hidden="true" />
          <a className="mark" href="#/studies">RAAV CONSOLE</a>
          <nav className="nav" aria-label="Main">
            {NAV.filter(([, , , where]) => where === "main").map(([path, screen, label]) => (
              <a key={path} href={hrefFor(path)} aria-current={isCurrent(screen, section) ? "page" : undefined}>
                {label}{screen === "live" && live.running && <i className="livedot" role="img" aria-label="running now" />}{screen === "approvals" && pending > 0 && <span className="count">{pending}</span>}
              </a>
            ))}
          </nav>
          <span className="spacer" />
          <SettingsMenu session={session} section={section} theme={theme} onTheme={() => setTheme(theme === "dark" ? "light" : "dark")} />
        </header>
        <div className="body">
          <main className="main">
            <div className="screen" key={`${session.env}-${section}`}>
              {section === "projects" && <Projects />}
              {section === "project" && <Project route={route} />}
              {section === "motivation" && <Motivation />}
              {section === "live" && <Live route={route} />}
              {section === "runs" && <Runs />}
              {section === "run" && <RunView route={route} />}
              {section === "cad" && <Suspense fallback={<div className="sweep" role="status" aria-label="Loading the CAD bench" />}><CadBench theme={theme} route={route} /></Suspense>}
              {section === "approvals" && <Approvals />}
              {section === "edits" && <EditLog />}
              {section === "wiki" && <Wiki route={route} />}
            </div>
          </main>
          {/* The chat steers the sample runs. Live and recorded runs have their own controls. */}
          {["run", "runs", "cad", "approvals", "edits"].includes(section) && (!runId || runsFor(session.env).some((r) => r.id === runId)) && <ChatDock runId={runId} />}
        </div>
      </div>
    </SessionContext.Provider>
  );
}
