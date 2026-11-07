import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { FileProjectBackend, ProjectError, buildProject, slug } from "./projects";

const TODAY = "2026-11-07";

describe("projects", () => {
  it("makes ids that can't leave the subjects folder", () => {
    expect(slug("../../etc/passwd")).toBe("etc-passwd");
    expect(slug("Coffee Maker, v2!")).toBe("coffee-maker-v2");
  });

  it("refuses a nameless project, a taken name and a bad seed", () => {
    expect(() => buildProject({ name: "!!!", kind: "physical" }, [], TODAY)).toThrow(ProjectError);
    expect(() => buildProject({ name: "Kettle", kind: "physical" }, ["kettle"], TODAY)).toThrow(ProjectError);
    expect(() => buildProject({ name: "Kettle", kind: "sim", sim: { seed: 1.5, fault: null } }, [], TODAY)).toThrow(ProjectError);
  });

  it("files a sim device's runs by its seed", () => {
    expect(buildProject({ name: "Seed 7", kind: "sim", sim: { seed: 7, fault: null } }, [], TODAY).products).toEqual(["Sim device 7"]);
  });

  it("keeps projects in files, and never overwrites one", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "rav-projects-"));
    const store = new FileProjectBackend(root);
    store.create({ name: "Kettle", summary: "", kind: "physical" }, TODAY);
    expect(store.list().map((p) => p.id)).toEqual(["kettle"]);
    expect(JSON.parse(fs.readFileSync(path.join(root, "kettle/project.json"), "utf8")).products).toEqual(["Kettle"]);
    expect(() => store.create({ name: "Kettle", summary: "", kind: "physical" }, TODAY)).toThrow(ProjectError);
    fs.rmSync(root, { recursive: true });
  });
});
