// Damage animation + video recording for the 3D viewer.
// Plays a schematic time history of a hazard scenario on the BIM model (earthquake shaking with progressive damage,
// internal fire, wildfire front, flood) and can record it, with an information overlay, to a video file.
import * as THREE from "three";
import { KIND_COLORS, rampColor } from "./viewer.js";
import { S, T, fmt, eur, pct } from "./util.js";

const clamp = (x, a = 0, b = 1) => Math.min(Math.max(x, a), b);
const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
const lerp = (a, b, t) => a + (b - a) * t;
function rng(seed) { let s = seed >>> 0; return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296); }
const GREEN = new THREE.Color("#3e9f4b");

function sprite() {
  const c = document.createElement("canvas"); c.width = c.height = 64;
  const g = c.getContext("2d"), r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(0.55, "rgba(255,255,255,.85)"); r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r; g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}

// ---------------------------------------------------------------- particles (flames, smoke, embers, dust)
class Particles {
  constructor(scene, n, { size = 1.5, additive = false, tex, buoy = 0, drag = 0, color }) {
    this.n = n; this.buoy = buoy; this.drag = drag; this.colorFn = color; this.next = 0; this.carry = 0;
    this.pos = new Float32Array(n * 3).fill(-1e4); this.col = new Float32Array(n * 4); this.vel = new Float32Array(n * 3); this.age = new Float32Array(n).fill(1e9); this.life = new Float32Array(n).fill(1);
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(this.pos, 3)); g.setAttribute("color", new THREE.BufferAttribute(this.col, 4));
    this.mat = new THREE.PointsMaterial({ size, map: tex, vertexColors: true, transparent: true, depthWrite: false, sizeAttenuation: true, blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending });
    this.pts = new THREE.Points(g, this.mat); this.pts.frustumCulled = false; scene.add(this.pts); this.geo = g;
  }
  emit(x, y, z, vx, vy, vz, life) {
    const i = this.next; this.next = (this.next + 1) % this.n;
    this.pos[i * 3] = x; this.pos[i * 3 + 1] = y; this.pos[i * 3 + 2] = z; this.vel[i * 3] = vx; this.vel[i * 3 + 1] = vy; this.vel[i * 3 + 2] = vz; this.age[i] = 0; this.life[i] = life;
  }
  rate(perSec, dt, fn) { this.carry += perSec * dt; while (this.carry >= 1) { this.carry -= 1; fn(); } }
  update(dt) {
    const c = new THREE.Color();
    for (let i = 0; i < this.n; i++) {
      if (this.age[i] > this.life[i]) { this.col[i * 4 + 3] = 0; this.pos[i * 3 + 1] = -1e4; continue; }
      this.age[i] += dt;
      const u = clamp(this.age[i] / this.life[i]);
      this.vel[i * 3 + 1] += this.buoy * dt; const dg = Math.exp(-this.drag * dt);
      this.vel[i * 3] *= dg; this.vel[i * 3 + 2] *= dg;
      this.pos[i * 3] += this.vel[i * 3] * dt; this.pos[i * 3 + 1] += this.vel[i * 3 + 1] * dt; this.pos[i * 3 + 2] += this.vel[i * 3 + 2] * dt;
      const a = this.colorFn(u, c); this.col[i * 4] = c.r; this.col[i * 4 + 1] = c.g; this.col[i * 4 + 2] = c.b; this.col[i * 4 + 3] = a;
    }
    this.geo.attributes.position.needsUpdate = true; this.geo.attributes.color.needsUpdate = true;
  }
  clear() { this.age.fill(1e9); this.pos.fill(-1e4); this.col.fill(0); this.geo.attributes.position.needsUpdate = true; this.geo.attributes.color.needsUpdate = true; }
  dispose(scene) { scene.remove(this.pts); this.geo.dispose(); this.mat.dispose(); }
}
const fireCol = (u, c) => { if (u < 0.25) c.setRGB(1, lerp(0.7, 0.5, u / 0.25), lerp(0.22, 0.08, u / 0.25)); else c.setRGB(lerp(0.98, 0.45, (u - 0.25) / 0.75), lerp(0.5, 0.06, (u - 0.25) / 0.75), 0.03); return Math.pow(1 - u, 0.7); };
const smokeCol = (u, c) => { c.setRGB(0.28 + 0.2 * u, 0.28 + 0.2 * u, 0.3 + 0.2 * u); return Math.sin(Math.PI * Math.min(1, u * 1.25)) * 0.55 * (1 - u * 0.4); };
const emberCol = (u, c) => { c.setRGB(1, lerp(0.62, 0.25, u), 0.04); return 1 - u * u; };
const dustCol = (u, c) => { c.setRGB(0.72, 0.67, 0.6); return Math.sin(Math.PI * clamp(u * 1.1)) * 0.5; };

// ---------------------------------------------------------------- the animation
export class DamageAnim {
  constructor(viewer, els, project) {
    this.v = viewer; this.els = els; this.project = project; this.t = 0; this.dur = 10; this.playing = false; this.speed = 1; this.orbit = false;
    this.exag = 8; this.type = null; this.onEnd = null; this.onTick = null; this.active = false; this.last = null; this.parts = []; this.extra = [];
    this.tex = sprite();
    viewer.anim = this;
  }

  // ---- set up one scenario
  setup(meta, damage, label) {
    this.reset();
    this.meta = meta; this.final = damage || {}; this.label = label || ""; this.type = meta.type; this.active = true;
    const v = this.v;
    this.items = v.meshes.map((m) => {
      const id = m.userData.eid, e = this.els[id] || { kind: "other" }, bb = new THREE.Box3().setFromObject(m);
      return { m, id, kind: e.kind, storey: e.storey, bb, c: bb.getCenter(new THREE.Vector3()), f: this.final[id] ?? 0, base: new THREE.Color(KIND_COLORS[e.kind] || "#c0c0c0"), glass: e.kind === "window" };
    });
    this.bld = this.items.filter((i) => !["site", "excavation", "vegetation", "fence"].includes(i.kind));
    const bb = new THREE.Box3(); this.bld.forEach((i) => bb.union(i.bb)); this.bb = bb; this.cen = bb.getCenter(new THREE.Vector3()); this.size = bb.getSize(new THREE.Vector3());
    this.roofY = bb.max.y;
    this.storeysAbove = this.project.storeys.filter((s) => s.elevation_m >= -0.01).sort((a, b) => a.elevation_m - b.elevation_m);
    const fn = { seismic: this._setupSeismic, fire_internal: this._setupFire, wildfire: this._setupWild, flood: this._setupFlood }[this.type];
    if (fn) fn.call(this);
    this.seek(0);
  }

