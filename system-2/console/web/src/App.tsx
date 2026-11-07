import { lazy, Suspense, useEffect, useState } from "react";
import { ChatDock } from "./components/ChatDock";
import { SessionContext, runsFor } from "./lib/context";
import { useEdits } from "./lib/edits";
import { useRoute, withTransition } from "./lib/route";
import { ENVIRONMENTS, OPERATORS, canEnter, signOut, switchOperator, useSession } from "./lib/session";
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

const NAV = [["projects", "Projects"], ["motivation", "Motivation"], ["wiki", "How it works"], ["live", "Live"], ["cad", "CAD"], ["approvals", "Approvals"], ["edits", "Edit log"]] as const;

export function App() {
  const session = useSession();
  const route = useRoute();
  const [theme, setTheme] = useTheme();
  const edits = useEdits(session?.env ?? "demo");

  // Load the 3D bench while idle, so opening it never shows a wait.
  useEffect(() => {
    if (!session) return;
    const idle = window.requestIdleCallback ?? ((fn: () => void) => window.setTimeout(fn, 400));
    idle(() => void loadCad());
  }, [session]);

  if (!session) return <Login />;

  const section = route.parts[0] ?? "projects";
  const pending = edits.filter((e) => e.state === "planned").length;
  const runId = section === "run" ? route.parts[1] : null;

  return (
    <SessionContext.Provider value={session}>
      <div className="app">
        <header className="top">
          <span className="topstatic" aria-hidden="true" />
          <a className="mark" href="#/projects">RAV CONSOLE</a>
          <nav className="nav" aria-label="Main">
            {NAV.map(([path, label]) => (
              <a key={path} href={`#/${path}`} aria-current={section === path || (path === "projects" && ["project", "run", "runs"].includes(section)) || (path === "wiki" && section === "systems") ? "page" : undefined}>
                {label}{path === "approvals" && pending > 0 && <span className="count">{pending}</span>}
              </a>
            ))}
          </nav>
          <span className="spacer" />
          <div className="tools">
            <button className="linkbtn" type="button" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? "Light" : "Dark"} theme</button>
            <span className="envchip">{ENVIRONMENTS[session.env].label}</span>
            <label className="label" htmlFor="pick-op">Acting as</label>
            <select id="pick-op" className="compact" value={session.operator.name} onChange={(e) => switchOperator(e.target.value)}>
              {OPERATORS.filter((o) => canEnter(o, session.env)).map((o) => <option key={o.name} value={o.name}>{o.name}{o.role === "judge" ? " (steer only)" : ""}</option>)}
            </select>
            <button className="linkbtn" type="button" onClick={() => withTransition(signOut)}>Exit</button>
          </div>
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
              {section === "cad" && <Suspense fallback={<div className="sweep" role="status" aria-label="Loading the CAD bench" />}><CadBench theme={theme} /></Suspense>}
              {section === "approvals" && <Approvals />}
              {section === "edits" && <EditLog />}
              {(section === "wiki" || section === "systems") && <Wiki route={route} />}
            </div>
          </main>
          {/* The chat steers the sample runs. Live and recorded runs have their own controls. */}
          {["run", "runs", "cad", "approvals", "edits"].includes(section) && (!runId || runsFor(session.env).some((r) => r.id === runId)) && <ChatDock runId={runId} />}
        </div>
      </div>
    </SessionContext.Provider>
  );
}
