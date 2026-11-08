// Renders comp.html frame by frame.
//   node render.mjs stills 10 20.5 ...        -> ../out/stills/t<time>.png
//   node render.mjs video [from] [to] [out]    -> ../out/<out> (silent, 30 fps)
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import fs from "node:fs";
const [, , mode, ...rest] = process.argv;
const URL = "http://127.0.0.1:8898/video/build/comp.html";
const b = await chromium.launch({ channel: "chrome", headless: true, args: ["--force-device-scale-factor=1"] });
const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
p.on("pageerror", (e) => console.error("pageerror", e.message));
p.on("console", (m) => m.type() === "error" && console.error("console", m.text()));
await p.goto(URL);
await p.evaluate(() => window.ready);
const DUR = await p.evaluate(() => window.DUR);
const stage = p.locator("#stage");
if (mode === "stills") {
  fs.mkdirSync("../out/stills", { recursive: true });
  for (const t of rest.map(Number)) {
    await p.evaluate((t) => window.seek(t), t);
    await stage.screenshot({ path: `../out/stills/t${t.toFixed(2)}.png` });
  }
} else {
  const from = Number(rest[0] ?? 0), to = Number(rest[1] ?? DUR), out = rest[2] ?? "silent.mp4";
  const ff = spawn("ffmpeg", ["-v", "error", "-y", "-f", "image2pipe", "-framerate", "30", "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", `../out/${out}`], { stdio: ["pipe", "inherit", "inherit"] });
  const n0 = Math.round(from * 30), n1 = Math.round(to * 30);
  const started = Date.now();
  for (let i = n0; i < n1; i++) {
    await p.evaluate((t) => window.seek(t), i / 30);
    const buf = await stage.screenshot({ type: "jpeg", quality: 92 });
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once("drain", r));
    if (i % 300 === 0) console.log(`frame ${i}/${n1}  ${((Date.now() - started) / 1000).toFixed(0)} s`);
  }
  ff.stdin.end();
  await new Promise((r) => ff.on("close", r));
  console.log("wrote", out);
}
await b.close();