  _newParticles(n, o) { const p = new Particles(this.v.scene, n, { tex: this.tex, ...o }); this.parts.push(p); return p; }
  _newMesh(geo, mat) { const m = new THREE.Mesh(geo, mat); this.v.scene.add(m); this.extra.push(m); return m; }

  // ---- seismic
  _setupSeismic() {
    const m = this.meta, pga = m.pga_g || 0.24, ms = m.Ms || 6;
    this.shakeStart = 1.0; this.shakeDur = clamp(6 + (ms - 5) * 4, 6, 14); this.dur = this.shakeStart + this.shakeDur + 3.5;
    const struct = this.bld.filter((i) => ["column", "beam", "slab", "wall"].includes(i.kind));
    this.meanDmg = struct.length ? struct.reduce((s, i) => s + i.f, 0) / struct.length : 0;
    this.drift = clamp(0.006 * (pga / 0.24), 0.002, 0.04) * (1 + 2 * this.meanDmg);
    // storey drift profile: soft / damaged storeys move more
    const ids = new Map((m.storeys || []).map((s) => [s.id, s]));
    const above = this.storeysAbove, ys = [], vs = [0]; let acc = 0;
    above.forEach((s, i) => { ys.push(s.elevation_m); const w = 1 + 1.5 * ((ids.get(s.id) || {}).mean_grade || 0); acc += w; vs.push(acc); });
    ys.push(this.roofY);
    const n = Math.min(ys.length, 16), U = this.v.U;
    for (let i = 0; i < 16; i++) { U.uProfY.value[i] = i < n ? ys[i] : ys[n - 1] + i; U.uProfV.value[i] = i < n ? vs[i] / acc : 1; }
    U.uProfN.value = n;
    // normalised envelope energy table
    this.cumTab = []; let a = 0; for (let i = 0; i <= 200; i++) { const e = this._env(i / 200); a += e * e; this.cumTab.push(a); } this.cumTab = this.cumTab.map((x) => x / a);
    const r = rng(7); this.ph = [[0, 1].map(() => [0, 1, 2, 3].map(() => r() * 6.28)), [0, 1].map(() => [0, 1, 2, 3].map(() => r() * 6.28))];
    this.dust = this._newParticles(1400, { size: 2.6, tex: this.tex, buoy: 0.25, drag: 0.8, color: dustCol });
    this._setupCollapse();
  }

