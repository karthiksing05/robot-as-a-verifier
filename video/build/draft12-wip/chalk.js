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
  X("findings · coverage · reward", 1480, 770, re + 0.5, 0.4, { size: 30, color: DIM });
  POINTS.push([re, 1600, 470]);
  // "our centrifuge": back to the prototype, circled, and the board gives way to the real one
  const oc = T("our", re);
  POINTS.push([oc - 0.2, 330, 430]);
  P(circ(335, 590, 205), oc - 0.05, 0.55, { color: YELLOW, w: 6 });

  POINTS.sort((a, b) => a[0] - b[0]);
  EL.sort((a, b) => a.start - b.start);
  for (const e of EL) {
    if (e.kind === "path") { e.len = e.node.getTotalLength(); e.node.style.strokeDasharray = `${e.len} ${e.len}`; e.node.style.strokeDashoffset = e.len; }
    else { e.bbox = e.node.getBBox(); e.rect.setAttribute("x", e.bbox.x - 10); }
  }
}
