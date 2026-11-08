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
  const gF = ramp(t, S.hinge - 0.4, S.hinge + 0.2) * (1 - ramp(t, S.s4 - 0.6, S.s4 - 0.2));
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
  H.ctl = CTL.map((c, i) => { const n = el("div", "mono", c, H.ctlWrap, "font-size:16px;color:#dfe2e5;padding:6px 11px;border:1.5px solid #3a4046;background:#181b1e;border-radius:3px;opacity:0;white-space:nowrap"); return { n, at: finds + 0.15 + i * 0.13, name: c }; });
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
    C(S.plan + 0.3, S.approves - 0.1, BLUE, `${b("plan-1", BLUE)} · 8 steps · claude-haiku-5-5 · 17,050 tokens in, 889 out`),
    C(S.approves, S.works - 0.25, GREEN, `${b("✓ approved", GREEN)} · plan-1 / Karthik · the arm waited 3.3 s`),
    C(S.works, S.board - 0.2, BLUE, `${b("real", YELLOW)} the bench, overhead &nbsp;·&nbsp; ${b("sim", BLUE)} the same 8 steps on Rev B in MuJoCo &nbsp;·&nbsp; lined up step by step`),
    C(S.board, S.five - 0.15, YELLOW, `MC-6 board &nbsp;${["TIME+ 0→1→0", "START 0→1→0", "STOP 0→1→0"].map((x, i) => `<span class="rd" data-at="${S.board + 0.5 + i * 0.45}" style="opacity:0;margin-left:18px;padding:3px 10px;border:1px solid ${YELLOW}66">${x}</span>`).join("")}`),
    C(S.five, S.timeq - 0.15, GREEN, `REWARD <span class="mich rw" style="font-size:30px;color:#fff">0.00</span> &nbsp;·&nbsp; ${b("5 passed", GREEN)} · 1 untested (display)`),
    C(S.timeq, S.lid - 0.15, AMBER, `${b("TIME+", AMBER)} · 22.5 N, 7.2 mm · button 0→1→0 · time 0:40 → 0:40 · SPEED 2700 → 2800`),
    C(S.lid, sus - 0.15, AMBER, `${b("START", AMBER)} · 15.8 N, 4.4 mm · button 0→1→0 · then the display:`),
    C(sus, S.cad - 0.6, AMBER, `${b("tube_place", AMBER)} · released ${b("56.2 mm", AMBER)} above the seat`),
  ];
  for (const c of H.cards) c.rd = [...c.n.querySelectorAll(".rd")];
  H.rw = H.cards[5].n.querySelector(".rw");
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
    tag(1340, 610, S.seated, GREEN, "seated within 0.97 mm", "0.2 mm from the designer's own fix"),
  ];
  /* §4 the hinge: labels over the render */
  const htag = (x, at, color, head, sub) => ({ at, n: el("div", "abs mono", `<div class="mich" style="font-size:26px;color:${color}">${head}</div><div style="font-size:18px;color:#c3c8cc;margin-top:8px;line-height:1.5">${sub}</div>`, hud, `left:${x}px;top:96px;opacity:0;padding:16px 22px;background:rgba(14,16,18,.86);border-top:4px solid ${color};white-space:nowrap`) });
  const hg = S.hinge;
  H.hingeTags = [
    htag(150, hg + 0.1, "#ff8a7a", "REV A", "Onshape original<br>0.025 mm clearances · pin headed at both ends"),
    htag(1110, T("second", hg) - 0.1, GREEN, "REV B · BY THE TEAM", "0.25 mm clearance · 0.4 mm knuckle gaps<br>one-headed pin · door swings to ~145°"),
  ];
  H.hingeFoot = el("div", "abs mono", "microwave hinge F1 · the team's meshes, Rev A and Rev B", hud, "right:48px;bottom:150px;font-size:16px;color:#8b9095;opacity:0");
}

function drawCad(t) {
  const A = H.cadAt, w = eio(ramp(t, A.widened - 0.1, A.widened + 1.3)), d = eio(ramp(t, A.retest - 0.1, A.seated));
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
    const vAt = S.verdict + (3 + STEP_CTL.indexOf(i)) * 0.07, vk = t >= vAt;
    let col = live ? YELLOW : "#3a4046", txt = c.name;
    if (vk) { if (i === 5) { txt = "display · untested"; col = "#5d6268"; } else { txt = "✓ " + c.name; col = GREEN; } }
    if ((i === 0 || i === 2) && t >= H.two) col = AMBER;
    c.n.style.borderColor = col; c.n.textContent = txt;
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
    const d = `M${x1} 688 C${x1} 600 ${x6} 600 ${x6} 688`;
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
  const go = ramp(t, S.cad - 0.5, S.cad + 0.2) * (1 - ramp(t, S.hinge - 0.6, S.hinge - 0.1));
  H.cad.style.opacity = go; H.cad.style.display = go > 0 ? "block" : "none";
  if (go > 0) { drawCad(t); for (const g of H.cadTags) show(g.n, ramp(t, g.at, g.at + 0.35), 12); }
  // §4 the hinge tags
  const ho = ramp(t, S.hinge - 0.2, S.hinge + 0.3) * (1 - ramp(t, S.s4 - 0.6, S.s4 - 0.2));
  for (const g of H.hingeTags) show(g.n, ho * ramp(t, g.at, g.at + 0.4), 12);
  H.hingeFoot.style.opacity = ho;
}
