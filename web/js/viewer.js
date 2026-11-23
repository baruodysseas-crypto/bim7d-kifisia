import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export const KIND_COLORS = { footing: "#8d8d8d", slab: "#b9b9b9", column: "#9a9a9a", beam: "#a8a8a8", wall: "#e6dccb", window: "#7fb5d6", door: "#8a5a3c", roof: "#c8c0b4", stair: "#bdb3a2",
  railing: "#9fd0e6", pergola: "#8b5e3c", fence: "#3b3b3b", vegetation: "#4f8f3a", furniture: "#a47c55", site: "#c9d6b0", other: "#c0c0c0" };
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
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.localClippingEnabled = true;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.clip = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1e4);
    this.U = { uG: { value: new THREE.Vector2() }, uAmp: { value: new THREE.Vector2() }, uProfY: { value: new Float32Array(16) }, uProfV: { value: new Float32Array(16) }, uProfN: { value: 0 } };   // earthquake shaking (damage animation)
    this.beforeRender = null; this.afterRender = null; this.anim = null;
    this.meshes = []; this.byId = new Map(); this.elMap = {}; this.storeys = []; this.mode = "type"; this.data = null; this.sel = null;
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a93a0, 1.05));
    const d = new THREE.DirectionalLight(0xffffff, 1.25); d.position.set(60, 90, 40); this.scene.add(d);
    const d2 = new THREE.DirectionalLight(0xffffff, 0.35); d2.position.set(-50, 30, -60); this.scene.add(d2);
    this.grid = new THREE.GridHelper(200, 40, 0xb9c0cb, 0xd7dce3); this.scene.add(this.grid);
    this.root = null; this.onPick = null; this.bounds = null;
    this._down = null;
    const el = this.renderer.domElement;
    el.addEventListener("pointerdown", (e) => (this._down = [e.clientX, e.clientY]));
    el.addEventListener("pointerup", (e) => { if (this._down && Math.hypot(e.clientX - this._down[0], e.clientY - this._down[1]) < 4) this._pick(e); this._down = null; });
    const loop = (now) => { requestAnimationFrame(loop); if (this.host && this.host.isConnected) { if (this.beforeRender) this.beforeRender(now); this.controls.update(); this.renderer.render(this.scene, this.camera); if (this.afterRender) this.afterRender(); } };
    loop();
    new ResizeObserver(() => this.resize()).observe(document.body);
  }
  attach(host) { this.host = host; host.replaceChildren(this.renderer.domElement); this.resize(); }
  resize() { if (!this.host) return; const w = this.host.clientWidth || 600, h = this.host.clientHeight || 400; this.renderer.setSize(w, h, false); this.camera.aspect = w / h; this.camera.updateProjectionMatrix(); }

  async load(url, elMap, storeys) {
    this.elMap = elMap; this.storeys = storeys;
    if (this.root) { this.scene.remove(this.root); this.root.traverse((o) => { if (o.geometry) o.geometry.dispose(); }); }
    const gltf = await new GLTFLoader().loadAsync(url);
    this.root = gltf.scene; this.scene.add(this.root);
    this.meshes = []; this.byId = new Map();
    this.root.traverse((o) => {
      if (!o.isMesh) return;
      let n = o, id = null;
      while (n && !id) { if (elMap[n.name]) id = n.name; n = n.parent; }
      o.userData.eid = id;
      const kind = id ? elMap[id].kind : "other";
      o.material = new THREE.MeshStandardMaterial({ color: KIND_COLORS[kind] || "#c0c0c0", roughness: 0.85, metalness: 0.02, flatShading: true, side: THREE.DoubleSide, clippingPlanes: [this.clip], transparent: kind === "window", opacity: kind === "window" ? 0.5 : 1, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
      this._shakeable(o.material, kind);
      this.meshes.push(o);
      if (id) { if (!this.byId.has(id)) this.byId.set(id, []); this.byId.get(id).push(o); }
    });
    const box = new THREE.Box3().setFromObject(this.root);
    this.bounds = box;
    const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3());
    const r = Math.max(s.x, s.y, s.z);
    this.camera.position.set(c.x + r * 0.9, c.y + r * 0.7, c.z + r * 1.1);
    this.controls.target.copy(c); this.camera.near = r / 200; this.camera.far = r * 20; this.camera.updateProjectionMatrix();
    this.grid.position.y = box.min.y - 0.02;
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
      mat.opacity = e.kind === "window" ? 0.5 : 1; mat.transparent = e.kind === "window"; mat.depthWrite = true; mat.emissive?.set(0x000000);
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
