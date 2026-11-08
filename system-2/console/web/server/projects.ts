// Where projects are kept. The Console only ever calls /api/projects, so moving to a database means writing another
// ProjectBackend and passing it to the dev server. No screen changes (Kanban: Move projects from repo files to a database).
import fs from "node:fs";
import path from "node:path";

// path: a device file instead of a seed, with its revisions (A, B and mixed ones like M1) and the one a run starts on
export interface SimDevice { seed: number | null; fault: string | null; path?: string; rev?: string; revs?: string[] }

export interface Project {
  id: string;
  name: string;
  summary: string;
  kind: "physical" | "sim";
  sim?: SimDevice;
  cad?: boolean; // it has a model on the CAD bench
  products: string[]; // runs logged under these product names belong here, for runs that don't name their project
  // On the real arm, so Prod shows it. runs: id prefixes of its real runs that name no project, such as rav run's
  real?: { runs: string[] };
  rules: string[];
  manual?: string; // the model reads it, as it would a real product's
  split?: "dev" | "validation" | "held_out"; // a sim device's place in the evals: a held-out one's faults are never shown
  created: string;
}

export type NewProject = Pick<Project, "name" | "summary" | "kind"> & { sim?: SimDevice; rules?: string[] };

export interface ProjectBackend {
  list(): Project[];
  create(input: NewProject, today: string): Project;
}

export class ProjectError extends Error {}

export const slug = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48);

/** Checks what a person typed, and fills in the rest. Any backend uses this, so the rules don't move with the storage. */
export function buildProject(input: Partial<NewProject>, taken: string[], today: string): Project {
  const name = typeof input.name === "string" ? input.name.trim() : "";
  const id = slug(name);
  if (!id) throw new ProjectError("A project needs a name with letters or numbers in it");
  if (taken.includes(id)) throw new ProjectError(`There's already a project called ${id}`);
  if (input.kind !== "physical" && input.kind !== "sim") throw new ProjectError("A project is a physical product or a sim device");
  const summary = typeof input.summary === "string" ? input.summary.trim() : "";
  const rules = Array.isArray(input.rules) ? input.rules.filter((r) => typeof r === "string" && r.trim()).map((r) => r.trim()) : [];
  if (input.kind === "physical") return { id, name, summary, kind: "physical", products: [name], rules, created: today };
  const seed = input.sim?.seed ?? null;
  if (seed !== null && !(Number.isInteger(seed) && seed >= 0)) throw new ProjectError("A seed is a whole number");
  const fault = input.sim?.fault ?? null;
  return { id, name, summary, kind: "sim", sim: { seed, fault }, products: seed === null ? [] : [`Sim device ${seed}`], rules, created: today };
}

/** One folder per product under subjects/, beside its CAD and manual. */
export class FileProjectBackend implements ProjectBackend {
  constructor(private root: string) {}

  list(): Project[] {
    if (!fs.existsSync(this.root)) return [];
    return fs.readdirSync(this.root).flatMap((id) => {
      const file = path.join(this.root, id, "project.json");
      return fs.existsSync(file) ? [JSON.parse(fs.readFileSync(file, "utf8")) as Project] : [];
    }).sort((a, b) => a.created.localeCompare(b.created) || a.name.localeCompare(b.name));
  }

  create(input: NewProject, today: string): Project {
    const taken = fs.existsSync(this.root) ? fs.readdirSync(this.root) : [];
    const project = buildProject(input, taken, today);
    fs.mkdirSync(path.join(this.root, project.id), { recursive: true });
    fs.writeFileSync(path.join(this.root, project.id, "project.json"), `${JSON.stringify(project, null, 2)}\n`, { flag: "wx" });
    return project;
  }
}
