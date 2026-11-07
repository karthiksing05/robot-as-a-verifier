import { useEffect, useRef, type RefObject } from "react";
import { HAND, Joints, PEDESTAL, REST, UPPER, forward, sideFor, solve, solveFree, type Point, type Side } from "../lib/so101";

type Ctx = CanvasRenderingContext2D;

/** Grabs an element, calling closed when the jaws meet it and done once it's held. */
export type Grabber = (el: HTMLElement, on: { closed: () => void; done: () => void }) => void;

const REST_MAX_MS = 750, REACH_MS = 480, CLOSE_MS = 130, HOLD_MS = 150, SETTLE_MS = 260;
const COMFORT = 200; // millimetres from shoulder to wrist: mid-range, with the elbow well open
const IDLE_OMEGA = 15, REST_OMEGA = 13, REACH_OMEGA = 22; // how quick the joints are: they settle in about 5 / omega seconds
const GLOW_RATE = 22; // how fast the grid's glow catches the cursor
const YELLOW = "#eebc24", SHADE = "#a87f0c", DARK = "#31363b", METAL = "#8d9296";
const JAW_OPEN = 0.72, JAW_RELAXED = 0.34, JAW_SHUT = -0.197; // shut: the moving jaw's tip on the fixed jaw's face
const CLICK_CLOSE_MS = 170;

const ease = (t: number) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);

function hull(ctx: Ctx, length: number, r0: number, r1: number) {
  ctx.beginPath();
  ctx.arc(0, 0, r0, Math.PI / 2, -Math.PI / 2);
  ctx.arc(length, 0, r1, -Math.PI / 2, Math.PI / 2);
  ctx.closePath();
}

/** One printed link: a yellow bracket with its long lightening slot. */
function drawLink(ctx: Ctx, a: Point, b: Point, r0: number, r1: number) {
  const length = Math.hypot(b.x - a.x, b.y - a.y);
  ctx.save();
  ctx.translate(a.x, a.y);
  ctx.rotate(Math.atan2(b.y - a.y, b.x - a.x));
  hull(ctx, length, r0, r1);
  ctx.fillStyle = YELLOW; ctx.fill();
  ctx.lineWidth = 1; ctx.strokeStyle = SHADE; ctx.stroke();
  const inset = Math.max(r0, r1) * 1.5;
  if (length > inset * 2.4) {
    ctx.beginPath();
    ctx.roundRect(inset, -Math.min(r0, r1) * 0.32, length - inset * 2, Math.min(r0, r1) * 0.64, Math.min(r0, r1) * 0.32);
    ctx.fillStyle = SHADE; ctx.fill();
  }
  ctx.restore();
}

/** A joint: the dark servo in the bracket, with its horn and screws. */
function drawServo(ctx: Ctx, at: Point, size: number, angle: number) {
  ctx.save();
  ctx.translate(at.x, at.y);
  ctx.rotate(angle);
  ctx.beginPath(); ctx.roundRect(-size, -size * 0.8, size * 2, size * 1.6, size * 0.2); ctx.fillStyle = DARK; ctx.fill();
  ctx.beginPath(); ctx.arc(0, 0, size * 0.58, 0, Math.PI * 2); ctx.fillStyle = METAL; ctx.fill();
  ctx.beginPath(); ctx.arc(0, 0, size * 0.22, 0, Math.PI * 2); ctx.fillStyle = DARK; ctx.fill();
  ctx.restore();
}

function drawPedestal(ctx: Ctx, base: Point, shoulder: Point, s: number) {
  ctx.beginPath(); ctx.roundRect(base.x - 44 * s, base.y - 15 * s, 88 * s, 21 * s, 3 * s); ctx.fillStyle = YELLOW; ctx.fill();
  ctx.lineWidth = 1; ctx.strokeStyle = SHADE; ctx.stroke();
  ctx.beginPath(); ctx.roundRect(shoulder.x - 21 * s, shoulder.y, 42 * s, base.y - shoulder.y - 12 * s, 3 * s); ctx.fillStyle = DARK; ctx.fill();
}

