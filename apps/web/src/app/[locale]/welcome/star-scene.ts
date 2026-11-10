/**
 * The Stravica sparkle (the logo's star) as a chrome 3D object with neon reflections.
 * Plain three.js, loaded on demand by <StarCanvas>. Renders only while on screen.
 */
import * as THREE from "three";
import { motionState } from "./state";

export type StarVariant = "hero" | "footer";

export interface StarHandle {
  dispose(): void;
}

/** A sphere pushed into a four-point sparkle: smooth closed surface, no seams, pointed tips. */
function sparkleGeometry(q = 0.52, thickness = 0.36) {
  const geo = new THREE.SphereGeometry(1, 220, 110);
  const pos = geo.attributes.position as THREE.BufferAttribute;
  const v = new THREE.Vector3();
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i);
    const a = Math.atan2(v.y, v.x);
    const s = Math.pow(Math.pow(Math.abs(Math.cos(a)), q) + Math.pow(Math.abs(Math.sin(a)), q), -1 / q);
    pos.setXYZ(i, v.x * s, v.y * s, v.z * thickness * (0.55 + 0.45 * s));
  }
  geo.computeVertexNormals();
  return geo;
}

/** A dark studio with neon light panels, baked into an environment map for the chrome to reflect. */
function neonEnvironment(renderer: THREE.WebGLRenderer, accent: THREE.Color) {
  const pmrem = new THREE.PMREMGenerator(renderer);
  const env = new THREE.Scene();
  env.add(new THREE.Mesh(new THREE.SphereGeometry(20, 32, 16), new THREE.MeshBasicMaterial({ color: 0x141118, side: THREE.BackSide })));
  const panel = (color: THREE.ColorRepresentation, k: number, w: number, h: number, p: [number, number, number]) => {
    const m = new THREE.Mesh(
      new THREE.PlaneGeometry(w, h),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(color).multiplyScalar(k), side: THREE.DoubleSide }),
    );
    m.position.set(...p);
    m.lookAt(0, 0, 0);
    env.add(m);
  };
  panel(accent, 4, 12, 2.4, [-7, 2.5, 3]);
  panel("#ffffff", 3, 6, 6, [5, 6, 6]);
  panel("#8f7bff", 2.4, 3, 11, [7, -1.5, -2]);
  panel(accent, 2.5, 14, 1, [0, -6.5, 2.5]);
  panel("#fff1e2", 1.6, 2.5, 12, [-4, 0, -8]);
  panel("#ffffff", 1.2, 20, 0.5, [0, 7, -3]);
  const rt = pmrem.fromScene(env, 0.035);
  env.traverse((o) => {
    if (o instanceof THREE.Mesh) {
      o.geometry.dispose();
      (o.material as THREE.Material).dispose();
    }
  });
  pmrem.dispose();
  return rt;
}

const easeOutBack = (x: number) => {
  const c1 = 1.5;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2);
};
const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

