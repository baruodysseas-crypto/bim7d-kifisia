import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export const KIND_COLORS = { footing: "#8d8d8d", slab: "#b9b9b9", column: "#9a9a9a", beam: "#a8a8a8", wall: "#e6dccb", window: "#7fb5d6", door: "#8a5a3c", roof: "#c8c0b4", stair: "#d4a24c",
  railing: "#9fd0e6", pergola: "#8b5e3c", fence: "#3b3b3b", vegetation: "#4f8f3a", furniture: "#a47c55", site: "#c9d6b0", other: "#c0c0c0" };
// lower value = drawn in front where faces coincide (polygon offset)
const DEPTH_PRI = { window: 0, door: 0, railing: 0.5, furniture: 0.5, pergola: 0.8, fence: 0.8, roof: 1, wall: 1.4, stair: 1.6, beam: 2.4, column: 2.6, slab: 2.8, footing: 3.2, site: 3.6, vegetation: 0.5, other: 2 };
const GLASS_OPACITY = 0.38;
export const isGlass = (e) => !!e && (e.kind === "window" || (e.kind === "railing" && /glass|γυάλ/i.test(e.name || "")));
const STOREY_PAL = ["#6250d6", "#2a78d6", "#1baf7a", "#eda100", "#eb6834", "#e87ba4", "#008300", "#e34948"];
const RAMP = ["#2e9e44", "#f2c200", "#e8742a", "#c8281e", "#5b0e0e"].map((c) => new THREE.Color(c));

export function rampColor(v, vmax = 0.6) {
  const t = Math.min(Math.max(v / vmax, 0), 1) * (RAMP.length - 1);
  const i = Math.min(Math.floor(t), RAMP.length - 2);
  return RAMP[i].clone().lerp(RAMP[i + 1], t - i);
}

