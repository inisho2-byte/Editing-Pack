// MIT. Owned draft object rig; local Three.js is an external MIT dependency.
// Defaults are example materials, not human-approved treatment.
import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

export { THREE };

/* ---------- timing / easing (pure functions of time; no clocks) ---------- */
export const clamp01 = x => Math.max(0, Math.min(1, x));
export const seg = (t, a, d) => {
  if (![t, a, d].every(Number.isFinite) || d < 0) throw new RangeError("invalid segment time");
  return d === 0 ? (t >= a ? 1 : 0) : clamp01((t - a) / d);
};
export const outCubic = x => 1 - Math.pow(1 - x, 3);
export const inCubic = x => x * x * x;
export const inOutSine = x => -(Math.cos(Math.PI * x) - 1) / 2;
export const inOutCubic = x => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
export const backOut = (x, s = 1.5) => 1 + (s + 1) * Math.pow(x - 1, 3) + s * Math.pow(x - 1, 2);
export const lerp = (a, b, k) => a + (b - a) * k;

export function mulberry32(a) {
  return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}

/* ---------- stage ---------- */
// floor: true on the grey stage (shadow catcher + contact pool); false when floating over footage.
export function createStage(canvas, { floor = true, fov = 26, width = 1080, height = 1920,
  environmentIntensity = 1.15, keyIntensity = 2.1, toneMapping = THREE.NeutralToneMapping } = {}) {
  if (![width, height].every(x => Number.isInteger(x) && x > 0) ||
      !Number.isFinite(fov) || fov <= 0 || fov >= 180 ||
      ![environmentIntensity, keyIntensity].every(x => Number.isFinite(x) && x >= 0)) {
    throw new RangeError("invalid stage dimensions, camera or light values");
  }
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(width, height, false);
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = toneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.VSMShadowMap;      // blurred, soft-edged studio shadow

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  const environmentTarget = pmrem.fromScene(room, 0.04);
  scene.environment = environmentTarget.texture;
  scene.environmentIntensity = environmentIntensity;
  room.dispose();
  pmrem.dispose();

  const camera = new THREE.PerspectiveCamera(fov, width / height, 0.1, 100);

  // High upper-left key (matches the example objects' light) so shadows pool under the object.
  const key = new THREE.DirectionalLight(0xfff4e8, keyIntensity);
  key.position.set(-3, 12, 5);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.radius = 16;
  key.shadow.blurSamples = 24;
  key.shadow.bias = -0.0006;
  key.shadow.normalBias = 0.02;
  Object.assign(key.shadow.camera, { left: -6, right: 6, top: 6, bottom: -4, near: 1, far: 30 });
  scene.add(key, key.target);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8984, 0.55));

  let ao = null, floorMesh = null;
  if (floor) {
    const f = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), new THREE.ShadowMaterial({ opacity: 0.16 }));
    f.rotation.x = -Math.PI / 2;
    f.receiveShadow = true;
    scene.add(f);
    floorMesh = f;
    ao = contactPool(3.6, 1.1);
    scene.add(ao);
  }
  const render = () => renderer.render(scene, camera);
  let disposed = false;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    // Dispose only this stage's resources. Caller meshes may share MAT or geometry.
    for (const mesh of [floorMesh, ao]) {
      if (!mesh) continue;
      scene.remove(mesh);
      mesh.geometry.dispose();
      if (mesh.material.map) mesh.material.map.dispose();
      mesh.material.dispose();
    }
    if (key.shadow.map) key.shadow.map.dispose();
    if (key.shadow.mapPass) key.shadow.mapPass.dispose();
    environmentTarget.dispose();
    scene.environment = null;
    renderer.dispose();
  };
  return { renderer, scene, camera, key, ao, render, dispose };
}

function radialTexture() {
  const c = document.createElement("canvas"); c.width = c.height = 256;
  const g = c.getContext("2d"), r = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  r.addColorStop(0, "rgba(0,0,0,0.55)"); r.addColorStop(0.45, "rgba(0,0,0,0.22)"); r.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = r; g.fillRect(0, 0, 256, 256);
  return new THREE.CanvasTexture(c);
}
// Soft dark pool on the floor right under an object (contact occlusion, no hard edge).
export function contactPool(w, d) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), new THREE.MeshBasicMaterial({ map: radialTexture(), transparent: true, depthWrite: false }));
  m.rotation.x = -Math.PI / 2;
  m.position.y = 0.002;
  return m;
}

