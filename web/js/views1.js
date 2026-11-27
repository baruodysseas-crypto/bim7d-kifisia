import { S, T, L, api, h, fmt, eur, pct, toast, modal, closeModal, debounce, chart, ax, canvasBox, kpi, numInput, select, field, spinner, PAL } from "./util.js";
import { Viewer, KIND_COLORS, rampColor } from "./viewer.js";
import { DamageAnim, VideoRecorder, drawOverlay } from "./anim.js";

let viewer = null;
let viewerPid = null;

export const KIND_NAMES = { footing: ["Θεμελίωση", "Footing"], column: ["Υποστυλώματα", "Columns"], beam: ["Δοκοί", "Beams"], slab: ["Πλάκες", "Slabs"], wall: ["Τοίχοι", "Walls"], window: ["Ανοίγματα", "Windows"], door: ["Πόρτες", "Doors"], roof: ["Δώμα/στέγη", "Roof"], stair: ["Σκάλες", "Stairs"], railing: ["Κιγκλιδώματα", "Railings"], pergola: ["Πέργκολες, ξύλινες επενδύσεις, ζαρντινιέρες", "Pergolas, timber cladding, planters"], fence: ["Περίφραξη", "Fence"], vegetation: ["Βλάστηση", "Vegetation"], furniture: ["Επίπλωση", "Furniture"], site: ["Έδαφος", "Site"], other: ["Άλλα", "Other"] };
const kn = (k) => (KIND_NAMES[k] ? KIND_NAMES[k][S.lang === "el" ? 0 : 1] : k);

