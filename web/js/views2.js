import { S, T, L, api, h, fmt, eur, pct, toast, modal, closeModal, debounce, chart, ax, canvasBox, kpi, clsChip, numInput, select, field, spinner, download, PAL } from "./util.js";

// ------------------------------------------------------------------ ENERGY
function classBar(classes, base, pkg) {
  const n = classes.length, pos = (r) => { let lo = 0; for (let i = 0; i < n; i++) { const hi = i === n - 1 ? 3.2 : classes[i][1]; if (r <= hi || i === n - 1) return (i + Math.min(1, Math.max(0, (r - lo) / (hi - lo)))) / n * 100; lo = hi; } return 100; };
  const cols = ["#0ca30c", "#5bb85b", "#9bcf53", "#d8d83a", "#fab219", "#ec835a", "#e34948", "#b83030", "#7a1f1f"];
  return h("div", { class: "bar-wrap" }, h("div", { class: "bar-class" }, classes.map(([nm], i) => h("div", { style: { background: cols[i], color: i === 2 || i === 3 || i === 4 ? "#222" : "#fff" } }, nm))),
    h("div", { class: "mk", style: { left: pos(base.ratio) + "%" } }, T("Αφετηρία", "Baseline") + " " + fmt(base.ratio, 2)), pkg ? h("div", { class: "mk b", style: { left: pos(pkg.ratio) + "%" } }, T("Πακέτο", "Package") + " " + fmt(pkg.ratio, 2)) : null);
}
const PNAME = { thickness_cm: ["Πάχος (cm)", "Thickness (cm)"], lambda: ["λ (W/mK)", "λ (W/mK)"], U_new: ["U (W/m²K)", "U (W/m²K)"], g_new: ["g", "g"], share_pct: ["Ποσοστό (%)", "Share (%)"], alpha_new: ["Απορροφητικότητα", "Absorptance"], fsh_summer: ["Σκίαση καλοκαίρι", "Summer shading"], fsh_winter: ["Σκίαση χειμώνα", "Winter shading"], kwp: ["Ισχύς (kWp)", "Power (kWp)"], pr: ["PR", "PR"], area_m2_per_kwp: ["m²/kWp", "m²/kWp"], scop: ["SCOP", "SCOP"], seer: ["SEER", "SEER"], kw_per_m2: ["kW/m²", "kW/m²"], efficiency: ["Απόδοση", "Efficiency"], fan_kwh_m2: ["Ανεμιστήρες kWh/m²", "Fans kWh/m²"], heating_factor: ["Συντ. θέρμανσης", "Heating factor"], cooling_factor: ["Συντ. ψύξης", "Cooling factor"] };

function liveNote(root, kind) {
  const box = h("div"); root.append(box);
  api(`/projects/${S.pid}/live?light=1`).then((l) => {
    const on = (l.use || {})[kind];
    const txt = kind === "climate"
      ? (on ? T(`Κλίμα υπολογισμού: το πραγματικό κλίμα της θέσης ${(l.climate_period || []).join("–")} (live, Open-Meteo/ERA5).`, `Climate used: the measured climate of the site ${(l.climate_period || []).join("–")} (live, Open-Meteo/ERA5).`) : T("Κλίμα υπολογισμού: τυπικό κλίμα ζώνης Β της μελέτης ΚΕΝΑΚ. Το κλίμα της θέσης από τα live δεδομένα μπορεί να ενεργοποιηθεί στην καρτέλα «Περιοχή – live δεδομένα».", "Climate used: typical zone-B climate of the KENAK study. The site climate from live data can be switched on in the “Site – live data” tab."))
      : (on ? T("Ετήσιες πιθανότητες σεισμού: από το ιστορικό της περιοχής (live, USGS) – καμπύλη σεισμικής επικινδυνότητας της θέσης.", "Annual earthquake probabilities: from the history of the area (live, USGS) – seismic hazard curve of the site.") : T("Ετήσιες πιθανότητες σεισμού: παραδοχές. Οι πιθανότητες από το ιστορικό των σεισμών της περιοχής μπορούν να ενεργοποιηθούν στην καρτέλα «Περιοχή – live δεδομένα».", "Annual earthquake probabilities: assumptions. Probabilities from the earthquake history of the area can be switched on in the “Site – live data” tab."));
    box.replaceChildren(h("div", { class: "card", style: { padding: "8px 14px" } }, h("span", { class: "pill", style: { marginRight: "8px" } }, on ? "live" : T("παραδοχή", "assumed")), h("span", { class: "small" }, txt), " ", h("a", { href: "#", onclick: (e) => { e.preventDefault(); window.go("site"); } }, T("→ Περιοχή", "→ Site"))));
  }).catch(() => {});
}

export async function energyView(root) {
  const settings = (await api(`/projects/${S.pid}/settings`)).settings;
  const state = { preset: settings.energy?.preset || "as_certified", selected: settings.energy?.selected || {} };
  root.append(h("h1", {}, T("Βιωσιμότητα και ενεργειακή απόδοση (6D)", "Sustainability and energy performance (6D)")), h("p", { class: "lead" }, T("Επιλέξτε αναβαθμίσεις (πάνελ οροφής, μόνωση, κουφώματα, Φ/Β, αντλία θερμότητας κ.ά.) και δείτε άμεσα τη νέα ενεργειακή κλάση, το κόστος και την απόσβεση. Το ισοζύγιο είναι μηνιαίο (ISO 13790) και βαθμονομημένο στο πιστοποιητικό ΚΕΝΑΚ του έργου· δεν είναι επίσημη πιστοποίηση.", "Pick upgrades (roof panel, insulation, windows, PV, heat pump…) and see the new energy class, cost and payback immediately. The monthly balance (ISO 13790) is calibrated to the project's KENAK certificate; it is not an official certificate.")));
  const out = h("div"), measureBox = h("div", { class: "grid g3" });
  const presetSel = h("div");
  liveNote(root, "climate");
  root.append(h("div", { class: "card" }, h("div", { class: "row" }, field(T("Αφετηρία (κατάσταση κτιρίου)", "Starting point (building condition)"), presetSel), h("span", { class: "small mutedt" }, T("Το «πιστοποιημένο» αναπαράγει το ΚΕΝΑΚ. Οι «υφιστάμενες» καταστάσεις δείχνουν τι δίνει κάθε αναβάθμιση σε παλαιότερο κτίριο.", "'As certified' reproduces KENAK. The 'existing' states show what each upgrade does in an older building.")))), measureBox, out);
  let busy = 0;
  const run = async () => {
    const my = ++busy;
    const r = await api(`/projects/${S.pid}/energy`, { method: "POST", body: { preset: state.preset, selected: state.selected } });
    if (my !== busy) return;
    const s = r.study, b = s.baseline, k = s.package;
    presetSel.replaceChildren(select(Object.entries(s.presets).map(([id, p]) => [id, p[S.lang === "el" ? "el" : "en"]]), state.preset, (v) => { state.preset = v; run(); }));
    measureBox.replaceChildren(...s.measures.map((m) => {
      const sel = state.selected[m.id]; const on = !!(sel && sel.enabled);
      return h("div", { class: "measure" + (on ? " on" : "") }, h("label", { class: "chk" }, h("input", { type: "checkbox", checked: on, onchange: (e) => { state.selected[m.id] = Object.assign(state.selected[m.id] || { params: {} }, { enabled: e.target.checked }); run(); } }), h("h4", { style: { margin: 0 } }, m[S.lang === "el" ? "el" : "en"])),
        h("p", {}, m[S.lang === "el" ? "hint_el" : "hint_en"]),
        h("div", { class: "row small", style: { gap: "8px", marginBottom: "6px" } }, Object.entries(m.params).filter(([, v]) => typeof v === "number").slice(0, 3).map(([p, v]) => h("label", { class: "f" }, (PNAME[p] || [p, p])[S.lang === "el" ? 0 : 1], numInput((state.selected[m.id]?.params || {})[p] ?? v, (nv) => { const cur = (state.selected[m.id] ||= { enabled: on, params: {} }); cur.params = cur.params || {}; cur.params[p] = nv; run(); }, { w: "70px" })))),
        h("div", { class: "nums" }, h("span", {}, "Δ ", h("b", {}, (m.delta_kwh_m2 > 0 ? "−" : "+") + fmt(Math.abs(m.delta_kwh_m2), 1)), " kWh/m²"), clsChip(m.class), h("span", {}, eur(m.cost_eur)), h("span", {}, m.payback_years ? fmt(m.payback_years, 1) + " " + T("έτη", "y") : "—")));
    }));
    const pkgOn = s.selected.length > 0;
    out.replaceChildren(
      h("div", { class: "card" }, h("h2", {}, T("Ενεργειακή κλάση", "Energy class")), classBar(s.classes, b, pkgOn ? k : null),
        h("div", { class: "grid g4" }, kpi(h("span", {}, clsChip(b.class), " " + fmt(b.primary_kwh_m2, 1)), T("Αφετηρία (kWh/m²·έτος πρωτ.)", "Baseline (kWh/m²·y primary)"), `${T("κτίριο αναφοράς", "reference")} ${fmt(b.reference_kwh_m2, 1)}`),
          kpi(pkgOn ? h("span", {}, clsChip(k.class), " " + fmt(k.primary_kwh_m2, 1)) : "—", T("Με επιλεγμένο πακέτο", "With selected package"), pkgOn ? `${s.selected.length} ${T("μέτρα", "measures")}` : T("επιλέξτε μέτρα", "select measures")),
          kpi(pkgOn ? eur(s.package_cost_eur) : "—", T("Κόστος πακέτου", "Package cost"), pkgOn ? `${T("εξοικονόμηση", "saving")} ${eur(s.package_saving_eur_year)}/${T("έτος", "y")}` : ""),
          kpi(pkgOn ? (s.package_payback_years ? fmt(s.package_payback_years, 1) + " " + T("έτη", "y") : "—") : "—", T("Απόσβεση", "Payback"), pkgOn ? `CO₂ ${fmt(k.co2_kg_m2, 1)} kg/m²·${T("έτος", "y")}` : `CO₂ ${fmt(b.co2_kg_m2, 1)} kg/m²·${T("έτος", "y")}`))),
      h("div", { class: "grid g2" }, h("div", { class: "card" }, h("h2", {}, T("Πρωτογενής ενέργεια ανά χρήση", "Primary energy by end-use")), canvasBox("chUse")), h("div", { class: "card" }, h("h2", {}, T("Μηνιαίες ανάγκες (ωφέλιμες)", "Monthly needs (useful)")), canvasBox("chMonth"))),
      baselineCard());
    const uses = [["heating", T("Θέρμανση", "Heating")], ["cooling", T("Ψύξη", "Cooling")], ["dhw", T("ΖΝΧ", "DHW")], ["ventilation_fans", T("Ανεμιστήρες", "Fans")], ["pv_credit", T("Πίστωση Φ/Β", "PV credit")]];
    chart("chUse", { type: "bar", data: { labels: [T("Αφετηρία", "Baseline"), T("Πακέτο", "Package")], datasets: uses.map(([key, lb], i) => ({ label: lb, data: [b.by_use[key], k.by_use[key]], backgroundColor: i === 4 ? PAL[5] : PAL[i], borderRadius: 3 })) }, options: { scales: { x: { stacked: true, grid: { display: false } }, y: Object.assign(ax("kWh/m²·" + T("έτος", "y")), { stacked: true }) } } });
    const mo = [T("Ιαν", "Jan"), T("Φεβ", "Feb"), T("Μαρ", "Mar"), T("Απρ", "Apr"), T("Μάι", "May"), T("Ιουν", "Jun"), T("Ιουλ", "Jul"), T("Αυγ", "Aug"), T("Σεπ", "Sep"), T("Οκτ", "Oct"), T("Νοε", "Nov"), T("Δεκ", "Dec")];
    const ln = (label, data, c, dash) => ({ label, data, borderColor: c, backgroundColor: c, borderWidth: 2.2, pointRadius: 0, borderDash: dash ? [5, 4] : [], tension: 0.3 });
    chart("chMonth", { type: "line", data: { labels: mo, datasets: [ln(T("Θέρμανση – αφετηρία", "Heating – baseline"), b.needs.heating_month, PAL[1]), ln(T("Ψύξη – αφετηρία", "Cooling – baseline"), b.needs.cooling_month, PAL[0]), ...(pkgOn ? [ln(T("Θέρμανση – πακέτο", "Heating – package"), k.needs.heating_month, PAL[1], true), ln(T("Ψύξη – πακέτο", "Cooling – package"), k.needs.cooling_month, PAL[0], true)] : [])] }, options: { scales: { y: ax("kWh/" + T("μήνα", "month")) } } });
  };
  function baselineCard() {
    const box = h("details", { class: "card" }, h("summary", { style: { cursor: "pointer", fontWeight: 600 } }, T("Επεξεργασία ενεργειακού μοντέλου αφετηρίας (κέλυφος, πιστοποιητικό)", "Edit baseline energy model (envelope, certificate)")));
    box.addEventListener("toggle", async () => {
      if (!box.open || box.dataset.l) return; box.dataset.l = 1;
      const b = await api(`/projects/${S.pid}/energy/baseline`); const e = b.envelope, c = b.certificate;
      const save = debounce(async () => { await api(`/projects/${S.pid}/energy/baseline`, { method: "PUT", body: b }); toast(T("Αποθηκεύτηκε", "Saved")); run(); }, 500);
      const n = (lbl, obj, key, st = "any") => field(lbl, numInput(obj[key], (v) => { obj[key] = v; save(); }, { step: st }));
      box.append(h("div", { class: "grid g4", style: { marginTop: "10px" } }, n(T("Τοίχοι A (m²)", "Walls A (m²)"), e.walls, "A"), n(T("Τοίχοι U", "Walls U"), e.walls, "U"), n(T("Δώμα A (m²)", "Roof A (m²)"), e.roof, "A"), n(T("Δώμα U", "Roof U"), e.roof, "U"),
        n(T("Ανοίγματα A (m²)", "Windows A (m²)"), e.windows, "A"), n(T("Ανοίγματα U", "Windows U"), e.windows, "U"), n("g", e.windows, "g"), n(T("Θερμογέφυρες (W/K)", "Thermal bridges (W/K)"), e, "thermal_bridges_WK"),
        n(T("Εναλλαγές αέρα (1/h)", "Air changes (1/h)"), b.ventilation, "ach"), n(T("Πιστοπ. πρωτ. kWh/m²", "Certified primary kWh/m²"), c, "primary_kwh_m2"), n(T("Κτίριο αναφοράς kWh/m²", "Reference bldg kWh/m²"), c, "reference_kwh_m2"), n(T("Θερμαιν. επιφάνεια m²", "Conditioned area m²"), b, "area_m2")),
        h("p", { class: "small mutedt" }, T("Σημείωση: το ενεργειακό μοντέλο είναι βαθμονομημένο στη διαφορά από το πιστοποιητικό. Αν αλλάξετε τιμές αφετηρίας, αλλάζει και το σημείο αναφοράς.", "Note: the model is calibrated on differences to the certificate. Changing baseline values moves the reference point.")));
    });
    return box;
  }
  await run();
  const lcaBox = h("div");
  root.append(lcaBox);
  await lifecycleView(lcaBox, "lca");
}

