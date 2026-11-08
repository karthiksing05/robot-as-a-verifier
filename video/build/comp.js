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
// The take is split (footage.py). Opening: it freezes as the chalk touches the board, the camera pushes in on that point,
// and the drawn board opens out of it while Bayan's RAAV logo (docs/assets/logo.png, our handwriting) writes itself on.
// Closing: back to the same frozen point, then out to the full frame while he really writes RAAV, walks off, black.
const PUSH = [6.6, 8.4], OPEN = [8.2, 9.3], INK = [8.9, 10.4], RISE = [10.6, 11.8];
const CAM0 = { cx: 1012.8, cy: 505.9, s: 1.45 }, CAM1 = { cx: 993, cy: 442, s: 3.2 }, CAMID = { cx: 960, cy: 540, s: 1 }; // CAM0 = the old crop
const camLerp = (a, b, k) => ({ cx: lerp(a.cx, b.cx, k), cy: lerp(a.cy, b.cy, k), s: Math.exp(lerp(Math.log(a.s), Math.log(b.s), k)) });
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

  const s2 = T("this");
  // RAAV, where the take left it
  SC.raav = svg("g", { "clip-path": "url(#inkwipe)" }, $("board"));
  const cp = svg("clipPath", { id: "inkwipe", clipPathUnits: "userSpaceOnUse" }, $("boardsvg").querySelector("defs"));
  SC.wipe = svg("rect", { x: HAND.x - 20, y: HAND.y - 40, width: 0, height: HAND.h + 80 }, cp);
  svg("image", { href: LOGO, x: HAND.x, y: HAND.y, width: HAND.w, height: HAND.h }, SC.raav);
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
  SC.wipe.setAttribute("width", ramp(t, INK[0], INK[1]) * (HAND.w + 40));
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
    svg("circle", { cx: x, cy: y, r: 7, fill: land, opacity: k }, g);
    if (pin.label) { const tx = svg("text", { x: x + 14, y: y - 12, fill: "#e4e6e8", "font-size": 22, "font-family": "JetBrains Mono", opacity: k }, g); tx.textContent = pin.label; }
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
  /* §3 the demo: a step rail and cards that carry what the voice doesn't */
  SC.cards = el("div", "abs", "", $("stage"), "inset:0;z-index:25;pointer-events:none");
  SC.c1 = card("System 1", "#eebc24", 70, 640, 760);
  SC.c2 = card("System 2", "#8fb3d9", 1090, 640, 760);
  SC.cp = card("A person", "#f0a63a", 780, 540, 360); SC.cp.style.background = "rgba(40,28,10,.94)"; SC.cp.style.textAlign = "center";
  SC.stamp = el("div", "abs mono", "", SC.cards, "left:40px;top:76px;font-size:18px;color:#cfd3d6;background:rgba(10,12,14,.7);padding:5px 10px;opacity:0");
  SC.note = el("div", "abs mono", "", SC.cards, "right:36px;top:76px;font-size:16px;color:#9aa0a5;background:rgba(10,12,14,.7);padding:5px 10px;opacity:0;max-width:820px;text-align:right");
  const RUN = "Rev A run · Claude Sonnet 5.5 · MuJoCo";
  const s3 = S.s3;
  SC.beats = [];
  const RAIL = ["survey", "scan", "segment", "map", "touch", "plan", "test", "verdicts", "report", "CAD fix", "Rev B"];
  SC.railAt = [T("surveys", s3), S.wrist, T("finds", s3), T("finds", s3) + 0.5, S.touches, S.model, S.then, T("verdict", s3), T("reported", s3), S.there, S.test];
  $("rail").innerHTML = RAIL.map((r) => `<span>${r}</span>`).join("");
  SC.rail = [...$("rail").children];

  /* §4 two systems: filled with the Rev A run's own data from the start; each part lights up as it's named */
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
  // System 1
  const PEAK = [["s1", 3.48], ["s2", 7.95], ["s3", 2.26], ["s4", 6.24], ["s6", 6.65], ["s8", 1.42], ["s9", 3.07]];
  const fy = (n) => 150 - n / 16 * 140;
  const bars = PEAK.map(([s, n], i) => `<rect x="${60 + i * 62}" y="${fy(n)}" width="34" height="${150 - fy(n)}" rx="3" fill="${Y}" opacity=".85"/><text x="${77 + i * 62}" y="172" fill="#8b9095" font-size="15" text-anchor="middle">${s}</text>`).join("");
  const chart = `<svg width="720" height="180" style="font-family:JetBrains Mono" overflow="visible">
    <line x1="40" x2="520" y1="${fy(15)}" y2="${fy(15)}" stroke="#e5604f" stroke-width="2.5"/><text x="530" y="${fy(15) + 6}" fill="#e5604f" font-size="18">15 N hard cap</text>
    <line x1="40" x2="520" y1="${fy(14)}" y2="${fy(14)}" stroke="#8b9095" stroke-width="1.5" stroke-dasharray="6 6"/><text x="530" y="${fy(14) + 22}" fill="#8b9095" font-size="16">steps ask ≤ 14 N</text>
    <line x1="40" x2="520" y1="150" y2="150" stroke="#3a4046"/>${bars}
    <rect id="clampbar" x="${60 + 7 * 62}" y="150" width="34" height="0" rx="3" fill="#e5604f"/><text id="clamptxt" x="${77 + 7 * 62}" y="172" fill="#e5604f" font-size="15" text-anchor="middle" opacity="0">40 N?</text></svg>`;
  SC.rows = [
    row(SC.col1, 92, "wrist camera · OWLv2 + SAM · 9 controls", chips(["toggle_1", "button_1", "button_3", "dial_1", "display_1", "handle_1", "…"], Y), Y, T("perception", s4)),
    row(SC.col1, 92, "inverse kinematics · servo control · skills", chips(["press", "flip", "slide", "turn", "push_latch", "observe"], Y), Y, T("inverse", s4)),
    row(SC.col1, 214, "peak force per step, Rev A", chart, Y, T("force", s4)),
    row(SC.col1, 150, "verdict rules", mono(`s1 &nbsp;lcd == “1000 RPM 0:30”<br>&nbsp;&nbsp;&nbsp;&nbsp;read “1000rpm&nbsp;&nbsp;0:30” <b style="color:#ff8a7a">FAIL</b><br>s7 &nbsp;handle_1 needs a pinch <b style="color:#ff8a7a">SKIPPED</b>`, 20), Y, T("verdict", s4)),
  // System 2
    row(SC.col2, 150, "manual.md", mono(`“Flip POWER up to ON… settings return<br>&nbsp;to 1000 rpm and 30 s”<br>“TIME+ Adds 10 s per press”`, 20, "#c9d6e3"), B, T("reads", s4)),
    row(SC.col2, 196, "plan-1 · 10 steps · 35 properties", mono(["s1 flip toggle_1", "s2 press button_3", "s3 turn dial_1 −90°", "s4 press button_1", "s5 observe display_1", "s6 press button_1_cad", "s7 turn handle_1", "s8 … s10"].map((x) => `<span style="display:inline-block;width:345px">${x}</span>`).join(""), 19), B, T("plans", s4)),
    row(SC.col2, 66, "recovery", mono(`s1 stopped → plan amended, s2–s10 · level 0`, 20), B, T("recovers", s4)),
    row(SC.col2, 66, "diagnosis", mono(`F1 wrong_feedback · toggle_1 &nbsp; NO-THUMBS · handle_1`, 20), B, T("diagnoses", s4)),
  ];
  // the tool lane: the only way across
  const TOOLS = ["read_manual", "look_at_device", "record_hypothesis", "propose_plan", "run_plan", "answer_stop", "finish_run"];
  SC.tools = el("div", "abs", TOOLS.map((x, i) => `<div style="position:absolute;left:0;right:0;top:${i * 62}px;height:1.5px;background:linear-gradient(90deg,${Y},${B})"></div><div class="mono" style="position:absolute;top:${i * 62 + 8}px;left:0;right:0;text-align:center;font-size:14px;color:#9aa0a5">${x}</div>`).join(""), SC.sys, "left:854px;top:250px;width:212px;height:440px");
  SC.gate = el("div", "abs", "", SC.sys, "left:957px;top:236px;width:4px;height:450px;background:#e5604f;opacity:0;box-shadow:0 0 18px #e5604f");
  const env = (txt, c) => el("div", "abs mono", txt, SC.sys, `font-size:19px;color:#111417;background:${c};padding:6px 12px;border-radius:4px;white-space:nowrap;opacity:0;box-shadow:0 8px 24px rgba(0,0,0,.5)`);
  SC.envs = [
    { n: env("move_joint(2, 40°)", B), t: T("motor", s4) - 0.3, y: 470, kind: "bounce" },
    { n: env("grade_own_step(s1, pass)", B), t: T("grades", s4) - 0.2, y: 560, kind: "bounce" },
    { n: env("run_plan · press button_3 at 40 N", B), t: T("grades", s4) + 1.9, y: 420, kind: "through" },
  ];
  SC.stamp4 = el("div", "abs mono", "no such tool", SC.sys, "left:878px;top:700px;width:164px;text-align:center;font-size:18px;color:#ff8a7a;opacity:0");
  SC.vla = el("div", "box", `<div class="label" style="margin-bottom:12px">instead: one network</div><div class="mono" style="font-size:26px;color:#e4e6e8">perception + reasoning + control</div>
    <div style="display:flex;gap:8px;margin:22px 0 14px">${Array.from({ length: 14 }, (_, i) => `<div class="reel" style="width:40px;height:30px;border:2px solid #8b9095;border-radius:3px;opacity:0;background:repeating-linear-gradient(90deg,#8b909555 0 4px,transparent 4px 10px)"></div>`).join("")}</div>
    <div class="mono" style="font-size:19px;color:#9aa0a5;line-height:1.6">SmolVLA · 50 demonstrations per task<br>GR00T N1 · 30–300 demonstrations per task</div>`, SC.sys, "left:560px;top:330px;width:800px;padding:30px 36px;box-sizing:border-box;opacity:0;background:rgba(17,20,23,.97);box-shadow:0 30px 90px rgba(0,0,0,.7)");
  SC.reels = [...SC.vla.querySelectorAll(".reel")];
  SC.limit = el("div", "abs mono", "new kind of control → a new skill, in code", SC.sys, `left:98px;top:880px;font-size:20px;color:#f0a63a;opacity:0`);

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
  SC.cases = el("div", "abs", "", SC.cards, "left:56px;top:136px;width:640px;opacity:0");
  const group = (txt, c) => el("div", "label", txt, SC.cases, `color:${c};margin:0 0 12px`);
  const CASES = [["proofs", "lean", "Lean", "Two AI-claimed refutations of the Exponential Time Hypothesis, checked", "Oct 2026 · still under examination", "#8fb3d9"],
    ["flight", "chip", "CompCert", "A compiler proven correct, qualified for ATR 42/72 avionics", "compcert.org · 2026", "#8fb3d9"],
    ["flight", "shield", "seL4", "A proven kernel on Boeing's Little Bird: a red team couldn't break out in flight", "DARPA HACMS", "#8fb3d9"],
    ["biosafety", "flask", "Pirbright", "Foot-and-mouth virus most likely escaped through damaged drains", "UK HSE report · 2007", "#e38b7a"],
    ["spacecraft", "scope", "JWST", "Sunshield fasteners shook loose in an acoustic test, part of a 29-month delay", "review board · 2018", "#e38b7a"],
    ["prototypes", "stack", "Dyson", "5,127 prototypes over 15 years before the first vacuum", "DC01 · 1993", "#e38b7a"]];
  SC.caseN = [];
  CASES.forEach(([w, icon, title, fact, src, c], i) => {
    if (i === 0) group("software · proven before use", "#8fb3d9");
    if (i === 3) { const g = group("hardware · found after the fact", "#e38b7a"); g.style.marginTop = "22px"; }
    const n = el("div", "", `<svg width="44" height="44" viewBox="0 0 64 64" style="flex:none">${ICON[icon]}</svg><div><div style="display:flex;align-items:baseline;gap:14px"><span class="mich" style="font-size:22px;color:${c}">${title}</span><span class="mono" style="font-size:13px;color:#8b9095">${src}</span></div><div style="font:500 19px/1.35 Inter,sans-serif;color:#dfe2e5;margin-top:5px">${fact}</div></div>`, SC.cases,
      `display:flex;gap:16px;align-items:flex-start;padding:14px 18px;margin-bottom:10px;background:rgba(21,24,27,.95);border:1.5px solid ${c}55;border-left:4px solid ${c};opacity:0`);
    SC.caseN.push({ n, t: T(w, s5) + (i === 2 ? 0.35 : 0) });
  });
  // §3: what the CAD loop did, as the voice says "proposes"
  SC.cadcard = el("div", "abs mono", `<div class="label" style="color:#8fb3d9;margin-bottom:8px">the full loop, in the sim · D36</div>MC-6 tube stopped <b style="color:#ff8a7a">8.15 mm</b> high<br>Opus 5.5 widened the bore, added a lead-in<br>retest: seated within <b style="color:#7fd68f">0.97 mm</b>`, SC.cards,
    "left:56px;bottom:150px;font-size:22px;line-height:1.5;color:#e4e6e8;background:rgba(14,16,18,.94);border:1.5px solid #8fb3d9;border-left:5px solid #8fb3d9;padding:18px 24px;opacity:0;box-shadow:0 20px 60px rgba(0,0,0,.5)");
  // §5 the pan-out: a globe, the twelve appliances, the real centrifuge, System 2 in the cloud
  SC.globeSvg = svg("svg", { width: 1920, height: 1080, style: "position:absolute;left:0;top:0;opacity:0;transform-origin:960px 450px" }, SC.cards);
  SC.globe = svg("g", {}, SC.globeSvg);
  SC.tunnel = svg("path", { fill: "none", stroke: "#8fb3d9", "stroke-width": 2.5, "stroke-dasharray": "9 9", opacity: 0 }, SC.globeSvg);
  SC.cloud = svg("g", { opacity: 0 }, SC.globeSvg);
  for (const [x, y, r] of [[-46, 8, 30], [-8, -14, 42], [36, 0, 34], [64, 14, 24], [-70, 18, 20]]) svg("circle", { cx: x, cy: y, r, fill: "#1b2530", stroke: "#8fb3d9", "stroke-width": 2.5 }, SC.cloud);
  svg("rect", { x: -88, y: 14, width: 176, height: 30, fill: "#1b2530" }, SC.cloud);
  const ct = svg("text", { x: 0, y: 12, "text-anchor": "middle", fill: "#cfe0f1", "font-size": 22, "font-family": "Michroma" }, SC.cloud); ct.textContent = "System 2";
  const APPS = ["centrifuge", "coffee-grinder", "cuvette-reader", "hotplate-stirrer", "incubator", "interval-timer", "kettle-base", "label-printer", "microwave", "tube-sealer", "vortex-mixer", "wall-thermostat"];
  SC.apps = APPS.map((a, i) => { const right = i >= 6, j = i % 6; const real = a === "centrifuge";
    return { at: i * 0.09, n: el("div", "abs mono", `${a}${real ? ' <span style="color:#eebc24">· sim + real</span>' : ""}`, SC.cards,
      `${right ? "right" : "left"}:110px;top:${200 + j * 92}px;font-size:22px;color:#dfe2e5;padding:9px 16px;background:rgba(21,24,27,.92);border:1.5px solid ${real ? "#eebc24" : "#3a4046"};opacity:0;text-align:${right ? "right" : "left"}`) }; });
  SC.backendLine = el("div", "abs mono", "", SC.col1, "left:430px;top:30px;font-size:19px;color:#eebc24;opacity:0;line-height:1.45");

}