// ------------------------------------------------------------------ PROJECT
export async function projectView(root) {
  const p = S.project, m = p.meta;
  root.append(h("h1", {}, T("Σχέδια, μοντέλο και ψηφιακό δίδυμο (3D)", "Drawings, model and digital twin (3D)")), h("p", { class: "lead" }, T("Τα σχέδια (PDF/DXF) και το 3D μοντέλο αποτελούν το ψηφιακό δίδυμο του κτιρίου. Από αυτό προκύπτουν τα στοιχεία BIM και οι ποσότητες που τροφοδοτούν το 4D (χρόνος), το 5D (κόστος), το 6D (βιωσιμότητα) και το 7D (διαχείριση εγκαταστάσεων, περιουσιακών στοιχείων και κινδύνων).", "The drawings (PDF/DXF) and the 3D model form the digital twin of the building. They give the BIM elements and quantities that feed 4D (time), 5D (cost), 6D (sustainability) and 7D (facility, asset and risk management).")));
  if (m.synthetic_geometry) root.append(h("div", { class: "card", style: { padding: "8px 14px" } }, h("span", { class: "small" }, T("Το 3D είναι μοντέλο BIM φτιαγμένο από τη μελέτη: ο φέρων οργανισμός (θέσεις και διατομές υποστυλωμάτων/τοιχωμάτων, δοκάρια, οπλισμοί) διαβάζεται από τους ξυλότυπους Σ.01–Σ.06, οι όγκοι και τα ανοίγματα από τις αρχιτεκτονικές κατόψεις και ο περιβάλλων χώρος από το μοντέλο Rhino.", "The 3D is a BIM model built from the design: the structural skeleton (positions and sections of columns/walls, beams, reinforcement) is read from the formwork drawings S.01–S.06, the volumes and openings from the architectural plans and the surroundings from the Rhino model."))));

  root.append(dimensionsCard());
  const nm = (x) => x[S.lang === "el" ? "name_el" : "name_en"];
  const isAttic = (x) => x.key === "attic" || /σοφίτ|attic/i.test(x.name_el + " " + x.name_en);
  const floorsAbove = p.storeys.filter((x) => x.elevation_m >= 0 && !isAttic(x)).length;   // basement and attic are not floors in the building-factor sense
  const cards = [kpi(fmt(p.element_count), T("Στοιχεία BIM", "BIM elements"))];
  cards.push(kpi(fmt(m.gfa_m2, 1) + " m²", T("Συνολική επιφάνεια ορόφων", "Total floor area"), T("με υπόγειο", "incl. basement")),
    kpi(fmt(floorsAbove) + " " + T("όροφοι", "floors"), T("Στάθμες", "Levels"), p.storeys.map(nm).join(" · ")), kpi(fmt(m.apartments), T("Διαμερίσματα", "Apartments")));
  const kpis = h("div", { class: "grid " + (cards.length > 4 ? "g5" : "g4") }, ...cards);
  root.append(kpis);
  // meta form
  const loc = m.location || {}, st = m.structure || {};
  const save = debounce(async (patch) => { await api(`/projects/${S.pid}/meta`, { method: "PATCH", body: patch }); await window.reloadProject(false); toast(T("Αποθηκεύτηκε", "Saved")); }, 600);
  const txt = (label, val, f) => field(label, h("input", { value: val ?? "", onchange: (e) => f(e.target.value) }));
  const num = (label, val, f, step) => field(label, numInput(val, (v) => f(v), { step }));
  root.append(h("div", { class: "grid g2" },
    h("div", { class: "card" }, h("h2", {}, T("Στοιχεία έργου", "Project data")), h("div", { class: "grid g2" },
      txt(T("Όνομα", "Name"), S.lang === "el" ? p.name : p.name_en, (v) => save(S.lang === "el" ? { name: v } : { name_en: v })),
      txt(T("Διεύθυνση", "Address"), loc.address, (v) => save({ meta: { location: { address: v } } })),
      num(T("Συνολική επιφάνεια ορόφων (m²) – με υπόγειο", "Total floor area (m²) – incl. basement"), m.gfa_m2, (v) => save({ meta: { gfa_m2: v } })),
      num(T("Θερμαινόμενη επιφάνεια (m²)", "Conditioned area (m²)"), m.conditioned_area_m2, (v) => save({ meta: { conditioned_area_m2: v } })),
      num(T("Διαμερίσματα", "Apartments"), m.apartments, (v) => save({ meta: { apartments: v } }), 1),
      num(T("Ύψος (m)", "Height (m)"), m.height_m, (v) => save({ meta: { height_m: v } })),
      num(T("Πληθυσμός (άτομα)", "Population"), m.population, (v) => save({ meta: { population: v } }), 1),
      num(T("Φυτεμένη επιφάνεια (m²) – 0 = εκτίμηση", "Planted area (m²) – 0 = estimate"), m.planting_m2, (v) => save({ meta: { planting_m2: v } })),
      num(T("Εμβαδόν εκσκαφής (m²) – 0 = εκτίμηση", "Excavation area (m²) – 0 = estimate"), (m.excavation || {}).area_m2, (v) => save({ meta: { excavation: { area_m2: v } } })),
      num(T("Βάθος εκσκαφής (m) – 0 = από υπόγειο", "Excavation depth (m) – 0 = from basement"), (m.excavation || {}).depth_m, (v) => save({ meta: { excavation: { depth_m: v } } })))),
    h("div", { class: "card" }, h("h2", {}, T("Φέρων οργανισμός και σεισμική δράση", "Structure and seismic parameters")), h("div", { class: "grid g3" },
      num("a_g (g)", st.a_g, (v) => save({ meta: { structure: { a_g: v } } }), 0.01),
      field(T("Έδαφος", "Soil"), select([["A", "A"], ["B", "B"], ["C", "C"], ["D", "D"]], st.soil, (v) => save({ meta: { structure: { soil: v } } }))),
      num("q", st.q, (v) => save({ meta: { structure: { q: v } } }), 0.1),
      num("T1 (s)", st.T1, (v) => save({ meta: { structure: { T1: v } } }), 0.01), num("T2 (s)", st.T2, (v) => save({ meta: { structure: { T2: v } } }), 0.01), num("β0", st.beta0, (v) => save({ meta: { structure: { beta0: v } } }), 0.1),
      num("Tx (s)", st.Tx, (v) => save({ meta: { structure: { Tx: v } } }), 0.01), num("Ty (s)", st.Ty, (v) => save({ meta: { structure: { Ty: v } } }), 0.01)))));

  // uploads
  const status = h("div", { class: "small mutedt", style: { marginTop: "8px" } });
  const layerBox = h("div");
  const mk = (title, sub, accept, handler) => {
    const inp = h("input", { type: "file", accept, multiple: true, style: { display: "none" } });
    const dz = h("div", { class: "dropzone", onclick: () => inp.click() }, h("b", {}, title), h("small", {}, sub));
    const go = async (files) => { for (const f of files) await handler(f); };
    inp.onchange = () => go(inp.files);
    dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("over"); }; dz.ondragleave = () => dz.classList.remove("over");
    dz.ondrop = (e) => { e.preventDefault(); dz.classList.remove("over"); go(e.dataTransfer.files); };
    return h("div", {}, dz, inp);
  };
  const upload = async (f, kind) => {
    status.replaceChildren(spinner(), " " + T("Ανέβασμα και ανάλυση: ", "Uploading and analysing: ") + f.name);
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await api(`/projects/${S.pid}/upload`, { method: "POST", body: fd });
      status.textContent = "✓ " + f.name; toast(T("Ολοκληρώθηκε: ", "Done: ") + f.name);
      await window.reloadProject(true);
      if (r.kind === "model") { S.lastLayers = r.layers; }
    } catch (e) { status.textContent = ""; toast(e.message, true); }
  };
  root.append(h("div", { class: "grid g2" },
    h("div", { class: "card" }, h("h2", {}, T("Σχέδια (PDF / DXF)", "Drawings (PDF / DXF)")), mk(T("Σύρετε ή επιλέξτε σχέδια", "Drop or choose drawings"), T("κατόψεις, τομές, όψεις, ξυλότυποι, πίνακες", "plans, sections, elevations, formwork, tables"), ".pdf,.dxf", (f) => upload(f, "plan"))),
    h("div", { class: "card" }, h("h2", {}, T("Μοντέλο 3D (GLB / OBJ / IFC / 3DM)", "3D model (GLB / OBJ / IFC / 3DM)")), mk(T("Σύρετε ή επιλέξτε το 3D", "Drop or choose the 3D"), T("Για πολύ μεγάλα αρχεία Rhino εξάγετε ελαφρύ GLB/OBJ ανά layer", "For very large Rhino files export a light GLB/OBJ per layer"), ".glb,.gltf,.obj,.ifc,.3dm,.stl,.ply", (f) => upload(f, "model")))), status);

  // uploaded files, sizes and limits
  const filesCard = h("div", { class: "card" });
  const drawFiles = async () => {
    try {
      const r = await api(`/projects/${S.pid}/files`), L = r.limits;
      filesCard.replaceChildren(h("h2", {}, T("Αρχεία του έργου", "Project files") + ` (${r.count} / ${L.files_per_project} · ${fmt(r.total_mb, 1)} / ${fmt(L.project_mb, 0)} MB)`),
        h("p", { class: "small mutedt" }, T(`Όρια: έως ${L.files_per_project} αρχεία ανά έργο, ${L.file_mb} MB ανά σχέδιο/PDF, ${L.model_mb} MB για το 3D, ${fmt(L.project_mb, 0)} MB συνολικά. Το 3D είναι ένα ανά έργο (νέο ανέβασμα αντικαθιστά το προηγούμενο). Ανεβάστε πολλά αρχεία μαζί επιλέγοντάς τα ή σύροντάς τα όλα μαζί.`, `Limits: up to ${L.files_per_project} files per project, ${L.file_mb} MB per drawing/PDF, ${L.model_mb} MB for the 3D, ${fmt(L.project_mb, 0)} MB in total. One 3D model per project (a new upload replaces it).`)),
        r.files.length ? h("table", { class: "small" }, h("tbody", {}, r.files.map((f) => h("tr", {}, h("td", {}, f.name), h("td", { class: "n" }, fmt(f.mb, 2) + " MB"),
          h("td", { class: "n" }, h("button", { class: "btn small ghost", onclick: async () => { if (!confirm(T(`Διαγραφή αρχείου ${f.name};`, `Delete file ${f.name}?`))) return; try { await api(`/projects/${S.pid}/files/${encodeURIComponent(f.name)}`, { method: "DELETE" }); await window.reloadProject(true); } catch (e) { toast(e.message, true); } } }, "🗑"))))))
          : h("p", { class: "small mutedt" }, T("Δεν έχουν ανέβει αρχεία.", "No files uploaded.")));
    } catch (e) { filesCard.replaceChildren(h("p", { class: "small" }, e.message)); }
  };
  root.append(filesCard); drawFiles();

  // layer mapping
  const lay = h("div", { class: "card" }, h("h2", {}, T("Αντιστοίχιση layers → στοιχεία BIM", "Layer → BIM element mapping")), layerBox);
  root.append(lay);
  const renderLayers = async () => {
    const r = await api(`/projects/${S.pid}/layers`);
    if (!r.layers.length) { layerBox.replaceChildren(h("p", { class: "mutedt" }, T("Δεν υπάρχει μοντέλο ακόμη.", "No model yet."))); return; }
    const map = {};
    const rows = r.layers.map((l) => h("tr", {}, h("td", {}, l.layer || "—"), h("td", { class: "n" }, fmt(l.count)), h("td", { class: "n" }, fmt(l.volume_m3, 1)),
      h("td", {}, r.remappable ? select(r.kinds.map((k) => [k, kn(k)]), l.kind, (v) => (map[l.layer] = v)) : kn(l.kind))));
    layerBox.replaceChildren(...[
      !r.remappable ? h("p", { class: "small mutedt" }, T("Τα πηγαία αντικείμενα αυτού του έργου δεν είναι διαθέσιμα για επαναταξινόμηση (δημιουργήθηκε ως demo). Ανεβάστε 3D για να ταξινομήσετε layers.", "Source parts of this project are not available for re-mapping (created as demo). Upload a 3D file to map layers.")) : null,
      h("div", { class: "scroll", style: { maxHeight: "320px" } }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Layer"), h("th", { class: "n" }, T("Πλήθος", "Count")), h("th", { class: "n" }, T("Όγκος m³", "Volume m³")), h("th", {}, T("Τύπος στοιχείου", "Element type")))), h("tbody", {}, rows))),
      r.remappable ? h("div", { class: "row end", style: { marginTop: "8px" } }, h("button", { class: "btn", onclick: async (e) => { e.target.disabled = true; try { await api(`/projects/${S.pid}/layers/map`, { method: "POST", body: { map } }); await window.reloadProject(true); toast(T("Το μοντέλο ξαναχτίστηκε", "Model rebuilt")); } catch (er) { toast(er.message, true); } } }, T("Εφαρμογή και επανυπολογισμός", "Apply and rebuild"))) : null].filter(Boolean));
  };
  renderLayers();

  // plans + checks
  const pl = await api(`/projects/${S.pid}/plans`);
  const plansCard = h("div", { class: "card" }, h("h2", {}, T("Σχέδια εισόδου και διασταύρωση με το 3D", "Input drawings and cross-check with the 3D")));
  if (pl.plans.length) {
    for (const f of pl.plans) {
      if (f.kind === "pdf") plansCard.append(h("h3", {}, `${f.name} (${f.pages_total} ${T("σελ.", "pages")})${f.scanned ? " – " + T("σκαναρισμένο", "scanned") : ""}`),
        h("div", { class: "thumbs" }, f.pages.filter((x) => x.thumb).slice(0, 12).map((x) => h("figure", {}, h("img", { src: `/api/projects/${S.pid}/plans/thumb/${encodeURIComponent(x.thumb)}`, loading: "lazy" }), h("figcaption", {}, `p.${x.page} ${x.scales.join(" ")} ${x.titles[0] || ""}`)))));
      else if (f.kind === "dxf") plansCard.append(h("h3", {}, `${f.name} (DXF ${f.dxf_version}) – ${f.size_m[0]}×${f.size_m[1]} m`), h("p", { class: "small" }, f.layers.slice(0, 14).map((l) => h("span", { class: "pill" }, `${l.layer} · ${l.entities}`))), h("p", { class: "small mutedt" }, (f.titles || []).join(" · ")));
    }
  } else plansCard.append(h("p", { class: "mutedt" }, T("Δεν έχουν ανέβει σχέδια ακόμη.", "No drawings uploaded yet.")));
  plansCard.append(h("h3", {}, T("Έλεγχοι συνέπειας", "Consistency checks")), ...pl.checks.map((c) => h("div", { class: "check" }, h("span", { class: "dot " + c.status }), h("span", {}, c[S.lang]))));
  root.append(plansCard);

  // model summary
  root.append(h("div", { class: "card" }, h("h2", {}, T("Στοιχεία μοντέλου ανά τύπο", "Model elements by type")), h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, T("Τύπος", "Type")), h("th", { class: "n" }, T("Πλήθος", "Count")), h("th", { class: "n" }, T("Όγκος m³", "Volume m³")))),
    h("tbody", {}, Object.entries(p.model).map(([k, v]) => h("tr", {}, h("td", {}, h("i", { style: { display: "inline-block", width: "10px", height: "10px", borderRadius: "3px", background: KIND_COLORS[k] || "#ccc", marginRight: "6px" } }), kn(k)), h("td", { class: "n" }, fmt(v.count)), h("td", { class: "n" }, fmt(v.volume_m3, 1))))))));
}