// ------------------------------------------------------------------ LIFECYCLE
export async function lifecycleView(root, mode = "lcc") {
  const LCA = mode === "lca";
  if (LCA) root.append(h("h2", { style: { marginTop: "22px" } }, T("Περιβαλλοντικό αποτύπωμα κύκλου ζωής (LCA, EN 15978)", "Life-cycle environmental footprint (LCA, EN 15978)")), h("p", { class: "lead" }, T("Ενσωματωμένος άνθρακας υλικών (A1–A5), αντικαταστάσεις (B4), λειτουργική ενέργεια (B6), τέλος ζωής (C) και πέραν των ορίων (D), στον ίδιο ορίζοντα με το κόστος κύκλου ζωής.", "Embodied carbon of the materials (A1–A5), replacements (B4), operational energy (B6), end of life (C) and beyond the system boundary (D), over the same horizon as the life-cycle cost.")));
  else root.append(h("h1", {}, T("Κόστος στον χρόνο: κατασκευή, συντήρηση, αντικαταστάσεις, ενέργεια (5D)", "Cost over time: construction, maintenance, replacements, energy (5D)")), h("p", { class: "lead" }, T("Κόστος κύκλου ζωής (LCC, EN 15459) με προεξόφληση: κόστος κατασκευής (έτος 0) και στη συνέχεια συντήρηση, περιοδικές επιθεωρήσεις, αντικαταστάσεις στοιχείων στο τέλος της ζωής τους, ενέργεια, ασφάλιστρα και καθαριότητα για κάθε έτος. Συγκρίνει το κτίριο ως έχει με το πακέτο ενεργειακών αναβαθμίσεων της καρτέλας «6D».", "Life-cycle cost (LCC, EN 15459) with discounting: construction cost (year 0), then maintenance, periodic inspections, replacements at the end of each component's life, energy, insurance and cleaning for every year. Compares the building as is with the energy-upgrade package of the '6D' tab.")));
  const out = h("div"), formBox = h("div", { class: "card" });
  root.append(formBox, out);
  const set = (await api(`/projects/${S.pid}/settings`));
  const a = {};
  const run = async () => {
    out.replaceChildren(spinner());
    const r = await api(`/projects/${S.pid}/lifecycle`, { method: "POST", body: { assumptions: a } });
    const A = r.base.assumptions;
    if (!formBox.dataset.f && !LCA) {
      formBox.dataset.f = 1;
      const f = (lbl, key, st) => field(lbl, numInput(A[key], (v) => { a[key] = v; run(); }, { step: st, w: "88px" }));
      formBox.append(h("h2", {}, T("Παραδοχές", "Assumptions")), h("div", { class: "row" }, f(T("Ορίζοντας (έτη)", "Horizon (years)"), "horizon_years", 1), f(T("Πραγματικό προεξοφλητικό %", "Real discount rate %"), "real_discount_pct", 0.1), f(T("Αύξηση τιμών ενέργειας %/έτος", "Energy price escalation %/y"), "energy_escalation_pct", 0.1),
        f(T("Έτος αναβάθμισης", "Retrofit year"), "retrofit_year", 1), f(T("Ασφάλιστρα % κατασκευής", "Insurance % of construction"), "insurance_pct_of_construction", 0.01), f(T("Καθαριότητα €/m²·έτος", "Cleaning €/m²·y"), "cleaning_eur_per_m2_gfa_year", 0.1), f(T("Υπολειμματική αξία % φορέα", "Residual value % structure"), "residual_value_pct_of_structure", 1)));
    }
    const b = r.base, u = r.upgrade, L_ = b.lca;
    const cmp = u ? ` (${T("με αναβαθμίσεις", "with upgrades")}: ${eur(u.npv_total)})` : "";
    if (LCA) {
      formBox.remove();
      out.replaceChildren(
        h("div", { class: "grid g3" }, kpi(fmt(L_.total_kg / 1000, 0) + " t", T(`Αποτύπωμα ${b.horizon} ετών (CO₂e)`, `${b.horizon}-year footprint (CO₂e)`), `${fmt(L_.per_m2_gfa)} kg/m² · ${L_.per_m2_gfa_year} kg/m²·${T("έτος", "y")}`), kpi(pct(L_.embodied_share_pct / 100, 0), T("Ενσωματωμένο μερίδιο", "Embodied share"), `${T("λειτουργικό", "operational")} ${fmt(100 - L_.embodied_share_pct, 0)}%`), kpi(fmt(L_.A1_A3_kg / 1000, 0) + " t", T("Υλικά κατασκευής (A1–A3)", "Construction materials (A1–A3)"))),
        h("div", { class: "grid g2", style: { marginTop: "14px" } }, h("div", { class: "card" }, h("h2", {}, T("LCA: στάδια", "LCA: modules")), canvasBox("chMod", "short")), h("div", { class: "card" }, h("h2", {}, T("LCA: ενσωματωμένος άνθρακας ανά ομάδα", "LCA: embodied carbon by group")), canvasBox("chGrp", "short"))),
        h("div", { class: "card" }, h("h2", {}, T("Κυριότερες συνεισφορές στο αποτύπωμα (A1–A3)", "Top carbon contributors (A1–A3)")), h("table", {}, h("tbody", {}, L_.by_item.map((i) => h("tr", {}, h("td", {}, i[S.lang === "el" ? "el" : "en"]), h("td", { class: "n" }, `${fmt(i.qty, 1)} ${i.unit}`), h("td", { class: "n" }, fmt(i.kg / 1000, 1) + " t")))))));
      chart("chMod", { type: "bar", data: { labels: ["A1–A3", "A4–A5", T("Αναβ.", "Upgr."), "B4", "B6", "C", "D"], datasets: [{ data: [L_.A1_A3_kg, L_.A4_A5_kg, L_.measures_kg, L_.B4_kg, L_.B6_kg, L_.C_kg, L_.D_kg].map((x) => Math.round(x / 100) / 10), backgroundColor: [PAL[0], PAL[2], PAL[3], PAL[1], PAL[6], PAL[4], PAL[5]], borderRadius: 3 }] }, options: { plugins: { legend: { display: false } }, scales: { y: ax("tCO₂e"), x: { grid: { display: false } } } } });
      const gk0 = Object.keys(L_.by_group);
      chart("chGrp", { type: "bar", data: { labels: gk0.map((k) => L_.groups[k][S.lang === "el" ? "el" : "en"]), datasets: [{ data: gk0.map((k) => Math.round(L_.by_group[k] / 100) / 10), backgroundColor: PAL[0], borderRadius: 3 }] }, options: { indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: ax("tCO₂e"), y: { grid: { display: false } } } } });
      return;
    }
    out.replaceChildren(
      h("div", { class: "grid g4" }, kpi(eur(b.npv_total), T(`Κόστος κύκλου ζωής ${b.horizon} ετών (ΠΑ)`, `${b.horizon}-year life-cycle cost (PV)`), u ? `${T("με αναβαθμίσεις", "with upgrades")}: ${eur(u.npv_total)}` : T("χωρίς πακέτο αναβαθμίσεων", "no upgrade package")), kpi(eur(b.annual_equivalent), T("Ισοδύναμο ετήσιο κόστος", "Equivalent annual cost"), `${fmt(b.npv_per_m2_gfa)} €/m²`),
        kpi(eur(b.npv_breakdown.construction), T("Κόστος κατασκευής (έτος 0)", "Construction cost (year 0)"), `${pct(b.npv_breakdown.construction / b.npv_total, 0)} ${T("του LCC", "of the LCC")}`), kpi(eur(b.undiscounted_total), T("Σύνολο χωρίς προεξόφληση", "Undiscounted total"), `${b.horizon} ${T("έτη", "years")}`)),
      h("div", { class: "grid g2", style: { marginTop: "14px" } }, h("div", { class: "card" }, h("h2", {}, T("Αθροιστικό προεξοφλημένο κόστος", "Cumulative discounted cost")), canvasBox("chCum")), h("div", { class: "card" }, h("h2", {}, T("Ανάλυση παρούσας αξίας", "Present-value breakdown")), canvasBox("chNpv"))),
      h("div", { class: "card" }, h("h2", {}, T("Ετήσιες ταμειακές ροές (χωρίς κατασκευή)", "Annual cash flows (excl. construction)")), canvasBox("chYear", "short")),
      h("div", { class: "card" }, h("h2", {}, T("Πρόγραμμα συντήρησης και αντικαταστάσεων (επεξεργάσιμο)", "Maintenance and replacement plan (editable)")),
        h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, T("Στοιχείο", "Component")), h("th", { class: "n" }, T("Αρχικό κόστος", "Initial cost")), h("th", { class: "n" }, T("Ετήσια συντήρηση %", "Annual maint. %")), h("th", { class: "n" }, T("Αντικατάσταση κάθε (έτη)", "Replace every (y)")), h("th", { class: "n" }, T("Ποσοστό αντικατάστασης", "Replaced share")), h("th", { class: "n" }, T("Ενσωματ. kgCO₂e", "Embodied kgCO₂e")))),
          h("tbody", {}, b.components.map((c) => { const sv = (k, v) => { const list = (set.maintenance_overrides || []).filter((o) => o.id !== c.id); const cur = Object.assign({ id: c.id }, (set.maintenance_overrides || []).find((o) => o.id === c.id) || {}, { [k]: v }); list.push(cur); set.maintenance_overrides = list; api(`/projects/${S.pid}/settings`, { method: "PATCH", body: { maintenance_overrides: list } }).then(run); };
            return h("tr", {}, h("td", {}, c[S.lang === "el" ? "el" : "en"]), h("td", { class: "n" }, eur(c.initial_cost)), h("td", { class: "n" }, numInput(c.annual_pct, (v) => sv("annual_pct", v), { w: "70px", step: 0.1 })), h("td", { class: "n" }, numInput(c.replace_every, (v) => sv("replace_every", v), { w: "70px", step: 1 })), h("td", { class: "n" }, numInput(c.replace_pct, (v) => sv("replace_pct", v), { w: "70px", step: 0.05 })), h("td", { class: "n" }, fmt(c.embodied_kg))); }))))),
        h("p", { class: "small mutedt" }, T("Τιμές τυπικού κύκλου ζωής στοιχείων (EN 15459/ΚΕΝΑΚ/εμπειρία). Αφήστε κενό «Αντικατάσταση» για καμία αντικατάσταση.", "Typical component lifetimes (EN 15459/KENAK/experience). Leave 'Replace every' empty for no replacement.")));
    const yrs = b.series.map((r) => r.year);
    const line = (label, d, c, dash) => ({ label, data: d, borderColor: c, borderWidth: 2.4, pointRadius: 0, borderDash: dash ? [5, 4] : [], tension: 0.2 });
    chart("chCum", { type: "line", data: { labels: yrs, datasets: [line(T("Αφετηρία", "Baseline"), b.series.map((r) => Math.round(r.cumulative_discounted / 1000)), PAL[0]), ...(u ? [line(T("Με αναβαθμίσεις", "With upgrades"), u.series.map((r) => Math.round(r.cumulative_discounted / 1000)), PAL[2])] : [])] }, options: { scales: { x: ax(T("έτος", "year")), y: ax("k€") } } });
    const keys = [["construction", T("Κατασκευή", "Construction")], ["retrofit", T("Αναβαθμίσεις", "Upgrades")], ["maintenance", T("Συντήρηση", "Maintenance")], ["replacement", T("Αντικαταστάσεις", "Replacements")], ["energy", T("Ενέργεια", "Energy")], ["other", T("Λοιπά", "Other")]];
    const sets = [[T("Αφετηρία", "Baseline"), b], ...(u ? [[T("Με αναβαθμίσεις", "With upgrades"), u]] : [])];
    chart("chNpv", { type: "bar", data: { labels: sets.map((s) => s[0]), datasets: keys.map(([k, lb], i) => ({ label: lb, data: sets.map((s) => Math.round(s[1].npv_breakdown[k] / 1000)), backgroundColor: PAL[i], borderRadius: 2 })) }, options: { scales: { x: { stacked: true, grid: { display: false } }, y: Object.assign(ax("k€"), { stacked: true }) } } });
    const yr = b.series.slice(1);
    chart("chYear", { type: "bar", data: { labels: yr.map((r) => r.year), datasets: [["maintenance", T("Συντήρηση", "Maintenance"), PAL[2]], ["replacement", T("Αντικαταστάσεις", "Replacements"), PAL[3]], ["energy", T("Ενέργεια", "Energy"), PAL[1]], ["other", T("Λοιπά", "Other"), PAL[6]]].map(([k, lb, c]) => ({ label: lb, data: yr.map((r) => Math.round(r[k] / 1000)), backgroundColor: c })) }, options: { scales: { x: Object.assign({ grid: { display: false } }, { stacked: true }), y: Object.assign(ax("k€"), { stacked: true }) } } });
  };
  await run();
}