export class Viewer {
  constructor() {
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 2000);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.localClippingEnabled = true;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    // calm navigation: soft inertia, slower rotation, zoom towards the cursor, no camera below the ground
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    Object.assign(this.controls, { enableDamping: true, dampingFactor: 0.09, rotateSpeed: 0.55, zoomSpeed: 0.7, panSpeed: 0.7, zoomToCursor: true, screenSpacePanning: true,
      minPolarAngle: 0.02, maxPolarAngle: Math.PI * 0.49 });
    this.controls.addEventListener("start", () => (this._fly = null));            // the user takes over from a camera transition
    this.clip = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1e4);
    this.U = { uG: { value: new THREE.Vector2() }, uAmp: { value: new THREE.Vector2() }, uProfY: { value: new Float32Array(16) }, uProfV: { value: new Float32Array(16) }, uProfN: { value: 0 } };   // earthquake shaking (damage animation)
    this.beforeRender = null; this.afterRender = null; this.anim = null; this._fly = null;
    this.meshes = []; this.byId = new Map(); this.elMap = {}; this.storeys = []; this.mode = "type"; this.data = null; this.sel = null;
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a93a0, 0.95));
    const d = new THREE.DirectionalLight(0xffffff, 1.35); d.position.set(60, 90, 40); d.castShadow = true;
    d.shadow.mapSize.set(2048, 2048); d.shadow.bias = -0.0004; d.shadow.normalBias = 0.03; d.shadow.radius = 3;
    this.sun = d; this.scene.add(d); this.scene.add(d.target);
    const d2 = new THREE.DirectionalLight(0xffffff, 0.3); d2.position.set(-50, 30, -60); this.scene.add(d2);
    // no line grid (a dense grid shimmers when the camera moves): an invisible ground that only receives the shadows
    this.grid = new THREE.Mesh(new THREE.CircleGeometry(1, 72), new THREE.ShadowMaterial({ opacity: 0.16 }));
    this.grid.rotation.x = -Math.PI / 2; this.grid.receiveShadow = true; this.scene.add(this.grid);
    this.root = null; this.onPick = null; this.bounds = null;
    this._down = null;
    const el = this.renderer.domElement;
    el.addEventListener("pointerdown", (e) => (this._down = [e.clientX, e.clientY]));
    el.addEventListener("pointerup", (e) => { if (this._down && Math.hypot(e.clientX - this._down[0], e.clientY - this._down[1]) < 4) this._pick(e); this._down = null; });
    el.addEventListener("dblclick", () => { if (this.sel) this.focus(this.sel); });
    let last = performance.now();
    const loop = (now) => {
      requestAnimationFrame(loop);
      const dt = Math.min((now - last) / 1000, 0.1); last = now;
      if (!this.host || !this.host.isConnected) return;
      if (this.beforeRender) this.beforeRender(now);
      this._stepFly(dt);
      this.controls.update();
      this._fitDepth();
      this.renderer.render(this.scene, this.camera);
      if (this.afterRender) this.afterRender();
    };
    requestAnimationFrame(loop);
    new ResizeObserver(() => this.resize()).observe(document.body);
  }
  // near/far follow the distance to the target: more depth precision, so touching faces do not flicker
  _fitDepth() {
    const dist = this.camera.position.distanceTo(this.controls.target), r = this.radius || 50;
    const near = Math.max(0.05, dist / 120), far = dist + r * 6;
    if (Math.abs(near - this.camera.near) / this.camera.near > 0.05 || Math.abs(far - this.camera.far) / this.camera.far > 0.05) {
      this.camera.near = near; this.camera.far = far; this.camera.updateProjectionMatrix();
    }
  }
  // smooth camera transitions (ease in-out) to a position/target
  flyTo(pos, target, ms = 900) {
    this._fly = { p0: this.camera.position.clone(), t0: this.controls.target.clone(), p1: pos.clone(), t1: target.clone(), u: 0, dur: ms / 1000 };
  }
  _stepFly(dt) {
    const f = this._fly; if (!f) return;
    f.u = Math.min(1, f.u + dt / f.dur);
    const e = f.u < 0.5 ? 4 * f.u ** 3 : 1 - (-2 * f.u + 2) ** 3 / 2;
    this.camera.position.lerpVectors(f.p0, f.p1, e); this.controls.target.lerpVectors(f.t0, f.t1, e);
    if (f.u >= 1) this._fly = null;
  }
  // preset views around the building: home (3/4 view), front, side, top
  view(name) {
    const b = this.buildingBox || this.bounds; if (!b) return;
    const c = b.getCenter(new THREE.Vector3()), s = b.getSize(new THREE.Vector3()), r = Math.max(s.x, s.y, s.z);
    const t = c.clone();
    const P = { home: [0.95, 0.65, 1.15], front: [0, 0.18, 1.9], side: [1.9, 0.18, 0], back: [0, 0.25, -1.9], top: [0.001, 2.3, 0.001] }[name] || [0.95, 0.65, 1.15];
    this.flyTo(new THREE.Vector3(c.x + r * P[0], c.y + r * P[1], c.z + r * P[2]), t);
  }
  focus(id) {
    const ms = this.byId.get(id); if (!ms || !ms.length) return;
    const b = new THREE.Box3(); ms.forEach((m) => b.expandByObject(m));
    const c = b.getCenter(new THREE.Vector3()), r = Math.max(b.getSize(new THREE.Vector3()).length(), 2);
    const dir = this.camera.position.clone().sub(this.controls.target).normalize();
    this.flyTo(c.clone().add(dir.multiplyScalar(r * 1.6)), c, 800);
  }
  attach(host) { this.host = host; host.replaceChildren(this.renderer.domElement); this.resize(); }
  resize() { if (!this.host) return; const w = this.host.clientWidth || 600, h = this.host.clientHeight || 400; this.renderer.setSize(w, h, false); this.camera.aspect = w / h; this.camera.updateProjectionMatrix(); }

  async load(url, elMap, storeys) {
    this.elMap = elMap; this.storeys = storeys;
    if (this.root) { this.scene.remove(this.root); this.root.traverse((o) => { if (o.geometry) o.geometry.dispose(); }); }
    const gltf = await new GLTFLoader().loadAsync(url);
    this.root = gltf.scene; this.scene.add(this.root);
    this.meshes = []; this.byId = new Map();
    let n0 = 0;
    this.root.traverse((o) => {
      if (!o.isMesh) return;
      let n = o, id = null;
      while (n && !id) { if (elMap[n.name]) id = n.name; n = n.parent; }
      o.userData.eid = id;
      const kind = id ? elMap[id].kind : "other";
      // depth priority: where two elements share a face, the finish (glass, doors, walls) always wins over the structure behind it,
      // and within the same kind a fixed per-element order decides; so coplanar faces never flicker or "bleed" into each other
      const pri = (DEPTH_PRI[kind] ?? 2) + ((n0++ % 4) * 0.15);
      const glass = isGlass(id ? elMap[id] : null);
      o.material = new THREE.MeshStandardMaterial({ color: KIND_COLORS[kind] || "#c0c0c0", roughness: glass ? 0.15 : 0.85, metalness: glass ? 0.1 : 0.02, flatShading: true, side: THREE.DoubleSide, clippingPlanes: [this.clip],
        transparent: glass, opacity: glass ? GLASS_OPACITY : 1, depthWrite: !glass, polygonOffset: true, polygonOffsetFactor: pri, polygonOffsetUnits: pri * 2 });
      o.renderOrder = glass ? 2 : 0;
      o.castShadow = !glass && kind !== "site"; o.receiveShadow = true;
      this._shakeable(o.material, kind);
      this.meshes.push(o);
      if (id) { if (!this.byId.has(id)) this.byId.set(id, []); this.byId.get(id).push(o); }
    });
    const box = new THREE.Box3().setFromObject(this.root);
    this.bounds = box;
    const bb = new THREE.Box3();                                  // the building itself (without the plot and the planting) frames the views
    for (const m of this.meshes) { const k = (elMap[m.userData.eid] || {}).kind; if (!["site", "vegetation", "fence", "excavation", "other"].includes(k)) bb.expandByObject(m); }
    this.buildingBox = bb.isEmpty() ? box : bb;
    const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3());
    const r = Math.max(s.x, s.y, s.z); this.radius = r;
    const bc = this.buildingBox.getCenter(new THREE.Vector3()), br = Math.max(...this.buildingBox.getSize(new THREE.Vector3()).toArray());
    this.camera.position.set(bc.x + br * 0.95, bc.y + br * 0.65, bc.z + br * 1.15);
    this.controls.target.copy(bc); this.controls.minDistance = 1.5; this.controls.maxDistance = r * 3.5; this._fitDepth();
    this.grid.position.set(c.x, box.min.y - 0.03, c.z); this.grid.scale.setScalar(r * 8);
    // sun shadow fitted to the model
    const sc = this.sun.shadow.camera, half = r * 0.75;
    this.sun.position.set(c.x + r * 0.9, c.y + r * 1.4, c.z + r * 0.6); this.sun.target.position.copy(c);
    Object.assign(sc, { left: -half, right: half, top: half, bottom: -half, near: 0.5, far: r * 4 }); sc.updateProjectionMatrix();
    this.setClip(null); this.setMode("real");
    return { min: box.min.y, max: box.max.y };
  }

  // vertex-shader shear: the building sways with the ground motion; site and excavation outline stay still
  _shakeable(mat, kind) {
    const shake = { value: kind === "site" || kind === "excavation" || kind === "vegetation" || kind === "fence" ? 0 : 1 }, U = this.U;
    mat.onBeforeCompile = (sh) => {
      Object.assign(sh.uniforms, { uG: U.uG, uAmp: U.uAmp, uProfY: U.uProfY, uProfV: U.uProfV, uProfN: U.uProfN, uShake: shake });
      sh.vertexShader = sh.vertexShader.replace("#include <common>", "#include <common>\nuniform vec2 uG; uniform vec2 uAmp; uniform float uProfY[16]; uniform float uProfV[16]; uniform int uProfN; uniform float uShake;")
        .replace("#include <begin_vertex>", `#include <begin_vertex>
        if (uShake > 0.5 && uProfN > 1) {
          float wy = (modelMatrix * vec4(transformed, 1.0)).y, f = 0.0;
          for (int i = 0; i < 15; i++) { if (i < uProfN - 1 && wy >= uProfY[i]) f = mix(uProfV[i], uProfV[i + 1], clamp((wy - uProfY[i]) / max(uProfY[i + 1] - uProfY[i], 0.001), 0.0, 1.0)); }
          vec2 dd = uG + uAmp * f; transformed += vec3(dd.x, 0.0, dd.y);
        }`);
    };
    mat.customProgramCacheKey = () => "shake1";
  }
  setClip(y) { this.clip.constant = y === null ? 1e4 : y; }
  setStorey(id) { for (const m of this.meshes) { const e = this.elMap[m.userData.eid]; m.visible = !id || (e && e.storey === id); } }
  _base(m) { const id = m.userData.eid, e = this.elMap[id] || { kind: "other" }; return e; }
  setMode(mode, data) {
    this.mode = mode; this.data = data || null;
    const idx = Object.fromEntries(this.storeys.map((s, i) => [s.id, i]));
    for (const m of this.meshes) {
      const e = this._base(m), mat = m.material;
      const glass = isGlass(e);
      mat.opacity = glass ? GLASS_OPACITY : 1; mat.transparent = glass; mat.depthWrite = !glass; mat.emissive?.set(0x000000);
      let col = KIND_COLORS[e.kind] || "#c0c0c0";
      if (mode === "real" || (mode === "4d" && e.color)) col = e.color || col;
      if (mode === "storey") col = e.storey != null ? STOREY_PAL[idx[e.storey] % STOREY_PAL.length] : "#c9d6b0";
      else if (mode === "4d" && data) {
        const st = data[m.userData.eid] || "done";
        if (st === "todo") { col = "#9aa5b4"; mat.transparent = true; mat.opacity = 0.07; mat.depthWrite = false; }
        else if (st === "active") col = "#eb6834";
      } else if (mode === "damage" && data) {
        const v = data[m.userData.eid]; col = v === undefined || (e.kind === "site") ? "#d5d9df" : rampColor(v);
        if (v === undefined || v === 0) { if (e.kind !== "site") col = "#3e9f4b"; }
        if (e.kind === "site" || e.kind === "vegetation") { mat.transparent = true; mat.opacity = 0.35; }
      }
      mat.color.set(col);
    }
    if (this.sel) this._hi(this.sel, true);
  }
  _hi(id, on) { for (const m of this.byId.get(id) || []) m.material.emissive?.set(on ? 0x2a78d6 : 0x000000); }
  select(id) { if (this.sel) this._hi(this.sel, false); this.sel = id; if (id) this._hi(id, true); }
  _pick(ev) {
    const r = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    const rc = new THREE.Raycaster(); rc.setFromCamera(ndc, this.camera);
    const hits = rc.intersectObjects(this.meshes.filter((m) => m.visible && m.material.opacity > 0.2), false).filter((h) => { const c = this.clip; return c.distanceToPoint(h.point) >= 0; });
    const id = hits.length ? hits[0].object.userData.eid : null;
    this.select(id); if (this.onPick) this.onPick(id);
  }
}