// the BIM dimensions as the tool uses them, aligned with the literature (Charef et al. 2018 and the standards of each dimension)
function dimensionsCard() {
  const rows = [
    ["3D", T("Γεωμετρία και πληροφορία των στοιχείων (ψηφιακό δίδυμο)", "Geometry and element information (digital twin)"), T("Στοιχεία τύπου IFC, ποσότητες, φέρων οργανισμός από τη στατική μελέτη", "IFC-type elements, quantities, structural frame from the static study"), "ISO 16739 (IFC), ISO 19650"],
    ["4D", T("Χρόνος", "Time"), T("Χρονοπρόγραμμα κατασκευής συνδεδεμένο με τα στοιχεία, διάρκεια ζωής στοιχείων", "Construction schedule linked to the elements, service life of components"), "ISO 15686-1"],
    ["5D", T("Κόστος", "Cost"), T("Κόστος κατασκευής από την προμέτρηση, κόστος κύκλου ζωής (LCC)", "Construction cost from the quantities, life-cycle cost (LCC)"), "ISO 15686-5, EN 15459"],
    ["6D", T("Βιωσιμότητα", "Sustainability"), T("Ενεργειακή απόδοση (πρωτογενής ενέργεια, κλάση), άνθρακας κύκλου ζωής (λειτουργίας και ενσωματωμένος), κλίμα της θέσης", "Energy performance (primary energy, class), whole-life carbon (operational and embodied), site climate"), "EN 15978, ISO 52000 / ΚΕΝΑΚ, EPBD 2024/1275"],
    ["7D", T("Διαχείριση εγκαταστάσεων και περιουσιακών στοιχείων", "Facility and asset management"), T("Ιδιοκτησίες και επιμερισμός δαπανών, μητρώο εγκαταστάσεων, συντήρηση. Διαχείριση κινδύνων: σεισμός, φωτιά, πλημμύρα, αναμενόμενη ετήσια απώλεια, ανθεκτικότητα", "Properties and cost allocation, asset register, maintenance. Risk management: earthquake, fire, flood, expected annual loss, resilience"), "ISO 41001, ISO 55000, ISO 31000, FEMA P-58"],
  ];
  return h("div", { class: "card" }, h("h2", {}, T("Οι διαστάσεις του BIM στο εργαλείο", "The BIM dimensions in the tool")),
    h("p", { class: "small" }, T("Μετά την τρίτη διάσταση δεν υπάρχει ενιαίος ορισμός. Το εργαλείο ακολουθεί την πλειονότητα των επαγγελματιών στην έρευνα των Charef κ.ά. (2018): το 6D είναι η βιωσιμότητα (86 %) και το 7D η διαχείριση εγκαταστάσεων (85 %). Οι κίνδυνοι κατά τη λειτουργία εντάσσονται στο 7D ως διαχείριση κινδύνων των περιουσιακών στοιχείων (ISO 55000, ISO 31000). Το «8D» της ασφάλειας στην κατασκευή (Kamardeen 2010) δεν καλύπτεται. Σε κάθε διάσταση δηλώνονται ρητά η πληροφορία και το πρότυπο, όπως προτείνει το NBS.",
      "Beyond the third dimension there is no single definition. The tool follows the majority of practitioners in the survey of Charef et al. (2018): 6D is sustainability (86 %) and 7D facility management (85 %). Risks during operation belong to 7D as risk management of the assets (ISO 55000, ISO 31000). The construction-safety \u201c8D\u201d (Kamardeen 2010) is not covered. Each dimension states its information and standard explicitly, as the NBS suggests.")),
    h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, T("Διάσταση", "Dimension")), h("th", {}, T("Θέμα", "Subject")), h("th", {}, T("Τι περιέχει στο εργαλείο", "What it contains in the tool")), h("th", {}, T("Πρότυπα", "Standards")))),
      h("tbody", {}, rows.map(([d, a, b, c]) => h("tr", {}, h("td", {}, h("b", {}, d)), h("td", {}, a), h("td", { class: "small" }, b), h("td", { class: "small" }, c))))));
}