// ------------------------------------------------------------------ HAZARDS
let hdef = null;
const HZ = { tab: "seismic", seismic: { code_level: "static", pilotis: false, plan_irregularity: false, mitigations: [], percentile: 50, scenario: "moderate" }, fire_internal: { mitigations: [], sprinkler: false, detector: false }, wildfire: { intensity_class: "high", distance_m: 12, slope_deg: 10, wind_kmh: 35, direction: "N", mitigations: [] }, flood: { mitigations: [], scenario: "moderate", custom: false } };
const showIn3D = (label, damage, meta) => { S.damage = damage; S.damageLabel = label; S.damageMeta = meta || null; window.go("model"); };

function mitChecks(kind) {
  const cat = hdef.mitigations[kind], cur = HZ[kind].mitigations;
  return h("div", { class: "row small", style: { alignItems: "flex-start" } }, Object.entries(cat).map(([id, m]) => h("label", { class: "chk" }, h("input", { type: "checkbox", checked: cur.includes(id), onchange: (e) => { if (e.target.checked) cur.push(id); else cur.splice(cur.indexOf(id), 1); } }), m[S.lang === "el" ? "el" : "en"])));
}
const post = (kind, params, all) => api(`/projects/${S.pid}/hazards/run`, { method: "POST", body: { kind, params, all } });
const lossKpis = (r) => h("div", { class: "grid g4" }, kpi(eur(r.loss_eur), T("Αναμενόμενη ζημιά", "Expected loss"), `${pct(r.loss_ratio, 1)} ${T("της αξίας αντικατάστασης", "of replacement value")}`), kpi("≈" + fmt(r.downtime_days) + " " + T("ημ.", "d"), T("Χρόνος εκτός χρήσης", "Downtime")), ...(r.type === "seismic" ? [kpi(fmt(r.pga_g, 3) + " g", "PGA", `${fmt(r.pga_over_design, 2)}× ${T("σχεδιασμού", "design")} · MMI ${r.intensity_mmi}`), kpi(pct(r.p_d3plus, 0), T("Πιθανότητα βλάβης ≥3", "P(damage ≥3)"), `${T("κατάρρευση", "collapse")} ${pct(r.p_collapse_d5, 1)}`)] : []));

export async function hazardsView(root) {
  if (!hdef) hdef = await api("/hazards/defaults");
  HZ.seismic.soil = HZ.seismic.soil || S.project.meta.structure.soil;
  root.append(h("h1", {}, T("Σενάρια κινδύνων και συμπεριφορά του κτιρίου", "Hazard scenarios and building behaviour")), h("div", { class: "warnbox" }, T("Εκτιμήσεις επιπέδου προμελέτης (screening) με διαφανείς, επεξεργάσιμες παραμέτρους. Δίνουν τάξη μεγέθους ζημιάς και σύγκριση μέτρων προστασίας — δεν αποτελούν στατικό έλεγχο (ΚΑΝ.ΕΠΕ.), μελέτη πυροπροστασίας ή υδραυλική μελέτη.", "Screening-level estimates with transparent, editable parameters. They give order of magnitude and compare protection measures — they are not a structural assessment, fire-safety design or hydraulic study.")));
  liveNote(root, "seismic_rates");
  const tabs = h("div", { class: "tabs" }), body = h("div");
  const T_ = [["seismic", T("Σεισμός", "Earthquake")], ["capacity", T("Αντοχή σε σεισμό (Ρίχτερ)", "Seismic resistance (Richter)")], ["fire_internal", T("Εσωτερική φωτιά", "Internal fire")], ["wildfire", T("Δασική πυρκαγιά", "Wildfire")], ["flood", T("Πλημμύρα", "Flood")], ["risk", T("Συνολικός κίνδυνος & μέτρα", "Overall risk & mitigation")]];
  const draw = async () => { [...tabs.children].forEach((b) => b.classList.toggle("on", b.dataset.t === HZ.tab)); body.replaceChildren(); await ({ seismic, capacity, fire_internal: fireInt, wildfire, flood, risk })[HZ.tab](body); };
  T_.forEach(([id, lb]) => tabs.append(h("button", { "data-t": id, onclick: () => { HZ.tab = id; draw(); } }, lb)));
  root.append(tabs, body); await draw();
}

