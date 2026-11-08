import fs from "node:fs";
import path from "node:path";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { parse as parseYaml } from "yaml";
import { defineConfig } from "vitest/config";
import { FileProjectBackend, ProjectError, type NewProject, type ProjectBackend } from "./server/projects";

const repoRoot = path.resolve(import.meta.dirname, "../..");

/** Lists recorded runs from runs/, so they can be revisited with only the dev server up. */
function recordedRuns(): Plugin {
  const root = path.join(repoRoot, "runs");
  return {
    name: "recorded-runs",
    configureServer(server) {
      server.middlewares.use("/api/runs", (_req, res) => {
        const read = (id: string) => {
          const dir = path.join(root, id);
          const file = (name: string) => path.join(dir, name);
          if (!["timeline.json", "report.json", "events.jsonl"].every((n) => fs.existsSync(file(n)))) return null;
          const replay = fs.existsSync(file("poses.bin")) && fs.existsSync(file("scene/scene.json"));
          if (!replay && !fs.existsSync(file("video.mp4"))) return null;
          return {
            id,
            events: fs.readFileSync(file("events.jsonl"), "utf8"),
            report: JSON.parse(fs.readFileSync(file("report.json"), "utf8")),
            timeline: JSON.parse(fs.readFileSync(file("timeline.json"), "utf8")),
            ...(replay ? { base: `/@fs${dir}/` } : { video: `/@fs${file("video.mp4")}` }),
            mtime: fs.statSync(file("timeline.json")).mtimeMs,
          };
        };
        const ids = fs.existsSync(root) ? fs.readdirSync(root) : [];
        const runs = ids.map(read).filter((r) => r !== null).sort((a, b) => b.mtime - a.mtime).slice(0, 40);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(runs));
      });
    },
  };
}

/** /api/projects: the only way the Console reads or changes projects. A database replaces the backend passed in here. */
function projectApi(backend: ProjectBackend): Plugin {
  return {
    name: "project-api",
    configureServer(server) {
      server.middlewares.use("/api/projects", (req, res) => {
        const send = (status: number, body: unknown) => {
          res.statusCode = status;
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify(body));
        };
        if (req.method === "GET") return send(200, backend.list());
        if (req.method !== "POST") return send(405, { error: "GET or POST" });
        let raw = "";
        req.on("data", (chunk) => { raw += chunk; });
        req.on("end", () => {
          try {
            send(201, backend.create(JSON.parse(raw) as NewProject, new Date().toISOString().slice(0, 10)));
          } catch (e) {
            if (e instanceof ProjectError || e instanceof SyntaxError) send(400, { error: e.message });
            else send(500, { error: "Couldn't save the project" });
          }
        });
      });
    },
  };
}

/** /api/cad: each appliance's printed parts per revision, and the fixes between them. Held-out devices only show Rev A. */
function applianceCad(): Plugin {
  const root = path.resolve(repoRoot, "../appliances");
  const safe = /^[A-Za-z0-9_.-]+$/;
  const registry = () => JSON.parse(fs.readFileSync(path.join(root, "registry.json"), "utf8")) as { id: string; title: string; split: string; project?: string }[];
  const meshDir = (id: string, rev: string) => path.join(root, id, "build", `meshes_rev${rev}`);
  const has = (id: string, rev: string) => fs.existsSync(path.join(meshDir(id, rev), "manifest.json"));
  return {
    name: "appliance-cad",
    configureServer(server) {
      server.middlewares.use("/api/cad", (req, res) => {
        const send = (status: number, body: unknown) => {
          res.statusCode = status;
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify(body));
        };
        const [id, rev, file] = (req.url ?? "/").split("?")[0].split("/").filter(Boolean).map(decodeURIComponent);
        const all = registry().filter((d) => has(d.id, "A"));
        if (!id) return send(200, all.map((d) => ({ id: d.id, project: d.project ?? d.id, title: d.title, split: d.split })));
        const device = all.find((d) => d.id === id || d.project === id);
        if (!device) return send(404, { error: `No CAD for ${id}` });
        const heldOut = /held/i.test(device.split);
        const revs = ["A", "B"].filter((r) => has(device.id, r) && !(heldOut && r !== "A"));
        if (rev) {
          if (!revs.includes(rev) || !file || !safe.test(file) || !file.endsWith(".stl")) return send(404, { error: "No such part" });
          const full = path.join(meshDir(device.id, rev), file);
          if (!fs.existsSync(full)) return send(404, { error: "No such part" });
          res.setHeader("Content-Type", "model/stl");
          res.setHeader("Cache-Control", "max-age=300");
          return fs.createReadStream(full).pipe(res);
        }
        const parts = Object.fromEntries(revs.map((r) => [r, JSON.parse(fs.readFileSync(path.join(meshDir(device.id, r), "manifest.json"), "utf8"))]));
        let faults: unknown[] = [];
        if (!heldOut) {
          try {
            const doc = parseYaml(fs.readFileSync(path.join(root, device.id, "device.yaml"), "utf8")) as { faults?: Record<string, Record<string, unknown>> };
            faults = Object.entries(doc.faults ?? {}).map(([fid, f]) => ({ id: fid, what: f.what, class: f.class, A: f.A ?? null, B: f.B ?? null }));
          } catch { faults = []; }
        }
        send(200, { id: device.id, project: device.project ?? device.id, title: device.title, split: device.split, heldOut, revs, parts, faults });
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), recordedRuns(), applianceCad(), projectApi(new FileProjectBackend(path.join(repoRoot, "subjects")))],
  resolve: { alias: { "@repo": repoRoot } },
  // The app reads system-2/fixtures/ and subjects/ directly, so regenerating them updates the UI.
  server: { port: 5173, host: "127.0.0.1", fs: { allow: [repoRoot] } },
  test: { environment: "node" },
});
