import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { NAV, SECTIONS, isCurrent, screenOf, sectionOf } from "./nav";
import { chartPanels, loadResults, logDomain } from "./wikidata";

describe("the top navigation", () => {
  it("lists its pages in order: working screens, then the explanations", () => {
    expect(NAV.map(([, , label]) => label)).toEqual(["Studies", "Live Experiment", "Design Analysis", "Change Review", "Revision History", "Background", "Methodology"]);
  });

  it("opens each page from its new path", () => {
    expect(NAV.map(([path]) => screenOf(path))).toEqual(["projects", "live", "cad", "approvals", "edits", "motivation", "wiki"]);
  });

  it("keeps every old path working", () => {
    const old = { projects: "projects", motivation: "motivation", wiki: "wiki", systems: "wiki", live: "live", cad: "cad", approvals: "approvals", edits: "edits", project: "project", run: "run", runs: "runs" };
    for (const [path, screen] of Object.entries(old)) expect(screenOf(path), path).toBe(screen);
  });

  it("opens Studies for no path or an unknown one", () => {
    expect(screenOf(undefined)).toBe("projects");
    expect(screenOf("nowhere")).toBe("projects");
  });

  it("keeps Studies lit inside a study and a run, and lights nothing else there", () => {
    for (const s of ["project", "run", "runs"] as const) {
      expect(isCurrent("projects", s)).toBe(true);
      expect(NAV.filter(([, screen]) => isCurrent(screen, s)).length).toBe(1);
    }
    expect(isCurrent("wiki", screenOf("methodology"))).toBe(true);
    expect(isCurrent("projects", "wiki")).toBe(false);
  });

  it("keeps the working screens in the top bar, and the pages that explain the project in the settings panel", () => {
    expect(NAV.filter(([, , , where]) => where === "main").map(([, , label]) => label)).toEqual(["Studies", "Live Experiment", "Design Analysis", "Change Review", "Revision History"]);
    expect(NAV.filter(([, , , where]) => where === "more").map(([, , label]) => label)).toEqual(["Background", "Methodology"]);
  });

  it("never gives two entries the same path", () => {
    expect(new Set(NAV.map(([path]) => path)).size).toBe(NAV.length);
  });
});

describe("the Methodology sections", () => {
  it("are numbered like a paper, in the order Karthik set", () => {
    expect(SECTIONS.map(([, , title]) => title)).toEqual([
      "System Architecture", "Perception and Pose Refinement", "Sensor-Grounded Verdicts", "Hardware as an MCP Server",
      "Verification Planning and Check-Back", "Exception-Driven Escalation", "Change Authorization", "Evaluation Metric",
      "Simulation Fidelity", "Compositional Device Theory", "Benchmark Devices", "Frontier Model Comparison", "Design Evolution",
      "Limitations and Current Status",
    ]);
  });

  it("send old section links to the section that holds their content now", () => {
    expect(sectionOf("models")).toBe("models");
    expect(sectionOf("journey")).toBe("evolution");
    expect(sectionOf("see")).toBe("perception");
    expect(sectionOf("touch")).toBe("perception");
    expect(sectionOf("judge")).toBe("verdicts");
    expect(sectionOf("trust")).toBe("authorization");
    expect(sectionOf("score")).toBe("metric");
    expect(sectionOf("sim")).toBe("simulation");
    expect(sectionOf("state")).toBe("limitations");
    expect(sectionOf("systems")).toBe("architecture");
    expect(sectionOf("nope")).toBeNull();
    expect(sectionOf(undefined)).toBeNull();
  });
});

describe("the model chart", () => {
  const committed = JSON.parse(fs.readFileSync(path.join(import.meta.dirname, "../data/model-results.json"), "utf8"));

  it("has a panel for each scored round with two or more models, and none for the partial or planned ones", () => {
    const r = loadResults(committed);
    const panels = chartPanels(r);
    const ids = panels.map((p) => p.id);
    expect(ids).not.toContain("1"); // no sim, so not scored
    expect(ids).not.toContain("3m"); // one model only
    expect(ids).not.toContain("4");
    for (const p of panels) {
      expect(p.points.length).toBeGreaterThanOrEqual(2);
      for (const q of p.points) {
        expect(q.share).toBeGreaterThanOrEqual(0);
        expect(q.share).toBeLessThanOrEqual(1);
        expect(q.perDevice).toBeGreaterThan(0);
      }
    }
  });

  it("works out dollars per device from the round's rows, not from typed-in numbers", () => {
    const r = loadResults(committed);
    const round = r.rounds.find((x) => x.id === panelsFirst(r))!;
    const row = round.rows.find((x) => !x.baseline)!;
    const point = chartPanels(r)[0].points.find((p) => p.model === row.model)!;
    expect(point.perDevice).toBeCloseTo((row.usd ?? 0) / row.runs, 6);
    expect(point.share).toBeCloseTo(row.faults_found / row.faults_planted, 6);
  });

  it("covers every cost with powers of ten", () => {
    expect(logDomain([0.004, 0.66])).toEqual([0.001, 1]);
    expect(logDomain([])).toEqual([0.001, 1]);
    const [lo, hi] = logDomain([0.5]);
    expect(lo).toBeLessThanOrEqual(0.5);
    expect(hi).toBeGreaterThan(0.5);
  });
});

function panelsFirst(r: ReturnType<typeof loadResults>) {
  return chartPanels(r)[0].id;
}