async function seismic(b) {
  const z = HZ.seismic, d = hdef.seismic;
  if (z._pid !== S.pid) {                     // per project: static study if there is one, otherwise the code level of the year of construction
    const mm = S.project.meta; z._pid = S.pid; z.userMs = z.userD = null; z.scenario = "moderate";
    z.code_level = mm.structural ? "static" : (mm.structure && mm.structure.code_level_default) || "high";
  }
  const out = h("div");
  const codeSel = select(Object.entries(S.lang === "el" ? d.code_levels : (d.code_levels_en || d.code_levels)), z.code_level, (v) => (z.code_level = v));
  let cm = null;
  const runAll = async () => {
    out.replaceChildren(spinner());
    const common = { code_level: z.code_level, soil: z.soil, pilotis: z.pilotis, plan_irregularity: z.plan_irregularity, mitigations: z.mitigations, percentile: z.percentile };
    const res = await post("seismic", common, true);
    const runs = res.runs, order = ["small", "moderate", "large"];
    // the user's own earthquake is recomputed on every run with the current building parameters
    z.custom = z.userMs != null ? await post("seismic", { ...common, Ms: z.userMs, distance_km: z.userD ?? 10 }, false) : null;
    if (z.custom) runs.custom = z.custom;
    if (z.scenario === "custom" && !z.custom) z.scenario = "moderate";
    const sel = runs[z.scenario] || runs.moderate; const keys = Object.keys(runs);
    const lab = (r, k) => (k === "custom" ? T(`Δικός σας σεισμός Ms ${fmt(r.Ms, 1)} @ ${fmt(r.distance_km, 0)} km`, `Your earthquake Ms ${fmt(r.Ms, 1)} @ ${fmt(r.distance_km, 0)} km`) : r[S.lang === "el" ? "label_el" : "label_en"]);
    out.replaceChildren(
      h("div", { class: "card" }, h("h2", {}, T("Σύγκριση σεναρίων", "Scenario comparison")), h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, ["", T("Ms (Ρίχτερ) / km", "Ms (Richter) / km"), "PGA (g)", "×a_g", "MMI", T("Μέσος βαθμός", "Mean grade"), "P(D≥3)", T("Ζημιά", "Loss"), T("Λόγος", "Ratio"), T("Ημέρες εκτός", "Days out"), ""].map((x, i) => h("th", { class: i > 0 ? "n" : "" }, x)))),
        h("tbody", {}, keys.map((k) => { const r = runs[k]; return h("tr", { style: { background: k === z.scenario ? "#f5f9ff" : "" } }, h("td", {}, h("b", {}, lab(r, k))), h("td", { class: "n" }, `${r.Ms} / ${fmt(r.distance_km, 0)}`), h("td", { class: "n" }, fmt(r.pga_g, 3)), h("td", { class: "n" }, fmt(r.pga_over_design, 2)), h("td", { class: "n" }, r.intensity_mmi), h("td", { class: "n" }, fmt(r.mean_grade, 2)), h("td", { class: "n" }, pct(r.p_d3plus, 0)), h("td", { class: "n" }, eur(r.loss_eur)), h("td", { class: "n" }, pct(r.loss_ratio, 1)), h("td", { class: "n" }, r.downtime_days), h("td", {}, h("button", { class: "btn small ghost", onclick: () => { z.scenario = k; runAll(); } }, T("Λεπτομέρειες", "Details")))); })))),
        sel.capacity ? h("p", { class: "small" }, h("b", {}, T("Αντοχή του κτιρίου: ", "Building resistance: ")), T(`πρώτη διαρροή στα ${fmt(sel.capacity.pga_g.yield, 3)} g, εξάντληση πλαστιμότητας (οιονεί κατάρρευση) στα ${fmt(sel.capacity.pga_g.collapse, 3)} g (${fmt(sel.capacity.pga_over_design.collapse, 2)}× a_g σχεδιασμού) · πηγή: ${sel.capacity.method === "static_report" ? "τεύχος στατικών" : "διατομές μοντέλου (χονδρική)"}. Αναλυτικά στην καρτέλα «Αντοχή σε σεισμό (Ρίχτερ)».`, `first yield at ${fmt(sel.capacity.pga_g.yield, 3)} g, ductility exhausted (near-collapse) at ${fmt(sel.capacity.pga_g.collapse, 3)} g (${fmt(sel.capacity.pga_over_design.collapse, 2)}× design a_g) · source: ${sel.capacity.method === "static_report" ? "static report" : "model sections (rough)"}. Details in the “Seismic resistance (Richter)” tab.`)) : null,
        h("p", { class: "small mutedt" }, `${T("Μοντέλο", "Model")}: ${sel.model}. ${T("Διασταύρωση LM1: μέσος βαθμός", "LM1 cross-check: mean grade")} ${keys.map((k) => fmt(runs[k].lm1_mean_grade, 2)).join(" / ")}`)),
      h("div", { class: "grid g2" }, h("div", { class: "card" }, h("h2", {}, T("Φάσματα απόκρισης", "Response spectra")), canvasBox("chSpec")), h("div", { class: "card" }, h("h2", {}, T("Κατανομή βαθμών βλάβης (0–5)", "Damage-grade distribution (0–5)")), canvasBox("chDist"))),
      h("div", { class: "card" }, h("div", { class: "row", style: { justifyContent: "space-between" } }, h("h2", { style: { margin: 0 } }, T("Λεπτομέρειες: ", "Details: ") + lab(sel, z.scenario)), h("button", { class: "btn", onclick: () => showIn3D(lab(sel, z.scenario), sel.element_damage, sel) }, T("Δείξε τις ζημιές στο 3D / βίντεο", "Show damage in 3D / video"))),
        lossKpis(sel), h("h3", {}, T("Ανά όροφο", "By storey")), h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, T("Όροφος", "Storey")), h("th", { class: "n" }, T("Μέσος βαθμός", "Mean grade")), h("th", { class: "n" }, "P(D≥3)"), h("th", { class: "n" }, "P(D≥4)"), h("th", { class: "n" }, T("Ζημιά", "Loss")))), h("tbody", {}, sel.storeys.map((s) => h("tr", {}, h("td", {}, s[S.lang === "el" ? "name_el" : "name_en"]), h("td", { class: "n" }, fmt(s.mean_grade, 2)), h("td", { class: "n" }, pct(s.p_d3plus, 0)), h("td", { class: "n" }, pct(s.p_d4plus, 0)), h("td", { class: "n" }, eur(s.loss_eur)))))),
        h("h3", {}, T("Δείκτης ζήτησης/ικανότητας", "Demand/capacity indicator")), h("table", {}, h("tbody", {}, sel.markers.map((m) => h("tr", {}, h("td", {}, m.name + ` (T=${m.T} s)`), h("td", {}, `Sa=${m.Sa_scenario_g} g`), h("td", {}, `${T("ικανότητα", "capacity")} ${m.capacity_Cy_g} g`), h("td", {}, `${T("ζήτηση/ικανότητα", "demand/capacity")} ${m.demand_to_capacity}`), h("td", {}, `${T("όλκιμότητα", "ductility")} ${m.ductility_demand}`))))),
        h("p", { class: "small mutedt" }, T("Η ικανότητα εκτιμάται ως Ω·Sd με Ω=1,8 (υπεραντοχή)· ενδεικτικός δείκτης, δεν τροφοδοτεί τον υπολογισμό ζημιάς.", "Capacity is estimated as Ω·Sd with Ω=1.8 (overstrength); indicative only, it does not feed the damage calculation."))));
    const cols = [PAL[0], PAL[1], PAL[2], PAL[3]];
    const sp = runs.moderate.spectrum;
    chart("chSpec", { type: "line", data: { labels: sp.T, datasets: [{ label: T("Ελαστικό φάσμα ΕΑΚ", "EAK elastic design"), data: sp.design_elastic, borderColor: "#0b0b0b", borderWidth: 2.2, pointRadius: 0 }, { label: T("Φάσμα σχεδιασμού (q)", "Design spectrum (q)"), data: sp.design_q, borderColor: "#8a8984", borderDash: [5, 4], borderWidth: 1.6, pointRadius: 0 }, ...keys.map((k, i) => ({ label: lab(runs[k], k), data: runs[k].spectrum.scenario, borderColor: cols[i], borderWidth: 2, pointRadius: 0 }))] }, options: { scales: { x: ax("T (s)", { ticks: { maxTicksLimit: 8 } }), y: ax("Sa (g)") } } });
    chart("chDist", { type: "bar", data: { labels: ["0", "1", "2", "3", "4", "5"], datasets: keys.map((k, i) => ({ label: lab(runs[k], k), data: runs[k].distribution, backgroundColor: cols[i], borderRadius: 3 })) }, options: { scales: { x: ax(T("βαθμός βλάβης", "damage grade")), y: ax(T("πιθανότητα", "probability")) } } });
  };
  const ms = numInput(z.userMs ?? 6.0, () => {}, { step: 0.1, w: "70px", min: 4, max: 8 }), dk = numInput(z.userD ?? 10, () => {}, { step: 1, w: "70px", min: 1, max: 200 });
  const useMine = () => { const m = Number(ms.value), dd = Number(dk.value); if (!(m >= 4 && m <= 8.5) || !(dd > 0)) { toast(T("Δώστε Ms 4–8,5 και απόσταση > 0 km", "Give Ms 4–8.5 and distance > 0 km"), true); return false; } z.userMs = m; z.userD = dd; z.scenario = "custom"; return true; };
  b.append(h("div", { class: "card" }, h("h2", {}, T("Παράμετροι κτιρίου και σεναρίων", "Building and scenario parameters")), h("div", { class: "row" },
    field(T("Κατηγορία αντισεισμικού κανονισμού", "Seismic code level"), codeSel), field(T("Έδαφος", "Soil"), select([["A", "A"], ["B", "B"], ["C", "C"], ["D", "D"]], z.soil, (v) => (z.soil = v))), field(T("Εκατοστημόριο PGA", "PGA percentile"), select([[50, "50% (median)"], [84, "84%"]], z.percentile, (v) => (z.percentile = Number(v)))),
    h("label", { class: "chk" }, h("input", { type: "checkbox", checked: z.pilotis, onchange: (e) => (z.pilotis = e.target.checked) }), T("Πυλωτή / ήπιος όροφος", "Pilotis / soft storey")), h("label", { class: "chk" }, h("input", { type: "checkbox", checked: z.plan_irregularity, onchange: (e) => (z.plan_irregularity = e.target.checked) }), T("Ανωμαλία κάτοψης", "Plan irregularity"))),
    h("h3", {}, T("Μέτρα ενίσχυσης", "Strengthening measures")), mitChecks("seismic"),
    h("p", { class: "small mutedt" }, T("Τρία προκαθορισμένα σενάρια: μικρός Ms 5,0 @15 km · μέτριος Ms 6,0 @10 km · μεγάλος Ms 6,8 @5 km (επεξεργάσιμα στο hazards.json). Προαιρετικά ορίστε δικό σας σεισμό:", "Three default scenarios: small Ms 5.0 @15 km · moderate Ms 6.0 @10 km · large Ms 6.8 @5 km (editable in hazards.json). Optionally define your own earthquake:")),
    h("div", { class: "row" }, field("Ms", ms), field(T("Απόσταση (km)", "Distance (km)"), dk), h("button", { class: "btn small", onclick: () => { if (useMine()) runAll(); } }, T("Υπολογισμός με αυτό τον σεισμό", "Run with this earthquake")), z.userMs != null ? h("button", { class: "btn small ghost", onclick: () => { z.userMs = z.userD = null; z.scenario = "moderate"; runAll(); } }, T("Αφαίρεση δικού μου σεισμού", "Remove my earthquake")) : null),
    h("p", { class: "small mutedt" }, T("Στο βίντεο το κτίριο καταρρέει όταν η πιθανότητα κατάρρευσης (βαθμός βλάβης D5) του σεναρίου είναι ≥ 50% (ολική κατάρρευση) ή ≥ 20% (μερική κατάρρευση του κρίσιμου ορόφου).", "In the video the building collapses when the scenario's collapse probability (damage grade D5) is ≥ 50% (total collapse) or ≥ 20% (partial collapse of the critical storey).")),
    h("div", { class: "row end" }, h("button", { class: "btn", onclick: () => { const changed = Number(ms.value) !== (z.userMs ?? 6.0) || Number(dk.value) !== (z.userD ?? 10); if (changed && !useMine()) return; runAll(); } }, T("Υπολογισμός", "Run")))), out);
  runAll();
}

