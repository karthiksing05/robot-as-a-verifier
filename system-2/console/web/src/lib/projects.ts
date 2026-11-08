// Projects, as the screens see them. Everything goes through ProjectStore, so where projects live can change without
// touching a screen. The review only reads run logs: nothing here invents a result.
import { useEffect, useSyncExternalStore } from "react";
import type { Finding, ParamChange, Status } from "./contracts";
import type { NewProject, Project } from "../../server/projects";
import { statusOfControl, type Run } from "./runs";

export type { NewProject, Project };

export interface ProjectStore {
  list(): Promise<Project[]>;
  create(input: NewProject): Promise<Project>;
}

const bundled = Object.values(import.meta.glob("@repo/subjects/*/project.json", { import: "default", eager: true })) as Project[];

class ApiStore implements ProjectStore {
  async list() {
    const res = await fetch("/api/projects");
    if (!res.ok) throw new Error("can't list projects");
    return (await res.json()) as Project[];
  }
  async create(input: NewProject) {
    const res = await fetch("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error ?? "couldn't create the project");
    return body as Project;
  }
}

const store: ProjectStore = new ApiStore();
let projects: Project[] = bundled;
const watchers = new Set<() => void>();

async function refresh() {
  try {
    projects = await store.list();
  } catch {
    projects = bundled; // a built Console with no dev server still shows what shipped with it
  }
  watchers.forEach((fn) => fn());
}

export async function createProject(input: NewProject) {
  const made = await store.create(input);
  await refresh();
  return made;
}

export function useProjects() {
  useEffect(() => { void refresh(); }, []);
  return useSyncExternalStore((fn) => { watchers.add(fn); return () => watchers.delete(fn); }, () => projects);
}

/** Exact, or followed by a space or comma, so "Sim device 14" doesn't claim "Sim device 140". */
const namedBy = (product: string, name: string) => product === name || product.startsWith(`${name} `) || product.startsWith(`${name},`);

export function projectOf(run: Run, list: Project[]): Project | undefined {
  const named = run.events.find((e) => e.type === "run_started")?.payload.project as string | undefined;
  return list.find((p) => p.id === named) ?? list.find((p) => p.products.some((name) => namedBy(run.product, name)));
}

/** The project Live is about: what the link asked for, else the run on screen, else the first device the sim can run. */
export function liveProject(asked: string | null, run: { project: Project | undefined } | null, list: Project[]): Project | undefined {
  if (asked === "none") return undefined;
  const named = list.find((p) => p.id === asked);
  if (named) return named;
  return run ? run.project : list.find((p) => p.kind === "sim");
}

export type Evidence = "mock" | "sim";
export const evidenceOf = (run: Run): Evidence => (!run.recording && (run.product.includes("(mock)") || run.plan.source === "mock") ? "mock" : "sim");

export type ControlStatus = Status | "pending";
export function controlStatus(run: Run, id: string): ControlStatus {
  const cov = run.report.coverage;
  return id in cov.skipped ? "skipped" : statusOfControl(cov, id);
}

export interface RevisionResult { revision: string; run: Run }
export interface Review {
  runs: Run[];
  revisions: RevisionResult[]; // oldest first, the newest run of each
  latest: Run | null;
  controls: string[];
  open: Finding[]; // failing in the latest revision
  fixed: (Finding & { revision: string })[]; // failed on an earlier revision, and pass on the latest
  untested: { id: string; why: string }[];
  patches: (ParamChange & { from: string; to: string })[];
  causes: Run["causes"];
  evidence: Evidence | null;
  headline: string;
}

/** The whole project in one reading. `runs` come newest first, so the first run seen of a revision is its newest. */
export function reviewOf(runs: Run[]): Review {
  const newest = new Map<string, Run>();
  for (const run of runs) if (!newest.has(run.revision)) newest.set(run.revision, run);
  const revisions = [...newest.entries()].sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true })).map(([revision, run]) => ({ revision, run }));
  const latest = revisions.at(-1)?.run ?? null;
  const controls = [...new Set(revisions.flatMap(({ run }) => run.scene.controls.map((c) => c.id)))];
  const open = latest ? latest.report.findings : [];
  const fixed = latest ? revisions.slice(0, -1).flatMap(({ revision, run }) => run.report.findings
    .filter((f) => controlStatus(latest, f.target) === "passed" && !open.some((o) => o.target === f.target))
    .map((f) => ({ ...f, revision }))) : [];
  const cov = latest?.report.coverage;
  const untested = cov ? [
    ...Object.entries(cov.skipped).map(([id, why]) => ({ id, why })),
    ...cov.inconclusive.map((id) => ({ id, why: "The robot couldn't complete this test" })),
  ] : [];
  const patches = revisions.flatMap(({ run }) => run.applied.flatMap((p) => p.changes.map((c) => ({ ...c, from: p.revision_from, to: p.revision_to }))));
  const faults = (n: number) => `${n} open fault${n === 1 ? "" : "s"}`;
  const headline = !latest ? "Not tested yet"
    : open.length ? faults(open.length)
    : fixed.length ? `${fixed.length} fault${fixed.length === 1 ? "" : "s"} found and fixed`
    : untested.length ? `No faults found, ${untested.length} untested`
    : "Every control passed";
  return {
    runs, revisions, latest, controls, open, fixed, untested, patches, causes: revisions.flatMap(({ run }) => run.causes),
    evidence: latest ? evidenceOf(latest) : null, headline,
  };
}