export function mountStar(canvas: HTMLCanvasElement, opts: { variant: StarVariant; accent: string; reduce: boolean }): StarHandle | null {
  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  } catch {
    return null;
  }
  const small = window.innerWidth < 768;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, small ? 1.5 : 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(0x000000, 0);

  const accent = new THREE.Color(opts.accent);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  camera.position.set(0, 0, 7);
  const envRT = neonEnvironment(renderer, accent);
  scene.environment = envRT.texture;

  const geo = sparkleGeometry();
  const chrome = new THREE.MeshPhysicalMaterial({
    color: 0xffffff, metalness: 1, roughness: 0.13, clearcoat: 1, clearcoatRoughness: 0.06,
    iridescence: 0.85, iridescenceIOR: 1.45, iridescenceThicknessRange: [180, 520],
  });
  const neon = new THREE.MeshPhysicalMaterial({
    color: accent, metalness: 0.25, roughness: 0.22, clearcoat: 1, clearcoatRoughness: 0.1, emissive: accent, emissiveIntensity: 0.45,
  });

  // Composition of the logo glyph: one big sparkle, two small ones to its upper side.
  const rig = new THREE.Group();
  const group = new THREE.Group();
  const main = new THREE.Mesh(geo, chrome);
  main.position.set(-0.22, -0.14, 0);
  const s1 = new THREE.Mesh(geo, neon);
  s1.scale.setScalar(0.27);
  s1.position.set(0.98, 0.98, 0.25);
  const s2 = new THREE.Mesh(geo, chrome);
  s2.scale.setScalar(0.15);
  s2.position.set(1.36, 0.36, -0.15);
  group.add(main, s1, s2);
  rig.add(group);
  scene.add(rig);

  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  const onMove = (e: PointerEvent) => {
    pointer.tx = (e.clientX / window.innerWidth) * 2 - 1;
    pointer.ty = (e.clientY / window.innerHeight) * 2 - 1;
  };
  window.addEventListener("pointermove", onMove, { passive: true });

  let fit = 1;
  let visH = 1;
  const resize = () => {
    const w = canvas.clientWidth || 1;
    const h = canvas.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    visH = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * camera.position.z;
    const visW = visH * camera.aspect;
    fit = opts.variant === "hero"
      ? Math.min((visH * 0.7) / 2.4, (visW * (camera.aspect < 0.9 ? 0.98 : 0.86)) / 2.8)
      : Math.min((visH * 0.95) / 2.4, (visW * 0.7) / 2.8);
    if (opts.reduce) draw(0);
  };

  let t = 0;
  const draw = (dt: number) => {
    t += dt;
    pointer.x += (pointer.tx - pointer.x) * Math.min(1, dt * 4);
    pointer.y += (pointer.ty - pointer.y) * Math.min(1, dt * 4);
    let intro = 1;
    let progress = 0;
    if (opts.variant === "hero") {
      intro = motionState.introAt < 0 ? 0 : clamp01((performance.now() - motionState.introAt) / 1900);
      progress = motionState.hero;
    }
    const e = opts.reduce ? 1 : easeOutBack(intro);
    const spin = opts.reduce ? 0.5 : t * 0.32;
    rig.scale.setScalar(fit * Math.max(0.0001, e) * (1 - progress * 0.28));
    rig.rotation.set(
      -pointer.y * 0.32 + Math.sin(t * 0.7) * 0.06,
      spin + pointer.x * 0.55 + (1 - e) * Math.PI * 1.4 + progress * Math.PI * 1.6,
      Math.sin(t * 0.45) * 0.05 + progress * 0.35,
    );
    if (opts.variant === "hero") rig.position.set(0, visH * (camera.aspect < 0.9 ? 0.2 : 0.07) + progress * visH * 0.3, 0);
    else rig.position.set(0, -visH * 0.18 + Math.sin(t * 0.8) * 0.05, 0);
    s1.rotation.z = t * 0.9;
    s1.position.y = 0.98 + Math.sin(t * 1.4) * 0.06;
    s2.rotation.z = -t * 1.3;
    s2.position.y = 0.36 + Math.sin(t * 1.1 + 1) * 0.05;
    renderer.render(scene, camera);
  };

  let raf = 0;
  let running = false;
  let last = 0;
  const frame = (now: number) => {
    const dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    draw(dt);
    raf = requestAnimationFrame(frame);
  };
  const start = () => {
    if (running || opts.reduce) return;
    running = true;
    last = performance.now();
    raf = requestAnimationFrame(frame);
  };
  const stop = () => {
    running = false;
    cancelAnimationFrame(raf);
  };

  let visible = false;
  const io = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    if (visible && !document.hidden) start();
    else stop();
  });
  io.observe(canvas);
  const onVis = () => (document.hidden || !visible ? stop() : start());
  document.addEventListener("visibilitychange", onVis);
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();
  draw(0);

  return {
    dispose() {
      stop();
      io.disconnect();
      ro.disconnect();
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("pointermove", onMove);
      geo.dispose();
      chrome.dispose();
      neon.dispose();
      envRT.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
}