// ------------------------------------------------------------------ MODEL 3D
export async function modelView(root) {
  root.append(h("h1", {}, T("Μοντέλο 3D και 4D", "3D model and 4D")), h("p", { class: "lead" }, T("Περιστροφή: αριστερό κλικ · μετακίνηση: δεξί κλικ · ζουμ: τροχός (προς τον δείκτη) · διπλό κλικ: εστίαση στο στοιχείο. Κλικ σε στοιχείο για ιδιότητες. Λειτουργίες: τύπος, όροφος, 4D (πρόοδος κατασκευής), ζημιές από σενάριο κινδύνου.", "Rotate: left click · pan: right click · zoom: wheel (towards the pointer) · double click: focus on the element. Click an element for its properties. Modes: type, storey, 4D (construction progress), hazard damage.")));
  const glwrap = h("div", { id: "glwrap" });
  const hud = h("div", { id: "glhud" });
  const info = h("div", { class: "card small" }, T("Κάντε κλικ σε στοιχείο.", "Click an element."));
  const legend = h("div", { class: "legend" });
  const side = h("div", { class: "side" });
  const modeSeg = h("div", { class: "seg" });
  let els = S.cache.els;
  if (!els || S.cache.elsPid !== S.pid || S.cache.elsVer !== S.project.element_count) {
    const r = await api(`/projects/${S.pid}/elements?limit=20000`);
    els = Object.fromEntries(r.elements.map((e) => [e.id, e])); S.cache.els = els; S.cache.elsPid = S.pid; S.cache.elsVer = S.project.element_count;
  }
  root.append(h("div", { class: "viewer-wrap" }, h("div", {}, glwrap), side));
  glwrap.append(hud);
  if (!viewer) { viewer = new Viewer(); window.__viewer = viewer; }
  const holder = h("div", { style: { position: "absolute", inset: 0 } }); glwrap.prepend(holder); viewer.attach(holder);
  const vb = (k, l) => h("button", { class: "btn small", onclick: () => viewer.view(k) }, l);
  glwrap.append(h("div", { class: "viewbar" }, vb("home", "⌂ " + T("Αρχική", "Home")), vb("front", T("Πρόσοψη", "Front")), vb("side", T("Πλάγια", "Side")), vb("back", T("Πίσω", "Back")), vb("top", T("Κάτοψη", "Top"))));
  let range = null;
  if (viewerPid !== S.pid + ":" + S.project.element_count + ":" + (S.cache.glbv || 0)) {
    hud.replaceChildren(h("div", { class: "hud" }, spinner(), " " + T("Φόρτωση μοντέλου…", "Loading model…")));
    try { range = await viewer.load(`/api/projects/${S.pid}/model.glb?v=${Date.now()}`, els, S.project.storeys); viewerPid = S.pid + ":" + S.project.element_count + ":" + (S.cache.glbv || 0); }
    catch (e) { hud.replaceChildren(h("div", { class: "hud" }, T("Δεν υπάρχει μοντέλο 3D: ", "No 3D model: ") + e.message)); return; }
    hud.replaceChildren();
  } else { range = { min: viewer.bounds.min.y, max: viewer.bounds.max.y }; viewer.elMap = els; }
  viewer.onPick = (id) => {
    if (!id) { info.replaceChildren(T("Κάντε κλικ σε στοιχείο.", "Click an element.")); return; }
    const e = els[id]; const st = S.project.storeys.find((s) => s.id === e.storey);
    const rows = [[T("Κωδικός", "ID"), id], [T("Όνομα", "Name"), e.name], [T("Τύπος", "Type"), kn(e.kind) + " (" + e.ifc_class + ")"], [T("Όροφος", "Storey"), st ? st[S.lang === "el" ? "name_el" : "name_en"] : "—"], [T("Υλικό", "Material"), e.material], [T("Layer", "Layer"), e.layer], [T("Όγκος", "Volume"), e.volume_m3 != null ? fmt(e.volume_m3, 2) + " m³" : "—"], [T("Επιφάνεια", "Area"), e.area_m2 != null ? fmt(e.area_m2, 2) + " m²" : "—"], [T("Μήκος", "Length"), e.length_m != null ? fmt(e.length_m, 2) + " m" : "—"]];
    if (S.damage && S.damage[id] !== undefined) rows.push([T("Λόγος ζημιάς", "Damage ratio"), pct(S.damage[id], 1)]);
    info.replaceChildren(h("table", {}, h("tbody", {}, rows.map(([a, b]) => h("tr", {}, h("td", { class: "mutedt" }, a), h("td", {}, b))))));
  };
  // controls
  let mode = S.damage ? "damage" : "real";
  const setLegend = () => {
    legend.replaceChildren();
    if (mode === "real") for (const [c, l] of [["#efebe4", T("Λευκός σοβάς", "White render")], ["#8f8378", T("Πλαίσια εξωστών", "Balcony frames")], ["#8a6242", T("Ξύλο (επενδύσεις, ζαρντινιέρες, πόρτες)", "Timber (cladding, planters, gates)")], ["#33373b", T("Κάγκελα (ανθρακί)", "Fences (anthracite)")], ["#5d5f61", T("Ράμπα υπογείου", "Basement ramp")], ["#86a364", T("Γκαζόν / φύτευση", "Lawn / planting")], ["#c9c7c1", T("Πλακοστρώσεις", "Paving")]]) legend.append(h("span", {}, h("i", { style: { background: c } }), l));
    else if (mode === "type") for (const k of [...new Set(Object.values(els).map((e) => e.kind))]) legend.append(h("span", {}, h("i", { style: { background: KIND_COLORS[k] } }), kn(k)));
    else if (mode === "storey") S.project.storeys.forEach((s, i) => legend.append(h("span", {}, h("i", { style: { background: ["#6250d6", "#2a78d6", "#1baf7a", "#eda100", "#eb6834", "#e87ba4", "#008300", "#e34948"][i % 8] } }), s[S.lang === "el" ? "name_el" : "name_en"])));
    else if (mode === "4d") legend.append(h("span", {}, h("i", { style: { background: "#e6dccb" } }), T("Ολοκληρώθηκε (χρώμα τύπου)", "Done (type colour)")), h("span", {}, h("i", { style: { background: "#eb6834" } }), T("Σε εξέλιξη", "In progress")), h("span", {}, h("i", { style: { background: "#dfe3e8", border: "1px solid #9aa5b4" } }), T("Δεν ξεκίνησε", "Not started")));
    else if (mode === "damage") legend.append(h("div", { style: { width: "100%" } }, h("div", { class: "small" }, S.damageLabel || T("Σενάριο ζημιάς", "Damage scenario")), h("div", { class: "ramp" }), h("div", { class: "row small", style: { justifyContent: "space-between" } }, h("span", {}, "0%"), h("span", {}, "≥60%"))));
  };
  const week = h("input", { type: "range", min: 0, max: 47, value: 47, step: 1 });
  const weekLbl = h("span", { class: "small" });
  let sched = null, playing = null;
  const apply4d = debounce(async () => {
    const w = Number(week.value);
    const r = await api(`/projects/${S.pid}/schedule/state?week=${w}`);
    viewer.setMode("4d", r.state);
    const active = (sched?.tasks || []).filter((t) => t.segments.some(([a, b]) => w >= a - 1 && w <= b)).map((t) => t.name);
    weekLbl.textContent = `${T("Εβδομάδα", "Week")} ${w} / ${sched?.weeks || 47} · ` + (active.join(", ") || "—");
  }, 120);
  let setMode = async (m) => {
    mode = m; [...modeSeg.children].forEach((b) => b.classList.toggle("on", b.dataset.m === m));
    fourD.style.display = m === "4d" ? "block" : "none";
    if (m === "4d") { if (!sched) { sched = await api(`/projects/${S.pid}/schedule`); week.max = sched.weeks; week.value = Math.min(week.value, sched.weeks); } apply4d(); }
    else if (m === "damage") viewer.setMode("damage", S.damage || {});
    else viewer.setMode(m);
    setLegend();
  };
  [["real", T("Υλικά", "Materials")], ["type", T("Τύπος", "Type")], ["storey", T("Όροφος", "Storey")], ["4d", "4D"], ["damage", T("Ζημιές", "Damage")]].forEach(([m, l]) => modeSeg.append(h("button", { "data-m": m, onclick: () => setMode(m) }, l)));
  const fourD = h("div", { style: { display: "none" } }, week, weekLbl, h("div", { class: "row", style: { marginTop: "6px" } }, h("button", { class: "btn small", onclick: (e) => { if (playing) { clearInterval(playing); playing = null; e.target.textContent = "▶ " + T("Αναπαραγωγή", "Play"); return; } e.target.textContent = "⏸ " + T("Παύση", "Pause"); if (Number(week.value) >= Number(week.max)) week.value = 0; playing = setInterval(() => { if (!week.isConnected) { clearInterval(playing); playing = null; return; } week.value = Number(week.value) + 1; apply4d(); if (Number(week.value) >= Number(week.max)) { clearInterval(playing); playing = null; e.target.textContent = "▶ " + T("Αναπαραγωγή", "Play"); } }, 450); } }, "▶ " + T("Αναπαραγωγή", "Play"))));
  week.oninput = apply4d;
  const stSel = select([["", T("Όλοι οι όροφοι", "All storeys")], ...S.project.storeys.map((s) => [s.id, s[S.lang === "el" ? "name_el" : "name_en"]])], "", (v) => viewer.setStorey(v || null));
  const cut = h("input", { type: "range", min: 0, max: 1000, value: 1000 });
  cut.oninput = () => { const y = range.min + (range.max - range.min + 0.1) * (cut.value / 1000); viewer.setClip(cut.value >= 1000 ? null : y); cutLbl.textContent = cut.value >= 1000 ? T("χωρίς τομή", "no cut") : `${fmt(y - range.min, 1)} m`; };
  const cutLbl = h("span", { class: "small mutedt" }, T("χωρίς τομή", "no cut"));
  // ---- damage animation + video
  if (viewer.anim) viewer.anim.dispose();
  viewer.afterRender = null;
  const overlay = h("canvas", { class: "ov" }); glwrap.append(overlay);
  const anim = new DamageAnim(viewer, els, S.project); window.__bimAnim = anim; let rec = null;
  const hasMeta = () => S.damage && S.damageMeta && ["seismic", "fire_internal", "wildfire", "flood"].includes(S.damageMeta.type);
  const tl = h("input", { type: "range", min: 0, max: 1000, value: 0 }), tlbl = h("span", { class: "small mutedt" }), playBtn = h("button", { class: "btn small" }, "▶ " + T("Αναπαραγωγή", "Play"));
  const recBtn = h("button", { class: "btn small primary" }, "🎥 " + T("Εγγραφή βίντεο", "Record video")), recMsg = h("div", { class: "small mutedt", style: { marginTop: "6px" } });
  const drawLive = () => { const w = glwrap.clientWidth, hh = glwrap.clientHeight, d = Math.min(window.devicePixelRatio || 1, 2); if (overlay.width !== Math.round(w * d)) { overlay.width = Math.round(w * d); overlay.height = Math.round(hh * d); } const c = overlay.getContext("2d"); c.clearRect(0, 0, overlay.width, overlay.height); if (anim.active && mode === "damage" && !(rec && rec.active)) drawOverlay(c, overlay.width, overlay.height, anim.info(), d * 0.8); };
  viewer.afterRender = drawLive;
  const setPlay = () => { playBtn.textContent = anim.playing ? "⏸ " + T("Παύση", "Pause") : "▶ " + T("Αναπαραγωγή", "Play"); };
  anim.onTick = (t, d) => { tl.value = Math.round((t / d) * 1000); tlbl.textContent = `${fmt(t, 1)} / ${fmt(d, 0)} s`; };
  anim.onEnd = () => { setPlay(); if (rec && rec.active) setTimeout(() => rec.stop(), 1800); };
  playBtn.onclick = () => { if (anim.playing) anim.pause(); else anim.play(); setPlay(); };
  tl.oninput = () => { anim.pause(); setPlay(); anim.seek((tl.value / 1000) * anim.dur); };
  const exag = select([["3", "×3"], ["8", "×8 (" + T("προεπιλογή", "default") + ")"], ["15", "×15"], ["25", "×25"]], "8", (v) => { anim.exag = Number(v); anim.seek(anim.t); });
  const orbit = h("input", { type: "checkbox", onchange: (e) => (anim.orbit = e.target.checked) });
  recBtn.onclick = () => {
    if (rec && rec.active) { rec.stop(); return; }
    try {
      rec = new VideoRecorder(viewer, anim); anim.seek(0);
      rec.onDone = (blob, ext) => {
        recBtn.textContent = "🎥 " + T("Εγγραφή βίντεο", "Record video"); const nm = `bim7d_${anim.type}_${S.pid}.${ext}`;
        const url = URL.createObjectURL(blob); window.__lastVideo = { url, size: blob.size, ext, type: blob.type };
        recMsg.replaceChildren(h("a", { href: url, download: nm, class: "btn small" }, "⬇ " + T("Λήψη βίντεο", "Download video") + ` (${ext.toUpperCase()}, ${fmt(blob.size / 1048576, 1)} MB)`));
        const a = h("a", { href: url, download: nm }); document.body.append(a); a.click(); a.remove();
      };
      rec.start(); recBtn.textContent = "⏹ " + T("Διακοπή εγγραφής", "Stop recording"); recMsg.textContent = "● REC — " + T("το βίντεο αποθηκεύεται αυτόματα όταν τελειώσει η προσομοίωση. Μπορείτε να γυρίσετε την κάμερα όσο γράφει.", "the video is saved automatically when the simulation ends. You may orbit the camera while it records.");
      anim.play(); setPlay();
    } catch (e) { recMsg.textContent = e.message; }
  };
  const animCard = h("div", { class: "card", style: { display: "none" } }, h("h3", { style: { marginTop: 0 } }, T("Προσομοίωση και βίντεο ζημιών", "Damage simulation and video")),
    h("div", { class: "small mutedt", style: { marginBottom: "8px" } }, S.damageLabel), h("div", { class: "row" }, playBtn, h("button", { class: "btn small", onclick: () => { anim.pause(); anim.seek(0); setPlay(); } }, "⟲")), tl, tlbl,
    field(T("Υπερβολή κίνησης (σεισμός)", "Motion exaggeration (earthquake)"), exag), h("label", { class: "chk" }, orbit, T("Αργή περιστροφή κάμερας", "Slow camera orbit")), h("div", { style: { marginTop: "8px" } }, recBtn), recMsg,
    h("p", { class: "small mutedt", style: { marginBottom: 0 } }, T("Η κίνηση είναι σχηματική και υπερβολική κλίμακας· τα χρώματα προέρχονται από τα αποτελέσματα του σεναρίου. Το βίντεο γράφεται στον περιηγητή (MP4 ή WebM) με πληροφορίες σεναρίου και μετρητή ζημιάς.", "Motion is schematic and exaggerated; colours come from the scenario results. The video is recorded in the browser (MP4 or WebM) with scenario information and a running loss counter.")));
  const prevSet = setMode;
  setMode = async (m) => { anim.pause(); setPlay(); anim.reset(); await prevSet(m); if (m === "damage" && hasMeta()) { animCard.style.display = "block"; anim.setup(S.damageMeta, S.damage, S.damageLabel); anim.exag = Number(exag.value); } else animCard.style.display = "none"; };
  side.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, T("Λειτουργία προβολής", "View mode")), modeSeg, h("div", { style: { marginTop: "10px" } }, legend), fourD), animCard,
    h("div", { class: "card" }, field(T("Απομόνωση ορόφου", "Isolate storey"), stSel), field(T("Τομή σε ύψος", "Cut at height"), h("div", {}, cut, cutLbl))),
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, T("Επιλεγμένο στοιχείο", "Selected element")), info));
  await setMode(mode);
}