function rebarCards(R, lang) {
  const nm = (s) => (lang ? s.name_el : s.name_en);
  const st = h("div", { class: "card" }, h("h2", {}, T("Αντοχή ανά όροφο από τους οπλισμούς", "Storey resistance from the reinforcement")),
    h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, [T("Όροφος", "Storey"), T("Στοιχεία", "Members"), "V_d (kN)", "V_R,x (kN)", "V_R,x / V_d", "V_R,y (kN)", "V_R,y / V_d", T("Διατμ. x/y", "Shear x/y"), T("Διαρροή x/y (g)", "Yield x/y (g)"), T("Κατάρρευση x/y (g)", "Collapse x/y (g)")].map((x, i) => h("th", { class: i ? "n" : "" }, x)))),
      h("tbody", {}, R.storeys.map((s) => h("tr", { style: { background: s.key === R.governing.storey ? "#fff7ea" : "" } }, h("td", {}, nm(s)), h("td", { class: "n" }, s.elements), h("td", { class: "n" }, fmt(s.Vd_x_kN)), h("td", { class: "n" }, fmt(s.V_R_x_kN)), h("td", { class: "n" }, h("b", {}, fmt(s.ratio_x, 2))), h("td", { class: "n" }, fmt(s.V_R_y_kN)), h("td", { class: "n" }, h("b", {}, fmt(s.ratio_y, 2))),
        h("td", { class: "n" }, `${fmt(s.shear_share_x * 100)}% / ${fmt(s.shear_share_y * 100)}%`), h("td", { class: "n" }, `${fmt(s.a_y_x, 3)} / ${fmt(s.a_y_y, 3)}`), h("td", { class: "n" }, `${fmt(s.a_c_x, 3)} / ${fmt(s.a_c_y, 3)}`)))))),
    h("p", { class: "small mutedt" }, T("V_R: άθροισμα της αντοχής των υποστυλωμάτων/τοιχωμάτων στον μηχανισμό του ορόφου (καμπτική 2M_R/h ή διατμητική από τους συνδετήρες – η μικρότερη)· στο υπόγειο και τα τοιχεία 25 cm. «Διατμ.»: μερίδιο της αντοχής από στοιχεία που αστοχούν ψαθυρά σε διάτμηση.", "V_R: sum of the column/wall resistances in the storey mechanism (flexural 2M_R/h or shear from the stirrups – the smaller); in the basement also the 25 cm RC walls. “Shear”: share of the resistance from elements failing in brittle shear.")));
  const J = R.joints;
  const jc = h("div", { class: "card" }, h("h2", {}, T("Ικανοτικός έλεγχος κόμβων: ΣM_Rc ≥ 1,3·ΣM_Rb", "Capacity design of joints: ΣM_Rc ≥ 1.3·ΣM_Rb")),
    h("p", {}, T(`${J.checked} κόμβοι ελέγχθηκαν (εκτός του τελευταίου ορόφου, EC8 §4.4.2.3)· ${J.below_1_3} κάτω από 1,3, ${J.below_1_0} κάτω από 1,0 (το υποστύλωμα είναι ασθενέστερο από τα δοκάρια).`, `${J.checked} joints checked (top storey excluded, EC8 §4.4.2.3); ${J.below_1_3} below 1.3, ${J.below_1_0} below 1.0 (the column is weaker than the beams).`)),
    h("table", {}, h("thead", {}, h("tr", {}, [T("Όροφος", "Storey"), T("Υποστύλωμα", "Column"), T("Διεύθ.", "Dir."), T("Δοκοί", "Beams"), "ΣM_Rc (kNm)", "ΣM_Rb (kNm)", T("Λόγος", "Ratio")].map((x, i) => h("th", { class: i > 3 ? "n" : "" }, x)))),
      h("tbody", {}, J.worst.filter((j) => j.ratio < 1.3).map((j) => h("tr", {}, h("td", {}, nm(R.storeys.find((s) => s.key === j.storey) || {})), h("td", {}, j.id + (j.column_above ? ` → ${j.column_above}` : "")), h("td", {}, j.dir.toUpperCase()), h("td", {}, j.beams.join(", ")), h("td", { class: "n" }, fmt(j.sum_MRc)), h("td", { class: "n" }, fmt(j.sum_MRb)), h("td", { class: "n" }, h("b", { style: { color: j.ratio < 1 ? "#c0392b" : "#b26b00" } }, fmt(j.ratio, 2))))))));
  const el = h("details", { class: "card" }, h("summary", {}, T(`Όλα τα υποστυλώματα/τοιχώματα (${R.elements.length})`, `All columns/walls (${R.elements.length})`)),
    h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, [T("Όροφος", "Storey"), "K", T("Διατομή", "Section"), T("Οπλισμός", "Bars"), T("Συνδ.", "Stirr."), "N (kN)", "M_R,x", "M_R,y", "V_x (kN)", "V_y (kN)", T("Αστοχία x/y", "Failure x/y")].map((x, i) => h("th", { class: i > 4 ? "n" : "" }, x)))),
      h("tbody", {}, R.elements.map((e) => h("tr", {}, h("td", {}, nm(R.storeys.find((s) => s.key === e.storey) || {})), h("td", {}, e.id), h("td", {}, e.section || "–"), h("td", {}, e.long || "–"), h("td", {}, e.stirrups), h("td", { class: "n" }, fmt(e.N_kN)), h("td", { class: "n" }, fmt(e.M_R_x)), h("td", { class: "n" }, fmt(e.M_R_y)), h("td", { class: "n" }, fmt(e.V_x)), h("td", { class: "n" }, fmt(e.V_y)),
        h("td", { class: "n small" }, `${e.mode_x === "shear" ? T("διάτμ.", "shear") : T("κάμψη", "flex.")} / ${e.mode_y === "shear" ? T("διάτμ.", "shear") : T("κάμψη", "flex.")}`)))))));
  const ch = R.checks.length ? h("details", { class: "card" }, h("summary", {}, T(`Παρατηρήσεις κατασκευαστικής διαμόρφωσης κατά EC8 (${R.checks.length})`, `Detailing remarks per EC8 (${R.checks.length})`)),
    h("ul", { class: "small" }, R.checks.map((x) => h("li", {}, `${nm(R.storeys.find((s) => s.key === x.storey) || {})} ${x.id}: ${lang ? x.el : x.en}`))),
    h("p", { class: "small mutedt" }, T("Η μελέτη είναι κατά ΕΑΚ/ΕΚΩΣ 2000· τα όρια του EC8 δίνονται για σύγκριση.", "The design follows EAK/EKOS 2000; EC8 limits are given for comparison."))) : null;
  const cr = (R.corrections || []).length ? h("div", { class: "card" }, h("h3", {}, T("Ασυμφωνίες των σχεδίων και πώς λύθηκαν", "Drawing inconsistencies and how they were resolved")),
    h("ul", { class: "small" }, R.corrections.map((x) => h("li", {}, lang ? x.el : x.en)))) : null;
  return h("div", {}, st, jc, cr || h("span"), el, ch || h("span"));
}