// §5: the Console sits in a window on the right; each view gets a feature label (keyed to the scenes tour's own clock)
const WIN = { x: 748, y: 196, s: 0.594 };
const FEATS = [[0, "Studies · every appliance, one harness"], [7.9, "Story · Rev A vs Rev B, control by control"], [14.5, "Settings · simulator or the real arm"],
  [16.9, "Methodology · the model plans, sensors decide"], [20.5, "Architecture · 7 tools, no joint commands"], [24.6, "Verdicts · rules on force, travel, readings"]];
const popDim = () => 1;
const APPS12 = ["centrifuge", "coffee-grinder", "cuvette-reader", "hotplate-stirrer", "incubator", "interval-timer", "kettle-base", "label-printer", "microwave", "tube-sealer", "vortex-mixer", "wall-thermostat"];
/** §5's pull-back: 0 → 1 from "Today". The Console window shrinks onto New York as the globe comes in. */
function pan(t) { const S = LAY.steps; return eio(ramp(t, S.today - 0.2, S.today + 1.3)); }
const NYC = [960, 334];
function winRect(k) { const f = lerp(1, 0.03, k), c0 = [WIN.x + 960 * WIN.s, WIN.y + 540 * WIN.s]; return { f, c: [lerp(c0[0], NYC[0], k), lerp(c0[1], NYC[1], k)], c0 }; }
const CITIES = [[-0.1, 51.5], [2.35, 48.9], [13.4, 52.5], [139.7, 35.7], [127, 37.6], [116.4, 39.9], [77.6, 13], [103.8, 1.35], [151.2, -33.9], [-46.6, -23.5], [-99.1, 19.4], [-79.4, 43.7], [-122.4, 37.8], [18.4, -33.9], [3.4, 6.5], [-71.1, 42.4], [8.5, 47.4], [34.8, 32.1]];
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
    const s1at = T("robot", s4), s2at = T("frontier", s4);
    const vla = T("vision", s4), split = T("split", s4);
    const dim = ramp(t, vla - 0.2, vla + 0.4) * (1 - ramp(t, split - 0.2, split + 0.4));
    SC.col1.style.filter = SC.col2.style.filter = SC.tools.style.filter = `brightness(${1 - 0.6 * dim})`;
    SC.col1.style.boxShadow = `0 0 ${40 * ramp(t, s1at - 0.2, s1at + 0.3) * (1 - ramp(t, s1at + 1.2, s1at + 2))}px #eebc2466`;
    SC.col2.style.boxShadow = `0 0 ${40 * ramp(t, s2at - 0.2, s2at + 0.3) * (1 - ramp(t, s2at + 1.2, s2at + 2))}px #8fb3d966`;
    // rows sit dim until named, then light up with an underline, and stay lit
    for (const r of SC.rows) {
      const on = ramp(t, r.at - 0.15, r.at + 0.25);
      r.n.style.opacity = 0.42 + 0.58 * on;
      r.hl.style.transform = `scaleX(${eio(ramp(t, r.at - 0.1, r.at + 0.5))})`;
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
        const grow = ramp(t, a + 1.3, a + 1.8), h = lerp(0, 150 - (150 - 15 / 16 * 140), eio(grow));
        const bar = SC.col1.querySelector("#clampbar");
        bar.setAttribute("y", 150 - h); bar.setAttribute("height", h);
        bar.setAttribute("opacity", 1 - 0.4 * Math.sin(ramp(t, a + 1.8, a + 2.6) * Math.PI * 3) ** 2);
        const txt = SC.col1.querySelector("#clamptxt");
        txt.setAttribute("opacity", ramp(t, a + 1.3, a + 1.5)); txt.textContent = t > a + 1.85 ? "15 N" : "40 N?";
      }
    }
    SC.gate.style.opacity = gate; SC.stamp4.style.opacity = stamp;
    const sw = T("four", s4), sim = T("simulator", s4), app = T("appliance", s4);
    SC.backendLine.style.opacity = ramp(t, sim - 0.2, sim + 0.2);
    SC.col1.querySelector(".sub").style.opacity = 1 - ramp(t, sim - 0.2, sim + 0.2);
    const flip = Math.floor(Math.max(0, t - sim) / 0.8) % 2, ai = Math.floor(Math.max(0, t - app) / 0.28);
    SC.backendLine.innerHTML = (flip ? "SO-101 · real arm" : "MuJoCo · simulator") + (t > app ? `<br><span style="color:#9aa0a5">${APPS12[ai < 24 ? ai % 12 : 0]}</span>` : "");
    const n = Math.floor((t - sw + 0.2) / 0.45); // the model cycles through the four that have run, then settles
    SC.model.textContent = "model: " + MODELS[n >= 0 && n < 9 ? n % MODELS.length : 0];
    show(SC.vla, ramp(t, vla - 0.2, vla + 0.4) * (1 - ramp(t, split - 0.3, split + 0.3)), 14);
    SC.reels.forEach((r, i) => { r.style.opacity = ramp(t, vla + 0.5 + i * 0.22, vla + 0.7 + i * 0.22); });
    // our split needs a manual: manual.md lights up again
    const m = SC.rows[4], mk = ramp(t, split + 0.6, split + 1.0) * (1 - ramp(t, split + 2.4, split + 3.0));
    m.hl.style.opacity = Math.max(+m.hl.style.opacity, mk);
    m.n.style.textShadow = mk > 0 ? `0 0 ${14 * mk}px #8fb3d9` : "none";
    const lm = T("limit", split); SC.limit.style.opacity = ramp(t, lm - 0.2, lm + 0.3);
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
  SC.cadcard.style.opacity = ramp(t, T("proposes", S.s3) - 0.2, T("proposes", S.s3) + 0.3) * (1 - ramp(t, S.test - 0.4, S.test));
  if (go > 0) {
    SC.globeSvg.style.transform = `scale(${lerp(1.3, 1, eio(ramp(t, S.today + 0.1, S.today + 1.8)))})`;
    const pins = [{ lon: -74, lat: 40.7, at: S.realc, label: "MC-6 · real arm" }, ...CITIES.map(([lon, lat], i) => ({ lon, lat, at: S.anylab + i * 0.11 }))];
    const pos = drawGlobe(SC.globe, t, 960, 450, 300, -74 + 11 * (t - (S.today + 1.3)), { pins });
    const co = ramp(t, S.cloud - 0.2, S.cloud + 0.3), cx = 1290, cy = 150 + Math.sin(t * 1.4) * 8;
    SC.cloud.setAttribute("opacity", co); SC.cloud.setAttribute("transform", `translate(${cx} ${cy})`);
    const ny = pos[0];
    if (ny && ny[2] > 0) { SC.tunnel.setAttribute("d", `M${ny[0]} ${ny[1]} Q ${(ny[0] + cx) / 2 + 60} ${Math.min(ny[1], cy) - 80} ${cx - 40} ${cy + 40}`); SC.tunnel.setAttribute("opacity", co * clamp(ny[2] * 4)); SC.tunnel.style.strokeDashoffset = -t * 36; }
    else SC.tunnel.setAttribute("opacity", 0);
  }
  for (const a of SC.apps) { const k = ramp(t, S.twelve + a.at - 0.1, S.twelve + a.at + 0.25) * (1 - ramp(t, S.outro + 0.3, S.outro + 0.8)); a.n.style.opacity = k; a.n.style.transform = `translateY(${(1 - eio(k)) * 14}px)`; }
  for (const c of SC.caseN) { const k = ramp(t, c.t - 0.15, c.t + 0.3); c.n.style.opacity = k; c.n.style.transform = `translateX(${(1 - eio(k)) * -24}px)`; }
  const f = FEATS.findLast(([a]) => a <= (SC.tourSec ?? 0));
  SC.feat.style.opacity = wo * (SC.tourClip === "tour/scenes" ? 1 : 0) * (1 - ramp(t, S.today - 0.3, S.today + 0.2));
  if (f) SC.feat.innerHTML = f[1].replace(/^([^·]+)·/, '<span style="color:#eebc24">$1</span>·');

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
  SC.tourClip = null;
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
    if (clip === "tour/scenes") { const wr = winRect(pan(t)), s = WIN.s * wr.f; cam = { cx: 960 - (wr.c[0] - 960) / s, cy: 540 - (wr.c[1] - 540) / s, s }; }
    SC.tourSec = sec; SC.tourClip = clip;
    if (clip === "intro") SC.introCam = cam = t < S.s3 ? camLerp(CAM0, CAM1, eio(ramp(t, PUSH[0], PUSH[1]))) : camLerp(CAM1, CAMID, eio(ramp(t, S.outro + 0.3, S.outro + 5.0)));
    const f = frozen ? 1 : 0;
    await setFrame(frameOf(clip, sec), `saturate(${1 - 0.6 * f}) brightness(${(1 - 0.3 * f) * popDim(t)})`, z, cam);
    if (cam && clip !== "intro") drawCursor(t, cam);
  } else await setFrame(null);
  $("footage").style.opacity = seg?.[2] === "intro" && t > S.s3 ? ramp(t, S.outro, S.outro + 0.6) : seg?.[2] === "tour/scenes" ? 1 - ramp(pan(t), 0.75, 1) : 1;
  $("tag").style.display = seg && /^clean_3d|^wrist/.test(seg[2]) ? "block" : "none";
  // chalk, from the take's end until the turn
  const chalkO = (t >= OPEN[0] ? 1 : 0) * (1 - ramp(t, turn + 0.6, turn + 1.6));
  $("chalklayer").style.opacity = chalkO;
  const R = eio(ramp(t, OPEN[0], OPEN[1])) * 1250, opening = t < S.s3 && R > 0; // the board opens out of the chalk's tip
  $("chalklayer").style.clipPath = t < OPEN[1] ? `circle(${R + 60}px at 960px 540px)` : "none";
  const ic = SC.introCam; // the mask is laid out in the image's own pixels, before the camera's scale
  $("footage").style.webkitMaskImage = opening && ic ? `radial-gradient(circle at ${ic.cx}px ${ic.cy}px, transparent ${R / ic.s}px, black ${(R + 60) / ic.s}px)` : "none";
  if (chalkO > 0) seekChalk(t, turn);
  $("tech").style.opacity = ramp(t, turn + 0.4, turn + 1.4);
  seekTech(t);
  caption(t);
  $("fade").style.opacity = ramp(t, DUR - 1.8, DUR - 0.3);
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
  window.DUR = DUR;
  return true;
})();