/* ---------- materials ---------- */
// Seeded noise so surfaces read as card stock, not CG plastic. Deterministic across renders.
export function noiseTexture(seed, size, lo, hi, repeat = 3) {
  const rnd = mulberry32(seed), c = document.createElement("canvas"); c.width = c.height = size;
  const g = c.getContext("2d"), d = g.createImageData(size, size);
  for (let i = 0; i < d.data.length; i += 4) { const v = lo + rnd() * (hi - lo); d.data[i] = d.data[i + 1] = d.data[i + 2] = v; d.data[i + 3] = 255; }
  g.putImageData(d, 0, 0);
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(repeat, repeat);
  return t;
}
const grain = noiseTexture(7, 256, 110, 145);
export const MAT = {
  folderBack: new THREE.MeshPhysicalMaterial({ color: 0xE09A06, roughness: 0.38, clearcoat: 1, clearcoatRoughness: 0.12, bumpMap: grain, bumpScale: 0.6 }),
  folderFront: new THREE.MeshPhysicalMaterial({ color: 0xF7BA1E, roughness: 0.36, clearcoat: 1, clearcoatRoughness: 0.1, bumpMap: grain, bumpScale: 0.6 }),
  cardEdge: new THREE.MeshStandardMaterial({ color: 0xEDEBE6, roughness: 0.92 }),
  aluminium: new THREE.MeshPhysicalMaterial({ color: 0xC9CBCE, metalness: 1, roughness: 0.32, clearcoat: 0.3, bumpMap: noiseTexture(11, 256, 120, 136, 6), bumpScale: 0.25 }),
  blackShell: new THREE.MeshPhysicalMaterial({ color: 0x1A1A1C, metalness: 0.6, roughness: 0.42, clearcoat: 0.5, clearcoatRoughness: 0.3 }),
  rubberBlack: new THREE.MeshStandardMaterial({ color: 0x141415, roughness: 0.78 }),
  glossBlack: new THREE.MeshPhysicalMaterial({ color: 0x0E0E10, roughness: 0.25, clearcoat: 1, clearcoatRoughness: 0.08 }),
};

/* ---------- geometry helpers ---------- */
export function roundedRect(w, h, r) {
  const s = new THREE.Shape();
  s.moveTo(-w / 2 + r, 0); s.lineTo(w / 2 - r, 0); s.quadraticCurveTo(w / 2, 0, w / 2, r);
  s.lineTo(w / 2, h - r); s.quadraticCurveTo(w / 2, h, w / 2 - r, h);
  s.lineTo(-w / 2 + r, h); s.quadraticCurveTo(-w / 2, h, -w / 2, h - r);
  s.lineTo(-w / 2, r); s.quadraticCurveTo(-w / 2, 0, -w / 2 + r, 0);
  return s;
}
// Back panel with the File Explorer tab on its top left.
function backShape(w, h, r, tabW, tabH) {
  const s = new THREE.Shape(), L = -w / 2, R = w / 2;
  s.moveTo(L + r, 0); s.lineTo(R - r, 0); s.quadraticCurveTo(R, 0, R, r);
  s.lineTo(R, h - r); s.quadraticCurveTo(R, h, R - r, h);
  s.lineTo(L + tabW + tabH * 0.9, h);                       // slanted shoulder up to the tab
  s.quadraticCurveTo(L + tabW + tabH * 0.55, h, L + tabW + tabH * 0.4, h + tabH * 0.45);
  s.quadraticCurveTo(L + tabW + tabH * 0.2, h + tabH, L + tabW - tabH * 0.2, h + tabH);
  s.lineTo(L + r, h + tabH); s.quadraticCurveTo(L, h + tabH, L, h + tabH - r);
  s.lineTo(L, r); s.quadraticCurveTo(L, 0, L + r, 0);
  return s;
}
export const ext = (shape, depth, bevel, curveSegments = 18) =>
  new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel, bevelSegments: 3, curveSegments });
const shadowed = (...ms) => ms.forEach(m => { m.castShadow = true; m.receiveShadow = true; });