async function capacity(b) {
  const z = HZ.capacity = HZ.capacity || { material_factor: 1.25, ductility_capacity: null };
  const out = h("div");
  const lang = S.lang === "el";
  const msCell = (v, ok) => (ok ? fmt(v, 1) : "> 7,5");
  const run = async () => {
    out.replaceChildren(spinner());
    const q = new URLSearchParams({ material_factor: z.material_factor });
    if (z.ductility_capacity) q.set("ductility_capacity", z.ductility_capacity);
    let r;
    try { r = await api(`/projects/${S.pid}/structural?${q}`); } catch (e) { out.replaceChildren(h("div", { class: "warnbox" }, e.message)); return; }
    const c = r.capacity, rb = c.method === "rebar_model", rep = c.method === "static_report" || rb, lim = c.limits;
    const at = (d) => lim.find((x) => x.distance_km === d) || lim[0];
    out.replaceChildren(
      h("div", { class: "card" }, h("h2", {}, T("Αντοχή του κτιρίου σε σεισμό", "Seismic resistance of the building")),
        h("p", { class: "small" }, rb ? T(`Από τον πραγματικό σκελετό των ξυλοτύπων Σ.01–Σ.06: ${c.rebar.elements.length} υποστυλώματα/τοιχώματα με τις διατομές, τα σίδερα και τους συνδετήρες τους, ${c.rebar.joints.checked} κόμβοι δοκών–υποστυλωμάτων. Σεισμός σχεδιασμού a_g=${c.design.a_g} g, q=${c.design.q}. Κρίσιμος: ${lang ? c.weakest_storey_name_el : c.weakest_storey_name_en}. (Με τη μέθοδο των ελέγχων του τεύχους: διαρροή ${fmt(c.report_based.pga_g.yield, 3)} g, κατάρρευση ${fmt(c.report_based.pga_g.collapse, 3)} g.)`, `From the real skeleton of the formwork drawings S.01–S.06: ${c.rebar.elements.length} columns/walls with their sections, bars and stirrups, ${c.rebar.joints.checked} beam–column joints. Design earthquake a_g=${c.design.a_g} g, q=${c.design.q}. Critical: ${lang ? c.weakest_storey_name_el : c.weakest_storey_name_en}. (With the report-utilisation method: yield ${fmt(c.report_based.pga_g.yield, 3)} g, collapse ${fmt(c.report_based.pga_g.collapse, 3)} g.)`)
          : rep ? T(`Από τους ελέγχους του τεύχους στατικών (${c.program}, ${c.members} έλεγχοι υποστυλωμάτων/τοιχωμάτων σε ${c.storeys.length} στάθμες): σεισμός σχεδιασμού a_g=${c.design.a_g} g, q=${c.design.q}, έδαφος ${c.design.soil}, ζώνη ${c.design.zone}.`, `From the member checks of the static report (${c.program}, ${c.members} column/wall checks in ${c.storeys.length} levels): design earthquake a_g=${c.design.a_g} g, q=${c.design.q}, soil ${c.design.soil}, zone ${c.design.zone}.`)
          : T("Δεν έχει ανεβεί τεύχος στατικών: χονδρική εκτίμηση από τις διατομές του μοντέλου (±2×).", "No static report uploaded: rough estimate from the model sections (±2×).")),
        h("div", { class: "grid g4" },
          kpi(fmt(c.pga_g.yield, 3) + " g", T("Πρώτη διαρροή (PGA)", "First yield (PGA)"), `${fmt(c.pga_over_design.yield, 2)}× a_g · Ms ≥ ${msCell(at(10).yield, at(10).in_range || at(10).yield <= 7.5)} @10 km`),
          kpi(fmt(c.pga_g.collapse, 3) + " g", T("Εξάντληση πλαστιμότητας (PGA)", "Ductility exhausted (PGA)"), `${fmt(c.pga_over_design.collapse, 2)}× a_g · Ms ≥ ${msCell(at(10).collapse, at(10).collapse <= 7.5)} @10 km`),
          kpi("Ms " + msCell(at(5).collapse, at(5).collapse <= 7.5), T("Ρίχτερ για οιονεί κατάρρευση @5 km", "Richter for near-collapse @5 km"), `±1σ: ${msCell(at(5).collapse_lo, at(5).collapse_lo <= 7.5)} – ${msCell(at(5).collapse_hi, at(5).collapse_hi <= 7.5)}`),
          rb ? kpi(fmt(c.overstrength_total, 2) + "×", T("Αντοχή/τέμνουσα σχεδιασμού (κρίσιμος όροφος)", "Resistance/design shear (critical storey)"), `${T("κρίσιμος", "critical")}: ${lang ? c.weakest_storey_name_el : c.weakest_storey_name_en}`)
          : rep ? kpi(`${fmt(c.lambda.mechanism, 2)} · ${fmt(c.overstrength_total, 2)}`, T("Υπεραντοχή λ · λ·Ω", "Overstrength λ · λ·Ω"), `${T("κρίσιμος όροφος", "critical storey")}: ${lang ? c.weakest_storey_name_el : c.weakest_storey_name_en}`) : kpi(fmt(c.base.Cu, 3), T("Συντελεστής αντοχής βάσης", "Base-shear strength coeff."), `Vu ≈ ${fmt(c.base.Vu_kN)} kN`)),
        h("div", { class: "row" }, rep && !rb ? field("Ω (αναμενόμενη/υπολογ. αντοχή)", numInput(z.material_factor, (v) => { z.material_factor = Number(v) || 1.25; run(); }, { step: 0.05, w: "80px" })) : null,
          rep && !rb ? field(T("Πλαστιμότητα μ (προεπιλ. = q)", "Ductility μ (default = q)"), numInput(z.ductility_capacity || c.ductility.mu_capacity, (v) => { z.ductility_capacity = Number(v) || null; run(); }, { step: 0.5, w: "80px" })) : null,
          h("button", { class: "btn small ghost", onclick: () => { HZ.seismic.code_level = "static"; HZ.tab = "seismic"; window.go("hazards"); } }, T("Εφαρμογή στα σενάρια σεισμού", "Apply to the earthquake scenarios")))),
      h("div", { class: "grid g2" },
        h("div", { class: "card" }, h("h2", {}, T("Μέγεθος σεισμού (Ρίχτερ, Ms) που φέρνει το κτίριο στην κάθε κατάσταση", "Earthquake magnitude (Richter, Ms) bringing the building to each state")),
          h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, T("Απόσταση επικέντρου", "Epicentral distance")), h("th", { class: "n" }, T("Πρώτη διαρροή", "First yield")), h("th", { class: "n" }, "±1σ"), h("th", { class: "n" }, T("Οιονεί κατάρρευση", "Near-collapse")), h("th", { class: "n" }, "±1σ"))),
            h("tbody", {}, lim.map((x) => h("tr", {}, h("td", {}, `${x.distance_km} km`), h("td", { class: "n" }, h("b", {}, msCell(x.yield, x.yield <= 7.5))), h("td", { class: "n small mutedt" }, `${msCell(x.yield_lo, x.yield_lo <= 7.5)} – ${msCell(x.yield_hi, x.yield_hi <= 7.5)}`), h("td", { class: "n" }, h("b", {}, msCell(x.collapse, x.collapse <= 7.5))), h("td", { class: "n small mutedt" }, `${msCell(x.collapse_lo, x.collapse_lo <= 7.5)} – ${msCell(x.collapse_hi, x.collapse_hi <= 7.5)}`)))))),
          h("p", { class: "small mutedt" }, T("Το «> 7,5» σημαίνει ότι σε αυτή την απόσταση δεν επιτυγχάνεται η κατάσταση ούτε με σεισμό Ms 7,5. Ms: μέγεθος επιφανειακών κυμάτων, το συνηθισμένο «Ρίχτερ» στη βιβλιογραφία των σχέσεων απόσβεσης.", "“> 7.5” means the state is not reached at that distance even with an Ms 7.5 earthquake. Ms: surface-wave magnitude, the “Richter” of attenuation-law literature."))),
        h("div", { class: "card" }, h("h2", {}, T("Ρίχτερ έναντι απόστασης", "Richter vs distance")), canvasBox("chRich"))),
      rb ? rebarCards(c.rebar, lang) : h("span"),
      rep && !rb ? h("div", { class: "card" }, h("h2", {}, T("Ανά όροφο (από το τεύχος στατικών)", "By storey (from the static report)")),
        h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, [T("Στάθμη", "Level"), "dh (m)", "W (kN)", "V_Ed (kN)", T("Μέλη", "Members"), T("Κάμψη max", "Flexure max"), T("Κάμψη μέση", "Flexure mean"), T("Διάτμηση max", "Shear max"), T("Τοιχώματα x/y", "Walls x/y")].map((x, i) => h("th", { class: i > 0 ? "n" : "" }, x)))),
          h("tbody", {}, c.storeys.map((s) => h("tr", { style: { background: s.key === c.weakest_storey ? "#fff7ea" : "" } }, h("td", {}, lang ? s.name_el : s.name_en), h("td", { class: "n" }, fmt(s.dh_m, 2)), h("td", { class: "n" }, fmt(s.W_kN)), h("td", { class: "n" }, fmt(s.Vx_kN)), h("td", { class: "n" }, s.members), h("td", { class: "n" }, fmt(s.u_flex_max, 2)), h("td", { class: "n" }, fmt(s.u_flex_mean, 2)), h("td", { class: "n" }, fmt(s.u_shear_max, 2)), h("td", { class: "n" }, s.wall_share_x != null ? `${fmt(s.wall_share_x, 2)} / ${fmt(s.wall_share_y, 2)}` : "–")))))),
        h("p", { class: "small mutedt" }, T(`Βάση: W=${fmt(c.base.W_kN)} kN, V_Ed=${fmt(c.base.Vd_kN)} kN (C=${fmt(c.base.Cd, 3)}) · αντοχή διαρροής V_y≈${fmt(c.base.Vy_kN)} kN, μηχανισμού V_u≈${fmt(c.base.Vu_kN)} kN. Σχέση χρησιμοποίησης = ζητούμενο/αντοχή (1,0 = οριακά επαρκές).`, `Base: W=${fmt(c.base.W_kN)} kN, V_Ed=${fmt(c.base.Vd_kN)} kN (C=${fmt(c.base.Cd, 3)}) · yield strength V_y≈${fmt(c.base.Vy_kN)} kN, mechanism V_u≈${fmt(c.base.Vu_kN)} kN. Utilisation = demand/resistance (1.0 = just adequate).`))) : h("span"),
      h("div", { class: "card" }, h("h3", {}, T("Παραδοχές και όρια", "Assumptions and limits")), h("ul", { class: "small" }, (lang ? c.assumptions_el : c.assumptions_en).map((t) => h("li", {}, t)))));
    chart("chRich", { type: "line", data: { labels: lim.map((x) => x.distance_km + " km"), datasets: [
      { label: T("Οιονεί κατάρρευση", "Near-collapse"), data: lim.map((x) => (x.collapse <= 9 ? x.collapse : null)), borderColor: PAL[1], borderWidth: 2.2, pointRadius: 3 },
      { label: T("Οιονεί κατάρρευση (−1σ)", "Near-collapse (−1σ)"), data: lim.map((x) => (x.collapse_lo <= 9 ? x.collapse_lo : null)), borderColor: PAL[1], borderDash: [4, 4], borderWidth: 1.4, pointRadius: 0 },
      { label: T("Πρώτη διαρροή", "First yield"), data: lim.map((x) => (x.yield <= 9 ? x.yield : null)), borderColor: PAL[0], borderWidth: 2.2, pointRadius: 3 },
      { label: T("Πρώτη διαρροή (−1σ)", "First yield (−1σ)"), data: lim.map((x) => (x.yield_lo <= 9 ? x.yield_lo : null)), borderColor: PAL[0], borderDash: [4, 4], borderWidth: 1.4, pointRadius: 0 }] },
      options: { scales: { x: ax(T("απόσταση επικέντρου", "epicentral distance")), y: ax("Ms", { min: 3.5, max: 9 }) } } });
  };
  // upload of the static report
  const msg = h("span", { class: "small mutedt" });
  const inp = h("input", { type: "file", accept: ".pdf", style: { display: "none" }, onchange: async (e) => {
    const f = e.target.files[0]; if (!f) return;
    msg.textContent = T("Ανάγνωση τεύχους… (μερικά δευτερόλεπτα)", "Reading the report… (a few seconds)");
    const fd = new FormData(); fd.append("file", f);
    try { const r = await api(`/projects/${S.pid}/structural/upload`, { method: "POST", body: fd }); S.project = await api(`/projects/${S.pid}`); toast(T(`Διαβάστηκαν ${r.members} έλεγχοι μελών σε ${r.storeys} στάθμες.`, `Read ${r.members} member checks in ${r.storeys} levels.`)); msg.textContent = f.name; await run(); } catch (ex) { msg.textContent = ""; toast(ex.message, true); }
  } });
  b.append(h("div", { class: "warnbox" }, T("Η αντοχή προκύπτει από τον πραγματικό σκελετό της στατικής μελέτης (θέσεις, διατομές, οπλισμοί και συνδετήρες των ξυλοτύπων) και τα βάρη/τέμνουσες ανά όροφο του τεύχους· χωρίς ξυλότυπους, από τους λόγους εκμετάλλευσης του τεύχους. Είναι εκτίμηση προμελέτης (screening), όχι αποτίμηση ΚΑΝ.ΕΠΕ.", "Resistance is derived from the real skeleton of the structural design (positions, sections, bars and stirrups of the formwork drawings) and the storey weights/shears of the report; without formwork drawings, from the member utilisation of the report. It is a pre-design (screening) estimate, not a ΚΑΝ.ΕΠΕ. assessment.")),
    h("div", { class: "card" }, h("div", { class: "row" }, h("b", {}, T("Τεύχος στατικής μελέτης (Statics PDF)", "Static-study report (Statics PDF)")), h("button", { class: "btn small", onclick: () => inp.click() }, T("Ανέβασμα τεύχους…", "Upload report…")), inp, msg,
      (S.project.meta.structural ? h("span", { class: "chip" }, S.project.meta.structural.file || T("φορτωμένο στατικό", "static loaded")) : null)),
      h("p", { class: "small mutedt" }, T("Δουλεύει με τεύχη του προγράμματος Statics (όπως της άδειας). Για άλλα προγράμματα στατικής χρησιμοποιείται η χονδρική εκτίμηση από τις διατομές του μοντέλου ή επικοινωνήστε για προσθήκη του αναγνώστη.", "Works with Statics-program reports (like the permit's). For other structural programs the rough section-based estimate is used."))), out);
  await run();
}

