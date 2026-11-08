// Sections 6 and 7: the centrifuge run, step by step, then the ending.
// Footage is pre-extracted to ../out/frames/<clip>/00001.jpg… at 30 fps (see footage.sh). Overlay numbers come from the
// recorded run system-2/runs/eval-1107-232000/002-claude-sonnet-5-5-centrifuge-A and appliances/centrifuge/build/verify.stock.json.
"use strict";
window.WALK = async function (k) {
  const { T, TE, el, $, ramp, eio, show } = k;
  const CLIPS = await (await fetch("../out/frames/clips.json").catch(() => null))?.json?.().catch(() => ({})) ?? {};
  const frame = (clip, sec) => {
    const c = CLIPS[clip];
    if (!c) return null;
    const n = Math.max(1, Math.min(c.frames, Math.floor(sec * 30) + 1));
    return `../out/frames/${clip}/${String(n).padStart(5, "0")}.jpg`;
  };

  const s6 = T("here", 100), s7 = T("our", T("rises", s6)), end = T("rav", T("relies", s7));
  const W = (w, after) => T(w, after);

  /* What's on screen, as footage segments: [from, to, clip, clipStart, speed, freezeAt?] (freezeAt: clip second held). */
  const STEP = {
    here: s6, surveys: W("surveys", s6), scans: W("scans", s6), segments: W("segments", s6), maps: W("maps", s6), touches: W("touches", s6),
    fail: W("fail", s6), plans: W("plans", s6), runs: W("runs", s6), when: W("when", W("rules", s6)), display: W("display", s6),
    lid: W("then", W("change", s6)), traces: W("traces", s6), unmasks: W("unmasks", s6), revb: W("rev", W("tube", s6)), s7,
  };
  const LAY = await (await fetch("segments.json")).json();
  const SEGS = LAY.segments, S = LAY.steps;

  /* The step rail. */
  const RAIL = ["survey", "scan", "segment", "map", "touch", "plan", "test", "verdicts", "report", "CAD fix", "Rev B"];
  const railAt = [S.surveys, S.scans, S.segments, S.maps, S.touches, S.plans, S.runs, W("judges", s6), S.lid, S.traces, S.revb];
  const rail = $("rail");
  rail.innerHTML = RAIL.map((r) => `<span>${r}</span>`).join("");
  const railSpans = [...rail.children];

  /* Cards: System 1 on the left, System 2 on the right, a person's approval between them. */
  const layer = el("div", "abs", "", document.getElementById("stage"), "inset:0;z-index:25;pointer-events:none");
  const card = (cls, label, color, x, w) => {
    const n = el("div", "abs", `<div class="label" style="color:${color};margin-bottom:10px">${label}</div><div class="body mono" style="font-size:24px;line-height:1.45;color:#eceef0"></div>`, layer,
      `left:${x}px;top:640px;width:${w}px;padding:20px 24px;background:rgba(14,16,18,.9);border:1.5px solid ${color};box-sizing:border-box;opacity:0`);
    n.body = n.querySelector(".body");
    return n;
  };
  const C1 = card("", "System 1 · did and measured", "#eebc24", 70, 760);
  const C2 = card("", "System 2 · responded", "#8fb3d9", 1090, 760);
  const CP = el("div", "abs", `<div class="label" style="color:#f0a63a;margin-bottom:8px">A person</div><div class="body mono" style="font-size:22px;color:#f6e3c4"></div>`, layer,
    "left:780px;top:560px;width:360px;padding:14px 18px;background:rgba(40,28,10,.94);border:1.5px solid #f0a63a;box-sizing:border-box;opacity:0;text-align:center");
  CP.body = CP.querySelector(".body");
  const stamp = el("div", "abs mono", "", layer, "left:40px;top:76px;font-size:18px;color:#cfd3d6;background:rgba(10,12,14,.7);padding:5px 10px;opacity:0");
  const note = el("div", "abs mono", "", layer, "right:36px;top:76px;font-size:16px;color:#9aa0a5;background:rgba(10,12,14,.7);padding:5px 10px;opacity:0;max-width:760px;text-align:right");
  const manual = el("div", "abs", `<div class="label" style="margin-bottom:10px">manual.md · MC-6 mini centrifuge</div><div class="mono" style="font-size:19px;line-height:1.6;color:#d9dcdf">1. Flip POWER up to ON. The display shows<br>&nbsp;&nbsp;&nbsp;1000 RPM 0:30.<br>2. Lift the lid by its handle. Seat a tube in well A.<br>3. Close the lid. Press START.</div>`, layer,
    "left:1180px;top:150px;width:660px;padding:20px 24px;background:rgba(14,16,18,.92);border:1.5px solid #3a4046;box-sizing:border-box;opacity:0");

  /* Each beat: when, the cards' text, a freeze, and a note on where the numbers come from. */
  const RUN = "Rev A run · Claude Sonnet 5.5 · MuJoCo";
  const BEATS = [
    { a: S.fail - 0.1, b: S.plans - 0.25, freeze: true, stamp: "explore · scan", s1: "Scan stopped: <b>pipeline_error</b><br>(a corrupt camera frame), reported back", s2: "Looked at the stop and ran explore again<br>→ <b>done</b>: panel mapped", src: RUN },
    { a: S.plans - 0.1, b: S.runs - 0.2, freeze: false, stamp: "plan", s2: "Read the manual, proposed a test plan;<br>fixed it when the plan check refused it", p: "Karthik approves the plan", src: RUN + " · approved in the Console" },
    { a: S.runs + 0.2, b: S.flip - 0.25, freeze: false, stamp: "test", s1: "Every step capped at <b>15 N</b> (steps ask ≤ 14 N)<br>Retries: Tethered 0 · Balanced 2 · Autonomous 4<br>Verdicts by fixed rules on sensor readings", src: "docs/system-boundary.md · decisions D31, D34" },
    { a: S.flip, b: S.display - 0.25, freeze: true, stamp: "s1 flip POWER", s1: "SafetyStop: tip force <b style='color:#ff8a7a'>16.4 N</b> over the 15.0 N cap<br>Stopped before anything else", p: "resuming after a safety stop needs a person", src: "from an earlier recorded run (eval-1107, Sonnet 5.5); no stop in this one" },
    { a: S.display, b: S.lid - 0.25, freeze: true, stamp: "s1 flip POWER", s1: "Display read <b>“1000rpm  0:30”</b><br>the manual says “1000 RPM 0:30” ✕", s2: "Stopped, then amended the plan<br>Level <b>0 · automatic</b>: set by code, not the model", src: RUN + " · step s1" },
    { a: S.lid, b: S.lidui + 1.4, freeze: true, stamp: "s7 turn handle_1", s1: "<b style='color:#ff8a7a'>SKIPPED</b> before the arm moved:<br>handle_1 needs a pinch grip; the no-thumbs<br>rule allows only the fingertip pad", s2: "Reported it: a no-thumbs finding<br>on the lid, not a guess", src: RUN + " · step s7" },
    { a: S.traces, b: S.unmasks - 0.25, freeze: false, stamp: "CAD fix", s2: "Root cause: the lid handle is a thin pinch fin<br>Fix: a <b>hook lip</b> the fingertip can pull", s1: "CAD check: a pull control catches<br>the fingertip, so nothing needs a pinch", p: "approves the patch", src: "Rev B's hook lip as drawn by the team · patches from a run aren't shown yet" },
    { a: S.unmasks, b: S.revb - 0.25, freeze: true, stamp: "lid fixed, well A still tight", s1: "Tube sits <b>11.1 mm</b> high (3.2 mm when seated)<br>START → display shows <b>TUBE</b>", s2: "A second fault, hidden<br>until the lid could open", src: "the device's verification check in the sim · tube placed by the check" },
    { a: S.revb, b: s7 - 0.3, freeze: false, stamp: "Rev B", s1: "Lid: handle_1 swung to <b style='color:#7fd68f'>100°</b> ✓<br>Well A seats the tube ✓", s2: "Same tests rerun<br>A patch is kept only if the score rises", src: "verification check · Rev B run shown (agent-centrifuge-045535) · not printed yet" },
  ];

  /* §7: what generalizes. */
  const ENDCHIPS = [
    [W("never", s7), "no device names in prompts or harness code"],
    [W("another", s7), "System 1 sits behind 7 tools · sim and real arms swap in"],
    [W("plans", s7), "test plans from any manual"],
    [W("any", W("we", W("plans", s7))), "any prototype, from its CAD"],
    [W("human", s7), "approval levels 0–3 · a person decides what matters"],
  ];
  const chipsBox = el("div", "abs", "", layer, "left:70px;top:620px;width:1000px");
  const endChips = ENDCHIPS.map(([t, txt]) => ({ t, n: el("div", "mono", `<i style="display:inline-block;width:10px;height:10px;background:#eebc24;margin-right:14px"></i>${txt}`, chipsBox, "font-size:26px;color:#eceef0;background:rgba(14,16,18,.88);border-left:3px solid #eebc24;padding:12px 18px;margin-bottom:12px;opacity:0") }));
  const finalLine = el("div", "abs mich", "", layer, "left:0;right:0;top:420px;text-align:center;font-size:40px;line-height:1.5;color:#f1f2f3;opacity:0");
  const titleCard = el("div", "abs", `<div class="mich" style="font-size:150px;color:#f1f2f3;text-align:center">RAAV</div><div class="mich" style="font-size:44px;color:#eebc24;text-align:center;letter-spacing:.2em;margin-top:6px">ROBOT AS A VERIFIER</div><div class="mono" style="font-size:22px;color:#8b9095;text-align:center;margin-top:40px">MakeCU 2026</div>`, layer, "left:0;right:0;top:330px;opacity:0");
  const titleBg = el("div", "abs", "", layer, "inset:0;background:#111417;opacity:0");
  titleBg.after(titleCard);

  const fmt = (x) => x.toFixed(1);
  return async function seekWalk(t) {
    if (t < s6 - 0.5) { layer.style.opacity = 0; return false; }
    layer.style.opacity = 1;
    // footage
    const seg = SEGS.find((s) => s[0] <= t && t < s[1]);
    const beat = BEATS.find((b) => b.a <= t && t < b.b);
    const img = $("footage");
    if (seg) {
      const [from, , clip, c0, speed = 1, hold, zoom] = seg;
      const frozen = beat?.freeze && t > beat.a + 0.35 && t < beat.b - 0.25;
      const sec = hold != null && frozen ? hold : c0 + (t - from) * speed;
      img.style.display = "block";
      const src = frame(clip, sec);
      if (src && img.getAttribute("src") !== src) { img.setAttribute("src", src); try { await img.decode(); } catch { } }
      const f = frozen ? 1 : 0;
      img.style.filter = `saturate(${1 - 0.6 * f}) brightness(${1 - 0.3 * f})`;
      img.style.transformOrigin = zoom ? `${zoom[1]}px ${zoom[2]}px` : "50% 50%";
      img.style.transform = zoom ? `scale(${zoom[0]})` : "none";
    } else { img.style.display = "none"; img.style.transform = "none"; }
    $("tag").style.display = seg && /^(clean_3d|wrist)/.test(seg[2]) ? "block" : "none";
    // rail
    const inWalk = t >= S.surveys - 0.3 && t < s7 - 0.2;
    rail.style.display = inWalk ? "flex" : "none";
    const cur = railAt.findLastIndex((x) => x <= t + 0.05);
    railSpans.forEach((s, i) => { s.className = i === cur ? "on" : i < cur ? "done" : ""; });
    // the manual, as the run begins
    manual.style.opacity = ramp(t, s6 + 0.8, s6 + 1.3) * (1 - ramp(t, S.surveys - 0.2, S.surveys + 0.3));
    // cards
    const o = beat ? ramp(t, beat.a, beat.a + 0.4) * (1 - ramp(t, beat.b - 0.25, beat.b)) : 0;
    for (const [n, key] of [[C1, "s1"], [C2, "s2"], [CP, "p"]]) {
      const txt = beat?.[key];
      if (txt && n.body.innerHTML !== txt) n.body.innerHTML = txt;
      const d = key === "p" ? 0.5 : key === "s2" ? 0.25 : 0;
      show(n, txt ? o * ramp(t, beat.a + d, beat.a + d + 0.35) : 0, 14);
    }
    stamp.style.opacity = o; if (beat) stamp.textContent = beat.stamp;
    note.style.opacity = o * 0.95; if (beat) note.textContent = beat.src;
    // §7
    const inEnd = t >= s7 - 0.3;
    for (const c of endChips) show(c.n, inEnd ? ramp(t, c.t - 0.1, c.t + 0.35) * (1 - ramp(t, W("as", W("loop", s7)) - 0.5, W("as", W("loop", s7)))) : 0, 12);
    const asAt = W("as", W("loop", s7));
    // the last line is carried by the voice and its caption, over the arm; then the title
    titleBg.style.opacity = ramp(t, end - 0.5, end + 0.2);
    titleCard.style.opacity = ramp(t, end - 0.3, end + 0.4);
    return true;
  };
};