// ------------------------------------------------------------------ QUANTITIES
export async function quantitiesView(root) {
  const r = await api(`/projects/${S.pid}/quantities`);
  const q = r.quantities, calc = r.calculated, ov = new Set(r.overridden);
  const names = { excavation_area_m2: ["Εμβαδόν εκσκαφής (διάγραμμα)", "Excavation area (diagram)", "m²"], excavation_depth_m: ["Βάθος εκσκαφής", "Excavation depth", "m"], excavation_haul_m3: ["Μεταφορά προϊόντων εκσκαφής (χαλαρός όγκος)", "Excavated soil to haul (loose)", "m³"], waterproof_basement_m2: ["Στεγάνωση υπογείου", "Basement waterproofing", "m²"], basement_floor_m2: ["Δάπεδο υπογείου", "Basement floor", "m²"], fence_length_m: ["Περίφραξη", "Fence", "m"], coverage_m2: ["Κάλυψη", "Coverage", "m²"], planting_area_m2: ["Φυτεμένη επιφάνεια", "Planted area", "m²"], excavation_m3: ["Εκσκαφές", "Excavation", "m³"], backfill_m3: ["Επιχώσεις", "Backfill", "m³"], concrete_foundation_m3: ["Σκυρόδεμα θεμελίωσης", "Foundation concrete", "m³"], formwork_foundation_m2: ["Ξυλότυποι θεμελίωσης", "Foundation formwork", "m²"], rebar_foundation_kg: ["Οπλισμός θεμελίωσης", "Foundation rebar", "kg"], concrete_structure_m3: ["Σκυρόδεμα ανωδομής", "Superstructure concrete", "m³"], formwork_structure_m2: ["Ξυλότυποι ανωδομής", "Superstructure formwork", "m²"], rebar_structure_kg: ["Οπλισμός ανωδομής", "Superstructure rebar", "kg"], masonry_external_m2: ["Εξωτερικές τοιχοποιίες", "External masonry", "m²"], masonry_internal_m2: ["Εσωτερικές τοιχοποιίες", "Internal masonry", "m²"], insulation_wall_m2: ["Θερμομόνωση όψεων", "Facade insulation", "m²"], plaster_m2: ["Επιχρίσματα", "Plaster", "m²"], paint_m2: ["Χρωματισμοί", "Painting", "m²"], floor_finish_m2: ["Δάπεδα", "Floors", "m²"], window_area_m2: ["Κουφώματα", "Windows", "m²"], interior_doors: ["Εσωτερικές πόρτες", "Interior doors", "τεμ./pcs"], railing_length_m: ["Κιγκλιδώματα", "Railings", "m"], pergola_area_m2: ["Πέργκολες", "Pergolas", "m²"], roof_area_m2: ["Δώμα/στέγη", "Roof", "m²"], gfa_m2: ["Συνολική επιφάνεια ορόφων (με υπόγειο)", "Total floor area (incl. basement)", "m²"], conditioned_area_m2: ["Θερμαινόμενη επιφάνεια", "Conditioned area", "m²"], site_area_m2: ["Περιβάλλων χώρος", "Site area", "m²"], paving_m2: ["Πλακοστρώσεις", "Paving", "m²"], planting_m2: ["Φυτεύσεις", "Planting", "m²"], apartments: ["Διαμερίσματα", "Apartments", "τεμ./pcs"], elevators: ["Ανελκυστήρες", "Elevators", "τεμ./pcs"] };
  const setOv = async (k, v) => { const cur = (await api(`/projects/${S.pid}/settings`)).settings.quantity_overrides || {}; cur[k] = v; await api(`/projects/${S.pid}/settings`, { method: "PATCH", body: { quantity_overrides: cur } }); window.render(); };
  const setAs = async (k, v) => { await api(`/projects/${S.pid}/settings`, { method: "PATCH", body: { assumptions: { [k]: v } } }); window.render(); };
  root.append(h("h1", {}, T("Προμέτρηση", "Quantity take-off")), h("p", { class: "lead" }, T("Οι ποσότητες προκύπτουν από το μοντέλο και τις παραδοχές. Μπορείτε να τροποποιήσετε οποιαδήποτε ποσότητα (κίτρινο πεδίο)· κενό = αυτόματη τιμή. Οι αλλαγές περνούν στο κοστολόγιο και στο PDF.", "Quantities come from the model and assumptions. Override any quantity (yellow field); empty = automatic. Changes flow to the cost estimate and the PDF.")));
  const rows = Object.keys(names).filter((k) => k in q).map((k) => h("tr", {}, h("td", {}, names[k][S.lang === "el" ? 0 : 1]), h("td", { class: "n mutedt" }, fmt(calc[k], 1)), h("td", { class: "n" }, numInput(ov.has(k) ? q[k] : null, (v) => setOv(k, v), { cls: ov.has(k) ? "ov" : "", step: "any" })), h("td", { class: "n" }, h("b", {}, fmt(q[k], 1))), h("td", { class: "mutedt" }, names[k][2])));
  const as = r.assumptions;
  const aLbl = { rebar_kg_m3_footing: ["Οπλισμός θεμελ. (kg/m³)", "Footing rebar (kg/m³)"], rebar_kg_m3_slab: ["Οπλισμός πλακών (kg/m³)", "Slab rebar (kg/m³)"], rebar_kg_m3_column: ["Οπλισμός υποστ. (kg/m³)", "Column rebar (kg/m³)"], rebar_kg_m3_beam: ["Οπλισμός δοκών (kg/m³)", "Beam rebar (kg/m³)"], rebar_kg_m3_wall: ["Οπλισμός τοίχων (kg/m³)", "Wall rebar (kg/m³)"], rebar_kg_m3_roof: ["Οπλισμός δώματος (kg/m³)", "Roof rebar (kg/m³)"], wall_insulation_cm: ["Πάχος μόνωσης όψεων (cm)", "Facade insulation (cm)"], internal_wall_m2_per_m2: ["Εσωτ. τοιχοποιία (m²/m²)", "Internal masonry (m²/m²)"], excavation_margin_m: ["Περιθώριο εκσκαφής (m)", "Excavation margin (m)"], excavation_extra_depth_m: ["Επιπλέον βάθος εκσκαφής (m)", "Extra excavation depth (m)"], doors_per_apartment: ["Πόρτες ανά διαμέρισμα", "Doors per apartment"], elevators: ["Ανελκυστήρες", "Elevators"], paving_share_of_site: ["Ποσοστό πλακοστρώσεων", "Paving share"], planting_share_of_site: ["Ποσοστό φυτεύσεων", "Planting share"] };
  root.append(h("div", { class: "grid g2" },
    h("div", { class: "card" }, h("div", { class: "scroll", style: { maxHeight: "640px" } }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, T("Εργασία", "Item")), h("th", { class: "n" }, T("Αυτόματο", "Auto")), h("th", { class: "n" }, T("Τροποποίηση", "Override")), h("th", { class: "n" }, T("Ισχύον", "Used")), h("th", {}, T("Μον.", "Unit")))), h("tbody", {}, rows)))),
    h("div", {}, h("div", { class: "card" }, h("h2", {}, T("Παραδοχές προμέτρησης", "Take-off assumptions")), h("div", { class: "grid g2" }, Object.keys(as).filter((k) => aLbl[k]).map((k) => field(aLbl[k][S.lang === "el" ? 0 : 1], numInput(as[k], (v) => setAs(k, v))))), h("p", { class: "small mutedt" }, T("Οι αναλογίες οπλισμού είναι τυπικές τιμές Αττικής· προσαρμόστε τις στη στατική μελέτη.", "Rebar ratios are typical values; adjust to the structural design."))),
      h("div", { class: "card" }, h("h2", {}, T("Σύνοψη υλικών", "Material summary")), h("table", {}, h("tbody", {}, [[T("Σκυρόδεμα (m³)", "Concrete (m³)"), fmt(r.totals.concrete_m3, 1)], [T("Οπλισμός (kg)", "Rebar (kg)"), fmt(r.totals.rebar_kg)], [T("Οπλισμός (kg/m³)", "Rebar (kg/m³)"), fmt(r.totals.rebar_kg_per_m3, 0)], [T("Σκυρόδεμα ανά m² δόμησης (m³/m²)", "Concrete per m² GFA (m³/m²)"), fmt(r.totals.concrete_m3_per_m2_gfa, 3)], [T("Ποσοστό υαλοπετασμάτων", "Glazing ratio"), pct(r.totals.glazing_ratio, 1)]].map(([a, b]) => h("tr", {}, h("td", {}, a), h("td", { class: "n" }, b)))))))));
}

