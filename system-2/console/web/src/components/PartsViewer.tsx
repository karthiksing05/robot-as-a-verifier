import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { partUrl, type CadModel } from "../lib/cad";

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const geometries = new Map<string, Promise<THREE.BufferGeometry>>();
const loader = new STLLoader();
function geometry(url: string) {
  if (!geometries.has(url)) {
    geometries.set(url, fetch(url).then((r) => r.arrayBuffer()).then((buf) => {
      const geo = loader.parse(buf);
      geo.computeVertexNormals();
      return geo;
    }));
  }
  return geometries.get(url)!;
}

/** One revision of an appliance's printed parts, as built. `marked` parts glow and the rest fade back. */
export function PartsViewer({ model, rev, marked, theme }: { model: CadModel; rev: string; marked: string[]; theme: string }) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<{ scene: THREE.Scene; root: THREE.Group; render: () => void; framed: boolean; frame: () => void } | null>(null);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);

  // The scene: made once, kept across revisions so the camera stays where the person left it.
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      setFailed(true);
      return;
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.NeutralToneMapping;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    el.prepend(renderer.domElement);

    const scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.add(new THREE.HemisphereLight("#ffffff", "#8a8478", 0.6));
    const key = new THREE.DirectionalLight("#fff6ea", 2.2);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.radius = 6;
    scene.add(key, key.target);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(4, 4), new THREE.ShadowMaterial({ opacity: 0.22 }));
    floor.receiveShadow = true;
    scene.add(floor);

    // Product frame: mm, +X toward the arm, +Z up.
    const root = new THREE.Group();
    root.scale.setScalar(0.001);
    scene.add(root);
    const camera = new THREE.PerspectiveCamera(28, 1, 0.005, 20);
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    let raf = 0;
    const render = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        if (controls.update()) render();
        renderer.render(scene, camera);
      });
    };
    controls.addEventListener("change", render);

    const frame = () => {
      const box = new THREE.Box3().setFromObject(root);
      if (box.isEmpty()) return;
      const centre = box.getCenter(new THREE.Vector3());
      const radius = box.getSize(new THREE.Vector3()).length() / 2;
      // Back off until every corner sits in the middle 80% of the frame, as in the project pictures.
      const toward = new THREE.Vector3(1, 0.62, 0.55).normalize();
      const corners = [0, 1, 2, 3, 4, 5, 6, 7].map((i) => new THREE.Vector3(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z));
      let d = radius;
      for (let k = 0; k < 200; k++) {
        camera.position.copy(centre).addScaledVector(toward, d);
        camera.lookAt(centre);
        camera.updateMatrixWorld();
        if (corners.every((c) => { const v = c.clone().project(camera); return Math.abs(v.x) < 0.8 && Math.abs(v.y) < 0.8; })) break;
        d *= 1.03;
      }
      controls.target.copy(centre);
      controls.minDistance = radius * 0.6;
      controls.maxDistance = radius * 8;
      floor.position.set(centre.x, centre.y, box.min.z);
      key.position.copy(centre).add(new THREE.Vector3(0.5, -0.25, 0.9).multiplyScalar(radius * 6));
      key.target.position.copy(centre);
      Object.assign(key.shadow.camera, { left: -radius * 2.5, right: radius * 2.5, top: radius * 2.5, bottom: -radius * 2.5, near: 0.01, far: radius * 14 });
      key.shadow.camera.updateProjectionMatrix();
      controls.update();
      render();
    };

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = el;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      render();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    resize();
    view.current = { scene, root, render, framed: false, frame };

    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      controls.dispose();
      root.traverse((o) => { if (o instanceof THREE.Mesh) (o.material as THREE.Material).dispose(); });
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      view.current = null;
    };
  }, []);

  // The backdrop follows the theme.
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    v.scene.background = new THREE.Color(css("--viewport") || "#d9d9d3");
    v.render();
  }, [theme, failed]);

  // The parts of this revision.
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    let stale = false;
    setLoading(true);
    const parts = Object.entries(model.parts[rev] ?? {});
    void Promise.all(parts.map(async ([name, part]) => ({ name, part, geo: await geometry(partUrl(model, rev, part.file)) }))).then((loaded) => {
      if (stale) return;
      v.root.children.slice().forEach((o) => { v.root.remove(o); ((o as THREE.Mesh).material as THREE.Material).dispose(); });
      loaded.forEach(({ name, part, geo }) => {
        const c = part.rgba ?? [0.86, 0.86, 0.84, 1];
        const mat = new THREE.MeshStandardMaterial({ color: new THREE.Color().setRGB(c[0], c[1], c[2], THREE.SRGBColorSpace), roughness: 0.62, metalness: 0.02, transparent: true, opacity: c[3] });
        mat.userData = { color: mat.color.clone(), opacity: c[3] };
        const mesh = new THREE.Mesh(geo, mat);
        mesh.name = name;
        mesh.castShadow = mesh.receiveShadow = true;
        v.root.add(mesh);
      });
      if (!v.framed) { v.frame(); v.framed = true; }
      setLoading(false);
      v.render();
    });
    return () => { stale = true; };
  }, [model, rev]);

  // Marked parts: accent, everything else faded so the change reads at a glance.
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    const accent = new THREE.Color(css("--accent-fill") || "#e3ae3c");
    v.root.children.forEach((o) => {
      const mat = (o as THREE.Mesh).material as THREE.MeshStandardMaterial;
      const on = marked.includes(o.name);
      mat.color.copy(on ? accent : mat.userData.color);
      mat.emissive.set(on ? accent : 0x000000).multiplyScalar(on ? 0.25 : 0);
      mat.opacity = marked.length && !on ? Math.min(0.28, mat.userData.opacity) : mat.userData.opacity;
      mat.depthWrite = !marked.length || on;
      (o as THREE.Mesh).castShadow = !marked.length || on;
    });
    v.render();
  }, [marked, loading, theme]);

  return (
    <div className="viewer partsviewer" ref={host} aria-label={`${model.title}, Rev ${rev}, 3D`}>
      <span className="tag">Rev {rev} · {Object.keys(model.parts[rev] ?? {}).length} printed parts</span>
      {failed
        ? <div className="empty" style={{ margin: 40, position: "relative" }}><p>This browser couldn't start 3D rendering.</p></div>
        : <span className="hint">{loading ? "Loading the parts" : "Drag to orbit, scroll to zoom"}</span>}
    </div>
  );
}