  // ---- collapse: when the building does not withstand the earthquake (probability of grade D5 from the scenario)
  //   P(D5) >= 50 %  -> total collapse: the critical storey gives way and the storeys above pancake onto it
  //   P(D5) >= 20 %  -> partial collapse: the critical storey is crushed, the mass above drops and tilts
  _setupCollapse() {
    const m = this.meta, pc = m.p_collapse_d5 || 0;
    this.collapse = pc >= 0.5 ? "total" : pc >= 0.2 ? "partial" : null; this.col = null;
    if (!this.collapse) return;
    const st = this.storeysAbove; if (!st.length) { this.collapse = null; return; }
    const hOf = (i) => st[i].height_m || ((st[i + 1] ? st[i + 1].elevation_m : this.roofY) - st[i].elevation_m) || 3;
    const grade = new Map((m.storeys || []).map((s) => [s.id, s.mean_grade || 0]));
    let k = 0; st.forEach((s, i) => { if ((grade.get(s.id) || 0) > (grade.get(st[k].id) || 0)) k = i; });
    const r = rng(11), dir = r() < 0.5 ? -1 : 1, axis = r() < 0.5 ? "x" : "z";
    const sq = 0.14, base = st[k].elevation_m;
    const idx = new Map(st.map((s, i) => [s.id, i]));
    let lower = base; const newBase = [];                                    // new base level of each storey after pancaking
    st.forEach((s, i) => { if (i < k) newBase.push(s.elevation_m); else { newBase.push(lower); lower += (this.collapse === "total" || i === k ? sq : 1) * hOf(i); } });
    const pivot = new THREE.Vector3(axis === "x" ? (dir > 0 ? this.bb.max.x : this.bb.min.x) : this.cen.x, base, axis === "z" ? (dir > 0 ? this.bb.max.z : this.bb.min.z) : this.cen.z);
    const items = [];
    this.v.scene.updateMatrixWorld(true);
    for (const it of this.bld) {
      const j = idx.get(it.storey); if (j === undefined || j < k) continue;
      const e = st[j].elevation_m, crushed = this.collapse === "total" || j === k;
      const P = it.m.parent ? it.m.parent.matrixWorld.clone() : new THREE.Matrix4();
      const out = new THREE.Vector3(it.c.x - this.cen.x, 0, it.c.z - this.cen.z); if (out.lengthSq() > 1e-6) out.normalize();
      const fall = e - newBase[j];
      items.push({ it, j, e, s: crushed ? sq : 1, drop: fall, L0: it.m.matrix.clone(), auto: it.m.matrixAutoUpdate, P, Pi: P.clone().invert(),
        rx: (r() - 0.5) * (crushed ? 0.5 : 0.02), rz: (r() - 0.5) * (crushed ? 0.5 : 0.02),
        hx: out.x * (crushed ? 0.6 + r() * 1.4 : 0) + (r() - 0.5) * (crushed ? 0.8 : 0), hz: out.z * (crushed ? 0.6 + r() * 1.4 : 0) + (r() - 0.5) * (crushed ? 0.8 : 0),
        delay: (j - k) * 0.22 + r() * 0.12 });
    }
    const shake = this.shakeStart + this.shakeDur;
    this.col = { k, items, pivot, dir, axis, tilt: this.collapse === "total" ? 0.05 : 0.09, t0: this.shakeStart + this.shakeDur * 0.45, dur: 1.7, storey: st[k] };
    this.dur = Math.max(this.dur, this.col.t0 + this.col.dur + (st.length - k) * 0.22 + 4, shake + 3.5);
  }
  _applyCollapse() {
    const C = this.col; if (!C) return 0;
    const M = new THREE.Matrix4(), T1 = new THREE.Matrix4(), R = new THREE.Matrix4(), Sm = new THREE.Matrix4(), c = new THREE.Vector3(), q = new THREE.Quaternion(), e3 = new THREE.Euler();
    let speed = 0;
    for (const x of C.items) {
      const tau = clamp((this.t - C.t0 - x.delay) / C.dur), p = tau * tau;                 // free fall: accelerating
      const p1 = tau >= 1 ? 1 : p;
      speed = Math.max(speed, tau > 0 && tau < 1 ? tau : 0);
      if (tau <= 0) { x.it.m.matrix.copy(x.L0); x.it.m.matrixAutoUpdate = false; x.it.m.matrixWorldNeedsUpdate = true; continue; }
      const s = lerp(1, x.s, p1), d = x.drop * p1;
      // squash about the storey base, then drop
      M.makeTranslation(0, x.e - d, 0).multiply(Sm.makeScale(1, s, 1)).multiply(T1.makeTranslation(0, -x.e, 0));
      // tilt of the falling mass about the pivot edge
      const a = C.tilt * C.dir * p1;
      e3.set(C.axis === "z" ? a : 0, 0, C.axis === "x" ? -a : 0); q.setFromEuler(e3);
      const Rt = new THREE.Matrix4().makeTranslation(C.pivot.x, C.pivot.y, C.pivot.z).multiply(R.makeRotationFromQuaternion(q)).multiply(new THREE.Matrix4().makeTranslation(-C.pivot.x, -C.pivot.y, -C.pivot.z));
      M.premultiply(Rt);
      // debris: own rotation + outward scatter
      c.copy(x.it.c).applyMatrix4(M);
      e3.set(x.rx * p1, 0, x.rz * p1); q.setFromEuler(e3);
      const Rd = new THREE.Matrix4().makeTranslation(c.x + x.hx * p1, c.y, c.z + x.hz * p1).multiply(new THREE.Matrix4().makeRotationFromQuaternion(q)).multiply(new THREE.Matrix4().makeTranslation(-c.x, -c.y, -c.z));
      M.premultiply(Rd);
      const W = M.multiply(x.P.clone().multiply(x.L0));                                    // new world = M · P · L0
      x.it.m.matrix.copy(x.Pi.clone().multiply(W)); x.it.m.matrixAutoUpdate = false; x.it.m.matrixWorldNeedsUpdate = true;
    }
    this.colSpeed = speed;
    return speed;
  }
  _resetCollapse() {
    if (!this.col) return;
    for (const x of this.col.items) { x.it.m.matrix.copy(x.L0); x.it.m.matrixAutoUpdate = x.auto; x.it.m.matrix.decompose(x.it.m.position, x.it.m.quaternion, x.it.m.scale); x.it.m.matrixWorldNeedsUpdate = true; }
    this.col = null;
  }
  _env(u) { if (u <= 0) return 0; const a = u / 0.25; return Math.pow(a * Math.exp(1 - a), 1.1) * (1 - smooth(0.82, 1, u)); }
  _cum(u) { const x = clamp(u) * 200, i = Math.min(199, Math.floor(x)); return lerp(this.cumTab[i], this.cumTab[i + 1], x - i); }
  _sig(tt, k, lag) { const F = [1.1, 1.9, 2.7, 3.5], A = [0.5, 1, 0.8, 0.4]; let s = 0; for (let i = 0; i < 4; i++) s += A[i] * Math.sin(6.2832 * F[i] * (tt - lag) + this.ph[k][0][i]); return s / 2.4; }
  _applySeismic() {
    const t = this.t, u = clamp((t - this.shakeStart) / this.shakeDur), env = this._env(u), cum = this._cum(u), U = this.v.U;
    const roof = this.roofY * this.drift * this.exag, tt = t - this.shakeStart;
    const gx = env * this._sig(tt, 0, 0), gz = env * this._sig(tt, 1, 0), sx = env * this._sig(tt, 0, 0.18), sz = env * this._sig(tt, 1, 0.18);
    const res = roof * 0.2 * this.meanDmg * cum;
    U.uG.value.set(gx * roof * 0.3, gz * roof * 0.18);
    U.uAmp.value.set(sx * roof + res, sz * roof * 0.6 + res * 0.4);
    this.p = cum; this.phase = t < this.shakeStart ? 0 : u < 1 ? 1 : 2;
    if (this.col) { this._applyCollapse(); if (t >= this.col.t0) this.phase = 3; }
    for (const it of this.items) this._paint(it, cum);
    this.lossNow = (this.meta.loss_eur || 0) * cum;
    if (u > 0 && u < 1 && this.active) this._pending = env;
  }

