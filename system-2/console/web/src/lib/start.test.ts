import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { FileProjectBackend } from "../../server/projects";
import { MAX_TURNS, revisionsOf, startBody } from "./agent";
import { GALLERY, galleryOf } from "./gallery";

const repo = path.join(import.meta.dirname, "../../../../..");
const registry = JSON.parse(fs.readFileSync(path.join(repo, "appliances/registry.json"), "utf8")) as { id: string; split: string; revs: string[]; device: string; project: string }[];
const projects = new FileProjectBackend(path.join(repo, "system-2/subjects")).list();
const form = { seed: "", fault: "", rev: "", effector: "stock", placement: "nominal", route: "depth", model: "claude-haiku-5-5", speed: "4", maxTurns: "15", errorRate: "5", errorSeed: "", auto: false };

describe("starting a run on any sim device", () => {
  it("lists a project for every device in the registry, with its revisions and split", () => {
    for (const d of registry) {
      const p = projects.find((x) => x.id === d.project);
      expect(p, d.id).toBeDefined();
      expect(p!.sim?.path).toBe(d.device);
      expect(revisionsOf(p)).toEqual(d.revs);
      expect(p!.split).toBe(d.split);
      expect(galleryOf(p!.id)?.id).toBe(d.id);
    }
    expect(GALLERY).toHaveLength(registry.length);
  });

  it("sends the device file, the chosen revision and the stock gripper, and never a planted fault", () => {
    const kettle = projects.find((p) => p.id === "kettle-base")!;
    const body = startBody(kettle, { ...form, rev: "M1", fault: "stuck_button" });
    expect(body.project).toBe("kettle-base");
    expect(body.device).toMatchObject({ path: "appliances/kettle-base/device.yaml", rev: "M1", effector: "stock", fault: null });
    expect(body.max_turns).toBe(15);
    expect(startBody(kettle, { ...form, effector: "probe" }).device).toMatchObject({ effector: "probe" });
    expect(startBody(kettle, { ...form, effector: "" }).device).toMatchObject({ effector: "stock" });
    expect(startBody(kettle, { ...form, maxTurns: "" }).max_turns).toBeNull();
    expect(MAX_TURNS).toBe(80);
  });

  it("keeps seeds and planted faults for generated devices", () => {
    const preset = projects.find((p) => p.id === "sim-preset-c")!;
    const body = startBody(preset, { ...form, fault: "stuck_button" });
    expect(body.device).toMatchObject({ preset: "C", fault: "stuck_button" });
    expect(body.device).not.toHaveProperty("effector");
    expect(revisionsOf(preset)).toEqual([]);
    expect(startBody(undefined, { ...form, seed: "1401" }).device).toMatchObject({ seed: 1401 });
  });
});
