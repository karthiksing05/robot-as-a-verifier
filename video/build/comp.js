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
// The take is split (footage.py). Opening: the camera pushes gently toward the chalk, then jumps into its tip with motion
// blur as he steps up; the board opens out of that point and RAAV builds in the Console's face. Closing: the Console pushes
// in and blurs away, the take comes back on the chalk and eases out to the full frame while he writes RAAV, walks off, black.
const OPEN = [6.1, 6.65], TITLE = [6.45, 7.4], RISE = [10.55, 11.45];
const CAM0 = { cx: 1012.8, cy: 505.9, s: 1.45 }, CAM1 = { cx: 993, cy: 442, s: 3.2 }, CAMID = { cx: 960, cy: 540, s: 1 }; // CAM0 = the old crop
const camLerp = (a, b, k) => ({ cx: lerp(a.cx, b.cx, k), cy: lerp(a.cy, b.cy, k), s: Math.exp(lerp(Math.log(a.s), Math.log(b.s), k)) });
const CAMP = camLerp(CAM0, CAM1, 0.1), CAMC = { cx: 993, cy: 442, s: 2.2 };
const LOGO = "../../docs/assets/logo.png";
const HAND = { x: 460, y: 282, w: 1000, h: 456 };
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

  /* RAAV in the Console's face, built scan line by scan line as the board opens, then the name, word by word as it's said */
  const defs = $("boardsvg").querySelector("defs");
  const cp = svg("clipPath", { id: "scanclip", clipPathUnits: "userSpaceOnUse" }, defs);
  SC.stripes = Array.from({ length: 18 }, (_, j) => svg("rect", { x: 400, y: 300 + j * 12, width: 0, height: 12.6 }, cp));
  SC.title = svg("g", { filter: "url(#chalk)" }, $("board"));
  const lettersG = svg("g", { "clip-path": "url(#scanclip)" }, SC.title);
  const LX = [-1.5, -0.5, 0.5, 1.5].map((k) => 960 + k * 245);
  const WORD = ["robot", "as", "a", "verifier"];
  let after = T("raav") + 0.2;
  SC.letters = LX.map((x, i) => {
    const at = T(WORD[i], after); after = at + 0.05;
    for (const [c, o] of [[WHITE, 1], [YELLOW, 0]]) { const n = svg("text", { x, y: 500, fill: c, opacity: o, "font-size": 196, "font-family": "Michroma", "text-anchor": "middle" }, lettersG); n.textContent = "RAAV"[i]; if (o === 0) var hi = n; }
    POINTS.push([at - 0.3, x, 268]);
    return { at, hi };
  });
  POINTS.unshift([T("raav") - 0.3, 960, 250]);
  SC.scan = svg("rect", { x: 420, y: 300, width: 1080, height: 3, fill: YELLOW, opacity: 0 }, SC.title);
  SC.sub = svg("text", { x: 960, y: 610, fill: DIM, "font-size": 40, "font-family": "Michroma", "text-anchor": "middle", "letter-spacing": 6 }, SC.title);
  SC.words = ["ROBOT", "AS", "A", "VERIFIER"].map((w, i) => {
    const sp = svg("tspan", { "fill-opacity": 0, dx: i ? 30 : 0 }, SC.sub);
    svg("tspan", { fill: YELLOW }, sp).textContent = w[0];
    if (w.length > 1) svg("tspan", {}, sp).textContent = w.slice(1);
    return { n: sp, at: SC.letters[i].at };
  });
  // once it's been named, it settles at the top as Bayan's handwritten logo
  SC.logo = svg("image", { href: LOGO, x: 960 - 175, y: 40, width: 350, height: 160, opacity: 0 }, $("board"));

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
  const ro = T("robot", ma);
  P(poly([820, 590], [960, 590]), ro - 0.3, 0.2); P(poly([935, 570], [962, 590], [935, 610]), ro - 0.1, 0.1);
  X("SO-101 · one $19 wrist camera", 1000, 770, ro + 0.2, 0.4, { size: 30, color: YELLOW });
  POINTS.push([ro, 1140, 560]);
  // it tests every control: the arm taps the drawing's three buttons, and each gets a tick
  const te = T("tests", ro);
  [250, 310, 370].forEach((x, i) => { const at = te + i * 0.45; POINTS.push([at, x, 540]); P(poly([x - 11, 596], [x - 2, 608], [x + 16, 582]), at + 0.3, 0.12, { color: YELLOW, w: 6 }); });
  // → the report
  const re = T("reports", te);
  P(poly([1320, 590], [1460, 590]), re - 0.3, 0.2); P(poly([1435, 570], [1462, 590], [1435, 610]), re - 0.1, 0.1);
  P(rectP(1500, 470, 200, 240), re, 0.35); P(rectP(1560, 455, 80, 26), re + 0.3, 0.1);
  [[1530, 530, true], [1530, 585, true], [1530, 640, false]].forEach(([x, y, ok], i) => { P(ok ? poly([x, y], [x + 12, y + 14], [x + 34, y - 12]) : poly([x, y - 10], [x + 26, y + 14]), re + 0.4 + i * 0.12, 0.08, { color: ok ? WHITE : "#e8877a" }); P(poly([x + 50, y], [x + 140, y]), re + 0.45 + i * 0.12, 0.06); });
  X("findings · coverage · reward", 1470, 770, re + 0.5, 0.4, { size: 26, color: DIM });
  POINTS.push([re, 1600, 470]);
  // "our centrifuge": back to the prototype, circled, and the board gives way to the real one
  const oc = T("our", re);
  POINTS.push([oc - 0.55, 330, 430]);
  P(circ(335, 590, 205), oc - 0.4, 0.4, { color: YELLOW, w: 6 });

  POINTS.sort((a, b) => a[0] - b[0]);
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
  const baseX = base ?? clamp(tip[0] * 0.35 + 980, 900, 1760), shoulder = [baseX, 935];
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
  svg("rect", { x: baseX - 95, y: 935, width: 190, height: 70, rx: 8, fill, stroke, "stroke-width": solid ? 2 : 5 }, grp);
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
  const lift = ramp(t, turn, turn + 1.4), fadeL = 1 - lift * 0.95;
  $("ink").setAttribute("opacity", fadeL);
  $("ink").setAttribute("transform", `translate(0 ${-lift * 40})`);
  // the title: scan lines build it, each word of the name lands as it's said, then it rises and becomes the logo
  const ta = TITLE[0];
  SC.stripes.forEach((r, j) => r.setAttribute("width", eio(ramp(t, ta + j * 0.03, ta + j * 0.03 + 0.42)) * 1120));
  SC.scan.setAttribute("y", lerp(300, 520, ramp(t, ta, ta + 0.9)));
  SC.scan.setAttribute("opacity", 0.8 * ramp(t, ta, ta + 0.1) * (1 - ramp(t, ta + 0.75, ta + 0.95)));
  SC.words.forEach((w) => w.n.setAttribute("fill-opacity", ramp(t, w.at - 0.12, w.at + 0.18)));
  SC.letters.forEach((L) => L.hi.setAttribute("opacity", ramp(t, L.at - 0.05, L.at + 0.1) * (1 - ramp(t, L.at + 0.6, L.at + 1.4))));
  const k = eio(ramp(t, RISE[0], RISE[1])), sw = ramp(t, RISE[1] - 0.25, RISE[1] + 0.45);
  SC.title.setAttribute("transform", `translate(960 ${lerp(430, 118, k) - lift * 40}) scale(${lerp(1, 0.34, k)}) translate(-960 -430)`);
  SC.title.setAttribute("opacity", (1 - sw) * fadeL);
  SC.sub.setAttribute("opacity", 1 - ramp(t, RISE[0], RISE[0] + 0.4));
  SC.logo.setAttribute("opacity", sw * fadeL);
  SC.logo.setAttribute("transform", `translate(0 ${-lift * 40})`);
  // the arm
  const tip = pointAt(t);
  const armIn = ramp(t, T("this") - 0.5, T("this") + 0.4);
  armShape($("armchalk"), tip, "chalk", armIn * (1 - ramp(t, turn + 0.3, turn + 0.9)));
  // a puff of dust at each tap
  const g = $("dust"); g.innerHTML = "";
  const i = POINTS.findLastIndex((p) => p[0] <= t);
  if (i >= 0 && t < turn + 0.3) {
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

/* ───────────── a caricature globe ───────────── */
// Rough continents as [lon, lat] outlines: a cartoon, not a map.
const LANDS = [
  [[-165, 65], [-140, 70], [-95, 72], [-75, 62], [-60, 50], [-80, 30], [-97, 18], [-85, 10], [-105, 22], [-118, 33], [-125, 48], [-150, 58]],
  [[-80, 10], [-60, 8], [-35, -7], [-40, -22], [-58, -38], [-70, -52], [-75, -40], [-72, -15], [-81, -4]],
  [[-10, 36], [0, 43], [-5, 48], [5, 53], [10, 58], [25, 70], [40, 66], [40, 45], [28, 40], [15, 38]],
  [[-17, 15], [-10, 30], [10, 37], [33, 31], [43, 12], [51, 11], [40, -15], [32, -28], [20, -35], [12, -17], [8, 4], [-8, 5]],
  [[40, 45], [40, 66], [70, 73], [110, 77], [140, 72], [170, 66], [140, 55], [130, 35], [120, 22], [105, 10], [100, 20], [80, 8], [72, 20], [58, 25], [48, 30]],
  [[114, -22], [122, -18], [131, -12], [142, -11], [153, -27], [146, -39], [135, -35], [115, -34]],
];
/** Draws a globe into SVG group g: centre (cx, cy), radius r, turned to lon0 degrees. pins: [{lon, lat, at, label}] pulse in from `at`. */
function drawGlobe(g, t, cx, cy, r, lon0, o = {}) {
  const ink = o.ink ?? "#8fb3d9", land = o.land ?? "#eebc24", tilt = (o.tilt ?? 18) * Math.PI / 180, D = Math.PI / 180;
  g.innerHTML = "";
  const P = (lon, lat) => { const l = (lon - lon0) * D, p = lat * D; const x = Math.cos(p) * Math.sin(l), y0 = Math.sin(p), z0 = Math.cos(p) * Math.cos(l);
    const y = y0 * Math.cos(tilt) - z0 * Math.sin(tilt), z = y0 * Math.sin(tilt) + z0 * Math.cos(tilt); return [cx + r * x, cy - r * y, z]; };
  const line = (pts, attrs) => { let d = "", pen = false; for (const [lon, lat] of pts) { const [x, y, z] = P(lon, lat); if (z > 0) { d += `${pen ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`; pen = true; } else pen = false; } if (d) svg("path", { d, fill: "none", ...attrs }, g); };
  svg("circle", { cx, cy, r: r + 26, fill: ink, opacity: 0.06 }, g);
  svg("circle", { cx, cy, r, fill: o.sea ?? "#151b22", stroke: ink, "stroke-width": 2.5 }, g);
  for (let lon = 0; lon < 360; lon += 30) line(Array.from({ length: 61 }, (_, i) => [lon, -90 + i * 3]), { stroke: ink, "stroke-width": 1.2, opacity: 0.45 });
  for (let lat = -60; lat <= 60; lat += 30) line(Array.from({ length: 121 }, (_, i) => [i * 3, lat]), { stroke: ink, "stroke-width": 1.2, opacity: lat ? 0.35 : 0.6 });
  for (const poly of LANDS) {
    const pts = []; poly.concat([poly[0]]).forEach((q, i, a) => { if (!i) return; const [a0, a1] = a[i - 1]; const n = Math.ceil(Math.hypot(q[0] - a0, q[1] - a1) / 3); for (let k = 0; k < n; k++) pts.push([a0 + (q[0] - a0) * k / n, a1 + (q[1] - a1) * k / n]); });
    line(pts, { stroke: land, "stroke-width": 3, "stroke-linejoin": "round", opacity: 0.9 });
  }
  const pos = [];
  for (const pin of o.pins ?? []) {
    const [x, y, z] = P(pin.lon, pin.lat), k = ramp(t, pin.at, pin.at + 0.4) * clamp(z * 4);
    pos.push([x, y, z]);
    if (k <= 0) continue;
    const age = (t - pin.at) % 1.6;
    svg("circle", { cx: x, cy: y, r: 8 + age * 22, fill: "none", stroke: land, "stroke-width": 2, opacity: k * (1 - age / 1.6) }, g);
    svg("circle", { cx: x, cy: y, r: 7, fill: pin.hollow ? "none" : land, stroke: pin.hollow ? "#c9cdd1" : "none", "stroke-width": 2, opacity: pin.hollow ? k * 0.8 : k }, g);
    if (pin.label) { const bg = svg("rect", { x: x + 8, y: y - 40, height: 36, rx: 3, fill: "#15181b", opacity: 0.92 * k }, g); const tx = svg("text", { x: x + 18, y: y - 15, fill: "#e4e6e8", "font-size": 22, "font-family": "JetBrains Mono", opacity: k }, g); tx.textContent = pin.label; bg.setAttribute("width", tx.getComputedTextLength() + 20); }
  }
  return pos;
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
  SC.cards = el("div", "abs", "", $("tech"), "inset:0;z-index:25;pointer-events:none");
  /* §4 two systems: filled with the real run's own data from the start; each part lights up as it's named */
  const s4 = S.s4;
  SC.sys = el("div", "abs", "", undefined, "inset:0");
  const panel = (x, color, title, sub) => el("div", "box", `<div style="display:flex;align-items:baseline;gap:18px"><div class="mich" style="font-size:40px;color:${color}">${title}</div><div class="mono sub" style="font-size:19px;color:${color}aa">${sub}</div></div>`, SC.sys, `left:${x}px;top:96px;width:790px;height:830px;padding:26px 34px;box-sizing:border-box;border-color:${color}`);
  SC.col1 = panel(64, "#eebc24", "SYSTEM 1", "the robot · code");
  SC.col2 = panel(1066, "#8fb3d9", "SYSTEM 2", "");
  SC.model = SC.col2.querySelector(".sub");
  const K = 'style="font:500 15px JetBrains Mono,monospace;letter-spacing:.12em;text-transform:uppercase;color:#7d8389;margin-bottom:10px"';
  const row = (col, h, label, html, color, at) => { const n = el("div", "", `<div ${K}>${label}</div>${html}<div class="hl" style="position:absolute;left:0;bottom:-4px;height:4px;width:100%;background:${color};transform-origin:0 50%;transform:scaleX(0)"></div>`, col, `position:relative;margin-top:32px;height:${h}px`); return { n, at, hl: n.querySelector(".hl") }; };
  const mono = (s, size = 21, c = "#dfe2e5") => `<div class="mono" style="font-size:${size}px;color:${c};line-height:1.5">${s}</div>`;
  const chips = (xs, c) => `<div>${xs.map((x) => `<span class="chip" style="font-size:18px;padding:4px 9px;margin:0 7px 7px 0;border-color:${c}55">${x}</span>`).join("")}</div>`;
  const Y = "#eebc24", B = "#8fb3d9";
  // System 1: the real run's own controls, skills, forces and a verdict rule
  const FORCES = [["TIME+", 22.5, "7.2 mm"], ["START", 15.8, "4.4 mm"], ["STOP", 13.8, "8.8 mm"]];
  const fx = (n) => n / 30 * 420;
  const bars = FORCES.map(([c, n, mm], i) => `<text x="0" y="${30 + i * 48}" fill="#8b9095" font-size="17">${c}</text><rect ${c === "START" ? 'id="startbar"' : ""} x="90" y="${12 + i * 48}" width="${fx(n)}" height="26" rx="3" fill="${Y}" opacity=".85" stroke="#fff" stroke-width="0"/><text x="${100 + fx(n)}" y="${31 + i * 48}" fill="#dfe2e5" font-size="17">${n} N · ${mm}</text>`).join("");
  const chart = `<svg width="720" height="150" style="font-family:JetBrains Mono" overflow="visible">${bars}</svg>`;
  SC.rows = [
    row(SC.col1, 92, "wrist camera · OWLv2 + SAM · 6 controls", chips(["POWER_switch", "TIME+", "SPEED_dial", "START", "STOP", "display"], Y), Y, T("perception", s4)),
    row(SC.col1, 92, "motion · skills", chips(["tube_pick", "tube_place", "lid_close", "flip", "press", "turn"], Y), Y, T("motion", s4)),
    row(SC.col1, 160, "peak force per press · the real run", chart, Y, T("force", s4)),
    row(SC.col1, 100, "verdict rules", mono(`s5 TIME+ &nbsp;button 0→1→0 <b style="color:#7fd68f">PASS</b><br>&nbsp;&nbsp;&nbsp;also changed: SPEED 2700 → 2800`, 20), Y, T("verdict", s4)),
  // System 2
    row(SC.col2, 150, "manual.md, as plan-1 quotes it", mono(`“Flip POWER up to ON. The light ring glows white.”<br>“press TIME+ to add 10 s.”<br>“Clockwise raises the speed.”`, 20, "#c9d6e3"), B, T("frontier", s4)),
    row(SC.col2, 196, "plan-1 · 8 steps · approved by Karthik", mono(["s1 tube_pick", "s2 tube_place", "s3 lid_close", "s4 flip POWER", "s5 press TIME+", "s6 turn SPEED −60°", "s7 press START", "s8 press STOP"].map((x) => `<span style="display:inline-block;width:345px">${x}</span>`).join(""), 19), B, T("plans", s4)),
    row(SC.col2, 66, "recovery · Rev A sim run", mono(`s1 stopped → plan amended, s2–s10 · level 0`, 20), B, T("recovers", s4)),
    row(SC.col2, 66, "diagnosis · the real run", mono(`TIME+ added no time · START → “LID”: tube seat?`, 20), B, T("diagnoses", s4)),
  ];
  // the tool lane: the only way across
  const TOOLS = ["read_manual", "look_at_device", "record_hypothesis", "propose_plan", "run_plan", "answer_stop", "finish_run"];
  SC.tools = el("div", "abs", TOOLS.map((x, i) => `<div style="position:absolute;left:0;right:0;top:${i * 62}px;height:1.5px;background:linear-gradient(90deg,${Y},${B})"></div><div class="mono" style="position:absolute;top:${i * 62 + 8}px;left:0;right:0;text-align:center;font-size:14px;color:#9aa0a5">${x}</div>`).join(""), SC.sys, "left:854px;top:250px;width:212px;height:440px");
  SC.gate = el("div", "abs", "", SC.sys, "left:957px;top:236px;width:4px;height:450px;background:#e5604f;opacity:0;box-shadow:0 0 18px #e5604f");
  const env = (txt, c) => el("div", "abs mono", txt, SC.sys, `font-size:19px;color:#111417;background:${c};padding:6px 12px;border-radius:4px;white-space:nowrap;opacity:0;box-shadow:0 8px 24px rgba(0,0,0,.5)`);
  SC.envs = [
    { n: env("move_joint(2, 40°)", B), t: T("motor", s4) - 0.3, y: 527, kind: "bounce" },
    { n: env("grade_own_step(s1, pass)", B), t: T("grades", s4) - 0.2, y: 589, kind: "bounce" },
    { n: env("run_plan · press START", B), t: T("grades", s4) + 1.9, y: 420, kind: "through" },
  ];
  SC.stamp4 = el("div", "abs mono", "no such tool", SC.sys, "left:878px;top:700px;width:164px;text-align:center;font-size:18px;color:#ff8a7a;opacity:0");
  SC.vla = el("div", "box", `<div class="label" style="margin-bottom:12px">VLA</div><div class="mono" style="font-size:26px;color:#e4e6e8">perception + reasoning + control</div>
    <div style="display:flex;gap:8px;margin:22px 0 14px">${Array.from({ length: 14 }, (_, i) => `<div class="reel" style="width:40px;height:30px;border:2px solid #8b9095;border-radius:3px;opacity:0;background:repeating-linear-gradient(90deg,#8b909555 0 4px,transparent 4px 10px)"></div>`).join("")}</div>
    <div class="mono" style="font-size:19px;color:#9aa0a5;line-height:1.6">SmolVLA · 50 demonstrations per task<br>GR00T N1 · 30–300 demonstrations per task</div>`, SC.sys, "left:560px;top:330px;width:800px;padding:30px 36px;box-sizing:border-box;opacity:0;background:rgba(17,20,23,.97);box-shadow:0 30px 90px rgba(0,0,0,.7)");
  SC.reels = [...SC.vla.querySelectorAll(".reel")];
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
  // §5 one shared screen: the Console in a window on the right, six cases filling in on the left
  SC.win = el("div", "abs", "", SC.cards, `left:${WIN.x - 2}px;top:${WIN.y - 2}px;width:${1920 * WIN.s + 4}px;height:${1080 * WIN.s + 4}px;border:2px solid #3a4046;border-radius:6px;box-shadow:0 30px 90px rgba(0,0,0,.6);opacity:0;pointer-events:none`);
  SC.feat = el("div", "abs", "", SC.cards, `left:${WIN.x}px;top:${WIN.y - 64}px;opacity:0;font:500 22px "JetBrains Mono",monospace;color:#e4e6e8;white-space:nowrap`);
  SC.cases = el("div", "abs", "", SC.cards, "left:56px;top:104px;width:640px;opacity:0");
  const group = (txt, c) => el("div", "label", txt, SC.cases, `color:${c};margin:0 0 12px`);
  const CASES = [["proofs", "lean", "Lean", "Two AI-claimed refutations of the Exponential Time Hypothesis, being checked in Lean", "Oct 2026 · still under examination", "#8fb3d9"],
    ["flight", "chip", "CompCert", "A compiler proven correct, qualified for ATR 42/72 avionics", "compcert.org · 2026", "#8fb3d9"],
    ["flight", "shield", "seL4", "A proven kernel on Boeing's Little Bird: a red team couldn't break out in flight", "DARPA HACMS", "#8fb3d9"],
    ["dyson", "stack", "Dyson", "", "Fast Company · May 2007", "#e38b7a"],
    ["biosafety", "flask", "Pirbright", "Foot-and-mouth virus most likely escaped through damaged drains", "UK HSE report · 2007", "#e38b7a"],
    ["space", "scope", "JWST", "Sunshield fasteners shook loose in an acoustic test, part of a 29-month delay", "review board · 2018", "#e38b7a"]];
  SC.caseN = [];
  CASES.forEach(([w, icon, title, fact, src, c], i) => {
    if (i === 0) group("software · proven before use", "#8fb3d9");
    if (i === 3) { const g = group("hardware · found after the fact", "#e38b7a"); g.style.marginTop = "18px"; SC.hwLabel = g; }
    const big = title === "Dyson";
    const body = big ? `<canvas width="500" height="150" style="display:block;margin-top:10px;width:500px;height:150px"></canvas><div class="mono" style="font-size:16px;color:#9aa0a5;margin-top:8px">one cell per prototype · DC01 · 1993 · 15 years</div>`
      : `<div class="fact" style="font:500 19px/1.35 Inter,sans-serif;color:#dfe2e5;margin-top:5px;overflow:hidden">${fact}</div>`;
    const n = el("div", "", `<svg width="${big ? 56 : 44}" height="${big ? 56 : 44}" viewBox="0 0 64 64" style="flex:none">${ICON[icon]}</svg><div><div style="display:flex;align-items:baseline;gap:14px"><span class="mich" style="font-size:${big ? 30 : 22}px;color:${c}">${title}</span><span class="mono" style="font-size:13px;color:#8b9095">${src}</span></div>${body}</div>`, SC.cases,
      `display:flex;gap:16px;align-items:flex-start;padding:${big ? "18px 22px" : "12px 18px"};margin-bottom:10px;background:rgba(21,24,27,.95);border:1.5px solid ${c}${big ? "" : "55"};border-left:${big ? 6 : 4}px solid ${c};opacity:0;${big ? "box-shadow:0 0 40px #e38b7a33" : ""}`);
    SC.caseN.push({ n, t: (i === 0 ? T("software", s5) : i === 1 ? T("proofs", s5) : T(w, s5)) + (i === 2 ? 0.35 : 0), soft: i < 3, fact: n.querySelector(".fact"), grid: n.querySelector("canvas") });
  });
  // §5 the pan-out: a globe, the twelve appliances, the real centrifuge, System 2 in the cloud
  SC.globeSvg = svg("svg", { width: 1920, height: 1080, style: "position:absolute;left:0;top:0;opacity:0;transform-origin:960px 450px" }, SC.cards);
  SC.globe = svg("g", {}, SC.globeSvg);
  SC.tunnel = svg("path", { fill: "none", stroke: "#8fb3d9", "stroke-width": 2.5, "stroke-dasharray": "9 9", opacity: 0 }, SC.globeSvg);
  SC.cloud = svg("g", { opacity: 0 }, SC.globeSvg);
  for (const [x, y, r] of [[-46, 8, 30], [-8, -14, 42], [36, 0, 34], [64, 14, 24], [-70, 18, 20]]) svg("circle", { cx: x, cy: y, r, fill: "#1b2530", stroke: "#8fb3d9", "stroke-width": 2.5 }, SC.cloud);
  svg("rect", { x: -88, y: 12, width: 176, height: 36, fill: "#1b2530" }, SC.cloud);
  const ct = svg("text", { x: 0, y: 38, "text-anchor": "middle", fill: "#cfe0f1", "font-size": 22, "font-family": "Michroma" }, SC.cloud); ct.textContent = "System 2";
  const APPS = ["centrifuge", "coffee-grinder", "cuvette-reader", "hotplate-stirrer", "incubator", "interval-timer", "kettle-base", "label-printer", "microwave", "tube-sealer", "vortex-mixer", "wall-thermostat"];
  SC.apps = APPS.map((a, i) => { const right = i >= 6, j = i % 6; const real = a === "centrifuge" || a === "microwave";
    return { at: i * 0.09, n: el("div", "abs mono", `${a}${real ? ' <span style="color:#eebc24">· sim + real</span>' : ""}`, SC.cards,
      `${right ? "right" : "left"}:110px;top:${200 + j * 92}px;font-size:22px;color:#dfe2e5;padding:9px 16px;background:rgba(21,24,27,.92);border:1.5px solid ${real ? "#eebc24" : "#3a4046"};opacity:0;text-align:${right ? "right" : "left"}`) }; });
  SC.backendLine = el("div", "abs mono", "", SC.col1, "left:430px;top:30px;font-size:19px;color:#eebc24;opacity:0;line-height:1.45");
}


// §5: the Console sits in a window on the right; each view gets a feature label (keyed to the scenes tour's own clock)
const WIN = { x: 748, y: 196, s: 0.594 };
const FEATS = [[0, "Studies · every appliance, one harness"], [7.9, "Story · Rev A vs Rev B, control by control"], [14.5, "Settings · the environment each run uses"],
  [16.9, "Methodology · the model plans, sensors decide"], [20.5, "Architecture · 7 tools, no joint commands"], [24.6, "Verdicts · rules on force, travel, readings"]];
const popDim = () => 1;
/** Dyson's 5,127 prototypes, one cell each: red as they fill, the last one green. */
function drawPrototypes(cv, p, last) {
  const g = cv.getContext("2d"), cols = 127, rows = 41, w = cv.width / cols, h = cv.height / rows, n = Math.floor(5127 * p);
  g.clearRect(0, 0, cv.width, cv.height);
  g.fillStyle = "#2a2f35"; g.fillRect(0, 0, cv.width, cv.height);
  g.fillStyle = "#e5604f";
  for (let i = 0; i < Math.min(n, 5126); i++) g.fillRect((i % cols) * w + 0.5, Math.floor(i / cols) * h + 0.5, w - 1, h - 1);
  if (last > 0) { const i = 5126, x = (i % cols) * w, y = Math.floor(i / cols) * h; g.fillStyle = "#7fd68f"; g.globalAlpha = last; g.shadowColor = "#7fd68f"; g.shadowBlur = 16; g.fillRect(x - 6, y - 8, w + 12, h + 12); g.shadowBlur = 0; g.globalAlpha = 1; }
}
const APPS12 = ["centrifuge", "coffee-grinder", "cuvette-reader", "hotplate-stirrer", "incubator", "interval-timer", "kettle-base", "label-printer", "microwave", "tube-sealer", "vortex-mixer", "wall-thermostat"];
/** §5's pull-back: 0 → 1 from "Today". The Console window shrinks onto New York as the globe comes in. */
function pan(t) { const S = LAY.steps; return eio(ramp(t, S.today - 0.2, S.today + 1.3)); }
const NYC = [960, 334];
function winRect(k) { const f = lerp(1, 0.03, k), c0 = [WIN.x + 960 * WIN.s, WIN.y + 540 * WIN.s]; return { f, c: [lerp(c0[0], NYC[0], k), lerp(c0[1], NYC[1], k)], c0 }; }
const CITIES = [[-0.1, 51.5], [2.35, 48.9], [13.4, 52.5], [139.7, 35.7], [127, 37.6], [116.4, 39.9], [77.6, 13], [103.8, 1.35], [151.2, -33.9], [-46.6, -23.5], [-99.1, 19.4], [-79.4, 43.7], [-122.4, 37.8], [18.4, -33.9], [3.4, 6.5], [-71.1, 42.4], [8.5, 47.4], [34.8, 32.1]];
const MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5", "openai-gpt-5.4", "grok-4.7"];
function seekTech(t) {
  const S = LAY.steps;
  // §4
  const s4 = S.s4, s5 = S.s5;
  const so = ramp(t, s4 - 0.4, s4 + 0.3) * (1 - ramp(t, s5 - 0.6, s5));
  SC.sys.style.opacity = so;
  SC.sys.style.display = so > 0 ? "block" : "none";
  if (so > 0) {
    const s1at = T("robot", s4), s2at = T("system", T("rules", s4));
    const vla = T("vision", s4), split = T("split", s4);
    const dim = ramp(t, vla - 0.2, vla + 0.4) * (1 - ramp(t, split - 0.2, split + 0.4));
    SC.col1.style.filter = SC.col2.style.filter = SC.tools.style.filter = `brightness(${1 - 0.6 * dim})`;
    SC.col1.style.boxShadow = `0 0 ${40 * ramp(t, s1at - 0.2, s1at + 0.3) * (1 - ramp(t, s1at + 1.2, s1at + 2))}px #eebc2466`;
    SC.col2.style.boxShadow = `0 0 ${40 * ramp(t, s2at - 0.2, s2at + 0.3) * (1 - ramp(t, s2at + 1.2, s2at + 2))}px #8fb3d966`;
    // rows sit dim until named, then light up with an underline, and stay lit
    for (const r of SC.rows) {
      const on = ramp(t, r.at - 0.5, r.at - 0.1);
      r.n.style.opacity = 0.42 + 0.58 * on;
      r.hl.style.transform = `scaleX(${eio(ramp(t, r.at - 0.45, r.at + 0.15))})`;
      r.hl.style.opacity = 1 - 0.75 * ramp(t, r.at + 1.6, r.at + 2.4);
    }
    SC.tools.style.opacity = 0.5 + 0.5 * ramp(t, T("plans", s4) - 0.2, T("plans", s4) + 0.4);
    // the model's messages: two bounce off the gate, one goes through and is clamped
    let gate = 0, stamp = 0;
    for (const e of SC.envs) {
      const a = e.t, k = ramp(t, a, a + 0.9);
      let x;
      if (e.kind === "bounce") {
        const back = ramp(t, a + 1.0, a + 1.7);
        x = lerp(1110, 965, eio(k)) + Math.sin(ramp(t, a + 0.9, a + 1.1) * Math.PI * 3) * 8 * (1 - back) + back * 60;
        e.n.style.opacity = ramp(t, a - 0.1, a + 0.15) * (1 - ramp(t, a + 1.3, a + 1.8));
        e.n.style.transform = `translate(${x}px, ${e.y + back * back * 60}px) translateX(${-e.n.offsetWidth * k}px) rotate(${back * 14}deg)`;
        gate = Math.max(gate, ramp(t, a + 0.6, a + 0.85) * (1 - ramp(t, a + 1.6, a + 2.0)));
        stamp = Math.max(stamp, ramp(t, a + 0.85, a + 1.0) * (1 - ramp(t, a + 1.6, a + 2.0)));
      } else {
        x = lerp(1110, 520, eio(ramp(t, a, a + 1.4)));
        e.n.style.opacity = ramp(t, a - 0.1, a + 0.15) * (1 - ramp(t, a + 1.3, a + 1.6));
        e.n.style.transform = `translate(${x}px, ${e.y}px) translateX(${-e.n.offsetWidth * ramp(t, a, a + 1.4)}px)`;
        const bar = SC.col1.querySelector("#startbar"), gl = ramp(t, a + 1.3, a + 1.5) * (1 - ramp(t, a + 2.8, a + 3.4));
        bar.setAttribute("stroke-width", 3 * gl); bar.setAttribute("opacity", 0.85 + 0.15 * gl);
      }
    }
    SC.gate.style.opacity = gate; SC.stamp4.style.opacity = stamp;
    const sw = T("four", s4), sim = T("simulator", s4), armT = T("arm", sim);
    SC.backendLine.style.opacity = ramp(t, sim - 0.2, sim + 0.2);
    SC.col1.querySelector(".sub").style.opacity = 1 - ramp(t, sim - 0.2, sim + 0.2);
    SC.backendLine.innerHTML = t > armT - 0.1 ? "SO-101 · real arm" : "MuJoCo · simulator";
    const n = Math.floor((t - sw + 0.2) / 0.45); // the model cycles through the four that have run, then settles
    const mi = n >= 0 && n < 9 ? n % MODELS.length : 0;
    SC.model.textContent = "model: " + MODELS[mi];
    for (const r of SC.rows.slice(4)) r.n.style.filter = mi ? "brightness(.35)" : "none"; // the plan and diagnosis are Haiku's
    const tl = T("tools", s4), pu = ramp(t, tl - 0.1, tl + 0.3) * (1 - ramp(t, tl + 1.3, tl + 2.0));
    SC.tools.style.filter = `brightness(${1 + 0.9 * pu})`;
    { const vo = ramp(t, vla - 0.2, vla + 0.4) * (1 - ramp(t, split - 0.15, split + 0.1)); SC.vla.style.opacity = vo; SC.vla.style.transform = `translateY(${(1 - vo) * 14}px) scale(${lerp(0.96, 1, vo)})`; }
    SC.reels.forEach((r, i) => { r.style.opacity = ramp(t, vla + 0.5 + i * 0.22, vla + 0.7 + i * 0.22); });
    // our split needs a manual: manual.md lights up again
    const m = SC.rows[4], mk = ramp(t, split + 0.6, split + 1.0) * (1 - ramp(t, split + 2.4, split + 3.0));
    m.hl.style.opacity = Math.max(+m.hl.style.opacity, mk);
    m.n.style.textShadow = mk > 0 ? `0 0 ${14 * mk}px #8fb3d9` : "none";
  }
  // §5
  const wo = ramp(t, s5 - 0.2, s5 + 0.5) * (1 - ramp(t, S.outro + 0.3, S.outro + 0.8));
  const pk = pan(t), wr = winRect(pk);
  SC.win.style.opacity = wo * (1 - ramp(pk, 0.75, 1));
  SC.win.style.transform = `translate(${wr.c[0] - wr.c0[0]}px, ${wr.c[1] - wr.c0[1]}px) scale(${wr.f})`;
  SC.cases.style.opacity = wo * (1 - ramp(t, S.today - 0.2, S.today + 0.5));
  SC.cases.style.transform = `translateX(${-pk * 500}px)`;
  const go = ramp(t, S.today + 0.1, S.today + 0.9) * (1 - ramp(t, S.outro + 0.3, S.outro + 0.8));
  SC.globeSvg.style.opacity = go;
  if (go > 0) {
    SC.globeSvg.style.transform = `scale(${lerp(1.3, 1, eio(ramp(t, S.today + 0.1, S.today + 1.8)))})`;
    const pins = [{ lon: -74, lat: 40.7, at: S.realc, label: "MC-6 + microwave · real arm" }, ...CITIES.map(([lon, lat], i) => ({ lon, lat, at: S.anylab + i * 0.11, hollow: true }))];
    const pos = drawGlobe(SC.globe, t, 960, 450, 300, -74 + 11 * (t - (S.today + 1.3)), { pins });
    const co = ramp(t, S.cloud - 0.2, S.cloud + 0.3), cx = 1290, cy = 150 + Math.sin(t * 1.4) * 8;
    SC.cloud.setAttribute("opacity", co); SC.cloud.setAttribute("transform", `translate(${cx} ${cy})`);
    const ny = pos[0];
    if (ny && ny[2] > 0) { SC.tunnel.setAttribute("d", `M${ny[0]} ${ny[1]} Q ${(ny[0] + cx) / 2 + 60} ${Math.min(ny[1], cy) - 80} ${cx - 40} ${cy + 40}`); SC.tunnel.setAttribute("opacity", co * clamp(ny[2] * 4)); SC.tunnel.style.strokeDashoffset = -t * 36; }
    else SC.tunnel.setAttribute("opacity", 0);
  }
  for (const a of SC.apps) { const k = ramp(t, S.twelve + a.at - 0.1, S.twelve + a.at + 0.25) * (1 - ramp(t, S.outro + 0.3, S.outro + 0.8)); a.n.style.opacity = k; a.n.style.transform = `translateY(${(1 - eio(k)) * 14}px)`; }
  const hw = T("dyson", s5) - 0.5, dy = SC.caseN[3].t;
  SC.hwLabel.style.opacity = ramp(t, dy - 0.35, dy);
  for (const c of SC.caseN) {
    const k = ramp(t, c.t - 0.15, c.t + 0.3); c.n.style.opacity = k; c.n.style.transform = `translateX(${(1 - eio(k)) * -24}px)`;
    if (c.fact) { const shut = c.soft ? eio(ramp(t, hw, hw + 0.6)) : 0; c.fact.style.maxHeight = `${(1 - shut) * 60}px`; c.fact.style.opacity = 1 - shut; c.fact.style.marginTop = `${5 * (1 - shut)}px`; }
    if (c.grid && k > 0) drawPrototypes(c.grid, ramp(t, dy + 0.4, T("failures", dy) + 0.4), ramp(t, T("failures", dy) + 0.5, T("failures", dy) + 0.8));
  }
  const f = FEATS.findLast(([a]) => a <= (SC.tourSec ?? 0));
  SC.feat.style.opacity = wo * (SC.tourClip === "tour/scenes" ? 1 : 0) * (1 - ramp(t, S.today - 0.3, S.today + 0.2));
  if (f) SC.feat.innerHTML = f[1].replace(/^([^·]+)·/, '<span style="color:#eebc24">$1</span>·');

}

/* ───────────── §3 the real run: split screens of the bench, the Console and the sim ───────────── */
// Pane rectangles on the stage, and for each clip, where in its own pixels the pane looks over time
// ([video t, centre x, centre y, width shown], or height shown for the portrait side view). Moves are slow and continuous.
const PR = { L: { x: 48, y: 100, w: 904, h: 566 }, R: { x: 968, y: 100, w: 904, h: 566 }, F: { x: 0, y: 0, w: 1920, h: 1080 } };
const VIEW = {
  over: [[19, 800, 460, 1560], [23.2, 840, 450, 1380], [30.8, 820, 470, 1560], [47, 860, 480, 1380], [51.2, 880, 500, 1250]],
  cons: [[19, 1222, 440, 780], [22.6, 1222, 440, 700], [23.4, 445, 450, 880], [30.8, 445, 470, 820], [47, 1225, 560, 740], [50.6, 1225, 560, 700], [51.4, 450, 520, 840], [62.5, 450, 560, 760]],
  sim: [[30.8, 1000, 560, 1560], [47, 980, 530, 1300]],
  hand: [[23.2, 239, 425, 850], [30.8, 239, 425, 760], [51.2, 239, 430, 800], [53.6, 239, 410, 700], [53.7, 245, 470, 640], [56.3, 245, 480, 560], [56.4, 239, 425, 850], [62.5, 239, 400, 720]],
};
const PLAB = { over: ["real", "SO-101 · overhead", YELLOW], hand: ["real", "SO-101 · side view", YELLOW], cons: ["live", "RAAV Console", "#8fb3d9"], sim: ["sim", "MuJoCo · Rev B", "#8fb3d9"] };
const PN = {};
function buildPanes() {
  for (const name of ["L", "R", "F"]) {
    const r = PR[name];
    const f = el("div", "abs", "", $("panes"), `left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px;overflow:hidden;background:#0b0d0f;opacity:0;display:none;${name === "F" ? "" : "border:1.5px solid #3a4046;border-radius:4px;box-shadow:0 24px 70px rgba(0,0,0,.55)"}`);
    const bg = el("img", "", null, f, "position:absolute;left:0;top:0;transform-origin:0 0;filter:blur(26px) brightness(.36) saturate(.8);display:none");
    const imgs = [0, 1, 2].map(() => el("img", "", null, f, "position:absolute;left:0;top:0;transform-origin:0 0;display:none"));
    if (name !== "F") el("div", "abs", "", f, "left:0;right:0;top:0;height:56px;background:linear-gradient(rgba(8,10,12,.96),rgba(8,10,12,.82))");
    const lab = el("div", "abs mono", "", f, "left:14px;top:14px;font-size:16px;letter-spacing:.1em;text-transform:uppercase;color:#e9ebed;background:rgba(10,12,14,.82);padding:6px 12px;border-radius:3px;white-space:nowrap");
    const spd = el("div", "abs mono", "", f, "right:14px;top:14px;font-size:15px;color:#9aa0a5;background:rgba(10,12,14,.82);padding:6px 10px;border-radius:3px");
    const flash = el("div", "abs", "", f, "inset:0;border:3px solid #f1efe6;border-radius:4px;opacity:0");
    if (name === "F") { lab.style.display = spd.style.display = flash.style.display = "none"; }
    PN[name] = { f, bg, imgs, lab, spd, flash, r, map: null };
  }
}
function viewAt(clip, t) {
  const c = CLIPS[clip], K = VIEW[clip] ?? [[0, c.w / 2, c.h / 2, c.h > c.w ? c.h : c.w]];
  let i = K.findLastIndex((k) => k[0] <= t); if (i < 0) i = 0;
  const a = K[i], b = K[i + 1] ?? a, k = b === a ? 0 : eio((t - a[0]) / (b[0] - a[0]));
  return [lerp(a[1], b[1], k), lerp(a[2], b[2], k), lerp(a[3], b[3], k)];
}
/** One pane at clip time `sec`. When the footage runs fast, three neighbouring frames are averaged: motion blur. */
function drawPane(P, clip, sec, speed, t) {
  const c = CLIPS[clip], r = P.r, portrait = c.h > c.w;
  let [cx, cy, v] = viewAt(clip, t);
  const s = portrait ? r.h / v : r.w / v;
  if (!portrait) { const hw = r.w / 2 / s, hh = r.h / 2 / s; cx = clamp(cx, Math.min(hw, c.w / 2), Math.max(c.w - hw, c.w / 2)); cy = clamp(cy, Math.min(hh, c.h / 2), Math.max(c.h - hh, c.h / 2)); }
  const tf = `translate(${r.w / 2 - cx * s}px, ${r.h / 2 - cy * s}px) scale(${s})`;
  P.map = (x, y) => [r.x + r.w / 2 + (x - cx) * s, r.y + r.h / 2 + (y - cy) * s];
  const n = speed > 2.5 ? 3 : 1, dt = Math.min(speed, 12) / FPS / 3, jobs = [];
  const put = (im, src) => { if (im.getAttribute("src") !== src) { im.setAttribute("src", src); jobs.push(im.decode().catch(() => { })); } };
  P.imgs.forEach((im, j) => {
    if (j >= n) { im.style.display = "none"; return; }
    Object.assign(im.style, { display: "block", width: c.w + "px", height: c.h + "px", transform: tf, opacity: 1 / (j + 1) });
    put(im, frameOf(clip, Math.max(0, sec - j * dt)));
  });
  P.bg.style.display = portrait ? "block" : "none";
  if (portrait) { const sb = Math.max(r.w / c.w, r.h / c.h); Object.assign(P.bg.style, { width: c.w + "px", height: c.h + "px", transform: `translate(${(r.w - c.w * sb) / 2}px, ${(r.h - c.h * sb) / 2}px) scale(${sb})` }); put(P.bg, frameOf(clip, sec)); }
  return Promise.all(jobs);
}
function seekPanes(t) {
  const S = LAY.steps, st = S.steps, jobs = [];
  const g3 = ramp(t, S.s3 - 0.6, S.s3 + 0.2) * (1 - ramp(t, S.cad - 0.7, S.cad - 0.2));
  const gF = ramp(t, S.hinge - 0.05, S.hinge + 0.45) * (1 - ramp(t, S.s4 - 0.6, S.s4 - 0.2));
  for (const name of ["L", "R", "F"]) {
    const P = PN[name], p = LAY.panes.find((x) => x[2] === name && x[0] <= t && t < x[1]);
    const o = p ? (name === "F" ? gF : g3) : 0;
    P.f.style.opacity = o; P.f.style.display = o > 0 ? "block" : "none";
    if (!(o > 0)) { P.map = null; continue; }
    const [from, , , clip, c0, speed] = p;
    P.clip = clip;
    if (name !== "F") {
      const side = name === "L" ? -1 : 1, slide = (1 - eio(ramp(t, S.s3 - 0.6, S.s3 + 0.4))) * 50 * side;
      P.f.style.transform = `translateX(${slide}px)`;
      const [kind, txt, col] = PLAB[clip];
      P.lab.innerHTML = `<span style="color:${col}">●</span> ${kind} · ${txt}`;
      P.spd.textContent = speed > 1.15 ? `${speed.toFixed(1)}×` : "";
      P.spd.style.display = speed > 1.15 ? "block" : "none";
      // in the steps, both sides flash together at each step boundary: the same step, sim and real
      let fl = 0;
      for (let i = 1; i < 8; i++) { const age = t - st[i]; if (age >= 0 && age < 0.45) fl = 0.75 * (1 - age / 0.45); }
      P.flash.style.opacity = t >= st[0] && t < st[8] ? fl : 0;
    }
    jobs.push(drawPane(P, clip, c0 + (t - from) * speed, speed, t));
  }
  return Promise.all(jobs);
}

/* the HUD over the split screens: the run's header and controls, the step strip, and one card at a time */
const H = {};
const CTL = ["START", "STOP", "TIME+", "POWER_switch", "SPEED_dial", "display"];
const STEP_CTL = [-1, -1, -1, 3, 2, 4, 0, 1];
const AMBER = "#f0a63a", GREEN = "#7fd68f", BLUE = "#8fb3d9";
function buildHud() {
  const S = LAY.steps, hud = $("hud");
  H.run = el("div", "abs mono", `<span style="color:${YELLOW}">●</span>&nbsp; agent-centrifuge-113400 &nbsp;·&nbsp; claude-haiku-5-5 &nbsp;·&nbsp; Nov 8, 2026, 11:34`, hud, "left:50px;top:40px;font-size:18px;color:#a9afb4;opacity:0;white-space:nowrap");
  H.ctlWrap = el("div", "abs", "", hud, "right:48px;top:32px;display:flex;gap:8px;opacity:0");
  const finds = T("finds", S.s3);
  H.ctl = CTL.map((c, i) => { const n = el("div", "mono", `<span class="tk" style="opacity:0">✓ </span>${c}`, H.ctlWrap, "font-size:16px;color:#dfe2e5;padding:6px 11px;border:1.5px solid #3a4046;background:#181b1e;border-radius:3px;opacity:0;white-space:nowrap"); return { n, at: finds + 0.15 + i * 0.13, name: c }; });
  H.strip = el("div", "abs", "", hud, "left:48px;top:690px;width:1824px;height:70px;display:flex;gap:8px");
  H.cells = LAY.stepNames.map((nm, i) => {
    const n = el("div", "", `<div class="mono" style="font-size:13px;color:#7d8389;letter-spacing:.1em">S${i + 1}</div><div class="mono nm" style="font-size:20px;color:#e9ebed;margin-top:2px">${nm}</div><div class="mono vd" style="position:absolute;right:10px;top:8px;font-size:14px"></div><div class="bar" style="position:absolute;left:0;bottom:0;height:3px;width:100%;background:${YELLOW};transform-origin:0 50%;transform:scaleX(0)"></div>`, H.strip,
      "position:relative;flex:1;padding:8px 12px;border:1.5px solid #3a4046;background:rgba(18,21,24,.95);border-radius:3px;opacity:0;overflow:hidden");
    return { n, vd: n.querySelector(".vd"), bar: n.querySelector(".bar") };
  });
  H.link = svg("path", { fill: "none", stroke: AMBER, "stroke-width": 3, "stroke-dasharray": "10 8", opacity: 0 }, svg("svg", { width: 1920, height: 1080, style: "position:absolute;left:0;top:0;overflow:visible" }, hud));
  // cards: one at a time, under the strip, carrying what the voice doesn't
  const C = (a, b, color, html) => ({ a, b, n: el("div", "abs mono", html, hud, `left:48px;top:786px;font-size:23px;color:#e4e6e8;background:rgba(14,16,18,.94);border:1.5px solid ${color}55;border-left:5px solid ${color};padding:13px 20px;opacity:0;white-space:nowrap;box-shadow:0 18px 50px rgba(0,0,0,.45)`) });
  const b = (s, c) => `<b style="color:${c};font-weight:600">${s}</b>`;
  const st = S.steps, sus = S.suspected;
  H.cards = [
    C(S.s3 + 0.5, S.plan - 0.15, BLUE, `${b("wrist camera", YELLOW)} → OWLv2 boxes → SAM masks → named controls`),
    C(S.plan + 0.3, S.plan + 2.7, "#ff8a7a", `${b("propose_plan refused", "#ff8a7a")} · nothing seen yet → look_at_device first`),
    C(S.plan + 2.9, S.approves - 0.1, BLUE, `${b("plan-1", BLUE)} · 8 steps · claude-haiku-5-5 · 17,050 tokens in, 889 out`),
    C(S.approves, S.works - 0.25, GREEN, `${b("✓ approved", GREEN)} · plan-1 / Karthik · the arm waited 3.3 s`),
    C(S.works, S.works + 4.2, BLUE, `${b("real", YELLOW)} the bench, overhead &nbsp;·&nbsp; ${b("sim", BLUE)} the same 8 steps on Rev B in MuJoCo &nbsp;·&nbsp; lined up step by step`),
    C(S.works + 4.4, S.board - 0.15, YELLOW, `${b("POWER_switch", YELLOW)} · flip toward +1 · the display then read 4200 RPM 0:40`),
    C(S.board, S.five - 0.15, YELLOW, `MC-6 board &nbsp;${["TIME+ 0→1→0", "START 0→1→0", "STOP 0→1→0"].map((x, i) => `<span class="rd" data-at="${S.board + 0.5 + i * 0.45}" style="opacity:0;margin-left:18px;padding:3px 10px;border:1px solid ${YELLOW}66">${x}</span>`).join("")}`),
    C(S.five, S.timeq + 0.05, GREEN, `REWARD <span class="mich rw" style="font-size:30px;color:#fff">0.00</span> &nbsp;·&nbsp; display untested`),
    C(S.timeq, S.lid - 0.15, AMBER, `${b("TIME+", AMBER)} · 22.5 N, 7.2 mm · button 0→1→0 · time 0:40 → 0:40 · SPEED 2700 → 2800`),
    C(S.lid, sus - 0.15, AMBER, `${b("START", AMBER)} · 15.8 N, 4.4 mm · button 0→1→0 · display: ${b("LID", AMBER)}`),
    C(sus, S.cad - 0.6, AMBER, `${b("tube_place", AMBER)} · observed · let go ${b("56.2 mm", AMBER)} above the seat · no reading changed`),
  ];
  for (const c of H.cards) c.rd = [...c.n.querySelectorAll(".rd")];
  H.rw = H.cards[7].n.querySelector(".rw");
  H.two = T("two", S.five); H.tube = T("tube", sus); H.which = T("which", sus); H.flagged = T("flagged", sus);

  /* §4 the tube adapter, as a cross-section: the agent's fix in the sim (D36) */
  H.cad = el("div", "abs", "", hud, "inset:0;opacity:0;display:none");
  H.cadSvg = svg("svg", { width: 1920, height: 1080, style: "position:absolute;left:0;top:0;font-family:JetBrains Mono" }, H.cad);
  const defs = svg("defs", {}, H.cadSvg);
  const pat = svg("pattern", { id: "hatch", width: 14, height: 14, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
  svg("rect", { width: 14, height: 14, fill: "#1f2428" }, pat); svg("line", { x1: 0, y1: 0, x2: 0, y2: 14, stroke: "#3a4248", "stroke-width": 3 }, pat);
  H.cadG = svg("g", {}, H.cadSvg);
  el("div", "abs", `<div class="mich" style="font-size:30px;color:#e9ebed">MC-6 WELL INSERT</div><div class="mono" style="font-size:17px;color:#8b9095;margin-top:8px">cross-section · sim · D36 · schematic, not to scale</div>`, H.cad, "left:120px;top:120px");
  const tag = (x, y, at, color, head, sub) => ({ at, n: el("div", "abs mono", `<div style="font-size:24px;color:${color}">${head}</div><div style="font-size:18px;color:#9aa0a5;margin-top:6px">${sub}</div>`, H.cad, `left:${x}px;top:${y}px;opacity:0;padding:14px 20px;background:rgba(14,16,18,.94);border-left:4px solid ${color};white-space:nowrap`) });
  H.cadAt = { cad: S.cad, agent: T("cad", S.cad), widened: S.widened, retest: T("retest", S.widened), seated: S.seated };
  H.cadTags = [
    tag(120, 420, S.cad + 0.2, "#ff8a7a", "Rev A bore", "the tube stopped 8.15 mm high"),
    tag(1340, 330, H.cadAt.agent, BLUE, "CAD agent · Opus 5.5", "14 tool calls · 102 s · $0.43"),
    tag(1340, 470, S.widened + 0.2, YELLOW, "bore +0.4 mm", "45° lead-in at the mouth"),
    tag(1340, 610, S.seated - 0.45, GREEN, "seated within 0.97 mm", "0.2 mm from the designer's own fix"),
  ];
  /* §4 the hinge: labels over the render */
  const htag = (x, at, color, head, sub) => ({ at, n: el("div", "abs mono", `<div class="mich" style="font-size:26px;color:${color}">${head}</div><div style="font-size:18px;color:#c3c8cc;margin-top:8px;line-height:1.5">${sub}</div>`, hud, `left:${x}px;top:96px;opacity:0;padding:16px 22px;background:rgba(14,16,18,.86);border-top:4px solid ${color};white-space:nowrap`) });
  const hg = S.hinge;
  H.hingeTags = [
    htag(150, hg + 0.1, "#ff8a7a", "REV A", "Onshape original<br>0.025 mm clearances · pin headed at both ends"),
    htag(1110, T("second", hg) - 0.1, GREEN, "REV B · BY THE TEAM", "0.25 mm clearance · 0.4 mm knuckle gaps<br>one-headed pin · door swings to ~145°"),
  ];
  H.hingeFoot = el("div", "abs mono", "microwave hinge F1 · the team's meshes, Rev A and Rev B", hud, "left:150px;bottom:150px;font-size:16px;color:#8b9095;opacity:0");
}

function drawCad(t) {
  const A = H.cadAt, w = eio(ramp(t, A.widened - 0.1, A.widened + 1.3)), d = eio(ramp(t, A.retest - 0.2, A.seated - 0.35));
  const cx = 960, top = 340, bot = 880, hb = lerp(84, 90, w), pin = 11 * (1 - w), c = 26 * w, R = 80;
  const seated = bot - 14, tb = lerp(seated - 114, seated, d);
  const L = cx - hb, Rr = cx + hb;
  // bore: lead-in, walls (with the pinch that stopped the tube), round bottom
  const bore = `M${L - c} ${top - 1} L${L} ${top + c} L${L} 690 Q${L + pin * 2} 735 ${L} 780 L${L} ${bot - hb} A${hb} ${hb} 0 0 0 ${Rr} ${bot - hb} L${Rr} 780 Q${Rr - pin * 2} 735 ${Rr} 690 L${Rr} ${top + c} L${Rr + c} ${top - 1} Z`;
  const tube = `M${cx - R} ${tb - 560} L${cx - R} ${tb - R} A${R} ${R} 0 0 0 ${cx + R} ${tb - R} L${cx + R} ${tb - 560}`;
  const gap = (bot - tb) > 30;
  const dimC = gap ? "#ff8a7a" : GREEN, dimT = d < 0.02 ? "8.15 mm" : d > 0.98 ? "0.97 mm" : "";
  const hl = w > 0 ? `<path d="M${L - c} ${top} L${L} ${top + c} L${L} ${bot - hb}" stroke="${YELLOW}" stroke-width="4" fill="none" opacity="${w}"/><path d="M${Rr + c} ${top} L${Rr} ${top + c} L${Rr} ${bot - hb}" stroke="${YELLOW}" stroke-width="4" fill="none" opacity="${w}"/>` : "";
  const pinch = pin > 0.5 ? `<path d="M${L} 690 Q${L + pin * 2} 735 ${L} 780 M${Rr} 690 Q${Rr - pin * 2} 735 ${Rr} 780" stroke="#ff8a7a" stroke-width="5" fill="none"/>` : "";
  H.cadG.innerHTML = `<g transform="translate(960 600) scale(${lerp(1, 1.05, ramp(t, A.cad, A.seated + 1))}) translate(-960 -600)">
    <rect x="${cx - 260}" y="${top}" width="520" height="${bot - top + 40}" fill="url(#hatch)" stroke="#5d6268" stroke-width="2.5"/>
    <path d="${bore}" fill="#111417" stroke="#8b9095" stroke-width="2.5"/>${pinch}${hl}
    <path d="${tube}" fill="rgba(200,215,230,.10)" stroke="#e4e6e8" stroke-width="3.5"/>
    <rect x="${cx - R - 8}" y="${tb - 580}" width="${2 * R + 16}" height="40" rx="5" fill="#c9473f"/>
    <path d="M${cx - R + 10} ${tb - 300} L${cx - R + 10} ${tb - R} A${R - 10} ${R - 10} 0 0 0 ${cx + R - 10} ${tb - R} L${cx + R - 10} ${tb - 300} Z" fill="#8fb3d9" opacity=".22"/>
    ${dimT ? `<g stroke="${dimC}" stroke-width="2.5"><line x1="1200" x2="1240" y1="${tb}" y2="${tb}"/><line x1="1200" x2="1240" y1="${bot}" y2="${bot}"/><line x1="1220" x2="1220" y1="${tb}" y2="${bot}"/></g><text x="1252" y="${(tb + bot) / 2 + 8}" fill="${dimC}" font-size="24">${dimT}</text>` : ""}
    <line x1="${cx - 300}" x2="${cx + 300}" y1="${bot}" y2="${bot}" stroke="#5d6268" stroke-dasharray="6 8"/><text x="${cx - 300}" y="${bot + 30}" fill="#7d8389" font-size="16">seat</text>
  </g>`;
}

function seekHud(t) {
  const S = LAY.steps, st = S.steps;
  const g3 = ramp(t, S.s3 - 0.4, S.s3 + 0.3) * (1 - ramp(t, S.cad - 0.7, S.cad - 0.2));
  $("hud").style.display = t > S.s3 - 1 && t < S.s4 ? "block" : "none";
  if (t < S.s3 - 1 || t >= S.s4) return;
  H.run.style.opacity = g3;
  H.ctlWrap.style.opacity = g3;
  const cur = st.findLastIndex((x) => x <= t);
  const inSteps = t >= st[0] && t < st[8];
  H.ctl.forEach((c, i) => {
    const k = ramp(t, c.at, c.at + 0.3);
    c.n.style.opacity = k; c.n.style.transform = `translateY(${(1 - eio(k)) * -10}px)`;
    const live = inSteps && STEP_CTL[cur] === i;
    const vAt = S.verdict + Math.max(0, STEP_CTL.indexOf(i)) * 0.07, vk = t >= vAt;
    let col = live ? YELLOW : "#3a4046";
    if (vk) col = i === 5 ? "#5d6268" : GREEN;
    if ((i === 0 || i === 2) && t >= H.two) col = AMBER;
    c.n.style.borderColor = col; c.n.style.borderStyle = vk && i === 5 ? "dashed" : "solid";
    c.n.querySelector(".tk").style.opacity = vk && i !== 5 ? 1 : 0; c.n.style.color = vk && i === 5 ? "#7d8389" : "#dfe2e5";
    c.n.style.boxShadow = live ? `0 0 18px ${YELLOW}66` : "none";
  });
  // the step strip
  H.strip.style.opacity = g3;
  H.cells.forEach((c, i) => {
    const a = st[i], b = st[i + 1], on = t >= a && t < b, done = t >= b;
    const shown = ramp(t, S.works - 0.6 + i * 0.06, S.works - 0.2 + i * 0.06);
    c.n.style.opacity = shown * (on || done ? 1 : 0.55);
    c.bar.style.transform = `scaleX(${ramp(t, a, b)})`;
    c.bar.style.opacity = done ? 0.35 : 1;
    const vAt = S.verdict + i * 0.07;
    let col = on ? YELLOW : "#3a4046", txt = done ? "done" : "", tc = "#7d8389";
    if (t >= vAt) { txt = i < 3 ? "observed" : "✓ passed"; col = tc = i < 3 ? BLUE : GREEN; }
    const flag = ((i === 4 || i === 6) && t >= H.two) || (i === 1 && t >= H.tube);
    if (flag) { col = tc = AMBER; txt = i === 1 ? "56.2 mm high" : i === 4 ? "passed · 0:40" : "passed · LID"; }
    const pulse = flag ? 0.5 + 0.5 * Math.sin(t * 5) : 0;
    c.n.style.borderColor = col; c.vd.textContent = txt; c.vd.style.color = tc;
    c.n.style.boxShadow = on ? `0 0 26px ${YELLOW}55` : flag ? `0 0 ${10 + 14 * pulse}px ${AMBER}55` : "none";
    c.n.style.transform = `translateY(${(1 - eio(shown)) * 16}px)`;
  });
  // the suspected cause: tube_place → START
  const lk = ramp(t, H.which, H.which + 0.9) * g3;
  if (lk > 0) {
    const cw = (1824 - 7 * 8) / 8, x1 = 48 + cw * 1.5 + 8, x6 = 48 + cw * 6.5 + 6 * 8;
    const d = `M${x1} 689 C${x1} 671 ${x6} 671 ${x6} 689`;
    H.link.setAttribute("d", d); const len = H.link.getTotalLength();
    H.link.style.strokeDasharray = `10 8`; H.link.setAttribute("opacity", 1);
    H.link.style.clipPath = `inset(0 ${(1 - lk) * 100}% 0 0)`;
  } else H.link.setAttribute("opacity", 0);
  // cards
  for (const c of H.cards) {
    const o = ramp(t, c.a, c.a + 0.3) * (1 - ramp(t, c.b - 0.25, c.b)) * g3;
    c.n.style.opacity = o; c.n.style.transform = `translateY(${(1 - eio(ramp(t, c.a, c.a + 0.35))) * 12}px)`;
    for (const r of c.rd) r.style.opacity = ramp(t, +r.dataset.at, +r.dataset.at + 0.25);
  }
  H.rw.textContent = (0.83 * eio(ramp(t, S.five + 0.15, S.five + 1.1))).toFixed(2);
  // the display reading LID, ringed in the side view
  const L = PN.L;
  if (L.map && L.clip === "hand" && t > S.lid - 0.2 && t < S.suspected - 0.1) {
    const [x, y] = L.map(250, 500), k = ramp(t, S.lid - 0.2, S.lid + 0.2) * (1 - ramp(t, S.suspected - 0.35, S.suspected - 0.1));
    svg("circle", { cx: x, cy: y, r: 58 + Math.sin(t * 6) * 4, fill: "none", stroke: AMBER, "stroke-width": 4, opacity: k }, $("overlay"));
  }
  // §4 the insert
  const go = ramp(t, S.cad - 0.5, S.cad + 0.2) * (1 - ramp(t, S.hinge + 0.05, S.hinge + 0.5));
  H.cad.style.opacity = go; H.cad.style.display = go > 0 ? "block" : "none";
  if (go > 0) { drawCad(t); for (const g of H.cadTags) show(g.n, ramp(t, g.at, g.at + 0.35), 12); }
  // §4 the hinge tags
  const ho = ramp(t, S.hinge - 0.2, S.hinge + 0.3) * (1 - ramp(t, S.s4 - 0.6, S.s4 - 0.2));
  for (const g of H.hingeTags) show(g.n, ho * ramp(t, g.at, g.at + 0.4), 12);
  H.hingeFoot.style.opacity = ho;
}

/* ───────────── the take: drawn through a canvas, so the camera's moves can carry motion blur ───────────── */
const IMG = new Image(); let IMGSRC = "";
function introCam(t) {
  const S = LAY.steps, [a, b] = S.snap;
  if (t < S.s3) return t < a ? camLerp(CAM0, CAMP, eio(ramp(t, 0, a))) : camLerp(CAMP, CAM1, eio(ramp(t, a, b)));
  return camLerp(CAMC, CAMID, eio(ramp(t, S.outro + 0.15, S.outro + 4.8)));
}
async function drawIntro(t, sec) {
  const S = LAY.steps, cv = $("fcan"), g = cv.getContext("2d");
  const src = frameOf("intro", sec);
  if (IMGSRC !== src) { IMG.src = src; IMGSRC = src; try { await IMG.decode(); } catch { } }
  cv.style.display = "block";
  const cam = introCam(t), prev = introCam(t - 1.5 / FPS);
  const moving = Math.abs(Math.log(cam.s / prev.s)) > 0.004 || Math.hypot(cam.cx - prev.cx, cam.cy - prev.cy) * cam.s > 1.5;
  const N = moving ? 12 : 1, out = t > S.s3;
  g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.globalCompositeOperation = "source-over"; g.filter = "none";
  g.fillStyle = "#000"; g.fillRect(0, 0, 1920, 1080);
  const soft = out ? 7 * (1 - ramp(t, S.outro + 0.05, S.outro + 0.6)) : 0;
  if (soft > 0.2) g.filter = `blur(${soft.toFixed(1)}px)`;
  for (let i = 0; i < N; i++) { const c = N === 1 ? cam : camLerp(prev, cam, i / (N - 1)); g.globalAlpha = 1 / (i + 1); g.setTransform(c.s, 0, 0, c.s, 960 - c.cx * c.s, 540 - c.cy * c.s); g.drawImage(IMG, 0, 0, 1920, 1080); }
  g.filter = "none"; g.globalAlpha = 1; g.setTransform(1, 0, 0, 1, 0, 0);
  if (!out) { // the board opens out of the chalk's tip
    const R = eio(ramp(t, OPEN[0], OPEN[1])) * 1250;
    if (R > 0) { g.globalCompositeOperation = "destination-out"; const gr = g.createRadialGradient(960, 540, 0, 960, 540, R + 60); gr.addColorStop(0, "rgba(0,0,0,1)"); gr.addColorStop(R / (R + 60), "rgba(0,0,0,1)"); gr.addColorStop(1, "rgba(0,0,0,0)"); g.fillStyle = gr; g.fillRect(0, 0, 1920, 1080); g.globalCompositeOperation = "source-over"; }
  }
  cv.style.opacity = out ? ramp(t, S.outro, S.outro + 0.5) : 1;
}

/* ───────────── captions and the clock ───────────── */
function caption(t) {
  const c = CAPS.find((x) => x.s <= t && t < x.e);
  const cap = $("cap");
  cap.style.display = c ? "inline-block" : "none";
  if (c && cap.textContent !== c.t) cap.textContent = c.t;
}

window.seek = async function (t) {
  const S = LAY.steps, o = S.outro;
  $("overlay").innerHTML = "";
  SC.tourClip = null;
  const turn = S.never - 0.1;
  const seg = LAY.segments.findLast((s) => s[0] <= t && t < s[1]);
  const jobs = [];
  // the take (cold open and close), held on its last frame while the board opens
  let introSec = null;
  if (seg && seg[2] === "intro") introSec = seg[3] + (t - seg[0]) * seg[4];
  else if (!seg && t < OPEN[1] + 0.1) introSec = 11.5;
  if (introSec != null) jobs.push(drawIntro(t, introSec)); else $("fcan").style.display = "none";
  // the Console's tour, in its window (§6)
  if (seg && seg[2] === "tour/scenes") {
    const [from, , clip, c0, speed] = seg, sec = c0 + (t - from) * speed;
    const wr = winRect(pan(t)), s = WIN.s * wr.f;
    SC.tourSec = sec; SC.tourClip = clip;
    jobs.push(setFrame(frameOf(clip, sec), "none", null, { cx: 960 - (wr.c[0] - 960) / s, cy: 540 - (wr.c[1] - 540) / s, s }));
    $("footage").style.opacity = 1 - ramp(pan(t), 0.75, 1);
  } else jobs.push(setFrame(null));
  jobs.push(seekPanes(t));
  // chalk, from the board's opening until the turn to the real run
  const chalkO = (t >= OPEN[0] ? 1 : 0) * (1 - ramp(t, turn + 0.55, turn + 1.05));
  $("chalklayer").style.opacity = chalkO;
  $("chalklayer").style.display = chalkO > 0 ? "block" : "none";
  if (chalkO > 0) seekChalk(t, turn);
  // the Console's look; at the close it pushes in, blurring, as the take comes back
  const zo = ramp(t, o - 0.15, o + 0.55);
  $("tech").style.opacity = ramp(t, turn + 0.4, turn + 1.4) * (1 - ramp(t, o + 0.1, o + 0.55));
  $("tech").style.transform = zo > 0 ? `scale(${1 + 0.45 * eio(zo)})` : "none";
  $("tech").style.filter = zo > 0 && zo < 1 ? `blur(${(6 * Math.sin(zo * Math.PI)).toFixed(1)}px)` : "none";
  $("footage").style.transform += ""; // (the tour's own camera is set in setFrame)
  seekTech(t);
  seekHud(t);
  caption(t);
  $("fade").style.opacity = ramp(t, DUR - 1.8, DUR - 0.3);
  await Promise.all(jobs);
};

window.ready = (async () => {
  WORDS = await (await fetch("words.json")).json();
  CAPS = await (await fetch("captions.json")).json();
  LAY = await (await fetch("segments.json")).json();
  CLIPS = await (await fetch("../out/frames/clips.json")).json();
  DUR = LAY.steps.fin;
  await document.fonts.load('700 40px "Cabin Sketch"'); await document.fonts.load('40px "Architects Daughter"');
  await document.fonts.load('40px Michroma'); await document.fonts.load('500 20px "JetBrains Mono"'); await document.fonts.load('600 20px Inter');
  await document.fonts.ready;
  buildChalk();
  buildTech();
  buildPanes();
  buildHud();
  window.DUR = DUR;
  return true;
})();
