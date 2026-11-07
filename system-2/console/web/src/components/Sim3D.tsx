import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import type { SceneData, SceneGeom, SimSource } from "../lib/simsource";

export interface SimFocus { target: string | null; label: string | null; verdict: string | null; force: number; limit: number; lcd: string[] }

/** Steps down until the view keeps up. 0 is the best a good GPU gets, and the last still runs without one. */
interface Tier { scale: number; shadow: number; shadowEvery: number; pbr: boolean }
const TIERS: Tier[] = [
  { scale: 2, shadow: 2048, shadowEvery: 1, pbr: true },
  { scale: 1.25, shadow: 1024, shadowEvery: 3, pbr: true },
  { scale: 1, shadow: 0, shadowEvery: 0, pbr: false },
  { scale: 0.66, shadow: 0, shadowEvery: 0, pbr: false },
];
const MAX_FPS = 60; // more only spends battery: the poses are blended, not faster
const SLOW_MS = 34, FAST_MS = 19, WINDOW = 30, RISE_AFTER = 8; // windows

const quat = (q: number[]) => new THREE.Quaternion(q[1], q[2], q[3], q[0]); // MuJoCo stores w first
const PASS = new THREE.Color("#1fa3ba"), FAIL = new THREE.Color("#e66a4a"), RUN = new THREE.Color("#e3ae3c");

function softwareRenderer(renderer: THREE.WebGLRenderer) {
  const gl = renderer.getContext();
  const info = gl.getExtension("WEBGL_debug_renderer_info");
  const name = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : "";
  return /swiftshader|llvmpipe|software|microsoft basic/i.test(name);
}

/** The real model, simplified, drawn here. Poses come from MuJoCo; nothing is animated by guesswork. It draws only when
 *  something has changed, and lowers its own quality until it keeps up, so it runs on whatever laptop it's given. */
