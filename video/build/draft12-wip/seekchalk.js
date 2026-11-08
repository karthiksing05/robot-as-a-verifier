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
