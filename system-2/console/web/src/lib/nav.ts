// The top navigation and the Methodology page's sections, named like a paper's parts. Paths that were in use before the
// rename stay as aliases, so old links and bookmarks still land on the same screen.

/** [path in the address, the screen it opens, its label]. The screen names are the app's internal ones. */
export const NAV = [
  ["studies", "projects", "Studies"],
  ["background", "motivation", "Background"],
  ["methodology", "wiki", "Methodology"],
  ["live", "live", "Live Experiment"],
  ["design-analysis", "cad", "Design Analysis"],
  ["change-review", "approvals", "Change Review"],
  ["revision-history", "edits", "Revision History"],
] as const;

export type Screen = (typeof NAV)[number][1] | "project" | "run" | "runs";

const ALIASES: Record<string, Screen> = {
  ...Object.fromEntries(NAV.map(([path, screen]) => [path, screen])),
  projects: "projects", motivation: "motivation", wiki: "wiki", systems: "wiki", "how-it-works": "wiki", "live-experiment": "live",
  cad: "cad", approvals: "approvals", edits: "edits", "edit-log": "edits", project: "project", run: "run", runs: "runs",
};

/** The screen a route's first part opens. Unknown or missing parts open Studies. */
export const screenOf = (part: string | undefined): Screen => (part && ALIASES[part]) || "projects";

/** Whether a nav entry is the current one. Studies stays lit inside a study, a run or the run list. */
export function isCurrent(navScreen: Screen, screen: Screen) {
  return navScreen === screen || (navScreen === "projects" && ["project", "run", "runs"].includes(screen));
}

/** The Methodology page's sections, in reading order: [id, short label for the contents, title]. */
export const SECTIONS = [
  ["architecture", "Architecture", "System Architecture"],
  ["perception", "Perception", "Perception and Pose Refinement"],
  ["verdicts", "Verdicts", "Sensor-Grounded Verdicts"],
  ["mcp", "MCP server", "Hardware as an MCP Server"],
  ["planning", "Planning", "Verification Planning and Check-Back"],
  ["escalation", "Escalation", "Exception-Driven Escalation"],
  ["authorization", "Authorization", "Change Authorization"],
  ["metric", "Metric", "Evaluation Metric"],
  ["simulation", "Simulation", "Simulation Fidelity"],
  ["theory", "Device theory", "Compositional Device Theory"],
  ["devices", "Devices", "Benchmark Devices"],
  ["models", "Models", "Frontier Model Comparison"],
  ["evolution", "Evolution", "Design Evolution"],
  ["limitations", "Limitations", "Limitations and Current Status"],
] as const;

export type SectionId = (typeof SECTIONS)[number][0];

const OLD_SECTIONS: Record<string, SectionId> = {
  overview: "architecture", systems: "architecture", run: "escalation", see: "perception", touch: "perception", judge: "verdicts",
  stops: "escalation", trust: "authorization", score: "metric", sim: "simulation", journey: "evolution", state: "limitations",
};

/** The section a link asks for, by its id or the id it had before the rename. Null for none or an unknown one. */
export function sectionOf(id: string | undefined): SectionId | null {
  if (!id) return null;
  if (SECTIONS.some(([s]) => s === id)) return id as SectionId;
  return OLD_SECTIONS[id] ?? null;
}
