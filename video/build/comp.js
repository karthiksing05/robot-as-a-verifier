// The whole video as one page: window.seek(t) puts every layer where it is at time t, so render.mjs can step it frame by frame.
// Times come from the voiceover's word timings (words.json), offset by the six-second cold open.
"use strict";
const FPS = 30, VO = 6.0, DUR = 194.6;
const NS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const ease = (x) => { x = clamp(x); return x * x * (3 - 2 * x); };
const eio = (x) => { x = clamp(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
const lerp = (a, b, k) => a + (b - a) * k;
const ramp = (t, a, b) => clamp((t - a) / (b - a));
function rng(seed) { return () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let x = Math.imul(seed ^ (seed >>> 15), 1 | seed); x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x; return ((x ^ (x >>> 14)) >>> 0) / 4294967296; }; }

let WORDS = [], CAPS = [], FOOT = null;
const norm = (w) => w.replace(/[^\w-]/g, "").toLowerCase();
/** When a word starts in the final video, at or after `after` seconds. */
function T(word, after = 0) {
  const w = WORDS.find((x) => x.s + VO >= after - 0.01 && norm(x.w).startsWith(word.toLowerCase()));
  if (!w) throw new Error(`no "${word}" after ${after}`);
  return w.s + VO;
}
function TE(word, after = 0) {
  const w = WORDS.find((x) => x.s + VO >= after - 0.01 && norm(x.w).startsWith(word.toLowerCase()));
  return w.e + VO;
}

/* ───────────────────────── act one: the chalkboard ───────────────────────── */
const WHITE = "#f1efe6", YELLOW = "#eebc24", DIM = "#c9d3c8";
const EL = [];
let seedN = 1;
function svg(tag, attrs, parent) { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (parent) parent.appendChild(n); return n; }

function roughD(pts, seed, j = 2.4) {
  const r = rng(seed);
  const p = pts.map(([x, y]) => [x + (r() - 0.5) * j, y + (r() - 0.5) * j]);
  let d = `M${p[0][0].toFixed(1)} ${p[0][1].toFixed(1)}`;
  for (let i = 0; i < p.length - 1; i++) {
    const p0 = p[i - 1] || p[i], p1 = p[i], p2 = p[i + 1], p3 = p[i + 2] || p2;
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6], c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += `C${c1[0].toFixed(1)} ${c1[1].toFixed(1)} ${c2[0].toFixed(1)} ${c2[1].toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}
function sub(pts, step = 36) { // subdivide a polyline so the jitter wanders along it
  const out = [pts[0]];
  for (let i = 1; i < pts.length; i++) {
    const [ax, ay] = pts[i - 1], [bx, by] = pts[i];
    const n = Math.max(1, Math.round(Math.hypot(bx - ax, by - ay) / step));
    for (let k = 1; k <= n; k++) out.push([ax + (bx - ax) * k / n, ay + (by - ay) * k / n]);
  }
  return out;
}
const line = (x1, y1, x2, y2) => { const dx = x2 - x1, dy = y2 - y1, L = Math.hypot(dx, dy) || 1, o = 6; return sub([[x1 - dx / L * o, y1 - dy / L * o], [x2 + dx / L * o, y2 + dy / L * o]]); };
const poly = (...p) => sub(p);
const rectP = (x, y, w, h) => sub([[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y - 4]]);
const circ = (cx, cy, r, turns = 1.06, a0 = -1.9) => { const n = Math.max(14, Math.round(r / 3)); return Array.from({ length: Math.round(n * turns) + 1 }, (_, i) => { const a = a0 + i / n * Math.PI * 2; return [cx + Math.cos(a) * r, cy + Math.sin(a) * r * 0.97]; }); };
const hexP = (cx, cy, r) => Array.from({ length: 7 }, (_, i) => [cx + r * Math.cos(Math.PI / 3 * i + Math.PI / 6), cy + r * Math.sin(Math.PI / 3 * i + Math.PI / 6)]);

/** A chalk stroke, drawn from `start` over `dur` seconds. */
function P(pts, start, dur, { color = WHITE, w = 5 } = {}) {
  const node = svg("path", { d: roughD(pts, seedN++), fill: "none", stroke: color, "stroke-width": w, "stroke-linecap": "round", "stroke-linejoin": "round" }, $("ink"));
  EL.push({ kind: "path", node, start, dur });
}
/** Hand-printed chalk text, written left to right from `start` over `dur` seconds. */
function X(text, x, y, start, dur, { size = 46, head = false, color = WHITE, weight = 400 } = {}) {
  const id = `c${EL.length}`;
  const cp = svg("clipPath", { id, clipPathUnits: "userSpaceOnUse" }, $("ink"));
  const rect = svg("rect", { x: x - 10, y: y - size * 1.2, width: 0, height: size * 1.7 }, cp);
  const node = svg("text", { x, y, fill: color, "font-size": size, "font-family": head ? "Cabin Sketch" : "Architects Daughter", "font-weight": head ? 700 : weight, "clip-path": `url(#${id})`, "letter-spacing": head ? 2 : 0.5, stroke: color, "stroke-width": head ? 0.6 : 1.3 }, $("ink"));
  node.textContent = text;
  EL.push({ kind: "text", node, rect, start, dur: dur ?? text.length * 0.045, x });
}

/** Camera shots on the board: from each shot's time, ease over 0.9 s to frame its box. */
const CAM = [];
function shot(t, x, y, w, h, fill = 0.92) { CAM.push({ t, cx: x + w / 2, cy: y + h / 2, z: Math.min(1920 / w, 1080 / h) * fill }); }
function camAt(t) {
  let i = CAM.findLastIndex((c) => c.t <= t);
  if (i < 0) i = 0;
  const cur = CAM[i], prev = CAM[Math.max(0, i - 1)];
  const k = eio((t - cur.t) / 1.0);
  // ease zoom in log space so pull-backs feel even
  return { cx: lerp(prev.cx, cur.cx, k), cy: lerp(prev.cy, cur.cy, k), z: Math.exp(lerp(Math.log(prev.z), Math.log(cur.z), k)) };
}

function buildChalk() {
  // faint ghosts of old lessons under everything
  const r = rng(99);
  const ghosts = ["F = ma", "∫ f(x) dx", "x² + y² = r²", "lim n→∞", "Δv", "P ≠ NP ?", "τ = r × F", "σ = E·ε", "∇·u = 0", "PV = nRT", "sin²θ + cos²θ", "Q.E.D."];
  for (let i = 0; i < 40; i++) { const t = svg("text", { x: r() * 3700, y: 80 + r() * 2050, fill: WHITE, "font-size": 50 + r() * 70, "font-family": "Architects Daughter", transform: `rotate(${(r() - 0.5) * 8})` }, $("ghosts")); t.textContent = ghosts[i % ghosts.length]; }
  for (let i = 0; i < 9; i++) svg("path", { d: roughD(circ(r() * 3800, r() * 2100, 120 + r() * 200, 1.0), 900 + i, 30), fill: "none", stroke: WHITE, "stroke-width": 60, opacity: 0.4 }, $("ghosts"));

  // §2a: models write proofs, machines verify them
  const a0 = T("models");
  shot(a0 - 0.6, 90, 60, 1150, 470);
  P(rectP(170, 130, 170, 220), a0, 0.5);
  P(poly([195, 180], [315, 180]), a0 + 0.45, 0.12); P(poly([195, 225], [300, 225]), a0 + 0.57, 0.12); P(poly([195, 270], [315, 270]), a0 + 0.69, 0.12); P(poly([195, 315], [280, 315]), a0 + 0.81, 0.1);
  X("proof", 185, 405, a0 + 0.9, 0.35, { size: 40 });
  P(line(380, 240, 560, 240), a0 + 1.3, 0.25); P(poly([530, 215], [565, 240], [530, 265]), a0 + 1.55, 0.12);
  P(rectP(600, 130, 230, 220), T("machines") - 0.15, 0.4);
  P(circ(715, 240, 55), T("machines") + 0.25, 0.35); P(circ(715, 240, 18), T("machines") + 0.6, 0.15);
  P(poly([880, 245], [915, 290], [990, 170]), T("verify"), 0.35, { w: 8 });
  X("machine-checked", 600, 405, T("verify") + 0.3, 0.7, { size: 40 });

  // §2b: ETH
  const b0 = T("october");
  shot(b0 - 0.5, 90, 470, 1820, 560);
  X("Oct 2026 — Lean checks two AI-claimed refutations of", 140, 590, b0, T("refutations") + 0.5 - b0, { size: 50 });
  X("THE EXPONENTIAL TIME HYPOTHESIS", 140, 720, T("exponential") - 0.1, TE("hypothesis") - T("exponential") + 0.2, { size: 82, head: true });
  X("“3-SAT can't be solved in 2^o(n) time”", 150, 810, TE("hypothesis") + 0.1, 0.9, { size: 42, color: DIM });
  X("age-old, seemingly impossible", 150, 905, T("age") - 0.05, TE("problem") - T("age") + 0.1, { size: 52 });
  P(poly([150, 925], [380, 932], [690, 922]), TE("problem") - 0.1, 0.3);
  P(poly([1380, 860], [1410, 900], [1470, 800]), T("age") + 0.3, 0.3, { w: 7 }); P(poly([1470, 860], [1500, 900], [1560, 800]), T("age") + 0.6, 0.3, { w: 7 });
  X("Lean", 1585, 890, T("age") + 0.9, 0.4, { size: 46 });
  X("Impagliazzo & Paturi, 2001 · claimed refutations under examination, Oct 26 2026 (ethdiscussion.blog)", 150, 985, TE("problem") + 0.2, 0.8, { size: 26, color: DIM });

  // §2c: verification already guards real systems
  const c0 = T("verification");
  shot(c0 - 0.5, 90, 1090, 1820, 880);
  X("VERIFICATION ALREADY GUARDS REAL SYSTEMS", 140, 1180, c0, TE("systems", c0) - c0, { size: 62, head: true });
  const d0 = T("compcert");
  P(rectP(140, 1240, 820, 450), d0 - 0.3, 0.6);
  X("CompCert", 185, 1345, d0, 0.5, { size: 72, head: true });
  X("a proven C compiler", 185, 1430, T("proven", d0), 0.7, { size: 46 });
  X("qualified for avionics", 185, 1505, T("qualified", d0), 0.8, { size: 46 });
  P(poly([700, 1600], [880, 1560], [905, 1548], [915, 1560], [740, 1612], [700, 1600]), T("avionics", d0) - 0.1, 0.4); P(poly([800, 1585], [760, 1530]), T("avionics", d0) + 0.3, 0.12); P(poly([800, 1588], [830, 1640]), T("avionics", d0) + 0.42, 0.12);
  X("ATR 42/72 computer · 2026 · compcert.org", 185, 1650, T("avionics", d0) + 0.6, 0.5, { size: 28, color: DIM });
  const e0 = T("sel4");
  P(rectP(1020, 1240, 840, 450), e0 - 0.35, 0.55);
  X("seL4", 1065, 1345, e0 + 0.1, 0.4, { size: 72, head: true });
  X("a proven OS kernel", 1065, 1430, T("red", e0) - 0.2, 0.6, { size: 46 });
  // a helicopter
  const hx = 1560, hy = 1380;
  P(circ(hx, hy, 52, 1.04), T("red", e0) + 0.3, 0.35); P(poly([hx + 50, hy - 5], [hx + 210, hy - 15]), T("red", e0) + 0.65, 0.15); P(poly([hx + 205, hy - 40], [hx + 215, hy + 15]), T("red", e0) + 0.8, 0.1);
  P(poly([hx - 120, hy - 70], [hx + 140, hy - 70]), T("team", e0), 0.18); P(poly([hx, hy - 70], [hx, hy - 52]), T("team", e0) + 0.18, 0.06);
  P(poly([hx - 60, hy + 75], [hx + 70, hy + 75]), T("team", e0) + 0.25, 0.12); P(poly([hx - 30, hy + 50], [hx - 35, hy + 75]), T("team", e0) + 0.37, 0.05); P(poly([hx + 30, hy + 50], [hx + 35, hy + 75]), T("team", e0) + 0.42, 0.05);
  X("kept a red team out, in flight", 1065, 1515, T("taking", e0), TE("flight", e0) - T("taking", e0), { size: 44 });
  X("DARPA HACMS · Boeing Little Bird", 1065, 1650, TE("flight", e0) - 0.2, 0.6, { size: 28, color: DIM });
  // ledger along the bottom
  X("also: Lean · Mathlib · Liquid Tensor Experiment, 2022 · AlphaProof, IMO 2024 · Four Colour Theorem in Coq, 2005", 140, 1790, TE("flight", e0) + 0.3, 0.8, { size: 28, color: DIM });
  X("TLA+ at AWS · DeepMind's fluid singularities, 2025 · weight-space programming, MIT CSAIL 2026", 140, 1840, TE("flight", e0) + 1.1, 0.7, { size: 28, color: DIM });

  // §3: where verification stops
  const f0 = T("but");
  shot(f0 - 0.4, 0, 0, 3840, 2160, 0.98);
  P(poly([1960, 70], [1955, 700], [1962, 1400], [1958, 2040]), f0, 1.0, { w: 7 });
  X("software ✓", 1550, 130, f0 + 0.9, 0.5, { size: 54 });
  X("hardware ?", 2010, 130, f0 + 1.35, 0.5, { size: 54, color: YELLOW });

  const g0 = T("biosafety");
  shot(g0 - 0.6, 2030, 170, 1790, 560);
  X("BIOSAFETY & BIOSECURITY", 2080, 260, g0 - 0.2, TE("biosecurity") - g0 + 0.2, { size: 62, head: true });
  // a cracked drain, dripping
  P(poly([2090, 340], [2330, 340], [2380, 360], [2400, 420], [2400, 600]), T("foot") - 0.1, 0.55);
  P(poly([2090, 400], [2310, 400], [2335, 412], [2340, 440], [2340, 600]), T("foot") + 0.4, 0.5);
  P(poly([2225, 335], [2238, 362], [2222, 380], [2240, 405]), T("virus"), 0.25, { color: YELLOW });
  P(circ(2236, 445, 7), T("virus") + 0.25, 0.1); P(circ(2232, 488, 6), T("virus") + 0.35, 0.1); P(circ(2240, 528, 5), T("virus") + 0.45, 0.1);
  P(poly([2070, 600], [2600, 606]), T("most", g0), 0.3);
  X("foot-and-mouth virus most likely escaped", 2660, 390, T("foot"), TE("escaped") - T("foot"), { size: 46 });
  X("England's labs through long-damaged drains", 2660, 465, T("england"), TE("drains") - T("england"), { size: 46 });
  X("Pirbright, Surrey · 2007 · HSE final report", 2660, 545, TE("drains") - 0.1, 0.5, { size: 30, color: DIM });

  const h0 = T("aerospace");
  shot(h0 - 0.6, 2030, 720, 1790, 560);
  X("AEROSPACE ENGINEERING", 2080, 815, h0 - 0.1, TE("engineering") - h0 + 0.1, { size: 62, head: true });
  // Webb: the mirror's hexagons over the sunshield's layers
  P(poly([2100, 1130], [2290, 1020], [2560, 1110], [2380, 1215], [2100, 1130]), T("acoustic"), 0.5);
  P(poly([2140, 1150], [2300, 1060], [2520, 1130], [2370, 1200]), T("acoustic") + 0.5, 0.3);
  [[2300, 930], [2352, 960], [2248, 960], [2300, 990], [2352, 1020], [2248, 1020]].forEach(([x, y], i) => P(hexP(x, y, 30), T("test", h0) + 0.1 + i * 0.12, 0.12));
  [[2470, 960], [2510, 1010], [2455, 1040]].forEach(([x, y], i) => { P(circ(x, y, 9), T("shook") + i * 0.14, 0.1, { color: YELLOW }); P(poly([x + 16, y - 2], [x + 46, y - 6]), T("shook") + 0.06 + i * 0.14, 0.06, { color: YELLOW }); });
  X("an acoustic test shook fasteners loose", 2660, 900, T("acoustic"), TE("fasteners") - T("acoustic") + 0.2, { size: 46 });
  X("on Webb's sunshield", 2660, 975, T("webb"), TE("sunshield") - T("webb"), { size: 46 });
  X("part of a 29-month delay", 2660, 1050, T("part", h0), TE("delay") - T("part", h0), { size: 46 });
  X("James Webb Space Telescope · 2018 review board · ~$1B", 2660, 1125, TE("delay") - 0.1, 0.5, { size: 30, color: DIM });

  const i0 = T("mechanical");
  shot(i0 - 0.6, 2030, 1280, 1790, 560);
  X("MECHANICAL & PRODUCT DESIGN", 2080, 1375, i0 - 0.1, TE("design", i0) - i0 + 0.1, { size: 62, head: true });
  // an upright vacuum
  P(poly([2190, 1430], [2200, 1690]), T("dyson"), 0.25); P(poly([2160, 1430], [2230, 1430]), T("dyson") + 0.25, 0.1);
  P(rectP(2150, 1560, 110, 130), T("dyson") + 0.35, 0.35); P(circ(2205, 1610, 28), T("dyson") + 0.7, 0.2);
  P(poly([2120, 1720], [2300, 1720]), T("dyson") + 0.9, 0.12); P(circ(2140, 1735, 16), T("dyson") + 1.0, 0.1);
  // a tally of attempts
  for (let k = 0; k < 4; k++) { const x = 2350 + k * 70; for (let m = 0; m < 4; m++) P(poly([x + m * 12, 1580], [x + m * 12 + 2, 1650]), T("built", i0) + 0.2 + k * 0.22 + m * 0.05, 0.05); P(poly([x - 8, 1640], [x + 48, 1590]), T("built", i0) + 0.4 + k * 0.22, 0.06); }
  X("5,127 prototypes", 2660, 1480, T("prototypes") - 0.3, 0.8, { size: 76, head: true });
  X("before the first Dyson vacuum succeeded", 2660, 1560, T("before", i0), TE("succeeded") - T("before", i0), { size: 46 });
  X("DC01, 1993 · after 15 years", 2660, 1635, TE("succeeded") - 0.1, 0.5, { size: 30, color: DIM });

  const j0 = T("most", i0);
  shot(j0 - 0.5, 2030, 1790, 1790, 360);
  // a finger on a button, and a clipboard
  P(rectP(2120, 1960, 150, 46), j0, 0.3); P(rectP(2165, 1940, 60, 20), j0 + 0.3, 0.15);
  P(poly([2195, 1935], [2190, 1870], [2200, 1850], [2222, 1858], [2225, 1935]), j0 + 0.45, 0.3);
  P(rectP(2330, 1830, 130, 170), j0 + 0.8, 0.3); P(poly([2350, 1880], [2440, 1880]), j0 + 1.1, 0.08); P(poly([2350, 1920], [2430, 1920]), j0 + 1.18, 0.08); P(poly([2350, 1960], [2440, 1960]), j0 + 1.26, 0.08);
  X("still tested by hand", 2560, 1945, T("tested", j0) - 0.2, TE("hand", j0) - T("tested", j0) + 0.2, { size: 62, head: true });

  // the turn: pull back to the whole argument
  shot(T("so", j0) - 0.9, 0, 0, 3840, 2160, 0.97);

  EL.sort((a, b) => a.start - b.start);
  for (const e of EL) {
    if (e.kind === "path") { e.len = e.node.getTotalLength(); e.node.style.strokeDasharray = `${e.len} ${e.len}`; e.node.style.strokeDashoffset = e.len; }
    else { e.bbox = e.node.getBBox(); }
  }
}

function tipAt(t) { // where the chalk is on the board at time t
  let cur = null, last = null, next = null;
  for (const e of EL) {
    if (e.start <= t && t < e.start + e.dur) cur = e;
    if (e.start + e.dur <= t) last = e;
    if (e.start > t && !next) next = e;
  }
  const at = (e, p) => {
    if (e.kind === "path") { const q = e.node.getPointAtLength(e.len * clamp(p)); return [q.x, q.y]; }
    const b = e.bbox; return [b.x + b.width * clamp(p), b.y + b.height * (0.62 + 0.16 * Math.sin(p * e.dur * 52))];
  };
  if (cur) return at(cur, (t - cur.start) / cur.dur);
  const a = last ? at(last, 1) : [300, 300], b = next ? at(next, 0) : a;
  if (!last || !next) return a;
  const k = eio((t - (last.start + last.dur)) / Math.max(0.05, next.start - (last.start + last.dur)));
  return [lerp(a[0], b[0], k), lerp(a[1] - 30 * Math.sin(k * Math.PI), b[1], k)];
}

/* The SO-101, drawn with two links and a two-finger gripper holding the chalk. */
function armShape(g, tip, style, alpha = 1) {
  g.innerHTML = "";
  if (alpha <= 0) return;
  const baseX = clamp(tip[0] * 0.45 + 820, 480, 1760), shoulder = [baseX, 1010];
  const wrist = [tip[0] + 58, tip[1] + 78];
  const L1 = 500, L2 = 470;
  let dx = wrist[0] - shoulder[0], dy = wrist[1] - shoulder[1], d = Math.hypot(dx, dy);
  const reach = L1 + L2 - 4;
  if (d > reach) { wrist[0] = shoulder[0] + dx / d * reach; wrist[1] = shoulder[1] + dy / d * reach; dx = wrist[0] - shoulder[0]; dy = wrist[1] - shoulder[1]; d = reach; }
  const a = Math.atan2(dy, dx), b = Math.acos(clamp((L1 * L1 + d * d - L2 * L2) / (2 * L1 * d), -1, 1));
  const elbow = [shoulder[0] + Math.cos(a - b) * L1, shoulder[1] + Math.sin(a - b) * L1];
  const solid = style === "solid";
  const stroke = YELLOW, fill = solid ? YELLOW : "none", dark = solid ? "#25282b" : "none";
  const grp = svg("g", { opacity: alpha, "stroke-linejoin": "round", "stroke-linecap": "round" }, g);
  const link = (p, q, w) => { const ang = Math.atan2(q[1] - p[1], q[0] - p[0]), nx = -Math.sin(ang) * w / 2, ny = Math.cos(ang) * w / 2;
    svg("path", { d: `M${p[0] + nx} ${p[1] + ny}L${q[0] + nx} ${q[1] + ny}A${w / 2} ${w / 2} 0 0 0 ${q[0] - nx} ${q[1] - ny}L${p[0] - nx} ${p[1] - ny}A${w / 2} ${w / 2} 0 0 0 ${p[0] + nx} ${p[1] + ny}Z`, fill, stroke, "stroke-width": solid ? 2 : 5 }, grp); };
  const servo = (p, s) => svg("rect", { x: p[0] - s / 2, y: p[1] - s / 2, width: s, height: s, rx: 6, fill: dark, stroke: solid ? "#111" : stroke, "stroke-width": solid ? 2 : 5 }, grp);
  svg("rect", { x: baseX - 95, y: 1010, width: 190, height: 70, rx: 8, fill, stroke, "stroke-width": solid ? 2 : 5 }, grp);
  link(shoulder, elbow, 56); link(elbow, wrist, 46);
  servo(shoulder, 70); servo(elbow, 60); servo(wrist, 50);
  if (solid) svg("circle", { cx: shoulder[0], cy: shoulder[1], r: 14, fill: "#9aa0a5" }, grp);
  // gripper: a fixed jaw and a moving jaw, chalk between them
  const ga = Math.atan2(tip[1] - wrist[1], tip[0] - wrist[0]), gx = Math.cos(ga), gy = Math.sin(ga);
  svg("path", { d: `M${wrist[0] - gy * 16} ${wrist[1] + gx * 16}L${tip[0] - gy * 10 + gx * 6} ${tip[1] + gx * 10 + gy * 6}`, stroke, "stroke-width": solid ? 12 : 6, fill: "none" }, grp);
  svg("path", { d: `M${wrist[0] + gy * 16} ${wrist[1] - gx * 16}L${tip[0] + gy * 10 + gx * 6} ${tip[1] - gx * 10 + gy * 6}`, stroke, "stroke-width": solid ? 12 : 6, fill: "none" }, grp);
  if (!solid) svg("path", { d: `M${tip[0] + gx * 2} ${tip[1] + gy * 2}L${tip[0] - gx * 26} ${tip[1] - gy * 26}`, stroke: WHITE, "stroke-width": 10 }, grp);
}

function dustAt(t, tipFn) {
  const g = $("dust"); g.innerHTML = "";
  for (let i = 0; i < 22; i++) {
    const te = Math.floor(t * 12 - i) / 12;
    if (te < 6.3) continue;
    const [x, y] = tipFn(te), age = t - te, r = rng(Math.floor(te * 12));
    svg("circle", { cx: x + (r() - 0.5) * 30 + (r() - 0.5) * age * 30, cy: y + age * age * 120 + r() * 8, r: 1.2 + r() * 2.2, fill: WHITE, opacity: clamp(0.55 - age * 0.3) }, g);
  }
}

let turnAt = 0;
function seekChalk(t) {
  const cam = camAt(t);
  const tf = (p) => [960 + (p[0] - cam.cx) * cam.z, 540 + (p[1] - cam.cy) * cam.z];
  $("board").setAttribute("transform", `translate(${960 - cam.cx * cam.z} ${540 - cam.cy * cam.z}) scale(${cam.z})`);
  for (const e of EL) {
    const p = clamp((t - e.start) / e.dur);
    if (e.kind === "path") e.node.style.strokeDashoffset = e.len * (1 - p);
    else e.rect.setAttribute("width", p * (e.bbox.width + 20));
  }
  // the turn: dust lifts off every line and the slate goes dark
  const lift = ramp(t, turnAt + 0.6, turnAt + 2.2);
  $("ink").setAttribute("opacity", 1 - lift * 0.92);
  $("ink").setAttribute("transform", `translate(0 ${-lift * 50})`);
  // the arm follows a smoothed tip (the last ~0.3 s, weighted to now), so fast tracing reads as a glide, not a jump
  const smooth = (tt) => { let x = 0, y = 0, wsum = 0; for (let k = 0; k < 18; k++) { const w = 1 - k / 18, p = tipAt(tt - k * 0.03); x += p[0] * w; y += p[1] * w; wsum += w; } return [x / wsum, y / wsum]; };
  const screenTip = (tt) => tf(smooth(tt));
  const tip = screenTip(t);
  if (t < turnAt + 0.6) { armShape($("armchalk"), tip, "chalk"); dustAt(t, screenTip); }
  else { $("armchalk").innerHTML = ""; $("dust").innerHTML = ""; }
  return tip;
}

/* ───────────────────────── act two: the Console look ───────────────────────── */
const SC = {}; // DOM nodes by name
function el(tag, cls, html, parent = $("scenes"), style = "") { const n = document.createElement(tag); if (cls) n.className = cls; if (html != null) n.innerHTML = html; if (style) n.style.cssText = style; parent.appendChild(n); return n; }
const show = (n, o, dy = 0) => { n.style.opacity = o; n.style.transform = `translateY(${(1 - o) * dy}px)`; };

function buildTech() {
  // title and thesis
  SC.title = el("div", "abs mich", "", undefined, "left:0;right:0;top:300px;text-align:center;font-size:118px;color:#f1f2f3");
  SC.titleSub = el("div", "abs mich", "", undefined, "left:0;right:0;top:450px;text-align:center;font-size:40px;color:#eebc24;letter-spacing:.18em");
  SC.thesis = el("div", "abs mono", "", undefined, "left:260px;right:260px;top:580px;text-align:center;font-size:36px;line-height:1.55;color:#cfd3d6");
  // the thesis, word by word as it's said
  const from = T("rav", T("so", 50)), start = T("tests", from), end = TE("measured", start);
  const tw = [];
  for (const w of WORDS.filter((w) => w.s + VO >= start - 0.01 && w.e + VO <= end + 0.01)) { if (tw.length && /^[-,]/.test(w.w)) tw[tw.length - 1] = { ...tw[tw.length - 1], w: tw[tw.length - 1].w + w.w }; else tw.push(w); }
  SC.thesisWords = tw.map((w) => {
    const s = document.createElement("span"); s.textContent = (w.w.startsWith("RA") ? "RAAV" : w.w) + " "; SC.thesis.appendChild(s); return { s, t: w.s + VO };
  });
  SC.thesisWords.unshift({ s: Object.assign(SC.thesis.insertBefore(document.createElement("span"), SC.thesis.firstChild), { textContent: "RAAV " }), t: start - 0.35 });
  SC.armSolid = document.createElementNS(NS, "g");

  // §5: one network, then two systems
  const vla = el("div", "", null);
  vla.innerHTML = `
    <div class="abs label" style="left:560px;top:206px">One network</div>
    <div class="box" style="left:560px;top:240px;width:800px;height:220px;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:14px">
      <div class="mich" style="font-size:34px;color:#f1f2f3">perception + reasoning + control</div>
      <div class="mono" style="font-size:20px;color:#8b9095">a vision-language-action model</div>
    </div>`;
  SC.vla = vla;
  SC.reels = el("div", "abs", [0, 1, 2].map((i) => `<div style="width:150px;height:46px;margin:0 0 16px;border:1.5px solid #5d6268;background:repeating-linear-gradient(90deg,#2a2e32 0 18px,#15181b 18px 26px)"></div>`).join("") + `<div class="label">demonstrations</div>`, undefined, "left:240px;top:262px");
  SC.reelArrow = el("div", "abs", "", undefined, "left:410px;top:345px;width:140px;height:2px;background:#5d6268");
  SC.chips = [["SmolVLA", "smallvla"], ["GR00T N1", "nvidia"], ["π0", null]].map(([name, w], i) => ({ n: el("span", "chip", name, undefined, `position:absolute;top:500px;left:${600 + i * 230}px`), w }));
  SC.grade = el("div", "abs", `<svg width="300" height="260"><path d="M10 120 C 180 120, 260 60, 230 10 M 10 120" fill="none" stroke="#c96a5a" stroke-width="2.5"/><path d="M230 10 C 200 -20, 120 -10, 60 10" fill="none" stroke="#c96a5a" stroke-width="2.5"/><path d="M70 0 L56 12 L74 20" fill="none" stroke="#c96a5a" stroke-width="2.5"/></svg><div class="mono" style="font-size:22px;color:#e38b7a;margin:-40px 0 0 120px">grades its own output</div>`, undefined, "left:1360px;top:150px");
  SC.vlaSrc = el("div", "abs src", "SmolVLA: 50 demonstrations per real task, SO-100/SO-101 data (Hugging Face, 2025) · GR00T N1: 30–300 demonstrations per task in sim; its own “System 2” and “System 1” are trained jointly, end to end (NVIDIA, 2025) · π0 (Physical Intelligence, 2024)", undefined, "left:240px;right:240px;top:600px");
  SC.vlaGroup = el("div", "abs", "", undefined, "inset:0;transform:scale(1.28);transform-origin:960px 330px");
  for (const n of [SC.vla, SC.reels, SC.reelArrow, ...SC.chips.map((c) => c.n), SC.grade, SC.vlaSrc]) SC.vlaGroup.appendChild(n);

  // the two columns
  SC.col1 = el("div", "box", "", undefined, "left:150px;top:150px;width:760px;height:560px;padding:34px 40px;box-sizing:border-box;border-color:#eebc24");
  SC.col2 = el("div", "box", "", undefined, "left:1010px;top:150px;width:760px;height:560px;padding:34px 40px;box-sizing:border-box;border-color:#8fb3d9");
  SC.h1 = el("div", "mich s1", "SYSTEM 1", SC.col1, "font-size:40px"); SC.k1 = el("div", "mono", "exact · fast · safe", SC.col1, "font-size:24px;color:#cfa21c;margin:10px 0 30px");
  SC.h2 = el("div", "mich s2", "SYSTEM 2", SC.col2, "font-size:40px"); SC.k2 = el("div", "mono", "a frontier model · context and judgment", SC.col2, "font-size:24px;color:#7d9ec2;margin:10px 0 30px");
  const r1 = [["perception", "perception"], ["inverse kinematics", "inverse"], ["control", "control"], ["force limits", "force"], ["verdicts from sensor readings, by fixed rules", "verdicts"]];
  const s2at = T("system", T("rules", 80));
  const r2 = [["reading the manual and spec", "reading"], ["reasoning over test plans", "reasoning"], ["recovering from failed steps", "recovering"], ["diagnosing causes", "diagnosing"], ["proposing CAD fixes", "proposing"]];
  SC.rows1 = r1.map(([txt, w]) => ({ n: el("div", "row", `<i style="background:#eebc24"></i>${txt}`, SC.col1), t: T(w, T("system", 75)) }));
  SC.rows2 = r2.map(([txt, w]) => ({ n: el("div", "row", `<i style="background:#8fb3d9"></i>${txt}`, SC.col2), t: T(w, s2at) }));
  SC.model = el("div", "abs mono", "", undefined, "left:1050px;top:722px;font-size:20px;color:#7d9ec2");
  SC.tools = el("div", "abs", Array.from({ length: 7 }, (_, i) => `<div style="position:absolute;left:0;top:${i * 34}px;width:100px;height:1.5px;background:linear-gradient(90deg,#eebc24,#8fb3d9)"></div>`).join("") + `<div class="label" style="position:absolute;top:244px;left:4px;width:100px;text-align:center">7 tools</div>`, undefined, "left:910px;top:300px;width:100px;height:290px");
  // long lines of existing work, and what VLAs get wrong
  SC.lines1 = el("div", "abs mono", "inverse kinematics · classical control · computer vision", undefined, "left:150px;top:745px;width:760px;font-size:23px;color:#b8bdc2");
  SC.lines2 = el("div", "abs mono", "language-model reasoning · planning · tool use", undefined, "left:1010px;top:745px;width:760px;font-size:23px;color:#b8bdc2");
  SC.linesLabel = el("div", "abs label", "Long lines of existing work", undefined, "left:150px;top:712px");
  SC.fails = el("div", "abs", `<div class="label" style="margin-bottom:12px">Classical failures of VLAs</div>`, undefined, "left:150px;top:800px;width:1620px");
  SC.fail1 = el("span", "chip", "✕ binding", SC.fails, "color:#e38b7a;border-color:#6b3a33");
  SC.fail2 = el("span", "chip", "✕ few-shot learning", SC.fails, "color:#e38b7a;border-color:#6b3a33");
}

const MODELS = ["claude-sonnet-5-5", "claude-haiku-5-5", "openai-gpt-5.4", "grok-4.7"];
let S5 = {};
function seekTech(t) {
  const so = T("so", 50), s5 = T("vision"), split = T("split", s5), each = T("each", s5), s6 = T("here", each);
  // title and thesis
  const titleOn = t >= so + 1.0 && t < s5 - 0.2;
  const titleOut = 1 - ramp(t, s5 - 1.0, s5 - 0.2);
  const ttxt = "RAAV", stxt = "ROBOT AS A VERIFIER";
  const tp = ramp(t, so + 1.0, so + 1.5), sp = ramp(t, T("robot", so) - 0.1, TE("verifier", so));
  SC.title.textContent = titleOn ? ttxt.slice(0, Math.ceil(tp * ttxt.length)) : "";
  SC.titleSub.textContent = titleOn ? stxt.slice(0, Math.ceil(sp * stxt.length)) : "";
  SC.title.style.opacity = SC.titleSub.style.opacity = SC.thesis.style.opacity = titleOut;
  for (const w of SC.thesisWords) w.s.style.opacity = titleOn && t >= w.t ? 1 : 0;

  // §5
  const on = (a, b) => t >= a && t < b;
  const inS5 = on(s5 - 0.6, s6 - 0.3);
  const vlaO = inS5 ? ramp(t, s5 - 0.6, s5) * (1 - ramp(t, split - 0.5, split - 0.05)) : 0;
  show(SC.vla, vlaO, 20);
  SC.reels.style.opacity = vlaO * ramp(t, T("learn", s5) - 0.2, T("learn", s5) + 0.3);
  SC.reelArrow.style.opacity = SC.reels.style.opacity;
  SC.reels.style.transform = `translateX(${((t * 60) % 26) - 13}px)`;
  for (const c of SC.chips) show(c.n, vlaO * ramp(t, (c.w ? T(c.w, s5) : T("nvidia", s5) + 0.9) - 0.1, (c.w ? T(c.w, s5) : T("nvidia", s5) + 0.9) + 0.3), 12);
  SC.grade.style.opacity = vlaO * ramp(t, T("grade", s5) - 0.1, T("grade", s5) + 0.4);
  SC.vlaSrc.style.opacity = vlaO * ramp(t, T("learn", s5), T("learn", s5) + 0.5);
  const colO = inS5 ? ramp(t, split, split + 0.6) : 0;
  const slide = (1 - eio(ramp(t, split, split + 0.9))) * 430;
  SC.col1.style.opacity = SC.col2.style.opacity = colO;
  SC.col1.style.transform = `translateX(${slide}px)`; SC.col2.style.transform = `translateX(${-slide}px)`;
  SC.tools.style.opacity = colO * ramp(t, split + 0.6, split + 1.2);
  const s1at = T("system", split);
  SC.k1.style.opacity = ramp(t, T("exact", s1at) - 0.1, T("exact", s1at) + 0.3);
  const s2at = T("system", T("rules", s1at));
  SC.k2.style.opacity = ramp(t, T("frontier", s2at) - 0.1, T("frontier", s2at) + 0.3);
  for (const r of [...SC.rows1, ...SC.rows2]) show(r.n, ramp(t, r.t - 0.15, r.t + 0.25), 10);
  SC.model.style.opacity = colO * ramp(t, T("frontier", s2at), T("frontier", s2at) + 0.4);
  SC.model.textContent = "model: " + MODELS[Math.floor(Math.max(0, t - T("frontier", s2at)) / 1.6) % MODELS.length] + "  ·  swappable";
  const glow = ramp(t, each - 0.1, each + 0.4);
  SC.col1.style.boxShadow = `0 0 ${glow * 40}px rgba(238,188,36,${glow * 0.25})`;
  SC.col2.style.boxShadow = `0 0 ${glow * 40}px rgba(143,179,217,${glow * 0.25})`;
  const lw = ramp(t, T("long", each) - 0.1, T("long", each) + 0.4) * colO;
  SC.lines1.style.opacity = SC.lines2.style.opacity = SC.linesLabel.style.opacity = lw;
  
  const fv = ramp(t, T("classical", each) - 0.1, T("classical", each) + 0.4) * colO;
  SC.fails.style.opacity = fv;
  show(SC.fail1, ramp(t, T("binding", each) - 0.1, T("binding", each) + 0.3), 10);
  show(SC.fail2, ramp(t, T("few", each) - 0.1, T("few", each) + 0.3), 10);
  SC.model.style.display = t < each ? "block" : "none";
}

/* ───────────────────────── footage, captions, and the clock ───────────────────────── */
const imgCache = new Map();
async function setFootage(src) {
  const img = $("footage");
  if (!src) { img.style.display = "none"; return; }
  img.style.display = "block";
  if (img.getAttribute("src") !== src) { img.setAttribute("src", src); try { await img.decode(); } catch { /* a missing frame stays blank */ } }
}

function caption(t) {
  const c = CAPS.find((x) => x.s <= t && t < x.e);
  const cap = $("cap");
  cap.style.display = c ? "inline-block" : "none";
  if (c && cap.textContent !== c.t) cap.textContent = c.t;
}

/** Sections 6 and 7 live in walk.js, which knows the footage. */
let seekWalk = async () => false;

window.seek = async function (t) {
  const so = T("so", 50);
  turnAt = so - 0.2;
  // cold open: Karthik erasing the board, at 1.75×
  if (t < 6.0) await setFootage(`../out/frames/intro/${String(Math.min(180, Math.floor(t * FPS) + 1)).padStart(4, "0")}.jpg`);
  else await setFootage(null);
  $("fade").style.opacity = t < 6.0 ? 0 : 1 - ramp(t, 6.0, 6.35);
  // chalk until the turn, then the Console's look
  const techO = ramp(t, turnAt + 1.0, turnAt + 2.4);
  $("chalklayer").style.opacity = 1 - techO;
  $("tech").style.opacity = techO;
  if (techO < 1) seekChalk(t);
  // the arm, solid, while the title is up
  const ov = $("overlay"); ov.innerHTML = "";
  if (t >= turnAt + 0.6 && t < T("vision") - 0.2) {
    const g = svg("g", {}, ov);
    const settle = eio(ramp(t, turnAt + 0.6, turnAt + 2.4));
    // the chalk arm snaps into the solid SO-101, then steps aside for the title
    armShape(g, [lerp(1060, 1300, settle), lerp(560, 620, settle)], "solid", ramp(t, turnAt + 0.5, turnAt + 0.9) * (1 - ramp(t, turnAt + 1.9, turnAt + 2.5)));
  }
  if (techO > 0) seekTech(t);
  const walked = await seekWalk(t);
  if (!walked) { $("rail").style.display = "none"; $("tag").style.display = "none"; }
  caption(t);
  // the end
  $("fade").style.opacity = Math.max(+$("fade").style.opacity, ramp(t, DUR - 1.1, DUR - 0.1));
};

window.ready = (async () => {
  WORDS = await (await fetch("words.json")).json();
  CAPS = await (await fetch("captions.json")).json();
  await document.fonts.load('700 40px "Cabin Sketch"'); await document.fonts.load('40px "Architects Daughter"');
  await document.fonts.load('40px Michroma'); await document.fonts.load('500 20px "JetBrains Mono"'); await document.fonts.load('600 20px Inter');
  await document.fonts.ready;
  buildChalk();
  buildTech();
  if (window.WALK) seekWalk = await window.WALK({ T, TE, VO, svg, el, $, clamp, ramp, eio, ease, lerp, show, armShape });
  window.DUR = DUR;
  return true;
})();
