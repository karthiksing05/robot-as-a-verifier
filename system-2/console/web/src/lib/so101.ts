// The home page's mock SO-101: a side-on arm with three joints, in its own lengths. Angles are absolute, in screen
// space, where y points down. Everything drawn comes from forward kinematics, so the links stay rigid.

export type Point = { x: number; y: number };
export interface Pose { upper: number; fore: number; hand: number } // the direction each link points

export const UPPER = 116, FORE = 135, HAND = 112, PEDESTAL = 62; // millimetres, the real arm's proportions

const ELBOW_MIN = (72 * Math.PI) / 180; // the elbow never closes tighter than this, so the links don't fold onto each other
const WRIST_MAX = 1.5; // how far the hand can bend from the forearm
const AIM_MIN = Math.PI - 0.55, AIM_MAX = (3 * Math.PI) / 2 + 0.05; // from a little below level on the left, to straight up
const MIN_REACH = Math.sqrt(UPPER ** 2 + FORE ** 2 - 2 * UPPER * FORE * Math.cos(ELBOW_MIN));
const MAX_REACH = (UPPER + FORE) * 0.995;

const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a));
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** The pose it returns to before it grabs: elbow up, forearm sloping down, hand level. */
export const REST: Pose = { upper: -1.6, fore: Math.PI - 0.35, hand: Math.PI };

const MAX_TILT = 0.28; // how far the hand leans off level, in radians
export type Side = -1 | 1; // which way the hand points: -1 is left

/** Which way the hand should point. It only changes once the target is clearly on the other side, so it can't flicker. */
export function sideFor(current: Side, tip: Point, shoulder: Point, scale: number): Side {
  const past = (tip.x - shoulder.x) / scale;
  return past > 25 ? 1 : past < -25 ? -1 : current;
}

/** For idling in the background: no joint limits, so the arm can go all the way around and through itself. Only the
 *  hand is held: always roughly level. */
export function solveFree(shoulder: Point, tip: Point, scale: number, side: Side): Pose {
  const lift = clamp((shoulder.y - tip.y) / (HAND * scale * 2), -1, 1) * MAX_TILT; // up a little when reaching high
  const aim = side < 0 ? Math.PI + lift : -lift;
  const dx = tip.x - Math.cos(aim) * HAND * scale - shoulder.x, dy = tip.y - Math.sin(aim) * HAND * scale - shoulder.y;
  const reach = clamp(Math.hypot(dx, dy) / scale, Math.abs(FORE - UPPER) + 1, MAX_REACH);
  const toWrist = Math.atan2(dy, dx);
  const upper = toWrist + Math.acos(clamp((UPPER ** 2 + reach ** 2 - FORE ** 2) / (2 * UPPER * reach), -1, 1));
  const fore = Math.atan2(Math.sin(toWrist) * reach - Math.sin(upper) * UPPER, Math.cos(toWrist) * reach - Math.cos(upper) * UPPER);
  return { upper, fore, hand: aim };
}

/** For grabbing: joint angles that put the fingertip at `tip`, pointing along `aim`, or as near as the joints allow. The
 *  elbow stays up and the wrist on the device's side of the shoulder, so the reach is clean and can't flip. */
export function solve(shoulder: Point, tip: Point, aim: number, scale: number): Pose {
  const a = ((aim % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
  const pointing = clamp(a < Math.PI / 2 ? a + 2 * Math.PI : a, AIM_MIN, AIM_MAX);
  const hand = HAND * scale;
  const wristX = Math.min(tip.x - Math.cos(pointing) * hand, shoulder.x - UPPER * scale * 0.1);
  const wristY = Math.min(tip.y - Math.sin(pointing) * hand, shoulder.y + UPPER * scale * 0.15);
  const dx = wristX - shoulder.x, dy = wristY - shoulder.y;
  const reach = clamp(Math.hypot(dx, dy) / scale, MIN_REACH, MAX_REACH);
  const toWrist = Math.atan2(dy, dx);
  const bend = Math.acos(clamp((UPPER ** 2 + reach ** 2 - FORE ** 2) / (2 * UPPER * reach), -1, 1));
  const upper = toWrist + bend;
  const elbow = { x: Math.cos(upper) * UPPER, y: Math.sin(upper) * UPPER };
  const fore = Math.atan2(Math.sin(toWrist) * reach - elbow.y, Math.cos(toWrist) * reach - elbow.x);
  return { upper, fore, hand: fore + clamp(wrap(pointing - fore), -WRIST_MAX, WRIST_MAX) };
}

export function forward(shoulder: Point, pose: Pose, scale: number) {
  const along = (from: Point, angle: number, length: number) => ({ x: from.x + Math.cos(angle) * length * scale, y: from.y + Math.sin(angle) * length * scale });
  const elbow = along(shoulder, pose.upper, UPPER);
  const wrist = along(elbow, pose.fore, FORE);
  return { elbow, wrist, tip: along(wrist, pose.hand, HAND) };
}

/** Joints that ease toward where they're asked to go, like servos: speed builds and settles, with no overshoot and no
 *  jumps, however suddenly the target moves. The same at any frame rate. */
export class Joints {
  pose: Pose;
  private speed: Pose = { upper: 0, fore: 0, hand: 0 };
  constructor(pose: Pose) { this.pose = { ...pose }; }

  /** The largest gap, in radians, between where the joints are and a pose. */
  distanceTo(goal: Pose) {
    return Math.max(...(["upper", "fore", "hand"] as const).map((joint) => Math.abs(wrap(goal[joint] - this.pose[joint]))));
  }

  /** omega sets how quick: it's settled after about 5 / omega seconds. */
  follow(goal: Pose, dt: number, omega: number) {
    const steps = Math.max(1, Math.ceil(dt / 0.008));
    for (let i = 0; i < steps; i += 1) {
      const h = dt / steps;
      for (const joint of ["upper", "fore", "hand"] as const) {
        const pull = omega * omega * wrap(goal[joint] - this.pose[joint]) - 2 * omega * this.speed[joint];
        this.speed[joint] += pull * h;
        this.pose[joint] += this.speed[joint] * h;
      }
    }
    return this.pose;
  }
}
