// Scripted Console sessions, recorded, with every cursor move and click logged (times relative to the video's start).
import { chromium } from "playwright";
import fs from "node:fs";
const OUT = "vid/footage/tour"; fs.mkdirSync(OUT, { recursive: true });
const b = await chromium.launch({ channel: "chrome", headless: true });

async function session(name, fn) {
  const ctx = await b.newContext({ viewport: { width: 1920, height: 1080 }, recordVideo: { dir: OUT + "/tmp", size: { width: 1920, height: 1080 } } });
  await ctx.addInitScript(() => { localStorage.setItem("rav.theme", "dark"); sessionStorage.setItem("rav.session", JSON.stringify({ env: "demo", operator: { name: "Karthik", role: "operator" } })); });
  const t0 = Date.now();
  const p = await ctx.newPage();
  const log = [];
  let at = [960, 540];
  const now = () => (Date.now() - t0) / 1000;
  const mark = (label, box) => log.push({ t: now(), kind: "mark", label, box });
  async function moveTo(x, y, ms = 700) {
    const steps = Math.max(8, Math.round(ms / 25)), [x0, y0] = at;
    for (let i = 1; i <= steps; i++) {
      const k = i / steps, e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      const px = x0 + (x - x0) * e, py = y0 + (y - y0) * e;
      await p.mouse.move(px, py); log.push({ t: now(), kind: "move", x: px, y: py });
      await p.waitForTimeout(ms / steps);
    }
    at = [x, y];
  }
  async function click(locator, label, { wait = 1800, zoomBox = null } = {}) {
    const l = typeof locator === "string" ? p.locator(locator).first() : locator;
    await l.scrollIntoViewIfNeeded().catch(() => {});
    const bb = await l.boundingBox();
    if (!bb) { console.log("missing", label); return; }
    const x = bb.x + bb.width / 2, y = bb.y + bb.height / 2;
    await moveTo(x, y);
    await p.waitForTimeout(150);
    log.push({ t: now(), kind: "click", x, y, label, box: zoomBox ?? [bb.x, bb.y, bb.width, bb.height] });
    await p.mouse.down(); await p.mouse.up();
    await p.waitForTimeout(wait);
  }
  await fn({ p, click, moveTo, mark, wait: (ms) => p.waitForTimeout(ms), now, log });
  const v = p.video(); await ctx.close();
  fs.renameSync(await v.path(), `${OUT}/${name}.webm`);
  fs.writeFileSync(`${OUT}/${name}.json`, JSON.stringify(log));
  console.log(name, "done", log.filter((x) => x.kind !== "move").map((x) => `${x.t.toFixed(1)} ${x.label}`).join(" | "));
}

// 1. the demo: the Rev A run page, then Design Analysis, then the Rev B run
await session("demo", async ({ p, click, moveTo, mark, wait }) => {
  await p.goto("http://127.0.0.1:5173/#/run/agent-centrifuge-043919"); await wait(2500);
  mark("page", [140, 160, 1640, 590]);
  await click('button:has-text("4x")', "speed 4x", { wait: 2500, zoomBox: [140, 160, 1040, 560] });
  await click('button:has-text("Scan")', "stage scan", { wait: 2500, zoomBox: [140, 160, 1040, 560] });
  await click('button:has-text("Segment")', "stage segment", { wait: 2200, zoomBox: [140, 160, 1040, 560] });
  await click('g.gnode:has-text("Map")', "node map", { wait: 2200, zoomBox: [140, 760, 1640, 220] });
  await click('button:has-text("Touch")', "stage touch", { wait: 2500, zoomBox: [140, 160, 1040, 560] });
  await click('g.gnode:has-text("Plan")', "node plan", { wait: 2800, zoomBox: [1188, 160, 592, 590] });
  await click('g.gnode:has-text("Approved")', "node approved", { wait: 2800, zoomBox: [1040, 160, 740, 700] });
  await click('button:has-text("Test")', "stage test", { wait: 3500, zoomBox: [140, 160, 1040, 560] });
  await click('g.gnode:has-text("s1")', "node s1", { wait: 2800, zoomBox: [1188, 160, 592, 590] });
  await click('g.gnode:has-text("F1")', "node F1", { wait: 3000, zoomBox: [1188, 160, 592, 590] });
  await click('button:has-text("Fit to view")', "fit", { wait: 1500, zoomBox: [140, 760, 1640, 220] });
  await click('g.gnode:has-text("s7")', "node s7", { wait: 3200, zoomBox: [1188, 160, 592, 590] });
  await click('a:has-text("CAD")', "tab CAD", { wait: 3000, zoomBox: [0, 120, 1920, 840] });
  await click('.seg button:has-text("Rev B")', "rev B", { wait: 2200, zoomBox: [0, 160, 1920, 800] });
  await click('.fix:has-text("F2")', "fix F2", { wait: 3000, zoomBox: [0, 160, 1920, 800] });
  await p.goto("http://127.0.0.1:5173/#/run/agent-centrifuge-045535"); await wait(2500);
  mark("rev B run", [140, 160, 1640, 590]);
  await click('button:has-text("4x")', "speed 4x B", { wait: 1200, zoomBox: [140, 160, 1040, 560] });
  await click('button:has-text("Test")', "stage test B", { wait: 5000, zoomBox: [140, 160, 1040, 560] });
});

// 2. behind the scenes: Studies, a project, Methodology
await session("scenes", async ({ p, click, moveTo, wait }) => {
  await p.goto("http://127.0.0.1:5173/#/studies"); await wait(2500);
  await moveTo(700, 700, 1200); await wait(600); await moveTo(1300, 640, 1000); await wait(600);
  await click('.projectcard:has-text("MC-6")', "project centrifuge", { wait: 3000, zoomBox: [0, 60, 1920, 1020] });
  for (let i = 0; i < 25; i++) { await p.mouse.wheel(0, 30); await wait(60); }
  await wait(800);
  await click('button.gear', "settings", { wait: 1200, zoomBox: [1300, 0, 620, 500] });
  await click('#settings-panel a:has-text("Methodology")', "methodology", { wait: 2500, zoomBox: [0, 60, 1920, 1020] });
  await click('.wikinav a:has-text("Architecture")', "architecture", { wait: 3000, zoomBox: [0, 60, 1920, 1020] });
  await click('.wikinav a:has-text("Verdicts")', "verdicts", { wait: 3000, zoomBox: [0, 60, 1920, 1020] });
  await click('.wikinav a:has-text("Devices")', "devices", { wait: 3000, zoomBox: [0, 60, 1920, 1020] });
});
await b.close();