  // ---- internal fire
  _setupFire() {
    const m = this.meta, c = m.curve || { t_min: [0, 60], gas_C: [20, 20] };
    this.curveT = c.t_min; this.curveG = c.gas_C; this.tEnd = Math.max(...c.t_min, 30); this.dur = 20; this.thMax = Math.max(m.theta_max_C || 800, 300);
    { // show the interesting part of the curve only: up to the point where the fire has largely burnt out
      const full = this.tEnd; let pk = 0, pi = 0; for (let i = 0; i <= 400; i++) { const I = this._fireI(i / 400); if (I > pk) { pk = I; pi = i; } }
      let cut = 400; for (let i = pi; i <= 400; i++) if (this._fireI(i / 400) < 0.15 * pk) { cut = i; break; }
      this.tEnd = Math.min(full, Math.max(30, (cut / 400) * full * 1.12)); }
    this.pv = clamp((m.spread && m.spread.vertical) || 0.3, 0, 1);
    const N = 200; this.fireI = []; this.fireCum = []; let a = 0;
    for (let i = 0; i <= N; i++) { const I = this._fireI(i / N); this.fireI.push(I); a += I; this.fireCum.push(a); } this.fireCum = this.fireCum.map((x) => x / (a || 1));
    this.origin = this.storeysAbove.findIndex((s) => s.id === m.storey); if (this.origin < 0) this.origin = 0;
    this.flames = this._newParticles(2200, { size: 3.2, additive: false, buoy: 4.5, drag: 1.2, color: fireCol });
    this.smoke = this._newParticles(900, { size: 5.5, buoy: 1.4, drag: 0.5, color: smokeCol });
    this.windows = this.items.filter((i) => i.glass);
  }
  _fireI(u) { const t = u * this.tEnd, T_ = this.curveT, G = this.curveG; let g = G[G.length - 1]; for (let i = 1; i < T_.length; i++) if (t <= T_[i]) { g = lerp(G[i - 1], G[i], (t - T_[i - 1]) / Math.max(T_[i] - T_[i - 1], 1e-6)); break; } return clamp((g - 20) / (this.thMax - 20)); }
  _fI(u) { if (u <= 0) return 0; const x = clamp(u) * 200, i = Math.min(199, Math.floor(x)); return lerp(this.fireI[i], this.fireI[i + 1], x - i); }
  _fC(u) { if (u <= 0) return 0; const x = clamp(u) * 200, i = Math.min(199, Math.floor(x)); return lerp(this.fireCum[i], this.fireCum[i + 1], x - i); }
  _applyFire(dt) {
    const u = this.t / this.dur, st = this.storeysAbove, oi = this.origin;
    this.phase = u < 0.12 ? 0 : this._fI(u) > 0.6 ? 1 : u < 0.55 ? 0 : 2;
    const perStorey = {};
    st.forEach((s, i) => { const k = i - oi; if (k < 0) return; const d = k * 0.05; perStorey[s.id] = { I: this._fI(u - d) * Math.pow(this.pv, k), p: this._fC(u - d), s, k }; });
    const tick = (i, it) => { const ps = perStorey[it.storey]; this._paint(it, ps ? ps.p : 0, ps ? ps.I : 0); };
    this.items.forEach((it, i) => tick(i, it));
    for (const w of this.windows) { const ps = perStorey[w.storey]; w.m.material.opacity = ps && ps.I > 0.35 ? lerp(0.5, 0.1, smooth(0.35, 0.6, ps.I)) : 0.5; }
    this.p = this._fC(u); this.lossNow = (this.meta.loss_eur || 0) * this.p;
    if (dt > 0) {
      for (const k in perStorey) {
        const ps = perStorey[k], s = ps.s, I = ps.I; if (I < 0.03) continue;
        const win = this.windows.filter((w) => w.storey === k);
        const inside = this.bld.filter((i) => i.storey === k), sb = new THREE.Box3(); inside.forEach((i) => sb.union(i.bb));
        this.flames.rate(I * 330, dt, () => {
          const w = win.length ? win[(Math.random() * win.length) | 0] : null;
          const x = w ? w.c.x + (Math.random() - 0.5) * 1.1 : lerp(sb.min.x, sb.max.x, Math.random()), z = w ? w.c.z + (Math.random() - 0.5) * 1.1 : lerp(sb.min.z, sb.max.z, Math.random()), y = (w ? w.c.y : s.elevation_m + 1) + Math.random() * 0.6;
          this.flames.emit(x, y, z, (Math.random() - 0.5) * 0.8, 1 + Math.random() * 2.4, (Math.random() - 0.5) * 0.8, 0.5 + Math.random() * 0.9 + I * 0.6);
        });
        this.flames.rate(I * 260, dt, () => {   // flames licking out of the facade at flashover
          const side = (Math.random() * 4) | 0, a = Math.random(); let x = lerp(sb.min.x, sb.max.x, a), z = lerp(sb.min.z, sb.max.z, a);
          if (side === 0) z = sb.min.z - 0.2; else if (side === 1) z = sb.max.z + 0.2; else if (side === 2) { x = sb.min.x - 0.2; z = lerp(sb.min.z, sb.max.z, Math.random()); } else { x = sb.max.x + 0.2; z = lerp(sb.min.z, sb.max.z, Math.random()); }
          this.flames.emit(x, s.elevation_m + 0.6 + Math.random() * Math.max(s.height_m - 0.8, 1), z, (Math.random() - 0.5) * 0.6, 0.8 + Math.random() * 2, (Math.random() - 0.5) * 0.6, 0.5 + Math.random() * 0.7);
        });
        this.smoke.rate(I * 120, dt, () => {
          const w = win.length ? win[(Math.random() * win.length) | 0] : null;
          const x = w ? w.c.x : lerp(sb.min.x, sb.max.x, Math.random()), z = w ? w.c.z : lerp(sb.min.z, sb.max.z, Math.random()), y = (w ? w.c.y : s.elevation_m + 1) + 0.8;
          this.smoke.emit(x, y, z, 0.8 + Math.random() * 0.8, 1.3 + Math.random() * 1.6, (Math.random() - 0.5) * 1.2, 2.5 + Math.random() * 2.5);
        });
      }
    }
  }