/** Wrist servo, palm, fixed jaw and moving jaw. +x is along the hand; the fixed jaw is on the -y side. */
function drawGripper(ctx: Ctx, wrist: Point, aim: number, s: number, jaw: number) {
  ctx.save();
  ctx.translate(wrist.x, wrist.y);
  ctx.rotate(aim);
  const flip = Math.cos(aim) < 0 ? 1 : -1; // the fixed jaw stays underneath, whichever way the hand points
  ctx.scale(1, flip);
  ctx.beginPath(); ctx.roundRect(6 * s, -14 * s, 32 * s, 28 * s, 3 * s); ctx.fillStyle = DARK; ctx.fill();
  ctx.beginPath(); ctx.roundRect(34 * s, -18 * s, 26 * s, 36 * s, 4 * s); ctx.fillStyle = YELLOW; ctx.fill();
  ctx.lineWidth = 1; ctx.strokeStyle = SHADE; ctx.stroke();
  // fixed jaw
  ctx.beginPath();
  ctx.moveTo(56 * s, -18 * s); ctx.lineTo(HAND * s, -FIXED_FACE * s - 5 * s); ctx.lineTo(HAND * s, -FIXED_FACE * s); ctx.lineTo(56 * s, -FIXED_FACE * s);
  ctx.closePath(); ctx.fillStyle = YELLOW; ctx.fill(); ctx.stroke();
  // moving jaw, on its pivot
  ctx.translate(56 * s, PIVOT_Y * s);
  ctx.rotate(jaw);
  ctx.beginPath();
  ctx.moveTo(0, 0); ctx.lineTo(JAW_LENGTH * s, 0); ctx.lineTo(JAW_LENGTH * s, 5 * s); ctx.lineTo(4 * s, 15 * s); ctx.closePath();
  ctx.fillStyle = YELLOW; ctx.fill(); ctx.stroke();
  ctx.beginPath(); ctx.arc(0, 4 * s, 6 * s, 0, Math.PI * 2); ctx.fillStyle = DARK; ctx.fill();
  ctx.restore();
}

const FIXED_FACE = 3, PIVOT_Y = 8, JAW_LENGTH = 56;
/** The jaw angle that leaves `gap` pixels at the fingertips. */
const jawFor = (gap: number, s: number) => Math.asin(Math.max(-1, Math.min(1, (gap / s - PIVOT_Y - FIXED_FACE) / JAW_LENGTH)));

/** The Go and home backdrop: a measurement grid that gives way around the pointer, and a mock SO-101 reaching for it.
 *  It works in the background with no limits, so it swings all the way around and through itself. Clicking sends a ripple
 *  through the grid and shuts the gripper. With no pointer in its area it rests, and it holds still for reduced-motion users. With no baseX it stands where it
 *  can reach the middle of the screen, ready to grab: it returns to rest, comes in front of the panel, moves forward and grips. */