async function fireInt(b) {
  const z = HZ.fire_internal, out = h("div");
  const st = S.project.storeys.filter((s) => s.elevation_m >= 0);
  z.storey = z.storey || (st[1] || st[0] || S.project.storeys[0]).id;
  const run = async () => {
    out.replaceChildren(spinner());
    const r = await post("fire_internal", z);
    out.replaceChildren(h("div", { class: "card" }, h("div", { class: "row", style: { justifyContent: "space-between" } }, h("h2", { style: { margin: 0 } }, T("Αποτελέσματα", "Results")), h("button", { class: "btn", onclick: () => showIn3D(T("Εσωτερική φωτιά", "Internal fire"), r.element_damage, r) }, T("Δείξε στο 3D / βίντεο", "Show in 3D / video"))), lossKpis(r),
      h("div", { class: "grid g2", style: { marginTop: "12px" } }, h("div", {}, canvasBox("chFire", "short")), h("table", {}, h("tbody", {}, [[T("Θάλαμος", "Compartment"), `${r.compartment_area_m2} m² (${r[S.lang === "el" ? "storey_name_el" : "storey_name_en"]})`], [T("Πυροφορτίο q_f,d", "Fire load q_f,d"), `${fmt(r.q_fd_MJ_m2)} MJ/m²`], [T("Παράγοντας ανοιγμάτων O", "Opening factor O"), r.opening_factor], [T("Μέγιστη θερμοκρασία", "Peak temperature"), `${r.theta_max_C} °C`], [T("Διάρκεια πλήρους ανάπτυξης", "Fully-developed duration"), `${r.t_max_min} min`], [T("Ισοδύναμος χρόνος πρότυπης πυρκαγιάς", "Equivalent standard-fire time"), `${r.t_e_min} min (${T("ενεργός", "effective")} ${r.t_e_effective_min})`], [T("Πυραντίσταση υποστυλωμάτων (διάμεσος)", "Column fire resistance (median)"), `R${r.R_provided_min} ${r.meets_required_R ? "✓" : "✗"} (${T("απαιτ.", "req.")} R${r.R_required_min})`], [T("Στήλες που πληρούν την απαίτηση", "Columns meeting requirement"), pct(r.columns_meeting_R_share, 0)], [T("Πιθανότητα flashover", "Flashover probability"), pct(r.flashover_probability, 0)], [T("Εξάπλωση (κάθετη / οριζόντια)", "Spread (vertical / horizontal)"), `${pct(r.spread.vertical, 0)} / ${pct(r.spread.horizontal, 0)}`], [T("Βαθμός βλάβης φορέα (αν flashover)", "Structural grade (if flashover)"), r.structural_grade_if_flashover]].map(([a, v]) => h("tr", {}, h("td", { class: "mutedt" }, a), h("td", {}, v)))))), h("p", { class: "small mutedt" }, r.model)));
    chart("chFire", { type: "line", data: { labels: r.curve.t_min, datasets: [{ label: T("Παραμετρική πυρκαγιά (EC1)", "Parametric fire (EC1)"), data: r.curve.gas_C, borderColor: PAL[1], borderWidth: 2.4, pointRadius: 0 }, { label: "ISO 834", data: r.curve.standard_C, borderColor: "#8a8984", borderDash: [5, 4], borderWidth: 1.6, pointRadius: 0 }] }, options: { scales: { x: ax("min", { ticks: { maxTicksLimit: 10 } }), y: ax("°C") } } });
  };
  const nf = (lbl, key, step, w) => field(lbl, numInput(z[key], (v) => (z[key] = v), { step, w: w || "80px" }));
  b.append(h("div", { class: "card" }, h("h2", {}, T("Σενάριο εσωτερικής πυρκαγιάς", "Internal fire scenario")), h("div", { class: "row" }, field(T("Όροφος έναρξης", "Storey of origin"), select(S.project.storeys.map((s) => [s.id, s[S.lang === "el" ? "name_el" : "name_en"]]), z.storey, (v) => (z.storey = v))), nf(T("Επιφάνεια θαλάμου (m²)", "Compartment area (m²)"), "compartment_area_m2", 1), nf(T("Ανοίγματα / δάπεδο", "Openings / floor"), "opening_ratio", 0.01), nf(T("Πυροφορτίο q_f,k (MJ/m²)", "Fire load q_f,k (MJ/m²)"), "q_fk", 10), nf(T("Απαιτ. πυραντίσταση R (min)", "Required R (min)"), "required_R", 15), nf(T("Άφιξη ΠΥ (min)", "Brigade response (min)"), "brigade_response_min", 1), nf(T("Αξονική απόσταση οπλισμού (mm)", "Axis distance (mm)"), "axis_mm", 1),
    h("label", { class: "chk" }, h("input", { type: "checkbox", checked: z.sprinkler, onchange: (e) => (z.sprinkler = e.target.checked) }), T("Υπάρχουν sprinklers", "Sprinklers present")), h("label", { class: "chk" }, h("input", { type: "checkbox", checked: z.detector, onchange: (e) => (z.detector = e.target.checked) }), T("Ανιχνευτές καπνού", "Smoke detection"))),
    h("h3", {}, T("Μέτρα πυροπροστασίας", "Fire protection measures")), mitChecks("fire_internal"), h("div", { class: "row end" }, h("button", { class: "btn", onclick: run }, T("Υπολογισμός", "Run")))), out);
  run();
}

async function wildfire(b) {
  const z = HZ.wildfire, out = h("div");
  const run = async () => {
    out.replaceChildren(spinner());
    const r = await post("wildfire", z);
    const balCol = ["#1baf7a", "#eda100", "#eb6834", "#e34948", "#a32c2c", "#6b1c1c"][r.bal_index];
    out.replaceChildren(h("div", { class: "card" }, h("div", { class: "row", style: { justifyContent: "space-between" } }, h("h2", { style: { margin: 0 } }, T("Αποτελέσματα", "Results")), h("button", { class: "btn", onclick: () => showIn3D(T("Δασική πυρκαγιά", "Wildfire"), r.element_damage, r) }, T("Δείξε στο 3D / βίντεο", "Show in 3D / video"))),
      h("div", { class: "grid g4" }, kpi(h("span", { class: "chip", style: { background: balCol, fontSize: "18px", padding: "2px 12px" } }, r.bal), T("Κατηγορία έκθεσης (AS 3959)", "Exposure class (AS 3959)"), `${fmt(r.flux_kW_m2, 1)} kW/m²`), kpi(eur(r.loss_eur), T("Αναμενόμενη ζημιά", "Expected loss"), pct(r.loss_ratio, 1)), kpi(fmt(r.flame_length_m, 1) + " m", T("Μήκος φλόγας", "Flame length"), `${T("κλίση", "tilt")} ${r.tilt_deg}°`), kpi(pct(r.ember_probability, 0), T("Πιθανότητα ανάφλεξης από ωλοκάρβουνα", "Ember ignition probability"), `${T("ενεργός απόσταση", "effective distance")} ${r.effective_distance_m} m`)),
      h("div", { class: "grid g2", style: { marginTop: "12px" } }, h("div", {}, h("h3", {}, T("Ροή θερμότητας συναρτήσει της απόστασης", "Heat flux vs. distance")), canvasBox("chWild", "short")),
        h("div", {}, h("h3", {}, T("Έλεγχος υλικών/στοιχείων", "Materials / elements check")), h("table", {}, h("tbody", {}, r.materials.map((m) => h("tr", {}, h("td", {}, m[S.lang === "el" ? "el" : "en"]), h("td", { class: "n" }, `${m.threshold_kW_m2} kW/m²`), h("td", { class: m.exceeded ? "bad" : "ok" }, m.exceeded ? T("ΥΠΕΡΒΑΣΗ", "EXCEEDED") : "OK"))))))),
      h("h3", {}, T("Ανάλυση ζημιάς", "Loss breakdown")), h("div", { class: "row small" }, Object.entries(r.loss_parts).map(([k, v]) => h("span", { class: "pill" }, `${{ envelope: T("κέλυφος", "envelope"), exterior: T("εξωτερικά", "exterior"), interior: T("εσωτερικά", "interior"), structure: T("φορέας", "structure"), embers: T("ωλοκάρβουνα", "embers") }[k]}: ${eur(v)}`))), h("p", { class: "small mutedt" }, r.model)));
    const dc = r.distance_curve;
    chart("chWild", { type: "line", data: { labels: dc.map((d) => d.d), datasets: [{ label: "kW/m²", data: dc.map((d) => d.q), borderColor: PAL[1], borderWidth: 2.4, pointRadius: 0, tension: 0.25 }, ...[12.5, 19, 29, 40].map((t, i) => ({ label: "BAL " + t, data: dc.map(() => t), borderColor: ["#eda100", "#eb6834", "#e34948", "#a32c2c"][i], borderDash: [4, 4], borderWidth: 1, pointRadius: 0 }))] }, options: { scales: { x: ax(T("απόσταση από βλάστηση (m)", "distance to vegetation (m)")), y: ax("kW/m²") } } });
  };
  const nf = (lbl, key, step) => field(lbl, numInput(z[key], (v) => (z[key] = v), { step, w: "80px" }));
  b.append(h("div", { class: "card" }, h("h2", {}, T("Σενάριο δασικής πυρκαγιάς στην ευρύτερη περιοχή", "Wildfire scenario in the wider area")), h("div", { class: "row" }, field(T("Ένταση πυρκαγιάς", "Fire intensity"), select(Object.entries(hdef.fire.intensity_classes).map(([k, v]) => [k, `${k} (${fmt(v)} kW/m)`]), z.intensity_class, (v) => (z.intensity_class = v))), nf(T("Απόσταση από βλάστηση (m)", "Distance to vegetation (m)"), "distance_m", 1), nf(T("Κλίση (°)", "Slope (°)"), "slope_deg", 1), nf(T("Άνεμος (km/h)", "Wind (km/h)"), "wind_kmh", 5), field(T("Κατεύθυνση μετώπου", "Fire direction"), select(["N", "NE", "E", "SE", "S", "SW", "W", "NW"].map((x) => [x, x]), z.direction, (v) => (z.direction = v)))),
    h("h3", {}, T("Μέτρα προστασίας", "Protection measures")), mitChecks("wildfire"), h("div", { class: "row end" }, h("button", { class: "btn", onclick: run }, T("Υπολογισμός", "Run")))), out);
  run();
}