// ------------------------------------------------------------------ COST
export async function costView(root) {
  const [r, so] = await Promise.all([api(`/projects/${S.pid}/cost`), api(`/projects/${S.pid}/settings`)]);
  const c = r.cost;
  const ovr = () => { so.price_overrides ||= {}; so.price_overrides.items ||= {}; so.price_overrides.overheads ||= {}; return so.price_overrides; };
  const savePO = async () => { await api(`/projects/${S.pid}/settings`, { method: "PATCH", body: { price_overrides: so.price_overrides, custom_cost_lines: so.custom_cost_lines } }); window.render(); };
  const setItem = (key, field, val) => { const it = (ovr().items[key] ||= {}); if (val === null || val === undefined) delete it[field]; else it[field] = val; if (!Object.keys(it).length) delete ovr().items[key]; savePO(); };
  root.append(h("h1", {}, T("Κοστολόγιο (5D)", "Cost estimate (5D)")), h("p", { class: "lead" }, T(`Τιμές μονάδας από ενδεικτικό τιμολόγιο (βάση ${r.price_book_base}) × τρέχοντες δείκτες τιμών (καρτέλα «Τιμές»). Επεξεργαστείτε ποσότητες, τιμές, ενεργοποίηση εργασιών και ποσοστά γενικών εξόδων· προσθέστε δικές σας γραμμές.`, `Unit prices from an indicative price book (base ${r.price_book_base}) × current price indices ("Prices" tab). Edit quantities, prices, enable/disable tasks and overhead percentages; add your own lines.`)));
  const oh = c.overheads;
  root.append(h("div", { class: "grid g4" }, kpi(eur(c.net), T("Καθαρό κόστος (χωρίς ΦΠΑ)", "Net cost (excl. VAT)"), `${T("με ΦΠΑ", "incl. VAT")}: ${eur(c.total_with_vat)}`), kpi(fmt(c.net_per_m2_gfa) + " €/m²", T("Κόστος ανά m² συνολικής επιφάνειας", "Cost per m² of total floor area"), T("με υπόγειο", "incl. basement")), kpi((c.index_effect_pct >= 0 ? "+" : "") + fmt(c.index_effect_pct, 1) + "%", T("Επίδραση δεικτών τιμών", "Price index effect"), T("σε σχέση με τη βάση", "vs. base period")), kpi(eur(c.direct), T("Άμεσο κόστος", "Direct cost"))));
  const trade = { mep: ["Η/Μ & ανελκυστήρας", "MEP & lift"], finishes: ["Φινιρίσματα", "Finishes"], structure: ["Φέρων οργανισμός", "Structure"], envelope: ["Κέλυφος", "Envelope"], site: ["Περιβάλλων χώρος", "Site"], earthworks: ["Χωματουργικά", "Earthworks"], general: ["Γενικά", "General"], other: ["Λοιπά", "Other"] };
  const rows = c.lines.map((l) => h("tr", { style: { opacity: l.disabled ? 0.45 : 1 } },
    h("td", {}, h("input", { type: "checkbox", checked: !l.disabled, onchange: (e) => setItem(l.key, "disabled", e.target.checked ? null : true) })),
    h("td", {}, l[S.lang === "el" ? "el" : "en"], h("span", { class: "pill", style: { marginLeft: "6px" } }, (trade[l.trade] || [l.trade, l.trade])[S.lang === "el" ? 0 : 1])), h("td", {}, l.unit),
    h("td", { class: "n" }, numInput(l.qty, (v) => setItem(l.key, "qty_override", v), { cls: (so.price_overrides?.items?.[l.key]?.qty_override != null) ? "ov" : "", w: "88px" })),
    h("td", { class: "n" }, numInput(l.price_base, (v) => setItem(l.key, "price", v), { cls: (so.price_overrides?.items?.[l.key]?.price != null) ? "ov" : "", w: "76px", step: "0.01" })),
    h("td", { class: "n mutedt" }, fmt(l.index_factor, 3)), h("td", { class: "n" }, fmt(l.price_now, 2)), h("td", { class: "n" }, h("b", {}, eur(l.total)))));
  const ohIn = (k, lbl) => field(lbl, numInput(oh[k], (v) => { ovr().overheads[k] = v; savePO(); }, { w: "70px" }));
  const custom = so.custom_cost_lines || [];
  root.append(h("div", { class: "card" }, h("div", { class: "row", style: { justifyContent: "space-between", marginBottom: "8px" } }, h("h2", { style: { margin: 0 } }, T("Αναλυτικό τιμολόγιο", "Itemised bill of quantities")),
      h("div", { class: "row" }, ohIn("general_expenses_pct", T("Γενικά έξοδα %", "General exp. %")), ohIn("profit_pct", T("Όφελος %", "Profit %")), ohIn("contingency_pct", T("Απρόβλεπτα %", "Contingency %")), ohIn("vat_pct", T("ΦΠΑ %", "VAT %")),
        h("button", { class: "btn small ghost", onclick: () => addLine() }, "+ " + T("Δική σας γραμμή", "Custom line")))),
    h("div", { class: "scroll", style: { maxHeight: "560px" } }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", {}, T("Εργασία", "Item")), h("th", {}, T("Μον.", "Unit")), h("th", { class: "n" }, T("Ποσότητα", "Quantity")), h("th", { class: "n" }, T("Τιμή βάσης €", "Base price €")), h("th", { class: "n" }, T("Δείκτης", "Index")), h("th", { class: "n" }, T("Τιμή τώρα €", "Price now €")), h("th", { class: "n" }, T("Σύνολο", "Total")))), h("tbody", {}, rows),
      h("tfoot", {}, [[T("Άμεσο κόστος", "Direct cost"), c.direct], [T(`Γενικά έξοδα (${oh.general_expenses_pct}%)`, `General expenses (${oh.general_expenses_pct}%)`), c.general_expenses], [T(`Όφελος (${oh.profit_pct}%)`, `Profit (${oh.profit_pct}%)`), c.profit], [T(`Απρόβλεπτα (${oh.contingency_pct || 0}%)`, `Contingency (${oh.contingency_pct || 0}%)`), c.contingency], [T("Σύνολο χωρίς ΦΠΑ", "Total excl. VAT"), c.net], [T(`ΦΠΑ (${oh.vat_pct}%)`, `VAT (${oh.vat_pct}%)`), c.vat], [T("ΓΕΝΙΚΟ ΣΥΝΟΛΟ", "GRAND TOTAL"), c.total_with_vat]].map(([a, b], i, arr) => h("tr", { class: i === 4 || i === arr.length - 1 ? "total" : "" }, h("td", { colspan: 7, class: "n" }, a), h("td", { class: "n" }, eur(b)))))))));
  function addLine() {
    const nm = h("input", { placeholder: T("Περιγραφή", "Description"), style: { width: "100%" } }), un = h("input", { value: "τεμ.", style: { width: "60px" } }), qt = h("input", { type: "number", value: 1 }), pr = h("input", { type: "number", value: 100 });
    modal(h("div", {}, h("h2", {}, T("Νέα γραμμή κόστους", "New cost line")), field(T("Περιγραφή", "Description"), nm), h("div", { class: "row" }, field(T("Μονάδα", "Unit"), un), field(T("Ποσότητα", "Quantity"), qt), field(T("Τιμή μονάδας €", "Unit price €"), pr)),
      h("div", { class: "row end", style: { marginTop: "12px" } }, h("button", { class: "btn ghost", onclick: closeModal }, T("Άκυρο", "Cancel")), h("button", { class: "btn", onclick: () => { so.custom_cost_lines = [...custom, { name: nm.value || "—", unit: un.value, qty: Number(qt.value), price: Number(pr.value), trade: "general", components: { general: 1 } }]; closeModal(); savePO(); } }, T("Προσθήκη", "Add")))));
  }
  if (custom.length) root.append(h("div", { class: "card" }, h("h2", {}, T("Δικές σας γραμμές", "Your custom lines")), custom.map((l, i) => h("div", { class: "row small" }, h("span", {}, `${l.name} — ${fmt(l.qty)} ${l.unit} × ${eur(l.price, 2)}`), h("button", { class: "btn small ghost", onclick: () => { so.custom_cost_lines = custom.filter((_, j) => j !== i); savePO(); } }, T("Διαγραφή", "Delete"))))));
  root.append(h("div", { class: "grid g2" }, h("div", { class: "card" }, h("h2", {}, T("Κόστος ανά ειδικότητα", "Cost by trade")), canvasBox("chTrade")), h("div", { class: "card" }, h("h2", {}, T("Ευαισθησία: +10% σε κάθε δείκτη", "Sensitivity: +10% in each index")), canvasBox("chSens"))));
  chart("chTrade", { type: "bar", data: { labels: Object.keys(c.by_trade).map((k) => (trade[k] || [k, k])[S.lang === "el" ? 0 : 1]), datasets: [{ data: Object.values(c.by_trade).map((v) => Math.round(v / 1000)), backgroundColor: PAL[0], borderRadius: 4 }] }, options: { indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: ax("k€"), y: { grid: { display: false } } } } });
  chart("chSens", { type: "bar", data: { labels: r.sensitivity.slice(0, 8).map((s) => s[S.lang === "el" ? "label_el" : "label_en"].slice(0, 36)), datasets: [{ data: r.sensitivity.slice(0, 8).map((s) => Math.round(s.delta_eur / 100) / 10), backgroundColor: PAL[1], borderRadius: 4 }] }, options: { indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: ax(T("k€ ανά +10%", "k€ per +10%")), y: { grid: { display: false } } } } });
  // Monte Carlo
  const mcBox = h("div", { class: "card" }, h("h2", {}, T("Κίνδυνος τιμών: Monte Carlo", "Price risk: Monte Carlo")), h("p", { class: "small mutedt" }, T("Κάθε εργασία κοστολογείται με στοχαστική πορεία των δεικτών της (τάση και μεταβλητότητα από την καρτέλα «Τιμές») μέχρι την εβδομάδα εκτέλεσής της.", "Each task is priced with the stochastic path of its indices (drift and volatility from the 'Prices' tab) up to its execution week.")));
  const mcOut = h("div"); const startIn = numInput(6, () => runMC(), { w: "70px", step: 1 });
  mcBox.append(h("div", { class: "row" }, field(T("Έναρξη σε (μήνες)", "Start in (months)"), startIn), h("button", { class: "btn small", onclick: () => runMC() }, T("Επανυπολογισμός", "Recalculate"))), mcOut);
  root.append(mcBox);
  async function runMC() {
    mcOut.replaceChildren(spinner());
    const m = await api(`/projects/${S.pid}/cost/montecarlo?start_months=${startIn.value || 0}&n=2500`);
    mcOut.replaceChildren(h("div", { class: "grid g4", style: { margin: "10px 0" } }, kpi(eur(m.today), T("Σήμερα", "Today")), kpi(eur(m.p50), "P50"), kpi(eur(m.p90), "P90", `+${fmt((m.p90 / m.today - 1) * 100, 1)}%`), kpi(eur(m.p10) + " – " + eur(m.p95), "P10 – P95")), canvasBox("chMC", "short"));
    chart("chMC", { type: "bar", data: { labels: m.edges.slice(0, -1).map((e, i) => fmt((e + m.edges[i + 1]) / 2000, 0)), datasets: [{ data: m.hist, backgroundColor: PAL[0], borderRadius: 2, barPercentage: 1, categoryPercentage: 0.95 }] }, options: { plugins: { legend: { display: false } }, scales: { x: ax(T("καθαρό κόστος (k€)", "net cost (k€)")), y: ax(T("σενάρια", "scenarios")) } } });
  }
  runMC();
}

