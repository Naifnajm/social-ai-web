/**
 * The Stravica logo ("Layers": three posts stacked in the publishing queue) as a glossy 3D object.
 * Plain three.js, loaded on demand by <StarCanvas>. Renders only while on screen.
 * The slabs sit apart in depth and spread further as the hero scrolls away.
 */
import * as THREE from "three";
import { motionState } from "./state";

export type StarVariant = "hero" | "footer";

export interface StarHandle {
  dispose(): void;
}

/** A rounded square slab (the logo's tile), centred on the origin, with soft bevelled edges. */
function slabGeometry(size = 1.6, radius = 0.43, depth = 0.16) {
  const h = size / 2, r = radius;
  const shape = new THREE.Shape();
  shape.moveTo(-h + r, -h);
  shape.lineTo(h - r, -h); shape.quadraticCurveTo(h, -h, h, -h + r);
  shape.lineTo(h, h - r); shape.quadraticCurveTo(h, h, h - r, h);
  shape.lineTo(-h + r, h); shape.quadraticCurveTo(-h, h, -h, h - r);
  shape.lineTo(-h, -h + r); shape.quadraticCurveTo(-h, -h, -h + r, -h);
  const geo = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: true, bevelThickness: 0.05, bevelSize: 0.05, bevelSegments: 6, curveSegments: 28 });
  geo.translate(0, 0, -depth / 2);
  return geo;
}

/** A pill (the "lines of a post" on the front slab). */
function pillGeometry(width: number, height: number, depth = 0.05) {
  const r = height / 2, w = width / 2 - r;
  const shape = new THREE.Shape();
  shape.absarc(w, 0, r, -Math.PI / 2, Math.PI / 2, false);
  shape.absarc(-w, 0, r, Math.PI / 2, -Math.PI / 2, false);
  const geo = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: true, bevelThickness: 0.015, bevelSize: 0.015, bevelSegments: 3, curveSegments: 20 });
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

  const geo = slabGeometry();
  const glossy = (color: THREE.ColorRepresentation, emissive = 0) => new THREE.MeshPhysicalMaterial({
    color, metalness: 0.35, roughness: 0.2, clearcoat: 1, clearcoatRoughness: 0.08, emissive: new THREE.Color(color), emissiveIntensity: emissive,
  });
  // The logo's three shades, back to front: deep rose, the accent pink, blush.
  const blush = new THREE.MeshPhysicalMaterial({
    color: "#ffd3e4", metalness: 0, roughness: 0.3, clearcoat: 1, clearcoatRoughness: 0.1, emissive: new THREE.Color("#ff8fbc"), emissiveIntensity: 0.42,
  });
  const mats = [glossy("#8f0d3f", 0.25), glossy(accent, 0.4), blush];
  const white = new THREE.MeshPhysicalMaterial({ color: 0xffffff, metalness: 0, roughness: 0.35, clearcoat: 1, emissive: 0xffffff, emissiveIntensity: 0.75 });

  // Composition of the logo: three tiles stepping down to the right, the front one carrying the lines of a post.
  const rig = new THREE.Group();
  const group = new THREE.Group();
  const STEP = 0.4;
  const layers = mats.map((m, i) => {
    const mesh = new THREE.Mesh(geo, m);
    mesh.position.set((i - 1) * STEP, (1 - i) * STEP, 0);
    return mesh;
  });
  const marks = [pillGeometry(0.56, 0.22), pillGeometry(1.0, 0.22)];
  const dot = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.17, 0.06, 40), white);
  dot.rotation.x = Math.PI / 2;
  dot.position.set(-0.36, 0.3, 0.13);
  const line1 = new THREE.Mesh(marks[0], white);
  line1.position.set(0.2, 0.3, 0.1);
  const line2 = new THREE.Mesh(marks[1], white);
  line2.position.set(0, -0.14, 0.1);
  layers[2].add(dot, line1, line2);
  group.add(...layers);
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
      ? Math.min((visH * 0.62) / 2.4, (visW * (camera.aspect < 0.9 ? 0.9 : 0.78)) / 2.8)
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
    // Face-on with a slow sway (a full spin would show the tiles edge-on half the time).
    const sway = opts.reduce ? -0.45 : -0.45 + Math.sin(t * 0.55) * 0.38;
    rig.scale.setScalar(fit * Math.max(0.0001, e) * (1 - progress * 0.28));
    rig.rotation.set(
      -0.2 - pointer.y * 0.3 + Math.sin(t * 0.7) * 0.05,
      sway + pointer.x * 0.5 + (1 - e) * Math.PI * 1.2 + progress * Math.PI * 0.9,
      Math.sin(t * 0.45) * 0.04 + progress * 0.25,
    );
    if (opts.variant === "hero") rig.position.set(0, visH * (camera.aspect < 0.9 ? 0.2 : 0.07) + progress * visH * 0.3, 0);
    else rig.position.set(0, -visH * 0.18 + Math.sin(t * 0.8) * 0.05, 0);
    // The tiles sit apart in depth, breathe a little, and spread as the page scrolls.
    const gap = (opts.reduce ? 0.5 : 0.5 + Math.sin(t * 0.9) * 0.06) * (0.35 + 0.65 * e) + progress * 0.9;
    layers.forEach((mesh, i) => {
      mesh.position.z = (i - 1) * gap;
      mesh.position.y = (1 - i) * STEP + (opts.reduce ? 0 : Math.sin(t * 1.1 + i * 0.9) * 0.035);
    });
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
      marks.forEach((g) => g.dispose());
      dot.geometry.dispose();
      mats.forEach((m) => m.dispose());
      white.dispose();
      envRT.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
}
