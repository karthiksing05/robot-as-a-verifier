import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export interface ApplianceParams {
  button_clearance: number[];
  handle_style: string;
  latch_overlap: number;
  lcd_tilt: number;
  dome_preload: number[];
}

// A placeholder drawn from the documented size: 120 wide, 180 tall, 160 deep. Clearance is exaggerated to be visible.
const W = 120, H = 180, D = 160;
const CLEARANCE_SCALE = 16;
const BUTTON_R = 9;
const BUTTON_X = [-34, 0, 34];

const css = (name: string) => new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue(name).trim());
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Parameter changes ease into place, and the parts settle together when the bench opens. */
export function Viewer3D({ params, highlight, theme }: { params: ApplianceParams; highlight: string[]; theme: string }) {
  const host = useRef<HTMLDivElement>(null);
  const live = useRef({ params, highlight });
  const [failed, setFailed] = useState(false);
  live.current = { params, highlight };

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setFailed(true);
      return;
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, 1, 1, 3000);
    camera.position.set(250, 170, 480);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.target.set(0, 0, 0);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(200, 400, 300);
    scene.add(sun);

    const body = css("--surface"), ink = css("--ink"), line = css("--muted"), accent = css("--accent"), sunk = css("--sunk");
    const matBody = new THREE.MeshStandardMaterial({ color: body, roughness: 0.8 });
    const matDark = new THREE.MeshStandardMaterial({ color: sunk, roughness: 0.9 });
    const matPart = () => new THREE.MeshStandardMaterial({ color: line, roughness: 0.6 });
    const matLcd = new THREE.MeshStandardMaterial({ color: ink, roughness: 0.25 });
    const edgeMat = new THREE.LineBasicMaterial({ color: ink });

    const withEdges = (mesh: THREE.Mesh) => {
      mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry, 28), edgeMat));
      return mesh;
    };
    const root = new THREE.Group();
    scene.add(root);
    const front = D / 2;

    const shell = withEdges(new THREE.Mesh(new THREE.BoxGeometry(W, H, D), matBody));
    root.add(shell);

    const lcd = withEdges(new THREE.Mesh(new THREE.BoxGeometry(84, 32, 3), matLcd));
    const lcdPivot = new THREE.Group();
    lcdPivot.position.set(0, 58, front + 1);
    lcdPivot.add(lcd);
    root.add(lcdPivot);

    const buttons = BUTTON_X.map((x) => {
      const gap = new THREE.Mesh(new THREE.CircleGeometry(1, 48), matDark);
      gap.position.set(x, 16, front + 0.2);
      const capMat = matPart();
      const cap = withEdges(new THREE.Mesh(new THREE.CylinderGeometry(BUTTON_R, BUTTON_R, 5, 40).rotateX(Math.PI / 2), capMat));
      cap.position.set(x, 16, front + 2.5);
      root.add(gap, cap);
      return { gap, cap, capMat };
    });

    const door = withEdges(new THREE.Mesh(new THREE.BoxGeometry(92, 66, 2), matBody));
    door.position.set(0, -48, front + 1);
    root.add(door);

    const tabMat = matPart();
    const tab = withEdges(new THREE.Mesh(new THREE.BoxGeometry(8, 18, 10), tabMat));
    tab.position.set(36, -48, front + 6);
    const latchMat = matPart();
    const latchPlate = withEdges(new THREE.Mesh(new THREE.BoxGeometry(30, 22, 1.5), latchMat));
    latchPlate.position.set(26, -48, front + 2.5);
    const latchBar = new THREE.Mesh(new THREE.BoxGeometry(1, 3, 2), matDark);
    latchBar.position.set(0, -14, front + 1);
    root.add(tab, latchPlate, latchBar);

    const parts: { obj: THREE.Object3D; home: THREE.Vector3; order: number }[] = [lcdPivot, ...buttons.flatMap((b) => [b.cap]), door, tab, latchPlate].map((obj, order) => ({ obj, home: obj.position.clone(), order }));

    const state = {
      clearance: [...live.current.params.button_clearance],
      latchMix: live.current.params.handle_style === "tab" ? 0 : 1,
      overlap: live.current.params.latch_overlap,
      tilt: live.current.params.lcd_tilt,
      dome: [...live.current.params.dome_preload],
    };
    const damp = (current: number, target: number, dt: number) => current + (target - current) * (1 - Math.exp(-dt * 7));

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = el;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    resize();

    const opened = performance.now();
    const assemble = !reduced();
    let last = opened, frame = 0;
    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const { params: p, highlight: marks } = live.current;
      const flag = (name: string) => marks.some((m) => m.startsWith(name));

      buttons.forEach((b, i) => {
        state.clearance[i] = damp(state.clearance[i], p.button_clearance[i], dt);
        state.dome[i] = damp(state.dome[i], p.dome_preload[i], dt);
        const r = BUTTON_R + state.clearance[i] * CLEARANCE_SCALE;
        b.gap.scale.setScalar(r);
        b.cap.userData.dome = state.dome[i] * 6;
        b.capMat.color.lerp(flag(`button_clearance[${i}]`) || flag(`dome_preload[${i}]`) ? accent : line, 1 - Math.exp(-dt * 8));
      });
      state.latchMix = damp(state.latchMix, p.handle_style === "tab" ? 0 : 1, dt);
      tab.scale.set(1, 1, Math.max(0.001, 1 - state.latchMix));
      tab.visible = state.latchMix < 0.99;
      latchPlate.scale.setScalar(Math.max(0.001, state.latchMix));
      latchPlate.visible = state.latchMix > 0.01;
      const handleColor = flag("handle_style") ? accent : line;
      tabMat.color.copy(handleColor);
      latchMat.color.copy(handleColor);
      state.overlap = damp(state.overlap, p.latch_overlap, dt);
      latchBar.scale.x = 8 + state.overlap * 24;
      state.tilt = damp(state.tilt, p.lcd_tilt, dt);
      lcdPivot.rotation.x = -THREE.MathUtils.degToRad(state.tilt);

      const elapsed = now - opened;
      for (const part of parts) {
        const t = assemble ? THREE.MathUtils.clamp((elapsed - part.order * 55) / 620, 0, 1) : 1;
        const eased = 1 - (1 - t) ** 3;
        part.obj.position.copy(part.home);
        part.obj.position.z += (1 - eased) * 46 + (part.obj.userData.dome ?? 0);
      }
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        mesh.geometry?.dispose();
        const m = mesh.material;
        if (Array.isArray(m)) m.forEach((x) => x.dispose());
        else (m as THREE.Material | undefined)?.dispose();
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [theme]);

  return (
    <div className="viewer" ref={host}>
      <span className="tag">PLACEHOLDER MODEL / NOT ONSHAPE DATA</span>
      {failed
        ? <div className="empty" style={{ margin: 40, position: "relative" }}><p>This browser couldn't start 3D rendering. Parameters and the patch diff still work.</p></div>
        : <span className="hint">Drag to orbit, scroll to zoom. Clearance drawn ×{CLEARANCE_SCALE}.</span>}
    </div>
  );
}