export default function Sim3D({ source, focus, focusAt, onUnavailable }: { source: SimSource; focus?: SimFocus; focusAt?: () => SimFocus; onUnavailable: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  const tag = useRef<HTMLSpanElement>(null);
  const latest = useRef(focus);
  latest.current = focus;
  const latestAt = useRef(focusAt);
  latestAt.current = focusAt;
  const [free, setFree] = useState(false);
  const [ready, setReady] = useState(false);
  const refollow = useRef<() => void>(() => undefined);

  useEffect(() => {
    const el = host.current!;
    let stopped = false, frame = 0;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    } catch {
      onUnavailable();
      return;
    }
    const software = softwareRenderer(renderer);
    if (software) { // antialiasing is set at creation, and costs a CPU the most
      renderer.dispose();
      renderer = new THREE.WebGLRenderer({ antialias: false });
    }
    let tierIndex = software ? 3 : navigator.hardwareConcurrency <= 4 ? 1 : 0;
    let ceiling = tierIndex; // the best it may climb back to: where it started, or just below a tier it couldn't hold

    renderer.toneMapping = THREE.NeutralToneMapping; // keeps the arm its own yellow
    renderer.toneMappingExposure = 0.92;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.shadowMap.autoUpdate = false;
    el.prepend(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#15181b");
    scene.fog = new THREE.Fog("#15181b", 1.6, 3.4);
    const pmrem = new THREE.PMREMGenerator(renderer);
    const room = new RoomEnvironment();
    const envMap = software ? null : pmrem.fromScene(room, 0.04).texture;
    pmrem.dispose();
    const flat = new THREE.HemisphereLight("#ffffff", "#50483c", 1.5);
    scene.add(flat);

    const camera = new THREE.PerspectiveCamera(34, 1, 0.02, 12);
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 0.08;
    controls.maxDistance = 2.5;

    const key = new THREE.DirectionalLight("#fff4e6", 2.6);
    key.position.set(0.25, 0.75, 1.35);
    key.target.position.set(0.22, 0, 0.05);
    Object.assign(key.shadow.camera, { left: -0.6, right: 0.6, top: 0.6, bottom: -0.6, near: 0.3, far: 3 });
    key.shadow.bias = -0.0004;
    key.shadow.normalBias = 0.005; // the arm's fine detail shadows itself as speckle otherwise
    key.shadow.radius = 5;
    const rim = new THREE.DirectionalLight("#bcd3ff", 0.9);
    rim.position.set(0.9, -0.6, 0.7);
    scene.add(key, key.target, rim);

    const halo = new THREE.Mesh(new THREE.RingGeometry(0.0155, 0.0185, 56), new THREE.MeshBasicMaterial({ color: RUN, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false, toneMapped: false }));
    scene.add(halo);

    const bodies: THREE.Group[] = [];
    const named = new Map<string, THREE.Group>();
    let moving: number[] = [];
    let pad: THREE.MeshStandardMaterial | null = null;
    const standards = new Map<string, THREE.MeshStandardMaterial>();
    const lamberts = new Map<THREE.Material, THREE.MeshLambertMaterial>();
    const meshesBuilt: THREE.Mesh[] = [];
    const lcdCanvas = document.createElement("canvas");
    lcdCanvas.width = 480; lcdCanvas.height = 176;
    const lcdCtx = lcdCanvas.getContext("2d")!;
    const lcdTexture = new THREE.CanvasTexture(lcdCanvas);
    lcdTexture.colorSpace = THREE.SRGBColorSpace;
    let lcdShown: string | null = null;

    const home = new THREE.Vector3(0.14, 0, 0.1), desired = new THREE.Vector3(), probe = new THREE.Vector3(), step = new THREE.Vector3();
    const qa = new THREE.Quaternion(), qb = new THREE.Quaternion(), v3 = new THREE.Vector3(), v3b = new THREE.Vector3(), normal = new THREE.Vector3(0, 0, 1);
    let following = true, haloFade = 0, flashUntil = 0, lastVerdict: string | null = null, lastTarget: string | null = null;
    let prev = performance.now(), lastDraw = 0, lastStamp = -1, dirty = true, draws = 0, moved = false;
    let sum = 0, count = 0, goodWindows = 0;

    /** Asks for the look this tier allows. Changing the materials is the only part that costs anything. */
    function applyTier() {
      const tier = TIERS[tierIndex];
      renderer.setPixelRatio(Math.min(devicePixelRatio, tier.scale));
      resize();
      const shadow = tier.shadow > 0;
      key.castShadow = shadow;
      if (shadow && key.shadow.mapSize.x !== tier.shadow) {
        key.shadow.mapSize.set(tier.shadow, tier.shadow);
        key.shadow.map?.dispose();
        key.shadow.map = null;
      }
      scene.environment = tier.pbr ? envMap : null;
      scene.environmentIntensity = 0.42;
      flat.visible = !tier.pbr || !envMap;
      for (const mesh of meshesBuilt) {
        const standard = mesh.userData.standard as THREE.MeshStandardMaterial;
        mesh.material = tier.pbr ? standard : lambert(standard);
      }
      renderer.shadowMap.needsUpdate = shadow;
      el.dataset.tier = String(tierIndex);
      dirty = true;
    }

    function lambert(from: THREE.MeshStandardMaterial) {
      let made = lamberts.get(from);
      if (!made) {
        made = new THREE.MeshLambertMaterial({ color: from.color, map: from.map, emissive: from.emissive, emissiveMap: from.emissiveMap, emissiveIntensity: from.emissiveIntensity });
        lamberts.set(from, made);
      }
      return made;
    }

    const reframe = () => {
      controls.target.copy(home);
      camera.position.copy(home).add(new THREE.Vector3(-0.18, 0.68, 0.43));
      following = true;
      dirty = true;
      setFree(false);
    };
    refollow.current = reframe;
    controls.addEventListener("start", () => { following = false; setFree(true); });
    controls.addEventListener("change", () => { dirty = true; });

    function resize() {
      const w = Math.max(el.clientWidth, 1), h = Math.max(el.clientHeight, 1);
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      dirty = true;
    }
    const observer = new ResizeObserver(resize);
    observer.observe(el);

    const material = (data: SceneData, g: SceneGeom, textures: Map<number, THREE.Texture>) => {
      const m = g.mat >= 0 ? data.materials[g.mat] : null;
      const unique = g.name === "probe_pad"; // it glows on its own
      const cacheKey = `${g.mat}|${m ? "" : g.rgba.join()}`;
      const cached = standards.get(cacheKey);
      if (cached && !unique) return cached;
      const rgba = m ? m.rgba : g.rgba;
      const mat = new THREE.MeshStandardMaterial({ roughness: THREE.MathUtils.clamp(1 - (m?.shininess ?? 0.5) * 0.8, 0.14, 0.95), metalness: (m?.specular ?? 0) >= 0.9 ? 0.92 : 0.02 });
      mat.color.setRGB(rgba[0], rgba[1], rgba[2], THREE.SRGBColorSpace);
      if (m && m.tex >= 0) {
        if (m.name === "dev_lcd") {
          mat.map = lcdTexture; mat.emissive.set("#ffffff"); mat.emissiveMap = lcdTexture; mat.emissiveIntensity = 0.75; mat.roughness = 0.3;
        } else mat.map = textures.get(m.tex) ?? null;
      } else if (m && m.emission > 0) {
        mat.emissive.copy(mat.color); mat.emissiveIntensity = m.emission;
      }
      if (!unique) standards.set(cacheKey, mat);
      return mat;
    };

    const geometry = (g: SceneGeom, meshes: Map<number, THREE.BufferGeometry>) => {
      const [a, b, c] = g.size;
      switch (g.type) {
        case "mesh": return meshes.get(g.mesh)!;
        case "box": return new THREE.BoxGeometry(a * 2, b * 2, c * 2);
        case "sphere": return new THREE.SphereGeometry(a, 24, 14);
        case "cylinder": return new THREE.CylinderGeometry(a, a, b * 2, 32).rotateX(Math.PI / 2);
        case "capsule": return new THREE.CapsuleGeometry(a, b * 2, 8, 20).rotateX(Math.PI / 2);
        default: return null;
      }
    };

    async function load() {
      const data = await source.scene(() => stopped);
      if (!data || stopped) return;
      const meshes = new Map<number, THREE.BufferGeometry>();
      await Promise.all(Object.entries(data.meshes).map(async ([id, size]) => {
        const buffer = await (await fetch(source.asset(`mesh/${id}.bin`))).arrayBuffer();
        const inter = new THREE.InterleavedBuffer(new Float32Array(buffer, 0, size.verts * 6), 6);
        const geo = new THREE.BufferGeometry();
        geo.setAttribute("position", new THREE.InterleavedBufferAttribute(inter, 3, 0));
        geo.setAttribute("normal", new THREE.InterleavedBufferAttribute(inter, 3, 3));
        geo.setIndex(new THREE.BufferAttribute(new Uint32Array(buffer, size.verts * 24, size.tris * 3), 1));
        meshes.set(Number(id), geo);
      }));
      const texIds = Object.keys(data.files).filter((f) => f.startsWith("tex/")).map((f) => Number(f.slice(4, -4)));
      const textures = new Map<number, THREE.Texture>();
      const loader = new THREE.TextureLoader();
      loader.setCrossOrigin("anonymous");
      await Promise.all(texIds.map(async (id) => {
        const t = await loader.loadAsync(source.asset(`tex/${id}.jpg`));
        t.colorSpace = THREE.SRGBColorSpace;
        t.anisotropy = software ? 1 : Math.min(8, renderer.capabilities.getMaxAnisotropy());
        textures.set(id, t);
      }));
      if (stopped) return;
      data.bodies.forEach((b, i) => {
        const group = new THREE.Group();
        group.position.fromArray(b.pos);
        group.quaternion.copy(quat(b.quat));
        scene.add(group);
        bodies[i] = group;
        named.set(b.name, group);
      });
      const moves = new Set(data.moving);
      for (const g of data.geoms) {
        const geo = geometry(g, meshes);
        if (!geo) continue;
        const standard = material(data, g, textures);
        const mesh = new THREE.Mesh(geo, standard);
        mesh.userData.standard = standard;
        mesh.position.fromArray(g.pos);
        mesh.quaternion.copy(quat(g.quat));
        mesh.receiveShadow = true;
        mesh.castShadow = g.name !== "table" && !g.name.endsWith("_print") && g.name !== "display_1";
        if (!moves.has(g.body)) { mesh.updateMatrix(); mesh.matrixAutoUpdate = false; }
        bodies[g.body].add(mesh);
        meshesBuilt.push(mesh);
        if (g.name === "probe_pad") pad = standard;
      }
      moving = data.moving;
      const device = named.get("panel");
      if (device) home.copy(device.position).multiplyScalar(0.62); // between the arm's base and the device
      applyTier();
      reframe();
      setReady(true);
      source.start();
    }
    void load().catch(() => { if (!stopped) onUnavailable(); });

    const applyPoses = (now: number) => {
      const pose = source.pose(now);
      if (!pose || pose.stamp === lastStamp) return false;
      lastStamp = pose.stamp;
      const { a, b, k } = pose;
      moving.forEach((id, n) => {
        const o = n * 7, group = bodies[id];
        if (!group) return;
        v3.set(a[o], a[o + 1], a[o + 2]); v3b.set(b[o], b[o + 1], b[o + 2]);
        group.position.lerpVectors(v3, v3b, k);
        qa.set(a[o + 4], a[o + 5], a[o + 6], a[o + 3]); qb.set(b[o + 4], b[o + 5], b[o + 6], b[o + 3]);
        group.quaternion.slerpQuaternions(qa, qb, k);
      });
      return true;
    };

    const updateFocus = (now: number, dt: number) => {
      const f = latestAt.current?.() ?? latest.current;
      if (!f) return;
      const lines = f.lcd.join("\n");
      if (lines !== lcdShown) {
        lcdShown = lines;
        lcdCtx.fillStyle = "#0b2a16"; lcdCtx.fillRect(0, 0, lcdCanvas.width, lcdCanvas.height);
        lcdCtx.fillStyle = "#7dffa6"; lcdCtx.textBaseline = "middle"; lcdCtx.textAlign = "center";
        lcdCtx.font = '500 52px "JetBrains Mono", monospace';
        f.lcd.forEach((line, i) => lcdCtx.fillText(line, lcdCanvas.width / 2, lcdCanvas.height * ((i + 0.5) / Math.max(f.lcd.length, 1))));
        lcdTexture.needsUpdate = true;
        dirty = true;
      }
      if (f.verdict && f.verdict !== lastVerdict) flashUntil = now + 900;
      lastVerdict = f.verdict;
      if (f.target) lastTarget = f.target;
      const part = lastTarget ? named.get(lastTarget) : null;
      const flashing = now < flashUntil;
      const showing = !!f.target || flashing;
      const fade = haloFade + ((showing && part ? 1 : 0) - haloFade) * Math.min(1, dt * 9);
      if (Math.abs(fade - haloFade) > 0.002 || flashing) dirty = true;
      haloFade = fade;
      const ring = halo.material as THREE.MeshBasicMaterial;
      ring.opacity = haloFade * (flashing ? 1 : 0.8);
      ring.color.copy(flashing && f.verdict ? (f.verdict.endsWith("failed") ? FAIL : PASS) : RUN);
      halo.visible = haloFade > 0.01;
      if (part && halo.visible) {
        part.getWorldPosition(halo.position);
        const parent = named.get("panel");
        normal.set(0, 0, 1).applyQuaternion(parent ? parent.quaternion : part.quaternion);
        halo.position.addScaledVector(normal, 0.0012);
        halo.quaternion.setFromUnitVectors(v3.set(0, 0, 1), normal);
        halo.scale.setScalar(1 + (flashing ? (1 - (flashUntil - now) / 900) * 0.7 : Math.sin(now / 170) * 0.03));
      }
      if (pad) {
        const load = THREE.MathUtils.clamp(f.force / Math.max(f.limit, 1), 0, 1);
        const glowing = pad as THREE.MeshStandardMaterial;
        glowing.emissive.copy(RUN).lerp(FAIL, load);
        glowing.emissiveIntensity = load * 2.4;
        const flatPad = lamberts.get(glowing);
        if (flatPad) { flatPad.emissive.copy(glowing.emissive); flatPad.emissiveIntensity = glowing.emissiveIntensity; }
      }
      const label = tag.current;
      if (label) {
        if (part && haloFade > 0.15 && f.label) {
          v3.copy(halo.position).project(camera);
          label.style.opacity = String(haloFade);
          label.style.transform = `translate(${((v3.x + 1) / 2) * el.clientWidth + 18}px, ${((1 - v3.y) / 2) * el.clientHeight - 12}px)`;
          if (label.textContent !== f.label) label.textContent = f.label;
        } else if (label.style.opacity !== "0") label.style.opacity = "0";
      }
    };

    /** Watches real frame times, and moves a tier when the view can't keep up or has room to spare. */
    const govern = (elapsed: number) => {
      sum += elapsed; count += 1;
      if (count < WINDOW) return;
      const average = sum / count;
      sum = 0; count = 0;
      if (average > SLOW_MS && tierIndex < TIERS.length - 1) {
        ceiling = Math.max(ceiling, tierIndex + 1); // don't climb back to the tier it just couldn't hold
        tierIndex += 1;
        goodWindows = 0;
        applyTier();
      } else if (average < FAST_MS && tierIndex > ceiling) {
        goodWindows += 1;
        if (goodWindows >= RISE_AFTER) { tierIndex -= 1; goodWindows = 0; applyTier(); }
      } else goodWindows = 0;
    };

    const loop = (now: number) => {
      frame = requestAnimationFrame(loop);
      if (document.hidden || now - lastDraw < 1000 / MAX_FPS - 1.5) return;
      const dt = Math.min((now - prev) / 1000, 0.1);
      prev = now;
      moved = applyPoses(now);
      if (moved) dirty = true;
      updateFocus(now, dt);
      if (following) { // lean toward the probe, and keep the same view of the device
        const tip = named.get("probe");
        desired.copy(home);
        if (tip) { tip.getWorldPosition(probe); desired.lerp(probe, 0.3); }
        step.subVectors(desired, controls.target).multiplyScalar(Math.min(1, dt * 2.2));
        if (step.lengthSq() > 1e-10) {
          controls.target.add(step);
          camera.position.add(step);
          dirty = true;
        }
      }
      controls.update();
      if (!dirty) return;
      dirty = false;
      const tier = TIERS[tierIndex];
      if (tier.shadowEvery && moved && draws % tier.shadowEvery === 0) renderer.shadowMap.needsUpdate = true;
      renderer.render(scene, camera);
      if (lastDraw && now - lastDraw < 200) govern(now - lastDraw); // a longer gap was idling, not slowness
      lastDraw = now;
      draws += 1;
      if (draws % 15 === 0) el.dataset.draws = String(draws);
    };
    frame = requestAnimationFrame(loop);

    return () => {
      stopped = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      source.stop();
      controls.dispose();
      const done = new Set<{ dispose(): void }>();
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        if (m.isMesh) { done.add(m.geometry); done.add(m.material as THREE.Material); }
      });
      lamberts.forEach((l) => done.add(l));
      standards.forEach((s) => { done.add(s); if (s.map) done.add(s.map); });
      done.forEach((d) => d.dispose());
      lcdTexture.dispose();
      envMap?.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [source, onUnavailable]);

  return (
    <div className="sim3d" ref={host}>
      <span className="simlabel" ref={tag} />
      {!ready && <div className="simloading"><div className="sweep" /></div>}
      {free && <button type="button" className="linkbtn simfollow" onClick={() => refollow.current()}>Follow the probe</button>}
    </div>
  );
}
