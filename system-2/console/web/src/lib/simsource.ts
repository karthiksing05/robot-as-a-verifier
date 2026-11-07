import { LIVE_URL } from "./live";

export interface SceneGeom { name: string; body: number; type: string; size: number[]; pos: number[]; quat: number[]; mesh: number; mat: number; rgba: number[] }
export interface SceneMat { name: string; rgba: number[]; specular: number; shininess: number; emission: number; tex: number }
export interface SceneData {
  run_id: string; geoms: SceneGeom[]; materials: SceneMat[]; moving: number[]; meshes: Record<string, { verts: number; tris: number }>;
  files: Record<string, string>; bodies: { name: string; pos: number[]; quat: number[] }[];
}
export interface PoseBlend { a: ArrayLike<number>; b: ArrayLike<number>; aAt: number; bAt: number; k: number; stamp: number }

/** Where the 3D view gets its model and its poses: a run happening now, or one that was recorded. */
export interface SimSource {
  scene(stopped: () => boolean): Promise<SceneData | null>;
  asset(path: string): string;
  start(): void;
  stop(): void;
  pose(now: number): PoseBlend | null;
}

const MIN_DELAY_MS = 70, MAX_DELAY_MS = 300;

/** How far behind the newest pose to draw, so there are always two to blend. Slower arrivals need a longer delay, or the
 *  view runs out of poses, stops, then jumps. A pause while the models run isn't slowness, so long gaps count for little. */
export function nextDelay(delay: number, gapMs: number) {
  const wanted = Math.min(MAX_DELAY_MS, Math.max(MIN_DELAY_MS, Math.min(gapMs, 200) * 2.2));
  return delay + (wanted - delay) * 0.05;
}

export class LiveSource implements SimSource {
  private samples: { at: number; v: number[] }[] = [];
  private stream: EventSource | null = null;
  private data: SceneData | null = null;
  private delay = MIN_DELAY_MS;
  constructor(private runId: string) {}

  async scene(stopped: () => boolean) {
    while (!stopped()) { // the sim exports its scene a moment after a run starts
      const res = await fetch(`${LIVE_URL}/scene.json`).catch(() => null);
      if (res?.ok) {
        const body = await res.json();
        if (body?.run_id === this.runId) { this.data = body; return body as SceneData; }
      }
      await new Promise((r) => setTimeout(r, 250));
    }
    return null;
  }
  asset(path: string) { return `${LIVE_URL}/scene/${path}?v=${this.data?.files[path] ?? ""}`; }
  start() {
    this.stream = new EventSource(`${LIVE_URL}/poses`);
    this.stream.onmessage = (e) => {
      const at = performance.now(), last = this.samples.at(-1);
      if (last) this.delay = nextDelay(this.delay, at - last.at);
      this.samples.push({ at, v: JSON.parse(e.data) });
      if (this.samples.length > 24) this.samples.shift();
    };
  }
  stop() { this.stream?.close(); }
  pose(now: number): PoseBlend | null {
    const list = this.samples;
    if (!list.length) return null;
    const t = now - this.delay;
    let i = list.length - 1;
    while (i > 0 && list[i - 1].at > t) i -= 1;
    const b = list[i], a = list[Math.max(i - 1, 0)];
    const span = b.at - a.at, k = span > 0 ? Math.min(1, Math.max(0, (t - a.at) / span)) : 1;
    return { a: a.v, b: b.v, aAt: 0, bAt: 0, k, stamp: i + k + b.at };
  }
}

/** A play head that works like a video element's, for a replay that isn't a video. */
export class ReplayClock {
  private base = 0;
  private startedAt = 0;
  private rate = 1;
  private running = false;
  constructor(public duration: number) {}

  get currentTime() {
    if (!this.running) return this.base;
    const t = this.base + ((performance.now() - this.startedAt) / 1000) * this.rate;
    if (t >= this.duration) { this.base = this.duration; this.running = false; return this.duration; }
    return t;
  }
  set currentTime(t: number) {
    this.base = Math.max(0, Math.min(this.duration, t));
    this.startedAt = performance.now();
  }
  get paused() { void this.currentTime; return !this.running; }
  get playbackRate() { return this.rate; }
  set playbackRate(r: number) { this.currentTime = this.currentTime; this.rate = r; }
  async play() {
    if (this.currentTime >= this.duration) this.base = 0;
    this.startedAt = performance.now();
    this.running = true;
  }
  pause() { this.base = this.currentTime; this.running = false; }
}

/** The body poses a run recorded: one float for the probe's force, then seven per moving body, 30 times a second. */
export class ReplaySource implements SimSource {
  private frames: Float32Array | null = null;
  private stride = 1;
  private data: SceneData | null = null;
  constructor(private assets: (path: string) => string, private clock: ReplayClock, private fps: number) {}

  async scene() {
    const [scene, poses] = await Promise.all([
      fetch(this.assets("scene/scene.json")).then((r) => r.json() as Promise<SceneData>),
      fetch(this.assets("poses.bin")).then((r) => r.arrayBuffer()),
    ]);
    this.data = scene;
    this.frames = new Float32Array(poses);
    this.stride = 1 + scene.moving.length * 7;
    return scene;
  }
  asset(path: string) { return this.assets(`scene/${path}`); }
  start() { /* nothing streams */ }
  stop() { /* nothing streams */ }
  private frameAt(t: number) {
    const count = this.frames ? Math.floor(this.frames.length / this.stride) : 0;
    return count ? Math.max(0, Math.min(count - 1, t * this.fps)) : -1;
  }
  force(t: number) {
    const f = this.frameAt(t);
    return f < 0 ? 0 : this.frames![Math.floor(f) * this.stride];
  }
  pose(): PoseBlend | null {
    const t = this.clock.currentTime, f = this.frameAt(t);
    if (f < 0 || !this.data) return null;
    const lo = Math.floor(f), hi = Math.min(lo + 1, Math.floor(this.frames!.length / this.stride) - 1);
    const view = (i: number) => this.frames!.subarray(i * this.stride + 1, (i + 1) * this.stride);
    return { a: view(lo), b: view(hi), aAt: lo, bAt: hi, k: f - lo, stamp: f };
  }
}