/* ---------- folder rig (glossy File Explorer folder made real) ---------- */
export const FOLDER = { W: 2.7, H: 1.9, FLAP: 1.62, GAP: 0.34, TH: 0.035 };
// hinge.rotation.x: 0 = closed, ~36° = open toward camera.
export function makeFolder() {
  const { W, H, FLAP, GAP, TH } = FOLDER;
  const group = new THREE.Group();
  const back = new THREE.Mesh(ext(backShape(W, H, 0.09, 0.95, 0.24), TH, 0.012), MAT.folderBack);
  back.position.z = -GAP / 2 - TH;
  const base = new THREE.Mesh(new THREE.BoxGeometry(W - 0.02, TH, GAP + TH), MAT.folderBack);
  base.position.set(0, TH / 2, 0);
  const hinge = new THREE.Group(); hinge.position.set(0, 0, GAP / 2);   // flap hinges on its bottom edge
  const flap = new THREE.Mesh(ext(roundedRect(W, FLAP, 0.09), TH, 0.012), MAT.folderFront);
  hinge.add(flap);
  group.add(back, base, hinge);
  shadowed(back, base, flap);
  return { group, hinge, back, base, flap };
}

/* ---------- cards (thick white matte cardstock, label printed in dark ink) ---------- */
export const CARD = { W: 2.3, H: 1.55, T: 0.028 };
export const LABELS = ["Captions", "B-roll", "SFX", "Music", "Color", "Tracking"];

// Paper face with fibre noise. draw(g, W, H) prints the content in ink on top.
export function paperTexture(seed, draw, w = CARD.W, h = CARD.H) {
  const W = 1024, H = Math.round(W * h / w), c = document.createElement("canvas"); c.width = W; c.height = H;
  const g = c.getContext("2d");
  g.fillStyle = "#F6F5F1"; g.beginPath(); g.roundRect(0, 0, W, H, 0.07 / w * W); g.fill();
  const rnd = mulberry32(100 + seed), d = g.getImageData(0, 0, W, H);
  for (let i = 0; i < d.data.length; i += 4) { if (!d.data[i + 3]) continue; const n = (rnd() - 0.5) * 9; d.data[i] += n; d.data[i + 1] += n; d.data[i + 2] += n; }
  g.putImageData(d, 0, 0);
  draw(g, W, H);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  return t;
}
export function labelDraw(label, idx) {
  return (g, W) => {
    g.fillStyle = "rgba(28,28,30,0.93)"; g.font = "700 84px ID"; g.textBaseline = "alphabetic";
    g.shadowColor = "rgba(28,28,30,0.35)"; g.shadowBlur = 1.2;
    g.fillText(label, 56, 98);
    g.font = "400 46px ID"; g.fillStyle = "rgba(28,28,30,0.42)"; g.textAlign = "right";
    g.fillText(String(idx + 1).padStart(2, "0"), W - 58, 92);
    g.textAlign = "left"; g.shadowBlur = 0;
  };
}
const cardGeo = ext(roundedRect(CARD.W, CARD.H, 0.07), CARD.T, 0.006);
const faceGeo = new THREE.PlaneGeometry(CARD.W, CARD.H); faceGeo.translate(0, CARD.H / 2, 0);
// Card origin = bottom-centre of its face; it stands in +y, faces +z. card.face.material.map is the print.
export function makeCard(seed, draw) {
  const group = new THREE.Group();
  const body = new THREE.Mesh(cardGeo, MAT.cardEdge);
  // alphaTest (not transparent) so the print stays in the glass transmission pass (loupe in a generic material scene)
  const face = new THREE.Mesh(faceGeo, new THREE.MeshStandardMaterial({ map: paperTexture(seed, draw), roughness: 0.88, alphaTest: 0.5 }));
  face.position.z = CARD.T + 0.0075;
  body.castShadow = true; body.receiveShadow = true; face.receiveShadow = true;
  group.add(body, face);
  group.userData = { face, seed, draw };
  return group;
}
// Reprint after fonts load (canvas text drawn before the font arrives falls back to a system face).
export function reprint(card) {
  const { face, seed, draw } = card.userData, m = face.material;
  m.map.dispose(); m.map = paperTexture(seed, draw); m.needsUpdate = true;
}