  // ---- wildfire
  _setupWild() {
    const m = this.meta, D = { N: [0, 1], NE: [0.7071, 0.7071], E: [1, 0], SE: [0.7071, -0.7071], S: [0, -1], SW: [-0.7071, -0.7071], W: [-1, 0], NW: [-0.7071, 0.7071] }[m.direction || "N"] || [0, 1];
    this.F = new THREE.Vector3(D[0], 0, -D[1]).normalize();                        // local (x, y) -> viewer (x, -z)
    this.Pd = new THREE.Vector3(-this.F.z, 0, this.F.x);
    this.hE = 0.5 * (Math.abs(this.size.x * this.F.x) + Math.abs(this.size.z * this.F.z));
    this.dist = Math.max(m.distance_m || 12, 3); this.dur = 22; this.flameL = clamp(m.flame_length_m || 6, 1.5, 25);
    const pr = this.bld.map((i) => (i.c.x - this.cen.x) * this.F.x + (i.c.z - this.cen.z) * this.F.z); this.pmin = Math.min(...pr); this.pmax = Math.max(...pr);
    this.flames = this._newParticles(2600, { size: 4.2, additive: false, buoy: 3.2, drag: 1.4, color: fireCol });
    this.smoke = this._newParticles(900, { size: 6.5, buoy: 1.0, drag: 0.35, color: smokeCol });
    this.embers = this._newParticles(500, { size: 0.8, additive: false, buoy: -0.8, drag: 0.2, color: emberCol });
    this.glow = this._newMesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ color: 0xff5a14, transparent: true, opacity: 0.0, depthWrite: false, side: THREE.DoubleSide }));
    this.glow.rotation.x = -Math.PI / 2;
  }
  _wildS(u) { return lerp(75, this.dist, smooth(0, 0.45, u)); }
  _applyWild(dt) {
    const u = this.t / this.dur, s = this._wildS(u), F = this.F, Pd = this.Pd, cx = this.cen.x, cz = this.cen.z, gy = this.bb.min.y + 0.1;
    const lineC = new THREE.Vector3(cx + F.x * (this.hE + s), 0, cz + F.z * (this.hE + s)), half = Math.max(this.size.x, this.size.z) * 0.5 + 22;
    this.phase = u < 0.45 ? 0 : 1;
    this.glow.rotation.order = "YXZ"; this.glow.rotation.set(-Math.PI / 2, Math.atan2(-Pd.z, Pd.x), 0);
    this.glow.position.set(lineC.x + F.x * 4, 0.05, lineC.z + F.z * 4); this.glow.scale.set(half * 2, 10, 1);
    this.glow.material.opacity = 0.28 * smooth(0, 0.1, u);
    for (const it of this.items) {
      if (!this.bld.includes(it)) { this._paint(it, 0); continue; }
      const pn = clamp(((it.c.x - cx) * F.x + (it.c.z - cz) * F.z - this.pmin) / Math.max(this.pmax - this.pmin, 1e-6));
      const p = smooth(0.3 + 0.25 * (1 - pn), 0.95, u);
      this._paint(it, p, smooth(0.3, 0.8, u) * pn * pn * 0.45);
    }
    this.p = smooth(0.3, 0.95, u) ; this.lossNow = (this.meta.loss_eur || 0) * this.p;
    if (dt > 0) {
      const act = smooth(0, 0.08, u);
      this.flames.rate(900 * act, dt, () => {
        const a = (Math.random() - 0.5) * 2 * half, x = lineC.x + Pd.x * a + (Math.random() - 0.5) * 5, z = lineC.z + Pd.z * a + (Math.random() - 0.5) * 5;
        this.flames.emit(x, gy, z, -F.x * (0.5 + Math.random()), this.flameL * (0.45 + Math.random() * 0.55), -F.z * (0.5 + Math.random()), 0.55 + Math.random() * 0.6);
      });
      this.smoke.rate(180 * act, dt, () => {
        const a = (Math.random() - 0.5) * 2 * half, x = lineC.x + Pd.x * a, z = lineC.z + Pd.z * a;
        this.smoke.emit(x, gy + this.flameL * 0.6, z, -F.x * (2 + Math.random() * 2), 2 + Math.random() * 2, -F.z * (2 + Math.random() * 2), 4 + Math.random() * 3);
      });
      const pe = (this.meta.ember_probability || 0.2);
      this.embers.rate((60 + 260 * pe) * act, dt, () => {
        const a = (Math.random() - 0.5) * 2 * (half * 0.6), x = lineC.x + Pd.x * a, z = lineC.z + Pd.z * a, sp = 7 + Math.random() * 7;
        this.embers.emit(x, gy + this.flameL * 0.8, z, -F.x * sp, 3 + Math.random() * 4, -F.z * sp, 2 + Math.random() * 2.2);
      });
    }
  }

  // ---- flood
  _setupFlood() {
    const m = this.meta; this.dur = 16;
    this.depth = Math.max(m.effective_depth_m ?? m.depth_m ?? 0, 0); this.bH = m.basement_flooded_m || 0;
    this.sh = new Map((m.storeys || []).map((s) => [s.id, s.water_depth_m || 0]));
    const base = this.project.storeys.filter((s) => s.elevation_m < 0).sort((a, b) => a.elevation_m - b.elevation_m)[0];
    this.baseY = base ? base.elevation_m : 0; this.baseIds = new Set(this.project.storeys.filter((s) => s.elevation_m < 0).map((s) => s.id));
    const span = Math.max(this.size.x, this.size.z) * 3.2;
    this.water = this._newMesh(new THREE.PlaneGeometry(span, span), new THREE.MeshPhongMaterial({ color: 0x2f7fbf, transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide, shininess: 80, specular: 0x88aadd }));
    this.water.rotation.x = -Math.PI / 2; this.water.position.set(this.cen.x, 0, this.cen.z);
    const bb = new THREE.Box3(); this.bld.filter((i) => this.baseIds.has(i.storey)).forEach((i) => bb.union(i.bb));
    this.bbB = bb.isEmpty() ? null : bb;
    if (this.bbB && this.bH > 0) {
      const sz = this.bbB.getSize(new THREE.Vector3()); this.inner = this._newMesh(new THREE.BoxGeometry(sz.x - 0.5, 1, sz.z - 0.5), new THREE.MeshPhongMaterial({ color: 0x2a6fb0, transparent: true, opacity: 0.6, depthWrite: false }));
      this.inner.position.set((this.bbB.min.x + this.bbB.max.x) / 2, this.baseY, (this.bbB.min.z + this.bbB.max.z) / 2);
    }
    this.splash = this._newParticles(300, { size: 1.0, tex: this.tex, buoy: -9, drag: 0.3, color: (u, c) => { c.setRGB(0.75, 0.88, 1); return 0.7 * (1 - u); } });
  }
  _applyFlood(dt) {
    const u = this.t / this.dur, lvl = this.depth * smooth(0.12, 0.92, u), fill = smooth(0.1, 0.6, u);
    this.phase = u < 0.9 ? 0 : 2; this.lvl = lvl;
    this.water.visible = this.depth > 0.02; this.water.position.y = Math.max(lvl, 0.03) - 0.02; this.water.material.opacity = 0.5 * smooth(0.04, 0.2, u);
    if (this.inner) { const h = Math.max(this.bH * fill, 0.02); this.inner.scale.y = h; this.inner.position.y = this.baseY + h / 2 + 0.02; this.inner.visible = fill > 0.02; }
    const z0 = new Map(this.project.storeys.map((s) => [s.id, s.elevation_m]));
    for (const it of this.items) {
      const hs = this.sh.get(it.storey) || 0; let p = 0;
      if (hs > 0 && this.bld.includes(it)) p = this.baseIds.has(it.storey) ? fill : clamp((lvl - (z0.get(it.storey) || 0)) / hs);
      this._paint(it, p, 0);
    }
    this.p = this.depth > 0 || this.bH > 0 ? clamp(Math.max(this.bH > 0 ? fill : 0, this.depth > 0 ? lvl / this.depth : 0)) : smooth(0.1, 0.9, u); this.lossNow = (this.meta.loss_eur || 0) * this.p;
    if (dt > 0 && this.depth > 0.05 && u > 0.1 && u < 0.9) {
      this.splash.rate(80, dt, () => { const a_ = Math.random() * 6.28, r = Math.max(this.size.x, this.size.z) * (0.75 + Math.random() * 0.5); this.splash.emit(this.cen.x + Math.cos(a_) * r, lvl + 0.1, this.cen.z + Math.sin(a_) * r, -Math.cos(a_) * 1.5, 3 + Math.random() * 2, -Math.sin(a_) * 1.5, 0.9); });
    }
  }

  // ---- colour of one element: type colour -> damage colour as p (development) grows; glow = emissive fire/heat
  _paint(it, p, glow = 0) {
    if (it.kind === "site" || it.kind === "excavation") return;
    const fin = smooth(0.93, 1, this.t / this.dur), pe = Math.max(p, fin), v = it.f * pe, mat = it.m.material;
    const target = v < 0.0005 ? GREEN : rampColor(v);
    const w = it.f < 0.0005 ? fin : smooth(0, 0.12, pe);
    mat.color.copy(it.base).lerp(target, w);
    if (glow > 0.01) mat.emissive.setRGB(1.0 * glow, 0.32 * glow * (0.7 + 0.3 * Math.sin(this.t * 17 + it.c.x)), 0.04 * glow); else mat.emissive.setRGB(0, 0, 0);
    if (it.id && it.id === this.v.sel && glow <= 0.01) mat.emissive.setRGB(0.16, 0.47, 0.84);
  }

  // ---- time control
  _apply(dt) { ({ seismic: this._applySeismic, fire_internal: this._applyFire, wildfire: this._applyWild, flood: this._applyFlood }[this.type] || (() => {})).call(this, dt); }
  _emitSeismic(dt) {
    if (!this.dust || this.type !== "seismic") return;
    const env = this._pending || 0, amp = clamp((this.meta.pga_g || 0.2) / 0.3), W = this.size, C = this.cen;
    this.dust.rate(env * (40 + 220 * amp * (0.3 + this.meanDmg * 2)), dt, () => {
      const side = (Math.random() * 4) | 0, a = Math.random() - 0.5; let x = C.x, z = C.z;
      if (side === 0) { x += W.x * 0.5 + 0.3; z += a * W.z; } else if (side === 1) { x -= W.x * 0.5 + 0.3; z += a * W.z; } else if (side === 2) { z += W.z * 0.5 + 0.3; x += a * W.x; } else { z -= W.z * 0.5 + 0.3; x += a * W.x; }
      this.dust.emit(x, 0.2, z, (Math.random() - 0.5) * 1.2, 0.6 + Math.random(), (Math.random() - 0.5) * 1.2, 1.6 + Math.random() * 1.6);
    });
  }
  _emitCollapseDust(dt) {
    const C = this.col; if (!C || !this.dust || !(this.colSpeed > 0)) return;
    const W = this.size, X = this.cen, y0 = C.storey.elevation_m;
    this.dust.rate(900 * this.colSpeed, dt, () => {
      const x = X.x + (Math.random() - 0.5) * W.x * 1.1, z = X.z + (Math.random() - 0.5) * W.z * 1.1;
      const a = Math.random() * 6.283, v = 2 + Math.random() * 4;
      this.dust.emit(x, y0 + Math.random() * 2, z, Math.cos(a) * v, 0.4 + Math.random() * 1.6, Math.sin(a) * v, 2.5 + Math.random() * 3);
    });
  }
  step(dt) {
    if (!this.active) return;
    this.t = clamp(this.t + dt * this.speed, 0, this.dur); this._pending = 0;
    this._apply(dt); this._emitSeismic(dt); this._emitCollapseDust(dt); for (const p of this.parts) p.update(dt);
    if (this.onTick) this.onTick(this.t, this.dur);
    if (this.t >= this.dur && this.playing) { this.playing = false; this.last = null; if (this.onEnd) this.onEnd(); }
  }
  seek(t) {
    if (!this.active) return; this.t = clamp(t, 0, this.dur); this.parts.forEach((p) => p.clear()); this._apply(0);
    // warm particles up so scrubbing shows flames / smoke / dust
    if (this.parts.length && this.t > 0) { let tt = Math.max(0, this.t - 1.6); const keep = this.t; this.t = tt; for (let i = 0; i < 32; i++) { this.t = clamp(tt + i * 0.05, 0, keep); this._pending = 0; this._apply(0.05); this._emitSeismic(0.05); this._emitCollapseDust(0.05); for (const p of this.parts) p.update(0.05); } this.t = keep; this._apply(0); }
    if (this.onTick) this.onTick(this.t, this.dur);
  }
  play() { if (!this.active) return; if (this.t >= this.dur - 0.01) this.seek(0); this.playing = true; this.last = null; this._hook(); }
  pause() { this.playing = false; this.last = null; }
  restart() { this.seek(0); }
  _hook() {
    const v = this.v;
    v.beforeRender = (now) => {
      if (!v.host || !v.host.isConnected) { this.pause(); return; }
      if (!this.playing) return;
      const dt = this.last === null ? 0 : Math.min((now - this.last) / 1000, 0.25); this.last = now;
      if (dt > 0) this.step(dt);
      if (this.orbit && dt > 0) { const a = 0.1 * dt, tg = v.controls.target, p = v.camera.position, dx = p.x - tg.x, dz = p.z - tg.z; p.x = tg.x + dx * Math.cos(a) - dz * Math.sin(a); p.z = tg.z + dx * Math.sin(a) + dz * Math.cos(a); }
    };
  }

  // ---- text for the overlay (live HUD and video)
  info() {
    const m = this.meta || {}, nm = (o, k) => o && (S.lang === "el" ? o[k + "_el"] : o[k + "_en"]);
    const u = this.dur ? this.t / this.dur : 0; let phase = "", lines = [];
    const pj = S.project.name || (S.project.meta && S.project.meta.name) || "";
    if (this.type === "seismic") {
      const sn = this.col ? (S.lang === "el" ? this.col.storey.name_el : this.col.storey.name_en) || "" : "";
      phase = [T("Πριν τον σεισμό", "Before the quake"), T("Σεισμική δόνηση", "Ground shaking"), T("Μετά τον σεισμό · εικόνα βλαβών", "After the quake · damage state"),
        this.collapse === "total" ? T("ΚΑΤΑΡΡΕΥΣΗ ΚΤΙΡΙΟΥ", "BUILDING COLLAPSE") : T("ΜΕΡΙΚΗ ΚΑΤΑΡΡΕΥΣΗ · ", "PARTIAL COLLAPSE · ") + sn][this.phase || 0];
      lines = [`Ms ${fmt(m.Ms, 1)} (${T("Ρίχτερ", "Richter")}) · R ${fmt(m.distance_km, 0)} km · PGA ${fmt(m.pga_g, 2)} g (×${fmt(m.pga_over_design, 2)} ${T("του σχεδιασμού", "of design")}) · MMI ${m.intensity_mmi}`,
        `${T("Μέση βλάβη", "Mean grade")} ${fmt(m.mean_grade, 2)} · P(D≥3) ${pct(m.p_d3plus, 0)} · ${T("πιθανότητα κατάρρευσης", "collapse probability")} ${pct(m.p_collapse_d5 || 0, 0)}` + (this.collapse ? ` · ${T("κρίσιμος όροφος", "critical storey")}: ${sn}` : "")];
    } else if (this.type === "fire_internal") {
      const tf = Math.round(u * this.tEnd); phase = [T("Ανάπτυξη πυρκαγιάς", "Fire growth"), T("Πλήρης ανάπτυξη (flashover)", "Fully developed (flashover)"), T("Φθίνουσα φάση", "Decay phase")][this.phase || 0];
      lines = [`${T("Εστία", "Origin")}: ${nm(m, "storey_name") || ""} · θmax ${fmt(m.theta_max_C, 0)} °C · t = ${tf} min`, `${T("Πυροσβεστική αντίσταση", "Fire resistance")} R${m.R_provided_min} / ${T("απαιτούμενη", "required")} R${m.R_required_min}`];
    } else if (this.type === "wildfire") {
      phase = [T("Προσέγγιση μετώπου", "Fire front approaching"), T("Έκθεση σε ακτινοβολία και ωλοκάρβουνα", "Radiant heat and ember attack")][this.phase || 0];
      lines = [`${m.bal} · ${T("απόσταση", "distance")} ${fmt(m.distance_m, 0)} m · ${T("φλόγες", "flames")} ${fmt(m.flame_length_m, 1)} m · ${fmt(m.flux_kW_m2, 1)} kW/m²`, `${T("Κατεύθυνση", "Direction")}: ${m.direction}`];
    } else if (this.type === "flood") {
      phase = this.phase === 2 ? T("Μέγιστη στάθμη · εικόνα βλαβών", "Peak level · damage state") : T("Άνοδος στάθμης", "Water rising");
      lines = [`${T("Βάθος", "Depth")} ${fmt(this.depth, 2)} m · ${T("υπόγειο", "basement")} ${fmt(this.bH, 2)} m · v = ${m.velocity_ms} m/s`];
    }
    return { title: this.label + (pj ? " — " + pj : ""), lines, phase, u, t: this.t, dur: this.dur, lossNow: this.lossNow || 0, lossTotal: m.loss_eur || 0, ratio: m.loss_ratio || 0 };
  }

  reset() {
    const v = this.v; this._resetCollapse(); this.playing = false; this.last = null; this.active = false; v.beforeRender = null;
    v.U.uProfN.value = 0; v.U.uG.value.set(0, 0); v.U.uAmp.value.set(0, 0);
    this.parts.forEach((p) => p.dispose(v.scene)); this.parts = [];
    this.extra.forEach((m) => { v.scene.remove(m); m.geometry.dispose(); m.material.dispose(); }); this.extra = [];
    this.flames = this.smoke = this.embers = this.dust = this.glow = this.water = this.inner = this.splash = null;
  }
  dispose() { this.reset(); if (this.v.anim === this) this.v.anim = null; }
}