// ------------------------------------------------------------------ SCHEDULE
export async function scheduleView(root) {
  const s = await api(`/projects/${S.pid}/schedule`);
  const cp = new Set(s.critical_path);
  root.append(h("h1", {}, T("Χρονοδιάγραμμα (4D)", "Schedule (4D)")), h("p", { class: "lead" }, T(`Το χρονοδιάγραμμα (${s.weeks} εβδομάδες) συνδέεται με τα στοιχεία του μοντέλου και με το κόστος κάθε εργασίας. Με πορτοκαλί η κρίσιμη διαδρομή. Δείτε την πρόοδο κατασκευής στο 3D (καρτέλα «Μοντέλο 3D» → 4D).`, `The schedule (${s.weeks} weeks) is linked to model elements and the cost of each task. Orange = critical path. See construction progress in 3D ("3D model" tab → 4D).`)));
  const grid = h("div", { class: "gantt" }, h("div", { class: "gr" }, h("div", { class: "gl" }, ""), h("div", { class: "gt", style: { background: "none", borderLeft: 0 } }, Array.from({ length: Math.floor(s.weeks / 5) + 1 }, (_, i) => i * 5).map((w) => h("span", { style: { position: "absolute", left: (w / s.weeks) * 100 + "%", fontSize: "10px", color: "#8a8984" } }, w)))));
  for (const t of s.tasks) grid.append(h("div", { class: "gr", title: `${t.name}: ${T("εβδ.", "wk")} ${t.start_week}–${t.end_week}` }, h("div", { class: "gl" }, `${t.id}. ${t.name}`), h("div", { class: "gt" }, t.segments.map(([a, b]) => h("div", { class: "gb" + (cp.has(t.id) ? " cp" : ""), style: { left: ((a - 1) / s.weeks) * 100 + "%", width: ((b - a + 1) / s.weeks) * 100 + "%" } })))));
  root.append(h("div", { class: "card" }, grid), h("div", { class: "grid g2" }, h("div", { class: "card" }, h("h2", {}, T("Καμπύλη S – αθροιστικό κόστος", "S-curve – cumulative cost")), canvasBox("chS")), h("div", { class: "card" }, h("h2", {}, T("Κόστος ανά εργασία (καθαρό)", "Cost by task (net)")), h("div", { class: "scroll", style: { maxHeight: "270px" } }, h("table", {}, h("tbody", {}, s.tasks.map((t) => h("tr", {}, h("td", {}, `${t.id}. ${t.name}`), h("td", { class: "n" }, `${t.weeks} ${T("εβδ.", "wk")}`), h("td", { class: "n" }, eur(s.cost_by_task[t.id] || 0))))))))));
  chart("chS", { type: "line", data: { labels: s.curve.map((c) => c.week), datasets: [{ label: T("Αθροιστικό (k€)", "Cumulative (k€)"), data: s.curve.map((c) => Math.round(c.cumulative / 1000)), borderColor: PAL[0], backgroundColor: "rgba(42,120,214,.10)", fill: true, pointRadius: 0, borderWidth: 2.4, tension: 0.25 }] }, options: { plugins: { legend: { display: false } }, scales: { x: ax(T("εβδομάδα", "week")), y: ax("k€") } } });
  // 4D extended to the life of the building: service life of each component and the years it is renewed
  const lifeCard = h("div", { class: "card" }, h("h2", {}, T("4D στον κύκλο ζωής: διάρκεια ζωής στοιχείων και αντικαταστάσεις", "4D over the life cycle: service life of components and replacements")), spinner());
  root.append(lifeCard);
  try {
    const f = await api(`/projects/${S.pid}/fm`), H = f.horizon;
    const lg = h("div", { class: "gantt" }, h("div", { class: "gr" }, h("div", { class: "gl" }, T("έτος λειτουργίας", "year in use")), h("div", { class: "gt", style: { background: "none", borderLeft: 0 } }, Array.from({ length: Math.floor(H / 5) + 1 }, (_, i) => i * 5).map((y) => h("span", { style: { position: "absolute", left: (y / H) * 100 + "%", fontSize: "10px", color: "#8a8a85" } }, String(y))))));
    for (const c of f.service_life) {
      const L_ = c.replace_every, segs = [];
      if (L_) { for (let y0 = 0, k = 0; y0 < H; y0 += L_, k++) segs.push([y0, Math.min(y0 + L_, H), k]); } else segs.push([0, H, 0]);
      lg.append(h("div", { class: "gr", title: L_ ? T(`${c.el}: αντικατάσταση κάθε ${L_} έτη (${Math.round(c.replace_pct * 100)}% του αρχικού κόστους)`, `${c.en}: replaced every ${L_} years`) : T(`${c.el}: χωρίς αντικατάσταση στον ορίζοντα (διάρκεια ζωής σχεδιασμού 50 έτη, EN 1990)`, `${c.en}: no replacement within the horizon (design working life 50 years, EN 1990)`) },
        h("div", { class: "gl" }, `${S.lang === "el" ? c.el : c.en}${L_ ? ` · ${L_} ${T("έτη", "y")}` : ""}`),
        h("div", { class: "gt", style: { backgroundImage: "none" } }, segs.map(([a, b, k]) => h("div", { class: "gb", style: { left: (a / H) * 100 + "%", width: `calc(${((b - a) / H) * 100}% - 2px)`, background: L_ ? (k % 2 ? "#7fb0ea" : "#2a78d6") : "#1baf7a" } })))));
    }
    lifeCard.replaceChildren(lifeCard.firstChild, h("p", { class: "small mutedt" }, T(`Κάθε γραμμή είναι ένα στοιχείο του κτιρίου· κάθε τμήμα είναι ένας κύκλος ζωής του μέχρι την αντικατάστασή του, στον ορίζοντα ${H} ετών της ανάλυσης κύκλου ζωής (ρυθμίζεται στο 5D). Ο φέρων οργανισμός (πράσινο) σχεδιάζεται για 50 έτη (EN 1990, κατηγορία 4) και δεν αντικαθίσταται. Οι διάρκειες είναι επεξεργάσιμες στο πρόγραμμα συντήρησης (5D) και τα έτη/κόστη των επεμβάσεων δίνονται στο ημερολόγιο του 7D.`, `Each row is a building component; each segment is one service life until its replacement, over the ${H}-year life-cycle horizon (set in 5D). The structure (green) has a 50-year design working life (EN 1990, category 4) and is not replaced. Lifetimes are editable in the maintenance plan (5D); the years and costs of the works are listed in the 7D calendar.`)), lg);
  } catch (e) { lifeCard.replaceChildren(lifeCard.firstChild, h("p", { class: "small" }, e.message)); }
}
