import fs from "node:fs";
import path from "node:path";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
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

export default defineConfig({
  plugins: [react(), recordedRuns(), projectApi(new FileProjectBackend(path.join(repoRoot, "subjects")))],
  resolve: { alias: { "@repo": repoRoot } },
  // The app reads system-2/fixtures/ and subjects/ directly, so regenerating them updates the UI.
  server: { port: 5173, host: "127.0.0.1", fs: { allow: [repoRoot] } },
  test: { environment: "node" },
});