export function Field({ baseX, reach = 0.46, grabber }: { baseX?: number; reach?: number; grabber?: RefObject<Grabber | null> }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const armRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current!, front = armRef.current!;
    const host = canvas.parentElement!;
    const ctx = canvas.getContext("2d")!;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0, h = 0, frame = 0, colors = readColors();
    const target = { x: 0, y: 0 }, tip = { x: 0, y: 0 }, glow = { x: 0, y: 0 };
    let pressed = false, closeUntil = 0;
    let client: Point | null = null, pointerHere = false, seeded = false, jaw = JAW_RELAXED, lastFrame = performance.now(), joints: Joints | null = null, goal: Point = { x: 0, y: 0 }, side: Side = -1;
    let grab: { el: HTMLElement; phase: "rest" | "reach"; start: number; from: Point; arrivedAt: number | null; closed: boolean; on: { closed: () => void; done: () => void } } | null = null;
    const ripples: { x: number; y: number; at: number }[] = [];

    function readColors() {
      const css = getComputedStyle(document.documentElement);
      const read = (name: string) => css.getPropertyValue(name).trim();
      return { accent: read("--accent"), line: read("--line"), muted: read("--muted"), fill: getComputedStyle(host).backgroundColor };
    }

    const resize = () => {
      const dpr = Math.min(devicePixelRatio || 1, 2);
      w = host.clientWidth; h = host.clientHeight; // not the bounding box, which a page's arrival animation scales
      for (const c of [canvas, front]) {
        c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
        c.getContext("2d")!.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
      if (!seeded) { target.x = tip.x = glow.x = w * 0.55; target.y = tip.y = glow.y = h * 0.4; seeded = true; }
      if (still) draw(0);
    };

    const onMove = (e: PointerEvent) => {
      client = { x: e.clientX, y: e.clientY };
      if (grab) return;
      const box = host.getBoundingClientRect();
      host.style.setProperty("--px", String((((e.clientX - box.left) / w) * 2 - 1).toFixed(3)));
      host.style.setProperty("--py", String((((e.clientY - box.top) / h) * 2 - 1).toFixed(3)));
    };
    /** The arm only attends to a pointer inside its own area. Read each frame, since a page can scroll under a still mouse. */
    function readPointer() {
      if (grab) return;
      const box = host.getBoundingClientRect();
      pointerHere = !!client && client.x >= box.left && client.x <= box.right && client.y >= box.top && client.y <= box.bottom;
      if (pointerHere) { target.x = client!.x - box.left; target.y = client!.y - box.top; }
    }
    const onLeave = () => { client = null; };
    const onDown = (e: PointerEvent) => {
      const box = host.getBoundingClientRect();
      ripples.push({ x: e.clientX - box.left, y: e.clientY - box.top, at: performance.now() });
      if (pointerHere) { pressed = true; closeUntil = performance.now() + CLICK_CLOSE_MS; }
    };
    const onUp = () => { pressed = false; };

    function grid(now: number) {
      const step = 30, reachPx = 170;
      const quiet = new Path2D(), lit = new Path2D();
      for (let gy = step / 2; gy < h + step; gy += step) {
        for (let gx = step / 2; gx < w + step; gx += step) {
          const dx = gx - glow.x, dy = gy - glow.y, d = Math.hypot(dx, dy) || 1;
          const pull = Math.exp(-((d / reachPx) ** 2));
          let px = gx + (dx / d) * pull * 20, py = gy + (dy / d) * pull * 20, wave = 0;
          for (const r of ripples) {
            const age = (now - r.at) / 1000, rx = gx - r.x, ry = gy - r.y, rd = Math.hypot(rx, ry) || 1;
            const front = Math.exp(-(((rd - age * 520) / 44) ** 2)) * Math.max(0, 1 - age / 1.3);
            px += (rx / rd) * front * 16; py += (ry / rd) * front * 16; wave = Math.max(wave, front);
          }
          const hot = Math.max(pull, wave), size = 2 + hot * 3, path = hot > 0.08 ? lit : quiet;
          path.moveTo(px - size, py); path.lineTo(px + size, py);
          path.moveTo(px, py - size); path.lineTo(px, py + size);
        }
      }
      ctx.lineWidth = 1;
      ctx.strokeStyle = colors.line; ctx.globalAlpha = 0.6; ctx.stroke(quiet);
      ctx.strokeStyle = colors.accent; ctx.globalAlpha = 0.85; ctx.stroke(lit);
      ctx.globalAlpha = 1;
    }

    function reticle() {
      if (grab || !pointerHere) return; // it marks your cursor, so it's only there when you are
      ctx.strokeStyle = colors.accent; ctx.lineWidth = 1; ctx.beginPath();
      ctx.arc(target.x, target.y, 9, 0, Math.PI * 2);
      ctx.moveTo(target.x - 15, target.y); ctx.lineTo(target.x - 5, target.y); ctx.moveTo(target.x + 5, target.y); ctx.lineTo(target.x + 15, target.y);
      ctx.moveTo(target.x, target.y - 15); ctx.lineTo(target.x, target.y - 5); ctx.moveTo(target.x, target.y + 5); ctx.lineTo(target.x, target.y + 15); ctx.stroke();
      ctx.font = '10.5px "JetBrains Mono", monospace'; ctx.fillStyle = colors.muted;
      ctx.fillText(`x ${Math.round(target.x)}  y ${Math.round(target.y)}`, target.x + 16, target.y - 12);
    }

    /** Where the arm stands. With no baseX it stands far enough from the middle that grabbing GO, a little below
     *  centre, is a comfortable pose for its joints. It may stand past the edge of a narrow screen and reach in. */
    function stance() {
      const scale = baseX === undefined ? Math.min(h * 0.25, Math.max(w * 0.2, Math.min(h * 0.2, w * 0.34))) / UPPER : Math.min(h * reach, w * 0.34) / UPPER;
      const y = h + 6 - PEDESTAL * scale;
      const across = Math.sqrt(Math.max(0, (COMFORT * scale) ** 2 - (y - h * 0.6) ** 2));
      const x = baseX !== undefined ? w * baseX : w / 2 + 40 + HAND * scale + across;
      return { scale, base: { x, y: h + 6 }, shoulder: { x, y } };
    }

    /** Moves the joints a frame: following in the background, or back to rest and forward to grab. */
    function move(now: number) {
      const dt = Math.min((now - lastFrame) / 1000, 0.05);
      lastFrame = now;
      const { scale, shoulder } = stance();
      let asked, omega = IDLE_OMEGA;
      if (grab?.phase === "rest") {
        asked = REST;
        omega = REST_OMEGA;
        jaw += (JAW_OPEN - jaw) * Math.min(1, dt * 9);
        joints ??= new Joints(REST);
        if (joints.distanceTo(REST) < 0.05 || now - grab.start > REST_MAX_MS) {
          grab.phase = "reach"; grab.start = now; grab.from = { ...tip };
          front.style.zIndex = "3"; // in front of the panel from here: at rest it isn't over anything, so the swap can't be seen
        }
      } else if (grab) {
        follow(now, scale);
        asked = solve(shoulder, goal, Math.PI, scale);
        omega = REACH_OMEGA;
      } else if (!pointerHere) { // nobody's here, so it rests and holds still
        asked = REST;
        omega = REST_OMEGA;
        jaw += (JAW_RELAXED - jaw) * Math.min(1, dt * 9);
      } else {
        side = sideFor(side, target, shoulder, scale);
        asked = solveFree(shoulder, target, scale, side);
        const closing = pressed || now < closeUntil; // however quick the click, the jaws visibly meet
        jaw += ((closing ? JAW_SHUT : JAW_RELAXED) - jaw) * Math.min(1, dt * (closing ? 32 : 9));
      }
      joints ??= new Joints(asked);
      const pose = joints.follow(asked, dt, omega);
      const at = forward(shoulder, pose, scale);
      tip.x = at.tip.x; tip.y = at.tip.y;
    }

    function so101() {
      const { scale, base, shoulder } = stance();
      const pose = joints!.pose;
      const { elbow, wrist } = forward(shoulder, pose, scale);
      const armCtx = front.getContext("2d")!;
      armCtx.clearRect(0, 0, w, h);
      drawPedestal(armCtx, base, shoulder, scale);
      drawLink(armCtx, shoulder, elbow, 19 * scale, 15 * scale);
      drawServo(armCtx, shoulder, 20 * scale, pose.upper);
      drawLink(armCtx, elbow, wrist, 15 * scale, 12 * scale);
      drawServo(armCtx, elbow, 16 * scale, pose.fore);
      drawGripper(armCtx, wrist, pose.hand, scale, jaw);
    }

    function draw(now: number) {
      const dt = Math.min((now - lastFrame) / 1000, 0.05);
      readPointer();
      move(now);
      const lead = grab ? tip : pointerHere ? target : tip;
      const catchUp = 1 - Math.exp(-GLOW_RATE * dt);
      glow.x += (lead.x - glow.x) * catchUp; glow.y += (lead.y - glow.y) * catchUp;
      while (ripples.length && now - ripples[0].at > 1400) ripples.shift();
      ctx.clearRect(0, 0, w, h);
      grid(now);
      reticle();
      so101();
    }

    /** Reaches for the element, closes on its top and bottom edges, and holds. Reads it live, since it can move. */
    function follow(now: number, s: number) {
      const g = grab!;
      const own = host.getBoundingClientRect(), box = g.el.getBoundingClientRect();
      const end = { x: box.right - own.left - Math.min(box.width * 0.28, 44), y: box.bottom - own.top - FIXED_FACE * s }; // the fixed jaw under the bottom edge
      const elapsed = now - g.start, k = ease(Math.min(1, elapsed / REACH_MS));
      goal = { x: g.from.x + (end.x + 60 * s * (1 - k) - g.from.x) * k, y: g.from.y + (end.y + 34 * s * (1 - k) - g.from.y) * k };
      const held = jawFor(box.height, s), open = Math.max(JAW_OPEN, held + 0.3);
      // close once the hand has really arrived, not when a timer says so
      if (g.arrivedAt === null && k >= 1 && (Math.hypot(tip.x - end.x, tip.y - end.y) < 3 || elapsed > REACH_MS + SETTLE_MS)) g.arrivedAt = now;
      const closing = g.arrivedAt === null ? 0 : Math.min(1, (now - g.arrivedAt) / CLOSE_MS);
      jaw += (open + (held - open) * ease(closing) - jaw) * (closing > 0 ? 1 : 0.2);
      if (closing >= 1 && !g.closed) { g.closed = true; g.on.closed(); }
      if (g.arrivedAt !== null && now - g.arrivedAt >= CLOSE_MS + HOLD_MS) { const { done } = g.on; g.on.done = () => undefined; done(); }
    }

    const loop = (now: number) => {
      frame = requestAnimationFrame(loop);
      if (!document.hidden) draw(now);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();
    const recolor = new MutationObserver(() => { colors = readColors(); if (still) draw(0); });
    recolor.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    if (grabber) {
      grabber.current = (el, on) => {
        if (grab || still || document.hidden) { on.closed(); on.done(); return; }
        grab = { el, phase: "rest", start: performance.now(), from: { ...tip }, arrivedAt: null, closed: false, on };
      };
    }
    if (!still) {
      document.documentElement.addEventListener("pointerleave", onLeave);
      document.addEventListener("mouseleave", onLeave);
      addEventListener("pointermove", onMove);
      addEventListener("pointerdown", onDown);
      addEventListener("pointerup", onUp);
      addEventListener("pointercancel", onUp);
      frame = requestAnimationFrame(loop);
    }
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      recolor.disconnect();
      document.documentElement.removeEventListener("pointerleave", onLeave);
      document.removeEventListener("mouseleave", onLeave);
      removeEventListener("pointermove", onMove);
      removeEventListener("pointerdown", onDown);
      removeEventListener("pointerup", onUp);
      removeEventListener("pointercancel", onUp);
      if (grabber) grabber.current = null;
    };
  }, [baseX, reach, grabber]);

  return (
    <>
      <canvas ref={ref} className="field-canvas" aria-hidden="true" />
      <canvas ref={armRef} className="field-canvas field-arm" aria-hidden="true" />
    </>
  );
}