// ---------------------------------------------------------------- overlay (HUD + legend), drawn on a 2D canvas
export function drawOverlay(ctx, W, H, info, scale) {
  const k = scale || W / 1280, px = (x) => x * k, FONT = '"Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif';
  ctx.save(); ctx.textBaseline = "top";
  const pad = px(12), lh = px(20), lines = info.lines;
  ctx.font = `700 ${px(18)}px ${FONT}`; let w = ctx.measureText(info.title).width;
  ctx.font = `500 ${px(14)}px ${FONT}`; for (const l of lines) w = Math.max(w, ctx.measureText(l).width);
  const bw = Math.min(w + pad * 2, W - px(24)), bh = pad * 2 + lh * (lines.length + 1) + px(4);
  ctx.fillStyle = "rgba(255,255,255,.9)"; ctx.strokeStyle = "rgba(0,0,0,.12)"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.roundRect(px(12), px(12), bw, bh, px(8)); ctx.fill(); ctx.stroke();
  ctx.fillStyle = "#1c1c1b"; ctx.font = `700 ${px(18)}px ${FONT}`; ctx.fillText(info.title, px(12) + pad, px(12) + pad, bw - pad * 2);
  ctx.font = `500 ${px(14)}px ${FONT}`; ctx.fillStyle = "#44433f"; lines.forEach((l, i) => ctx.fillText(l, px(12) + pad, px(12) + pad + lh * (i + 1) + px(4), bw - pad * 2));
  // phase pill
  if (info.phase) {
    ctx.font = `700 ${px(15)}px ${FONT}`; const pw = ctx.measureText(info.phase).width + px(28), x = W - pw - px(12);
    ctx.fillStyle = /ΚΑΤΑΡΡΕΥΣΗ|COLLAPSE/.test(info.phase) ? "rgba(179,38,30,.95)" : "rgba(25,31,43,.88)"; ctx.beginPath(); ctx.roundRect(x, px(12), pw, px(34), px(17)); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.fillText(info.phase, x + px(14), px(12) + px(8));
  }
  // bottom: legend ramp, loss counter, progress bar
  const by = H - px(86), bw2 = px(300);
  ctx.fillStyle = "rgba(255,255,255,.9)"; ctx.beginPath(); ctx.roundRect(px(12), by, bw2 + px(24), px(74), px(8)); ctx.fill();
  const g = ctx.createLinearGradient(px(24), 0, px(24) + bw2, 0);
  ["#2e9e44", "#f2c200", "#e8742a", "#c8281e", "#5b0e0e"].forEach((c, i) => g.addColorStop(i / 4, c));
  ctx.fillStyle = "#1c1c1b"; ctx.font = `600 ${px(12.5)}px ${FONT}`; ctx.fillText(T("Λόγος ζημιάς στοιχείου", "Element damage ratio"), px(24), by + px(8));
  ctx.fillStyle = g; ctx.beginPath(); ctx.roundRect(px(24), by + px(28), bw2, px(12), px(6)); ctx.fill();
  ctx.fillStyle = "#44433f"; ctx.font = `500 ${px(12)}px ${FONT}`; ctx.fillText("0%", px(24), by + px(46)); ctx.textAlign = "right"; ctx.fillText("≥60%", px(24) + bw2, by + px(46)); ctx.textAlign = "left";
  ctx.fillText(T("Πράσινο = χωρίς βλάβη", "Green = undamaged"), px(24) + bw2 / 2 - px(40), by + px(46));
  const lw = px(330), lx = W - lw - px(12);
  ctx.fillStyle = "rgba(255,255,255,.9)"; ctx.beginPath(); ctx.roundRect(lx, by, lw, px(74), px(8)); ctx.fill();
  ctx.fillStyle = "#44433f"; ctx.font = `500 ${px(13)}px ${FONT}`; ctx.fillText(T("Ζημιά μέχρι αυτή τη στιγμή", "Loss so far"), lx + px(14), by + px(8));
  ctx.fillStyle = "#b3261e"; ctx.font = `700 ${px(24)}px ${FONT}`; ctx.fillText(eur(Math.round(info.lossNow / 1000) * 1000), lx + px(14), by + px(26));
  ctx.fillStyle = "#44433f"; ctx.font = `500 ${px(12)}px ${FONT}`; ctx.fillText(`${T("τελική", "final")} ${eur(info.lossTotal)} · ${pct(info.ratio, 1)}`, lx + px(14), by + px(56), lw - px(28));
  ctx.fillStyle = "rgba(25,31,43,.25)"; ctx.fillRect(0, H - px(6), W, px(6)); ctx.fillStyle = "#2a78d6"; ctx.fillRect(0, H - px(6), W * clamp(info.u), px(6));
  ctx.restore();
}