async function flood(b) {
  const z = HZ.flood, out = h("div"), sc = hdef.flood.scenarios;
  const run = async () => {
    out.replaceChildren(spinner());
    const common = { mitigations: z.mitigations };
    const res = await post("flood", common, true); const runs = res.runs; let cust = null;
    if (z.custom) cust = await post("flood", Object.assign({ depth_m: z.depth, velocity_ms: z.vel }, common), false);
    const sel = z.custom ? cust : runs[z.scenario];
    out.replaceChildren(h("div", { class: "card" }, h("h2", {}, T("Σύγκριση σεναρίων", "Scenario comparison")), h("table", {}, h("thead", {}, h("tr", {}, ["", T("Βάθος (m)", "Depth (m)"), T("Υπόγειο (m)", "Basement (m)"), T("Ζημιά", "Loss"), T("Λόγος", "Ratio"), T("Ημέρες εκτός", "Days out"), ""].map((x, i) => h("th", { class: i ? "n" : "" }, x)))), h("tbody", {}, Object.entries(runs).map(([k, r]) => h("tr", {}, h("td", {}, h("b", {}, r[S.lang === "el" ? "label_el" : "label_en"])), h("td", { class: "n" }, r.depth_m), h("td", { class: "n" }, r.basement_flooded_m), h("td", { class: "n" }, eur(r.loss_eur)), h("td", { class: "n" }, pct(r.loss_ratio, 1)), h("td", { class: "n" }, r.downtime_days), h("td", {}, h("button", { class: "btn small ghost", onclick: () => { z.custom = false; z.scenario = k; run(); } }, T("Λεπτομέρειες", "Details"))))))),
      h("div", { class: "grid g2", style: { marginTop: "12px" } }, h("div", {}, h("h3", {}, T("Καμπύλη βάθους–ζημιάς", "Depth–damage curve")), canvasBox("chDD", "short")), h("div", {}, h("h3", {}, T("Ανά όροφο", "By storey") + " – " + (z.custom ? T("προσαρμοσμένο", "custom") : sel[S.lang === "el" ? "label_el" : "label_en"])), h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, T("Όροφος", "Storey")), h("th", { class: "n" }, T("Βάθος νερού", "Water depth")), h("th", { class: "n" }, T("Λόγος ζημιάς", "Damage ratio")), h("th", { class: "n" }, T("Ζημιά", "Loss")))), h("tbody", {}, sel.storeys.map((s) => h("tr", {}, h("td", {}, s[S.lang === "el" ? "name_el" : "name_en"]), h("td", { class: "n" }, s.water_depth_m + " m"), h("td", { class: "n" }, pct(s.damage_ratio, 0)), h("td", { class: "n" }, eur(s.loss_eur)))))))),
      h("div", { class: "row end", style: { marginTop: "8px" } }, h("button", { class: "btn", onclick: () => showIn3D(T("Πλημμύρα", "Flood"), sel.element_damage, sel) }, T("Δείξε στο 3D / βίντεο", "Show in 3D / video"))), h("p", { class: "small mutedt" }, sel.model)));
    chart("chDD", { type: "line", data: { labels: sel.curve.map((c) => c.depth), datasets: [{ label: T("Λόγος ζημιάς", "Damage ratio"), data: sel.curve.map((c) => c.ratio), borderColor: PAL[0], borderWidth: 2.4, pointRadius: 3 }] }, options: { plugins: { legend: { display: false } }, scales: { x: ax(T("βάθος νερού (m)", "water depth (m)")), y: ax(T("λόγος ζημιάς", "damage ratio")) } } });
  };
  const dep = numInput(0.8, (v) => (z.depth = v), { step: 0.1, w: "70px" }), vel = numInput(1, (v) => (z.vel = v), { step: 0.5, w: "70px" });
  z.depth = 0.8; z.vel = 1;
  b.append(h("div", { class: "card" }, h("h2", {}, T("Σενάριο πλημμύρας", "Flood scenario")), h("p", { class: "small mutedt" }, T("Βάθος νερού πάνω από τη στάθμη του ισογείου. Το υπόγειο πλημμυρίζει όταν το βάθος ξεπεράσει το όριο εισόδου (ράμπα).", "Water depth above the ground-floor level. The basement floods when depth exceeds the entry threshold (ramp).")), h("div", { class: "row" }, field(T("Προκαθορισμένο σενάριο", "Preset scenario"), select(Object.entries(sc).map(([k, v]) => [k, `${v[S.lang === "el" ? "el" : "en"]} – ${v.depth_m} m`]), z.scenario, (v) => { z.scenario = v; z.custom = false; })), field(T("ή δικό σας βάθος (m)", "or custom depth (m)"), dep), field(T("Ταχύτητα (m/s)", "Velocity (m/s)"), vel), h("button", { class: "btn small ghost", onclick: () => { z.custom = true; run(); } }, T("Χρήση προσαρμοσμένου", "Use custom"))),
    h("h3", {}, T("Μέτρα προστασίας", "Protection measures")), mitChecks("flood"), h("div", { class: "row end" }, h("button", { class: "btn", onclick: () => { z.custom = false; run(); } }, T("Υπολογισμός", "Run")))), out);
  run();
}

async function risk(b) {
  const out = h("div");
  const run = async (exposure) => {
    out.replaceChildren(spinner());
    const r = await api(`/projects/${S.pid}/hazards/risk`, { method: "POST", body: exposure ? { exposure } : {} });
    const names = { seismic: T("Σεισμός", "Earthquake"), fire_internal: T("Εσωτ. φωτιά", "Internal fire"), wildfire: T("Δασική πυρκαγιά", "Wildfire"), flood: T("Πλημμύρα", "Flood") };
    const exp = r.exposure;
    out.replaceChildren(h("div", { class: "card" }, h("h2", {}, T("Αναμενόμενη ετήσια ζημιά (EAL)", "Expected annual loss (EAL)")), h("p", { class: "small mutedt" }, T("EAL = Σ ετήσια πιθανότητα × ζημιά. Ο συντελεστής έκθεσης θέσης (0–1) εκφράζει πόσο εκτεθειμένο είναι το οικόπεδο (π.χ. 0 αν είναι εκτός ζώνης πλημμύρας).", "EAL = Σ annual probability × loss. The site exposure multiplier (0–1) expresses how exposed the plot is (e.g. 0 if outside flood zones).")),
      h("div", { class: "row" }, Object.keys(names).map((k) => field(T("Έκθεση: ", "Exposure: ") + names[k], numInput(exp[k], (v) => run({ [k]: v }), { step: 0.05, w: "70px" })))),
      h("div", { class: "grid g2", style: { marginTop: "10px" } }, h("div", {}, canvasBox("chEal", "short")), h("div", {}, kpi(eur(r.total_eal_eur) + "/" + T("έτος", "y"), T("Συνολική αναμενόμενη ετήσια ζημιά", "Total expected annual loss")), h("table", { style: { marginTop: "10px" } }, h("tbody", {}, Object.entries(r.hazards).map(([k, v]) => h("tr", {}, h("td", {}, names[k]), h("td", { class: "n" }, eur(v)))))))) ),
      h("div", { class: "card" }, h("h2", {}, T("Κόστος–όφελος μέτρων προστασίας", "Mitigation cost–benefit")), h("p", { class: "small mutedt" }, T("Όφελος = μείωση EAL προεξοφλημένη στον ορίζοντα των 50 ετών (3%). BCR>1 σημαίνει ότι το μέτρο αποπληρώνεται.", "Benefit = EAL reduction discounted over 50 years (3%). BCR>1 means the measure pays back.")), h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, T("Μέτρο", "Measure")), h("th", {}, T("Κίνδυνος", "Hazard")), h("th", { class: "n" }, T("Κόστος", "Cost")), h("th", { class: "n" }, T("Μείωση EAL/έτος", "EAL reduction/y")), h("th", { class: "n" }, T("Όφελος", "Benefit")), h("th", { class: "n" }, "BCR"))),
        h("tbody", {}, r.mitigations.map((m) => h("tr", {}, h("td", {}, m[S.lang === "el" ? "el" : "en"]), h("td", {}, names[m.hazard]), h("td", { class: "n" }, eur(m.cost_eur)), h("td", { class: "n" }, eur(m.eal_reduction_eur_year)), h("td", { class: "n" }, eur(m.benefit_eur)), h("td", { class: "n " + (m.bcr >= 1 ? "ok" : "mutedt") }, m.bcr === null ? "—" : fmt(m.bcr, 2)))))))));
    chart("chEal", { type: "bar", data: { labels: Object.keys(r.hazards).map((k) => names[k]), datasets: [{ data: Object.values(r.hazards), backgroundColor: PAL[0], borderRadius: 4 }] }, options: { plugins: { legend: { display: false } }, scales: { y: ax("€/" + T("έτος", "y")), x: { grid: { display: false } } } } });
  };
  b.append(out); run();
}
