// Shared helpers: state, API, DOM builder, formatting, charts.
export const S = { pid: null, project: null, lang: localStorage.getItem("lang") || "el", tab: "project", damage: null, damageLabel: "", cache: {} };
export const T = (el, en) => (S.lang === "el" ? el : en);
export const L = (o, base = "") => (o ? (o[base + (S.lang === "el" ? "el" : "en")] ?? o[(S.lang === "el" ? "label_el" : "label_en")] ?? o[(S.lang === "el" ? "name_el" : "name_en")] ?? "") : "");
export const PAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
export const INK2 = "#52514e";

export async function api(path, opts = {}) {
  const o = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined && !(opts.body instanceof FormData)) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(opts.body); }
  else if (opts.body instanceof FormData) o.body = opts.body;
  const r = await fetch("/api" + path, o);
  if (r.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search); throw new Error("login"); }
  if (!r.ok) { let m = r.statusText; try { const j = await r.json(); m = j.detail || JSON.stringify(j); } catch (e) {} throw new Error(m); }
  if (opts.raw) return r;
  return r.json();
}

export function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") e.className = v;
    else if (k === "html") e.innerHTML = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
    else if (k === "value") e.value = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat(Infinity)) { if (c == null || c === false) continue; e.append(c.nodeType ? c : document.createTextNode(String(c))); }
  return e;
}

export function fmt(x, d = 0) {
  if (x === null || x === undefined || Number.isNaN(x)) return "–";
  return Number(x).toLocaleString(S.lang === "el" ? "el-GR" : "en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}
export const eur = (x, d = 0) => (x === null || x === undefined ? "–" : fmt(x, d) + " €");
export const pct = (x, d = 1) => (x === null || x === undefined ? "–" : fmt(x * 100, d) + "%");

export function toast(msg, err = false) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.className = "show" + (err ? " err" : "");
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.className = ""), err ? 6000 : 2600);
}
export function modal(content) { const m = document.getElementById("modal"); const b = document.getElementById("modalBody"); b.replaceChildren(content); m.classList.remove("hidden"); m.onclick = (e) => { if (e.target === m) closeModal(); }; }
export function closeModal() { document.getElementById("modal").classList.add("hidden"); }

export function debounce(fn, ms = 500) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

const charts = {};
export function chart(id, cfg) {
  if (charts[id]) { charts[id].destroy(); delete charts[id]; }
  const el = document.getElementById(id);
  if (!el) {   // the view may not be attached to the document yet: retry for a short while
    let n = 0; const retry = () => { if (document.getElementById(id)) chart(id, cfg); else if (++n < 90) requestAnimationFrame(retry); };
    requestAnimationFrame(retry); return null;
  }
  cfg.options = Object.assign({ responsive: true, maintainAspectRatio: false, animation: { duration: 250 } }, cfg.options || {});
  cfg.options.plugins = Object.assign({ legend: { labels: { boxWidth: 10, boxHeight: 10, color: INK2, font: { size: 11 } } } }, cfg.options.plugins || {});
  Chart.defaults.font.family = '"Segoe UI", system-ui, "DejaVu Sans", Arial, sans-serif';
  Chart.defaults.color = INK2;
  charts[id] = new Chart(el, cfg);
  return charts[id];
}
export const ax = (title, extra = {}) => Object.assign({ title: { display: !!title, text: title, font: { size: 11 } }, grid: { color: "#ececea" }, border: { color: "#dcdcd8" } }, extra);
export function canvasBox(id, cls = "") { return h("div", { class: "chartbox " + cls }, h("canvas", { id })); }

export function kpi(v, l, s) { return h("div", { class: "kpi" }, h("div", { class: "v" }, v), h("div", { class: "l" }, l), s ? h("div", { class: "s" }, s) : null); }
export function clsChip(c) { const m = { "A+": "Aplus", "B+": "Bplus", "Γ": "G", "Δ": "D", "Ε": "E", "Ζ": "Z", "Η": "H" }; return h("span", { class: "chip cls-" + (m[c] || c) }, c); }

export function numInput(value, onchange, opts = {}) {
  const i = h("input", { type: "number", step: opts.step ?? "any", value: value ?? "", class: opts.cls || "", min: opts.min, max: opts.max, style: opts.w ? { width: opts.w } : null });
  i.addEventListener("change", () => onchange(i.value === "" ? null : Number(i.value), i));
  return i;
}
export function select(options, value, onchange) {
  const s = h("select", {}, options.map(([v, l]) => h("option", { value: v, selected: String(v) === String(value) }, l)));
  s.addEventListener("change", () => onchange(s.value)); return s;
}
export function field(label, input) { return h("label", { class: "f" }, label, input); }
export function spinner() { return h("span", { class: "spin" }); }
export function download(blob, name) { const a = h("a", { href: URL.createObjectURL(blob), download: name }); document.body.append(a); a.click(); a.remove(); }