// ---------------------------------------------------------------- video recorder
export class VideoRecorder {
  constructor(viewer, anim) { this.v = viewer; this.anim = anim; this.active = false; this.onDone = null; }
  static mime() {
    const c = ["video/mp4;codecs=avc1.640028", "video/mp4;codecs=avc1", "video/mp4", "video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];
    return typeof MediaRecorder === "undefined" ? null : c.find((m) => MediaRecorder.isTypeSupported(m)) || null;
  }
  start(maxW = 1600) {
    const mime = VideoRecorder.mime(); if (!mime) throw new Error(T("Ο περιηγητής δεν υποστηρίζει εγγραφή βίντεο (MediaRecorder).", "This browser does not support video recording (MediaRecorder)."));
    const r = this.v.renderer, css = this.v.host.clientWidth || 800;
    this.prevPR = r.getPixelRatio(); r.setPixelRatio(clamp(1280 / css, this.prevPR, 3)); this.v.resize();        // render at ~720p or better while recording
    const gl = r.domElement, sc = Math.min(1, maxW / gl.width), W = Math.max(2, Math.round((gl.width * sc) / 2) * 2), H = Math.max(2, Math.round((gl.height * sc) / 2) * 2);
    this.cv = document.createElement("canvas"); this.cv.width = W; this.cv.height = H; this.ctx = this.cv.getContext("2d");
    this.mime = mime; this.ext = mime.startsWith("video/mp4") ? "mp4" : "webm"; this.chunks = [];
    this.rec = new MediaRecorder(this.cv.captureStream(30), { mimeType: mime, videoBitsPerSecond: 8e6 });
    this.rec.ondataavailable = (e) => { if (e.data && e.data.size) this.chunks.push(e.data); };
    this.rec.onstop = () => { this.active = false; this.v.afterRender = this.prevAfter || null; this.v.renderer.setPixelRatio(this.prevPR); this.v.resize(); const blob = new Blob(this.chunks, { type: this.mime.split(";")[0] }); if (this.onDone) this.onDone(blob, this.ext); };
    this.prevAfter = this.v.afterRender;
    this.v.afterRender = () => { this.prevAfter && this.prevAfter(); this.frame(); };
    this.rec.start(250); this.active = true;
  }
  frame() { if (!this.active) return; const { ctx, cv } = this; ctx.fillStyle = "#e9eef4"; ctx.fillRect(0, 0, cv.width, cv.height); ctx.drawImage(this.v.renderer.domElement, 0, 0, cv.width, cv.height); drawOverlay(ctx, cv.width, cv.height, this.anim.info()); }
  stop() { if (this.active && this.rec.state !== "inactive") this.rec.stop(); }
}
