// The whole video as one page (Draft 9 order): window.seek(t) puts every layer where it is at time t, and render.mjs
// steps it frame by frame. Times come from words.json (absolute seconds): the voiceover's word timings, or, for a
// silent preview, the script's guide timings from guide_words.py. Footage placement comes from segments.json.
"use strict";
const FPS = 30;
const NS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const eio = (x) => { x = clamp(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
const lerp = (a, b, k) => a + (b - a) * k;
const ramp = (t, a, b) => clamp((t - a) / (b - a));
function rng(seed) { return () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let x = Math.imul(seed ^ (seed >>> 15), 1 | seed); x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x; return ((x ^ (x >>> 14)) >>> 0) / 4294967296; }; }
function svg(tag, attrs, parent) { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (parent) parent.appendChild(n); return n; }
function el(tag, cls, html, parent, style = "") { const n = document.createElement(tag); if (cls) n.className = cls; if (html != null) n.innerHTML = html; if (style) n.style.cssText = style; (parent ?? $("scenes")).appendChild(n); return n; }
const show = (n, o, dy = 0) => { n.style.opacity = o; n.style.transform = `translateY(${(1 - o) * dy}px)`; };

let WORDS = [], CAPS = [], LAY = null, CLIPS = {}, DUR = 165;
// The take ends on its own push-in to RAAV (untransformed by then). The drawn slate fades in under it while his
// handwritten RAAV, cut out of that very frame (raav_hand.png, footage.py RAAV_AT), stays put; then RAAV rises.
const FADE = [14.1, 15.0], RISE = [15.1, 16.4];
const HAND = { x: 475, y: 275, w: 1040, h: 440 };
const norm = (w) => w.replace(/[^\w-]/g, "").toLowerCase();
function T(word, after = 0) {
  const w = WORDS.find((x) => x.s >= after - 0.01 && norm(x.w).startsWith(word.toLowerCase()));
  if (!w) throw new Error(`no "${word}" after ${after}`);
  return w.s;
}
function TE(word, after = 0) { const w = WORDS.find((x) => x.s >= after - 0.01 && norm(x.w).startsWith(word.toLowerCase())); return w.e; }

/* ───────────── chalk: drawings that appear on their own, and an arm that points ───────────── */
const WHITE = "#f1efe6", YELLOW = "#eebc24", DIM = "#c9d3c8";
const EL = [];
let seedN = 1;
function roughD(pts, seed, j = 2.4) {
  const r = rng(seed);
  const p = pts.map(([x, y]) => [x + (r() - 0.5) * j, y + (r() - 0.5) * j]);
  let d = `M${p[0][0].toFixed(1)} ${p[0][1].toFixed(1)}`;
  for (let i = 0; i < p.length - 1; i++) {
    const p0 = p[i - 1] || p[i], p1 = p[i], p2 = p[i + 1], p3 = p[i + 2] || p2;
    d += `C${(p1[0] + (p2[0] - p0[0]) / 6).toFixed(1)} ${(p1[1] + (p2[1] - p0[1]) / 6).toFixed(1)} ${(p2[0] - (p3[0] - p1[0]) / 6).toFixed(1)} ${(p2[1] - (p3[1] - p1[1]) / 6).toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}
function sub(pts, step = 30) { const out = [pts[0]]; for (let i = 1; i < pts.length; i++) { const [ax, ay] = pts[i - 1], [bx, by] = pts[i]; const n = Math.max(1, Math.round(Math.hypot(bx - ax, by - ay) / step)); for (let k = 1; k <= n; k++) out.push([ax + (bx - ax) * k / n, ay + (by - ay) * k / n]); } return out; }
const poly = (...p) => sub(p);
const rectP = (x, y, w, h) => sub([[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y - 4]]);
const circ = (cx, cy, r, turns = 1.06) => { const n = Math.max(14, Math.round(r / 3)); return Array.from({ length: Math.round(n * turns) + 1 }, (_, i) => { const a = -1.9 + i / n * Math.PI * 2; return [cx + Math.cos(a) * r, cy + Math.sin(a) * r]; }); };
function P(pts, start, dur, { color = WHITE, w = 5 } = {}) {
  const node = svg("path", { d: roughD(pts, seedN++), fill: "none", stroke: color, "stroke-width": w, "stroke-linecap": "round", "stroke-linejoin": "round" }, $("ink"));
  EL.push({ kind: "path", node, start, dur });
}
function X(text, x, y, start, dur, { size = 40, head = false, color = WHITE, anchor = "start" } = {}) {
  const id = `c${EL.length}`;
  const cp = svg("clipPath", { id, clipPathUnits: "userSpaceOnUse" }, $("ink"));
  const rect = svg("rect", { x: 0, y: y - size * 1.2, width: 0, height: size * 1.7 }, cp);
  const node = svg("text", { x, y, fill: color, "font-size": size, "font-family": head ? "Cabin Sketch" : "Architects Daughter", "font-weight": head ? 700 : 400, "clip-path": `url(#${id})`, "text-anchor": anchor, stroke: color, "stroke-width": head ? 0.6 : 1.2, "letter-spacing": head ? 3 : 0.5 }, $("ink"));
  node.textContent = text;
  EL.push({ kind: "text", node, rect, start, dur });
}
/** Where the arm points, from when. */
const POINTS = [];

function buildChalk() {
  const r = rng(99);
  const ghosts = ["F = ma", "∫ f(x) dx", "x² + y² = r²", "lim n→∞", "Δv", "τ = r × F", "σ = E·ε", "PV = nRT", "Q.E.D."];
  for (let i = 0; i < 18; i++) { const t = svg("text", { x: r() * 1900, y: 60 + r() * 1000, fill: WHITE, "font-size": 40 + r() * 50, "font-family": "Architects Daughter", transform: `rotate(${(r() - 0.5) * 8})` }, $("ghosts")); t.textContent = ghosts[i % ghosts.length]; }

  const s2 = T("this");
  // RAAV, where the take left it
  SC.raav = svg("g", {}, $("board"));
  svg("image", { href: "raav_hand.png", x: HAND.x, y: HAND.y, width: HAND.w, height: HAND.h }, SC.raav);
  // a prototype (the centrifuge, roughly)
  const pr = T("prototype");
  P(rectP(170, 520, 300, 190), pr - 0.1, 0.35); P(poly([170, 520], [240, 460], [540, 460], [470, 520]), pr + 0.2, 0.25); P(poly([540, 460], [540, 650], [470, 710]), pr + 0.4, 0.2);
  P(circ(250, 600, 18), pr + 0.55, 0.12); P(circ(310, 600, 18), pr + 0.62, 0.12); P(circ(370, 600, 18), pr + 0.69, 0.12); P(rectP(220, 650, 120, 30), pr + 0.75, 0.15);
  X("MC-6 centrifuge · Rev A", 170, 770, pr + 0.4, 0.4, { size: 30, color: DIM });
  POINTS.push([pr, 320, 470]);
  // its manual
  const ma = T("manual", pr);
  P(rectP(610, 470, 170, 230), ma - 0.1, 0.35); for (let k = 0; k < 5; k++) P(poly([640, 520 + k * 34], [750 - (k % 2) * 30, 520 + k * 34]), ma + 0.25 + k * 0.05, 0.06);
  X("manual.md", 610, 770, ma + 0.3, 0.3, { size: 30, color: DIM });
  POINTS.push([ma, 700, 470]);
  // → the arm
  const ro = T("robot");
  P(poly([820, 590], [960, 590]), ro - 0.3, 0.2); P(poly([935, 570], [962, 590], [935, 610]), ro - 0.1, 0.1);
  X("SO-101 · one $19 wrist camera", 1000, 770, ro + 0.2, 0.4, { size: 30, color: YELLOW });
  POINTS.push([ro, 1140, 560]);
  // → the report
  const re = T("reports");
  P(poly([1320, 590], [1460, 590]), re - 0.3, 0.2); P(poly([1435, 570], [1462, 590], [1435, 610]), re - 0.1, 0.1);
  P(rectP(1500, 470, 200, 240), re, 0.35); P(rectP(1560, 455, 80, 26), re + 0.3, 0.1);
  [[1530, 530, true], [1530, 585, true], [1530, 640, false]].forEach(([x, y, ok], i) => { P(ok ? poly([x, y], [x + 12, y + 14], [x + 34, y - 12]) : poly([x, y - 10], [x + 26, y + 14]), re + 0.4 + i * 0.12, 0.08, { color: ok ? WHITE : "#e8877a" }); P(poly([x + 50, y], [x + 140, y]), re + 0.45 + i * 0.12, 0.06); });
  X("findings · coverage · reward", 1480, 770, re + 0.5, 0.4, { size: 30, color: DIM });
  POINTS.push([re, 1600, 470]);
  // never seen
  const nv = T("never");
  X("no device names in its prompts or code", 960, 880, nv - 0.1, 0.5, { size: 34, color: YELLOW, anchor: "middle" });
  POINTS.push([nv, 960, 850]);

  EL.sort((a, b) => a.start - b.start);
  for (const e of EL) {
    if (e.kind === "path") { e.len = e.node.getTotalLength(); e.node.style.strokeDasharray = `${e.len} ${e.len}`; e.node.style.strokeDashoffset = e.len; }
    else { e.bbox = e.node.getBBox(); e.rect.setAttribute("x", e.bbox.x - 10); }
  }
}

/* The SO-101, two links and a two-finger jaw. `tip` is where the jaw points. */
function armShape(g, tip, style, alpha = 1, base = null) {
  g.innerHTML = "";
  if (alpha <= 0) return;
  const baseX = base ?? clamp(tip[0] * 0.35 + 980, 900, 1760), shoulder = [baseX, 1010];
  const wrist = [tip[0] + 40, tip[1] + 95];
  const L1 = 470, L2 = 440;
  let dx = wrist[0] - shoulder[0], dy = wrist[1] - shoulder[1], d = Math.hypot(dx, dy);
  const reach = L1 + L2 - 4;
  if (d > reach) { wrist[0] = shoulder[0] + dx / d * reach; wrist[1] = shoulder[1] + dy / d * reach; dx = wrist[0] - shoulder[0]; dy = wrist[1] - shoulder[1]; d = reach; }
  const a = Math.atan2(dy, dx), b = Math.acos(clamp((L1 * L1 + d * d - L2 * L2) / (2 * L1 * d), -1, 1));
  const elbow = [shoulder[0] + Math.cos(a + b) * L1, shoulder[1] + Math.sin(a + b) * L1];
  const solid = style === "solid";
  const stroke = YELLOW, fill = solid ? YELLOW : "none", dark = solid ? "#25282b" : "none";
  const grp = svg("g", { opacity: alpha, "stroke-linejoin": "round", "stroke-linecap": "round" }, g);
  const link = (p, q, w) => { const ang = Math.atan2(q[1] - p[1], q[0] - p[0]), nx = -Math.sin(ang) * w / 2, ny = Math.cos(ang) * w / 2;
    svg("path", { d: `M${p[0] + nx} ${p[1] + ny}L${q[0] + nx} ${q[1] + ny}A${w / 2} ${w / 2} 0 0 0 ${q[0] - nx} ${q[1] - ny}L${p[0] - nx} ${p[1] - ny}A${w / 2} ${w / 2} 0 0 0 ${p[0] + nx} ${p[1] + ny}Z`, fill, stroke, "stroke-width": solid ? 2 : 5 }, grp); };
  const servo = (p, s) => svg("rect", { x: p[0] - s / 2, y: p[1] - s / 2, width: s, height: s, rx: 6, fill: dark, stroke: solid ? "#111" : stroke, "stroke-width": solid ? 2 : 5 }, grp);
  svg("rect", { x: baseX - 95, y: 1010, width: 190, height: 70, rx: 8, fill, stroke, "stroke-width": solid ? 2 : 5 }, grp);
  link(shoulder, elbow, 54); link(elbow, wrist, 44);
  servo(shoulder, 66); servo(elbow, 56); servo(wrist, 46);
  const ga = Math.atan2(tip[1] - wrist[1], tip[0] - wrist[0]), gx = Math.cos(ga), gy = Math.sin(ga);
  const jaw = (s) => svg("path", { d: `M${wrist[0] + s * gy * 14} ${wrist[1] - s * gx * 14}L${tip[0] + s * gy * 5} ${tip[1] - s * gx * 5}`, stroke, "stroke-width": solid ? 12 : 6, fill: "none" }, grp);
  jaw(1); jaw(-1);
}

/** Where the arm points at time t: eased between targets, with a small tap on arrival. */
function pointAt(t) {
  const rest = [1300, 860];
  let i = POINTS.findLastIndex((p) => p[0] <= t);
  const from = i > 0 ? POINTS[i - 1].slice(1) : rest, to = i >= 0 ? POINTS[i].slice(1) : rest;
  const k = i >= 0 ? eio((t - POINTS[i][0] + 0.35) / 0.6) : 1;
  const tap = i >= 0 ? Math.max(0, Math.sin(clamp((t - POINTS[i][0] - 0.25) / 0.35) * Math.PI)) * 18 : 0;
  const p = [lerp(from[0], to[0], k), lerp(from[1], to[1], k) + 60 + tap];
  return [p[0], p[1] + Math.sin(t * 1.3) * 4];
}

function seekChalk(t, turn) {
  for (const e of EL) {
    const p = clamp((t - e.start) / e.dur);
    if (e.kind === "path") e.node.style.strokeDashoffset = e.len * (1 - p);
    else e.rect.setAttribute("width", p * (e.bbox.width + 20));
  }
  const lift = ramp(t, turn, turn + 1.4);
  $("ink").setAttribute("opacity", 1 - lift * 0.95);
  $("ink").setAttribute("transform", `translate(0 ${-lift * 40})`);
  const k = eio(ramp(t, RISE[0], RISE[1])), cx = HAND.x + HAND.w / 2, cy = HAND.y + HAND.h / 2;
  SC.raav.setAttribute("opacity", 1 - lift * 0.95);
  SC.raav.setAttribute("transform", `translate(${lerp(cx, 990, k)} ${lerp(cy, 215, k) - lift * 40}) scale(${lerp(1, 0.55, k)}) translate(${-cx} ${-cy})`);
  const tip = pointAt(t);
  const armIn = ramp(t, T("this") - 0.2, T("this") + 0.6);
  armShape($("armchalk"), tip, "chalk", armIn * (1 - ramp(t, turn + 0.3, turn + 0.9)));
  // a puff of dust at each tap
  const g = $("dust"); g.innerHTML = "";
  const i = POINTS.findLastIndex((p) => p[0] <= t);
  if (i >= 0) {
    const age = t - POINTS[i][0] - 0.4, r = rng(i * 7 + 3);
    if (age > 0 && age < 1.2) for (let k = 0; k < 14; k++) svg("circle", { cx: tip[0] + (r() - 0.5) * 40 + (r() - 0.5) * age * 60, cy: tip[1] - 40 + age * age * 90 + r() * 10, r: 1.4 + r() * 2.2, fill: WHITE, opacity: clamp(0.6 - age * 0.5) }, g);
  }
}

/* ───────────── footage ───────────── */
async function setFrame(src, filter = "none", zoom = null, cam = null) {
  const img = $("footage");
  if (!src) { img.style.display = "none"; return; }
  img.style.display = "block";
  img.style.filter = filter;
  if (cam) { img.style.transformOrigin = "0 0"; img.style.transform = `translate(${960 - cam.cx * cam.s}px, ${540 - cam.cy * cam.s}px) scale(${cam.s})`; }
  else { img.style.transformOrigin = zoom ? `${zoom[1]}px ${zoom[2]}px` : "50% 50%"; img.style.transform = zoom ? `scale(${zoom[0]})` : "none"; }
  if (img.getAttribute("src") !== src) { img.setAttribute("src", src); try { await img.decode(); } catch { } }
}
function frameOf(clip, sec) {
  const c = CLIPS[clip];
  if (!c) return null;
  const n = Math.max(1, Math.min(c.frames, Math.floor(sec * FPS) + 1));
  return `../out/frames/${c.dir}/${String(n).padStart(5, "0")}.jpg`;
}

/* ───────────── a user's view of the Console: the camera follows the clicks, and a cursor ───────────── */
function camOf(box) {
  const [x, y, w, h] = box, s = clamp(Math.min(1920 / w, 1080 / h) * 0.94, 1, 2.2);
  const hw = 960 / s, hh = 540 / s;
  return { cx: clamp(x + w / 2, hw, 1920 - hw), cy: clamp(y + h / 2, hh, 1080 - hh), s };
}
function camAt(t) {
  const K = LAY.cam;
  let i = K.findLastIndex((k) => k[0] <= t);
  if (i < 0) i = 0;
  const cur = camOf(K[i][1]), prev = camOf(K[Math.max(0, i - 1)][1]);
  const k = eio((t - K[i][0]) / 0.9);
  return { cx: lerp(prev.cx, cur.cx, k), cy: lerp(prev.cy, cur.cy, k), s: Math.exp(lerp(Math.log(prev.s), Math.log(cur.s), k)) };
}
function drawCursor(t, cam) {
  const C = LAY.cursor;
  let i = C.findLastIndex((c) => c[0] <= t);
  if (i < 0) return;
  const a = C[i], b = C[i + 1] && C[i + 1][0] - a[0] < 0.3 ? C[i + 1] : a;
  const k = b === a ? 0 : clamp((t - a[0]) / (b[0] - a[0]));
  const x = 960 + (lerp(a[1], b[1], k) - cam.cx) * cam.s, y = 540 + (lerp(a[2], b[2], k) - cam.cy) * cam.s;
  const g = svg("g", {}, $("overlay"));
  for (const c of LAY.clicks) {
    const age = t - c[0];
    if (age >= 0 && age < 0.6) svg("circle", { cx: 960 + (c[1] - cam.cx) * cam.s, cy: 540 + (c[2] - cam.cy) * cam.s, r: 10 + age * 70, fill: "none", stroke: "#eebc24", "stroke-width": 3, opacity: 1 - age / 0.6 }, g);
  }
  svg("path", { d: "M0 0 L0 26 L7 20 L12 31 L17 29 L12 18 L21 18 Z", transform: `translate(${x} ${y})`, fill: "#fff", stroke: "#111", "stroke-width": 1.6, "stroke-linejoin": "round" }, g);
}

/* ───────────── the Console's look: demo cards, the two systems, the end ───────────── */
const SC = {};
function card(label, color, x, y, w) {
  const n = el("div", "abs", `<div class="label" style="color:${color};margin-bottom:8px">${label}</div><div class="body mono" style="font-size:23px;line-height:1.45;color:#eceef0"></div>`, SC.cards,
    `left:${x}px;top:${y}px;width:${w}px;padding:18px 22px;background:rgba(14,16,18,.9);border:1.5px solid ${color};box-sizing:border-box;opacity:0`);
  n.body = n.querySelector(".body");
  return n;
}

function buildTech() {
  const S = LAY.steps;
  /* §3 the demo: a step rail and cards that carry what the voice doesn't */
  SC.cards = el("div", "abs", "", $("stage"), "inset:0;z-index:25;pointer-events:none");
  SC.c1 = card("System 1", "#eebc24", 70, 640, 760);
  SC.c2 = card("System 2", "#8fb3d9", 1090, 640, 760);
  SC.cp = card("A person", "#f0a63a", 780, 540, 360); SC.cp.style.background = "rgba(40,28,10,.94)"; SC.cp.style.textAlign = "center";
  SC.stamp = el("div", "abs mono", "", SC.cards, "left:40px;top:76px;font-size:18px;color:#cfd3d6;background:rgba(10,12,14,.7);padding:5px 10px;opacity:0");
  SC.note = el("div", "abs mono", "", SC.cards, "right:36px;top:76px;font-size:16px;color:#9aa0a5;background:rgba(10,12,14,.7);padding:5px 10px;opacity:0;max-width:820px;text-align:right");
  const RUN = "Rev A run · Claude Sonnet 5.5 · MuJoCo";
  const s3 = S.s3;
  SC.beats = []; const OLD_BEATS = [
    { a: T("touches", s3), b: S.model - 0.2, freeze: true, stamp: "explore", s1: "First scan stopped on a corrupt frame<br>→ System 2 reran it: <b>9 controls</b> mapped", src: RUN },
    { a: S.model + 0.4, b: S.then - 0.2, stamp: "plan", s2: "35 properties to test · plan check<br>refused plan 0; the model fixed it", p: "Karthik · Approve", pAt: T("person", s3), src: RUN + " · approved in the Console" },
    { a: T("capped", s3) - 0.3, b: S.display - 0.2, stamp: "test", s1: "Hard cap <b>15 N</b> · steps ask ≤ 14 N<br>Retries 0 / 2 / 4 by autonomy<br>Verdicts: fixed rules, in System 1", src: "docs/system-boundary.md · decisions D31, D34" },
    { a: S.display, b: S.lid - 0.2, freeze: true, stamp: "s1 flip POWER", s1: "lcd <b>“1000rpm  0:30”</b><br>≠ manual “1000 RPM 0:30”", s2: "Plan amended: s2 … s11<br>Level <b>0 · automatic</b>, set by code", src: RUN + " · step s1" },
    { a: S.lid, b: S.lidui - 0.1, freeze: true, stamp: "s7 turn handle_1", s1: "<b style='color:#ff8a7a'>SKIPPED</b> before the arm moved<br>rule: usable with no thumbs", s2: "Finding: “NO-THUMBS” on the lid lip", src: RUN + " · step s7" },
    { a: S.there, b: S.test - 0.2, stamp: "Design Analysis", s2: "F2 · lid_grip <span class='old'>pinch</span> → tip<br>F3 · well_a_id <span class='old'>15.6</span> → 16.8 mm", p: "approves the patch", pAt: T("approve", S.there), src: "Rev B as drawn by the team · patches from a run aren't shown yet" },
    { a: S.test, b: S.s4 - 0.3, stamp: "Rev B", s1: "handle_1 swung to <b style='color:#7fd68f'>100°</b> ✓<br>well A seats the tube ✓", src: "verification check (verify.stock.json) · Rev B run agent-centrifuge-045535" },
  ];
  const RAIL = ["survey", "scan", "segment", "map", "touch", "plan", "test", "verdicts", "report", "CAD fix", "Rev B"];
  SC.railAt = [T("surveys", s3), S.wrist, T("finds", s3), T("finds", s3) + 0.5, S.touches, S.model, S.then, T("verdict", s3), T("reported", s3), S.there, S.test];
  $("rail").innerHTML = RAIL.map((r) => `<span>${r}</span>`).join("");
  SC.rail = [...$("rail").children];

  /* §4 two systems: a diagram, not the spoken list */
  const s4 = S.s4;
  SC.sys = el("div", "abs", "", undefined, "inset:0");
  SC.col1 = el("div", "box", `<div class="mich s1" style="font-size:42px">SYSTEM 1</div><div class="mono" style="font-size:20px;color:#a88a2a;margin-top:6px">the robot</div>`, SC.sys, "left:150px;top:150px;width:700px;height:520px;padding:32px 36px;box-sizing:border-box;border-color:#eebc24");
  SC.col2 = el("div", "box", `<div class="mich s2" style="font-size:42px">SYSTEM 2</div><div class="mono" style="font-size:20px;color:#6f8fb0;margin-top:6px">a frontier model</div>`, SC.sys, "left:1070px;top:150px;width:700px;height:520px;padding:32px 36px;box-sizing:border-box;border-color:#8fb3d9");
  const tag = (parent, txt, color) => el("span", "chip", txt, parent, `margin:0 10px 12px 0;border-color:${color}55;opacity:0`);
  SC.wrap1 = el("div", "", "", SC.col1, "margin-top:34px"); SC.wrap2 = el("div", "", "", SC.col2, "margin-top:34px");
  const t1 = [["OWLv2 + SAM", "perception"], ["IK", "inverse"], ["servo control", "control"], ["15 N cap", "force"], ["fixed verdict rules", "verdict"]];
  const t2 = [["manual → 35 properties", "reads"], ["plan · 7 tools", "plans"], ["retry · re-plan", "recovers"], ["root cause → CAD patch", "diagnoses"]];
  SC.tags = [...t1.map(([x, w]) => ({ n: tag(SC.wrap1, x, "#eebc24"), t: T(w, s4) })), ...t2.map(([x, w]) => ({ n: tag(SC.wrap2, x, "#8fb3d9"), t: T(w, s4) }))];
  SC.tools = el("div", "abs", Array.from({ length: 7 }, (_, i) => `<div style="position:absolute;left:0;top:${i * 30}px;width:220px;height:1.5px;background:linear-gradient(90deg,#eebc24,#8fb3d9)"></div>`).join("")
    + `<div class="label" style="position:absolute;top:214px;width:220px;text-align:center">7 tools</div>`, SC.sys, "left:850px;top:300px;width:220px;height:240px");
  SC.noMotor = el("div", "abs mono", "<span style='text-decoration:line-through'>move_joint</span> · <span style='text-decoration:line-through'>grade_own_step</span>", SC.sys, "left:850px;top:560px;width:220px;text-align:center;font-size:17px;color:#e38b7a;opacity:0");
  SC.model = el("div", "abs mono", "", SC.sys, "left:1106px;top:600px;font-size:21px;color:#9fbddc;opacity:0");
  SC.lock = el("div", "abs mono", "limits enforced in code", SC.sys, "left:186px;top:610px;font-size:20px;color:#eebc24;opacity:0");
  SC.vla = el("div", "abs", `<div class="label" style="margin-bottom:8px">Instead: one network</div><div class="box" style="position:relative;padding:16px 20px"><div class="mono" style="font-size:21px;color:#d9dcdf">perception + reasoning + control</div><div class="mono" style="font-size:17px;color:#8b9095;margin-top:8px">SmolVLA · 50 demos/task &nbsp; GR00T N1 · 30–300 demos/task</div></div>`, SC.sys, "left:150px;top:720px;width:820px;opacity:0");
  SC.manualTag = el("div", "abs mono", "a manual, not demonstrations", SC.sys, "left:1070px;top:740px;font-size:22px;color:#9fbddc;opacity:0");
  SC.limit = el("div", "abs mono", "new kind of control → a new skill, in code", SC.sys, "left:1070px;top:790px;font-size:22px;color:#f0a63a;opacity:0");

  /* §5 behind the scenes: source chips, and the title card */
  const s5 = S.s5;
  // case studies: one pop-up at a time as each is named
  const ICON = {
    lean: `<text x="32" y="44" text-anchor="middle" font-size="40" fill="#8fb3d9" font-family="JetBrains Mono">⊢</text>`,
    chip: `<rect x="14" y="14" width="36" height="36" rx="4" fill="none" stroke="#8fb3d9" stroke-width="3"/>${[20, 32, 44].map((v) => `<path d="M${v} 6v8M${v} 50v8M6 ${v}h8M50 ${v}h8" stroke="#8fb3d9" stroke-width="3"/>`).join("")}`,
    shield: `<path d="M32 6 L54 14 V30 C54 44 44 54 32 58 C20 54 10 44 10 30 V14 Z" fill="none" stroke="#8fb3d9" stroke-width="3"/><path d="M22 32 l7 7 l14 -15" fill="none" stroke="#8fb3d9" stroke-width="3.5"/>`,
    flask: `<path d="M24 8 h16 M27 8 v16 L12 52 a4 4 0 0 0 4 6 h32 a4 4 0 0 0 4 -6 L37 24 V8" fill="none" stroke="#e38b7a" stroke-width="3"/><path d="M17 44 h30" stroke="#e38b7a" stroke-width="3"/>`,
    scope: `${[[32, 22], [22, 34], [42, 34], [32, 46]].map(([x, y]) => `<path d="M${x} ${y - 9} l8 4.5 v9 l-8 4.5 l-8 -4.5 v-9 z" fill="none" stroke="#e38b7a" stroke-width="2.6"/>`).join("")}`,
    stack: `${[0, 1, 2, 3].map((i) => `<rect x="${12 + i * 3}" y="${46 - i * 11}" width="${40 - i * 6}" height="9" fill="none" stroke="#e38b7a" stroke-width="2.6"/>`).join("")}`,
  };
  SC.pops = [["lean", "lean", "Lean", "Two AI-claimed refutations of the Exponential Time Hypothesis, checked in Lean", "Oct 2026 · still under examination", "#8fb3d9"],
    ["compcert", "chip", "CompCert", "A C compiler proven correct in Coq, qualified for ATR 42/72 avionics", "compcert.org · 2026", "#8fb3d9"],
    ["sel4", "shield", "seL4", "A proven OS kernel: on Boeing's Little Bird, a red team couldn't break out, even in flight", "DARPA HACMS", "#8fb3d9"],
    ["biosafety", "flask", "Biosafety", "Foot-and-mouth virus most likely escaped Pirbright's labs through damaged drains", "UK HSE report · 2007", "#e38b7a"],
    ["spacecraft", "scope", "Spacecraft", "Webb's sunshield fasteners shook loose in an acoustic test, part of a 29-month delay", "JWST review board · 2018", "#e38b7a"],
    ["thousands", "stack", "Prototypes", "5,127 prototypes over 15 years before Dyson's first vacuum, the DC01", "1993", "#e38b7a"]]
    .map(([w, icon, title, fact, src, c]) => ({ t: T(w, s5), n: el("div", "abs", `<svg width="64" height="64" viewBox="0 0 64 64" style="flex:none">${ICON[icon]}</svg><div><div class="mich" style="font-size:34px;color:${c}">${title}</div><div style="font:500 29px/1.4 Inter,sans-serif;color:#eceef0;margin-top:8px">${fact}</div><div class="mono" style="font-size:16px;color:#8b9095;margin-top:10px">${src}</div></div>`, SC.cards,
      `left:460px;top:330px;width:1000px;display:flex;gap:26px;align-items:flex-start;padding:28px 32px;background:rgba(14,16,18,.95);border:1.5px solid ${c};border-left-width:5px;box-sizing:border-box;opacity:0;box-shadow:0 30px 80px rgba(0,0,0,.55)`) }));
  SC.titleBg = el("div", "abs", "", SC.cards, "inset:0;background:#111417;opacity:0");
  SC.title = el("div", "abs", `<div class="mich" style="font-size:150px;color:#f1f2f3;text-align:center">RAAV</div><div class="mich" style="font-size:44px;color:#eebc24;text-align:center;letter-spacing:.2em;margin-top:6px">ROBOT AS A VERIFIER</div><div class="mono" style="font-size:22px;color:#8b9095;text-align:center;margin-top:40px">MakeCU 2026</div>`, SC.cards, "left:0;right:0;top:330px;opacity:0");
}

/** The B-roll dims while a case-study pop-up is up. */
function popDim(t) { return SC.pops ? 1 - 0.45 * Math.max(0, ...SC.pops.map((p, i) => { const until = Math.min(SC.pops[i + 1]?.t ?? LAY.steps.as_, p.t + 4.0); return ramp(t, p.t - 0.15, p.t + 0.2) * (1 - ramp(t, until - 0.2, until)); })) : 1; }
const MODELS = ["claude-sonnet-5-5", "claude-haiku-5-5", "openai-gpt-5.4", "grok-4.7"];
function seekTech(t) {
  const S = LAY.steps;
  // §3 rail and cards
  const inDemo = t >= S.s3 - 0.2 && t < S.s4 - 0.2;
  $("rail").style.display = "none";
  const cur = SC.railAt.findLastIndex((x) => x <= t + 0.05);
  SC.rail.forEach((s, i) => { s.className = i === cur ? "on" : i < cur ? "done" : ""; });
  const beat = SC.beats.find((b) => b.a <= t && t < b.b);
  const o = beat ? ramp(t, beat.a, beat.a + 0.4) * (1 - ramp(t, beat.b - 0.25, beat.b)) : 0;
  for (const [n, key] of [[SC.c1, "s1"], [SC.c2, "s2"], [SC.cp, "p"]]) {
    const txt = beat?.[key];
    if (txt && n.body.innerHTML !== txt) n.body.innerHTML = txt;
    const at = key === "p" ? beat?.pAt ?? beat?.a + 0.5 : beat?.a + (key === "s2" ? 0.25 : 0);
    show(n, txt ? o * ramp(t, at, at + 0.35) : 0, 14);
  }
  SC.stamp.style.opacity = o; if (beat) SC.stamp.textContent = beat.stamp;
  SC.note.style.opacity = o * 0.95; if (beat) SC.note.textContent = beat.src;
  // §4
  const s4 = S.s4, s5 = S.s5;
  const so = ramp(t, s4 - 0.4, s4 + 0.3) * (1 - ramp(t, s5 - 0.6, s5));
  SC.sys.style.opacity = so;
  SC.sys.style.display = so > 0 ? "block" : "none";
  if (so > 0) {
    const s1at = T("robot", s4) - 1.0, s2at = T("frontier", s4) - 1.2;
    SC.col1.style.opacity = ramp(t, s1at - 0.2, s1at + 0.3);
    SC.col2.style.opacity = ramp(t, s2at - 0.2, s2at + 0.3);
    for (const g of SC.tags) show(g.n, ramp(t, g.t - 0.15, g.t + 0.25), 8);
    SC.tools.style.opacity = ramp(t, T("plans", s4) - 0.2, T("plans", s4) + 0.4);
    SC.noMotor.style.opacity = ramp(t, T("motor", s4) - 0.2, T("motor", s4) + 0.3);
    SC.model.style.opacity = ramp(t, T("swapped", s4) - 0.3, T("swapped", s4) + 0.3);
    SC.model.textContent = "model: " + MODELS[Math.floor(Math.max(0, t - T("swapped", s4)) / 1.1) % MODELS.length];
    const lim = T("limits", T("swapped", s4)); SC.lock.style.opacity = ramp(t, lim - 0.2, lim + 0.3);
    const vla = T("vision", s4);
    show(SC.vla, ramp(t, vla - 0.2, vla + 0.4) * (1 - 0.6 * ramp(t, T("split", s4) - 0.2, T("split", s4) + 0.4)), 12);
    const dim = ramp(t, vla - 0.2, vla + 0.4) * (1 - ramp(t, T("split", s4) - 0.2, T("split", s4) + 0.4));
    SC.col1.style.filter = SC.col2.style.filter = `brightness(${1 - 0.45 * dim})`;
    SC.manualTag.style.opacity = ramp(t, T("manual", T("split", s4)) - 0.2, T("manual", T("split", s4)) + 0.3);
    SC.limit.style.opacity = ramp(t, T("limit", T("split", s4)) - 0.2, T("limit", T("split", s4)) + 0.3);
  }
  // §5
  const end = S.end;
  SC.pops.forEach((p, i) => {
    const until = Math.min(SC.pops[i + 1]?.t ?? S.as_, p.t + 4.0);
    const o = ramp(t, p.t - 0.15, p.t + 0.2) * (1 - ramp(t, until - 0.2, until));
    p.n.style.opacity = o; p.n.style.transform = `scale(${0.94 + 0.06 * eio(ramp(t, p.t - 0.15, p.t + 0.3))})`;
  });
  SC.titleBg.style.opacity = ramp(t, end - 0.5, end + 0.2);
  SC.title.style.opacity = ramp(t, end - 0.2, end + 0.5);
}

/* ───────────── captions and the clock ───────────── */
function caption(t) {
  const c = CAPS.find((x) => x.s <= t && t < x.e);
  const cap = $("cap");
  cap.style.display = c ? "inline-block" : "none";
  if (c && cap.textContent !== c.t) cap.textContent = c.t;
}

window.seek = async function (t) {
  const S = LAY.steps;
  $("overlay").innerHTML = "";
  const turn = S.never - 0.1;
  // footage, wherever a segment covers t
  const seg = LAY.segments.find((s) => s[0] <= t && t < s[1]);
  const beat = SC.beats.find((b) => b.a <= t && t < b.b);
  if (seg) {
    const [from, , clip, c0, speed, hold, zoom] = seg;
    const frozen = beat?.freeze && t > beat.a + 0.35 && t < beat.b - 0.25;
    const sec = hold != null && frozen ? hold : c0 + (t - from) * speed;
    let z = zoom, cam = null;
    if (clip.startsWith("tour/")) cam = camAt(t);
    if (clip === "intro") {
      // centered on the question mark, then following the take's own push-in to RAAV
      const k = eio(ramp(t, 11.6, 13.8)); // identity by the hold, so the cutout lines up
      z = [lerp(1.45, 1.0, k), lerp(1130, 980, k), lerp(430, 480, k)];
    }
    const f = frozen ? 1 : 0;
    await setFrame(frameOf(clip, sec), `saturate(${1 - 0.6 * f}) brightness(${(1 - 0.3 * f) * popDim(t)})`, z, cam);
    if (cam) drawCursor(t, cam);
  } else await setFrame(null);
  $("footage").style.opacity = seg?.[2] === "intro" ? 1 - ramp(t, FADE[0], FADE[1]) : 1;
  $("tag").style.display = seg && /^clean_3d|^wrist/.test(seg[2]) ? "block" : "none";
  // chalk, from the take's end until the turn
  const chalkO = (t >= FADE[0] ? 1 : 0) * (1 - ramp(t, turn + 0.6, turn + 1.6));
  $("chalklayer").style.opacity = chalkO;
  if (chalkO > 0) seekChalk(t, turn);
  $("tech").style.opacity = ramp(t, turn + 0.4, turn + 1.4);
  seekTech(t);
  caption(t);
  $("fade").style.opacity = ramp(t, DUR - 1.0, DUR);
};

window.ready = (async () => {
  WORDS = await (await fetch("words.json")).json();
  CAPS = await (await fetch("captions.json")).json();
  LAY = await (await fetch("segments.json")).json();
  CLIPS = await (await fetch("../out/frames/clips.json")).json();
  DUR = LAY.steps.end + 4.5;
  await document.fonts.load('700 40px "Cabin Sketch"'); await document.fonts.load('40px "Architects Daughter"');
  await document.fonts.load('40px Michroma'); await document.fonts.load('500 20px "JetBrains Mono"'); await document.fonts.load('600 20px Inter');
  await document.fonts.ready;
  buildChalk();
  buildTech();
  window.DUR = DUR;
  return true;
})();