/* ---------- beat wiring: one paused timeline, seek-safe, fonts gate readiness ---------- */
// Word times in the markup are on the cut timeline; this returns the host slot's start.
export function hostStart(id, fallback) {
  const host = [...document.querySelectorAll(`[data-composition-id="${id}"]`)].find(e => e.hasAttribute("data-start"));
  const value = host ? Number(host.getAttribute("data-start")) : fallback;
  if (!Number.isFinite(value)) throw new TypeError("host start must be finite");
  return value;
}
export function wireBeat({ id, T0, DUR, renderAt, words, ready, onFonts,
  fontLoads = ["700 84px ID", "400 46px ID"],
  wordMotion = { blur: 14, y: 18, scale: 1.07, duration: 0.34, anticipation: 0.06, ease: "power2.out" } }) {
  if (!id || !Number.isFinite(T0) || !Number.isFinite(DUR) || DUR <= 0 || typeof renderAt !== "function") {
    throw new TypeError("wireBeat requires an id, finite start, positive duration and renderAt");
  }
  if (!wordMotion || ![wordMotion.blur, wordMotion.y, wordMotion.scale,
      wordMotion.duration, wordMotion.anticipation].every(Number.isFinite) ||
      wordMotion.blur < 0 || wordMotion.scale <= 0 || wordMotion.duration < 0 ||
      wordMotion.anticipation < 0 || typeof wordMotion.ease !== "string") {
    throw new TypeError("invalid selected word motion");
  }
  window.__timelines = window.__timelines || {};
  window.__hf = window.__hf || {};
  window.__hf.beatDisposers = window.__hf.beatDisposers || {};
  if (window.__hf.beatDisposers[id]) window.__hf.beatDisposers[id]();
  let active = true, assetsReady = false, requestedTime = 0;
  const tl = gsap.timeline({ paused: true });
  const S = { t: 0 };
  // Timeline declares duration; hf-seek alone owns canvas poses. GSAP rounds
  // tweened values, so rendering again from its proxy can overwrite an exact pose.
  tl.fromTo(S, { t: 0 }, { t: DUR, duration: DUR, ease: "none" }, 0);
  // kinetic words: blur in on their spoken time (draft motion option)
  (words ? document.querySelectorAll(words) : []).forEach(w => {
    const at = parseFloat(w.dataset.t) - T0;
    if (!Number.isFinite(at)) throw new TypeError("word requires finite cut-timeline data-t");
    const m = wordMotion;
    tl.fromTo(w, { opacity: 0, filter: `blur(${m.blur}px)`, y: m.y, scale: m.scale },
      { opacity: 1, filter: "blur(0px)", y: 0, scale: 1, duration: m.duration, ease: m.ease }, Math.max(0, at - m.anticipation));
  });
  const onSeek = e => {
    const g = e && e.detail && e.detail.time;
    if (Number.isFinite(g)) {
      requestedTime = Math.max(0, Math.min(DUR, g - hostStart(id, T0)));
      if (active && assetsReady) renderAt(requestedTime);
    }
  };
  window.addEventListener("hf-seek", onSeek);
  window.__timelines[id] = tl;
  window.__hf.buildReady = window.__hf.buildReady || {};
  const buildReady = Promise.all([...fontLoads.map(async font => { const faces = await document.fonts.load(font); if (!faces.length) throw new Error(`required font unavailable: ${font}`); return faces; }), ...(ready || [])])
    .then(() => { if (!active) return; if (onFonts) onFonts(); renderAt(DUR * 0.5); renderAt(requestedTime); assetsReady = true; });
  // Log rejection without converting the authoritative readiness promise to success.
  buildReady.catch(error => console.error(`3D beat ${id} failed readiness`, error));
  window.__hf.buildReady[id] = buildReady;
  window.__hf.beatDisposers[id] = () => {
    active = false;
    window.removeEventListener("hf-seek", onSeek);
    tl.kill();
    if (window.__timelines[id] === tl) delete window.__timelines[id];
    if (window.__hf.buildReady[id] === buildReady) delete window.__hf.buildReady[id];
    delete window.__hf.beatDisposers[id];
  };
  return tl;
}

export function loadTexture(url, { color = true } = {}) {
  return new Promise((res, reject) => new THREE.TextureLoader().load(url, t => { t.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace; t.anisotropy = 8; res(t); }, undefined, () => reject(new Error(`required texture failed: ${url}`))));
}
export function loadImage(url) {
  return new Promise((res, reject) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => reject(new Error(`required image failed: ${url}`)); i.src = url; });
}
