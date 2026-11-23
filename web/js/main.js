import { S, T, api, h, toast, modal, closeModal, spinner, field } from "./util.js";
import { projectView, modelView, quantitiesView, costView, scheduleView } from "./views1.js";
import { energyView, lifecycleView, hazardsView } from "./views2.js";
import { pricesView, reportView } from "./views3.js";
import { fmView } from "./views4.js";
import { siteView } from "./views5.js";

const TABS = [["project", "1D–3D Σχέδια", "1D–3D Drawings", projectView], ["site", "Περιοχή – live δεδομένα", "Site – live data", siteView], ["model", "3D ψηφιακό δίδυμο / 4D", "3D digital twin / 4D", modelView], ["quantities", "Προμέτρηση", "Quantities", quantitiesView],
  ["schedule", "4D Χρόνος", "4D Time", scheduleView], ["cost", "5D Κόστος κατασκευής", "5D Construction cost", costView], ["lifecycle", "5D Κόστος στον χρόνο", "5D Cost over time", lifecycleView],
  ["energy", "6D Ενέργεια & βιωσιμότητα", "6D Energy & sustainability", energyView], ["fm", "7D Διαχείριση εγκαταστάσεων", "7D Facility management", fmView], ["hazards", "7D Κίνδυνοι", "7D Risks", hazardsView],
  ["prices", "Τιμές", "Prices", pricesView], ["report", "PDF", "PDF", reportView]];
const $ = (id) => document.getElementById(id);
let renderToken = 0;

async function loadProject(pid) {
  S.pid = pid; S.damage = null; S.damageLabel = ""; S.damageMeta = null; S.cache = {};
  localStorage.setItem("pid", pid);
  S.project = await api(`/projects/${pid}`);
}
window.reloadProject = async (rerender = true) => { S.project = await api(`/projects/${S.pid}`); S.cache = {}; S.cache.glbv = Date.now(); if (rerender) render(); };
window.go = (tab) => { S.tab = tab; render(); };

function drawNav() {
  $("nav").replaceChildren(...TABS.map(([id, el, en]) => h("button", { class: S.tab === id ? "on" : "", onclick: () => { S.tab = id; render(); } }, S.lang === "el" ? el : en)));
  document.documentElement.lang = S.lang;
  [...$("langSeg").children].forEach((b) => b.classList.toggle("on", b.dataset.l === S.lang));
  $("lblProject").textContent = T("Έργο", "Project");
  $("top") && ($("top").dataset.l = S.lang);
}

export async function render() {
  const my = ++renderToken;
  drawNav();
  const view = $("view");
  if (!S.project) { view.replaceChildren(h("div", { class: "card" }, h("p", {}, T("Δεν υπάρχει έργο. Δημιουργήστε νέο.", "No project. Create a new one.")))); return; }
  $("sub").textContent = (S.lang === "el" ? S.project.name : S.project.name_en) + " · " + (S.project.meta.location?.address || "");
  const fn = TABS.find((t) => t[0] === S.tab)[3];
  const holder = h("div", {}, h("div", { class: "card" }, spinner(), " " + T("Φόρτωση…", "Loading…")));
  view.replaceChildren(holder);
  const root = h("div");
  try { await fn(root); } catch (e) { console.error(e); root.replaceChildren(h("div", { class: "warnbox" }, T("Σφάλμα: ", "Error: ") + e.message)); }
  if (my !== renderToken) return;
  view.replaceChildren(root);
  window.scrollTo({ top: 0 });
}
window.render = render;

async function fillProjects(select) {
  const list = (await api("/projects")).filter((p) => p.id === "demo-kifisia");
  const r = { projects: list };
  const sel = $("projectSelect");
  sel.replaceChildren(...r.projects.map((p) => h("option", { value: p.id }, S.lang === "el" ? p.name : p.name_en || p.name)));
  const want = select || S.pid || localStorage.getItem("pid");
  if (r.projects.some((p) => p.id === want)) sel.value = want; else if (r.projects.length) sel.value = r.projects[0].id;
  return r.projects.length ? sel.value : null;
}

$("projectSelect").onchange = async (e) => { await loadProject(e.target.value); render(); };
[...$("langSeg").children].forEach((b) => (b.onclick = async () => { S.lang = b.dataset.l; localStorage.setItem("lang", S.lang); await fillProjects(S.pid); render(); }));

(async function init() {
  try {
    const pid = await fillProjects();
    if (pid) await loadProject(pid);
  } catch (e) { $("view").replaceChildren(h("div", { class: "warnbox" }, "API: " + e.message)); return; }
  render();
})();
