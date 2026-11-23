// 7D – facility and asset management: properties (table of shares), allocation of the running costs, asset register, maintenance calendar.
import { S, T, api, h, fmt, eur, toast, chart, ax, canvasBox, kpi, numInput, spinner, PAL } from "./util.js";

const TYPE = { apartment: ["Διαμέρισμα", "Apartment"], storage: ["Αποθήκη", "Storage"], parking: ["Θέση στάθμευσης", "Parking space"], common: ["Κοινόχρηστο", "Common"] };
const STOREY = { basement: ["Υπόγειο", "Basement"], ground: ["Ισόγειο", "Ground floor"], first: ["1ος όροφος", "1st floor"], second: ["2ος όροφος", "2nd floor"], attic: ["Σοφίτα", "Attic"], all: ["Όλο το κτίριο", "Whole building"] };
const CAT = [["maintenance", "Συντήρηση & επιθεωρήσεις", "Maintenance & inspections"], ["replacement", "Αντικαταστάσεις", "Replacements"], ["energy", "Ενέργεια", "Energy"],
  ["insurance", "Ασφάλιστρα", "Insurance"], ["cleaning", "Καθαριότητα", "Cleaning"], ["measures", "Ενεργειακές αναβαθμίσεις", "Energy upgrades"]];
const TARGET = { private: ["Ιδιωτικό (ανά εμβαδόν διαμερίσματος)", "Private (by apartment area)"], private_energy: ["Ενέργεια διαμερίσματος (ανά εμβαδόν)", "Apartment energy (by area)"] };
const L2 = (pair) => (pair ? pair[S.lang === "el" ? 0 : 1] : "");

export async function fmView(root) {
  root.append(h("h1", {}, T("Διαχείριση εγκαταστάσεων και περιουσιακών στοιχείων (7D)", "Facility and asset management (7D)")),
    h("p", { class: "lead" }, T("Οι ιδιοκτησίες του κτιρίου από τη σύσταση οριζόντιας ιδιοκτησίας (πίνακας ποσοστών), το μητρώο εγκαταστάσεων με τις περιοδικές εργασίες τους, το ημερολόγιο συντήρησης και ο επιμερισμός του κόστους λειτουργίας του 5D σε κάθε ιδιοκτησία: τα κοινόχρηστα με τα χιλιοστά κάθε στήλης του πίνακα, τα ιδιωτικά με το εμβαδόν κάθε διαμερίσματος.",
      "The properties of the building from the deed of horizontal ownership (table of shares), the asset register with its periodic tasks, the maintenance calendar and the allocation of the 5D running costs to each property: common costs by the shares of each column of the table, private costs by the area of each apartment.")));
  const out = h("div", {}, spinner());
  root.append(out);
  let f;
  try { f = await api(`/projects/${S.pid}/fm`); } catch (e) { out.replaceChildren(h("div", { class: "warnbox" }, e.message)); return; }
  const keys = Object.keys(f.keys), KL = (k) => L2(f.keys[k]) || L2(TARGET[k]) || k;
  const props = f.properties, apts = props.filter((p) => p.type === "apartment");
  const bldAvg = props.reduce((s, p) => s + p.avg_annual_total, 0);
  const cnt = (t) => props.filter((p) => p.type === t).length;
  const allOk = f.checks.every((c) => c.ok);
  const aptArea = apts.reduce((s, p) => s + (p.total_m2 || p.area_m2 || 0), 0);

  const kp = h("div", { class: "grid g4" },
    kpi(fmt(props.length), T("Αυτοτελείς ιδιοκτησίες", "Independent properties"), `${cnt("apartment")} ${T("διαμερίσματα", "apartments")} · ${cnt("storage")} ${T("αποθήκες", "storage rooms")} · ${cnt("parking")} ${T("θέσεις στάθμευσης", "parking spaces")}`),
    kpi(allOk ? "✓ 1000‰" : "⚠", T("Έλεγχος χιλιοστών", "Shares check"), allOk ? T("όλες οι στήλες αθροίζουν 1000", "every column adds up to 1000") : f.checks.filter((c) => !c.ok).map((c) => `${KL(c.key)} ${fmt(c.sum, 1)}`).join(" · ")),
    kpi(eur(bldAvg), T("Μέσο ετήσιο κόστος λειτουργίας κτιρίου", "Average annual running cost of the building"), `${f.horizon} ${T("έτη", "years")} · ${T("χωρίς την κατασκευή", "excl. construction")}`),
    kpi(fmt(apts.reduce((s, p) => s + p.avg_annual_total, 0) / (aptArea || 1), 1) + " €/m²", T("Διαμερίσματα: κόστος ανά m² και έτος", "Apartments: cost per m² and year"), T("μέσος όρος, όλες οι κατηγορίες", "average, all categories")));
  const parts = [kp];
  if (f.estimated) parts.push(h("div", { class: "warnbox" }, T("Δεν έχει δοθεί πίνακας ποσοστών· τα χιλιοστά εκτιμώνται από τα εμβαδά των διαμερισμάτων. Περάστε τα χιλιοστά της σύστασης στον πίνακα παρακάτω.", "No table of shares given; shares are estimated from the apartment areas. Enter the shares of the deed in the table below.")));

  // ---- properties (table of shares), editable
  const edit = JSON.parse(JSON.stringify(props.map((p) => ({ id: p.id, name_el: p.name_el, name_en: p.name_en, type: p.type, storey: p.storey, area_m2: p.area_m2, total_m2: p.total_m2, volume_m3: p.volume_m3, note: p.note, keys: p.keys }))));
  const sumRow = h("tr", { style: { fontWeight: 700 } });
  const drawSums = () => sumRow.replaceChildren(h("td", { colspan: 4 }, T("Σύνολο", "Total")), h("td", { class: "n" }, fmt(edit.reduce((s, p) => s + (p.total_m2 || p.area_m2 || 0), 0), 2)),
    ...keys.map((k) => { const s = edit.reduce((a, p) => a + Number(p.keys[k] || 0), 0); return h("td", { class: "n", style: { color: Math.abs(s - 1000) < 0.5 ? "#1a7f37" : "#b42318" } }, fmt(s, 0)); }));
  drawSums();
  const save = async (btn) => { btn.disabled = true; try { const r = await api(`/projects/${S.pid}/fm/properties`, { method: "PUT", body: { properties: edit, common_areas: f.common_areas } }); toast(r.checks.every((c) => c.ok) ? T("Ο πίνακας αποθηκεύτηκε", "Table saved") : T("Αποθηκεύτηκε, αλλά κάποια στήλη δεν αθροίζει 1000", "Saved, but a column does not add up to 1000"), !r.checks.every((c) => c.ok)); window.go("fm"); } catch (e) { toast(e.message, true); btn.disabled = false; } };
  parts.push(h("div", { class: "card" }, h("h2", {}, T("Ιδιοκτησίες και πίνακας ποσοστών (σύσταση οριζόντιας ιδιοκτησίας)", "Properties and table of shares (deed of horizontal ownership)")),
    h("p", { class: "small mutedt" }, (S.lang === "el" ? f.source : f.source_en) || ""),
    h("div", { class: "scroll", style: { maxHeight: "460px" } }, h("table", { class: "small" },
      h("thead", {}, h("tr", {}, h("th", {}, T("Κωδ.", "Code")), h("th", {}, T("Ιδιοκτησία", "Property")), h("th", {}, T("Είδος", "Type")), h("th", {}, T("Όροφος", "Storey")), h("th", { class: "n" }, "m²"), ...keys.map((k) => h("th", { class: "n" }, KL(k) + " ‰")))),
      h("tbody", {}, edit.map((p) => h("tr", {}, h("td", {}, p.id), h("td", {}, S.lang === "el" ? p.name_el : p.name_en, p.note ? h("div", { class: "small mutedt" }, p.note) : null), h("td", {}, L2(TYPE[p.type])), h("td", {}, L2(STOREY[p.storey]) || p.storey || ""),
        h("td", { class: "n" }, fmt(p.total_m2 || p.area_m2, 2)), ...keys.map((k) => h("td", { class: "n" }, numInput(p.keys[k], (v) => { p.keys[k] = v; drawSums(); }, { w: "58px", step: 1 }))))), sumRow))),
    f.common_areas.length ? h("p", { class: "small mutedt" }, T("Κοινόχρηστοι χώροι: ", "Common areas: ") + f.common_areas.map((c) => `${L2(STOREY[c.storey]) || c.storey} ${fmt(c.area_m2, 2)} m²`).join(" · ") + ` (${T("σύνολο", "total")} ${fmt(f.common_areas.reduce((s, c) => s + c.area_m2, 0), 2)} m²)`) : null,
    h("div", { class: "row end", style: { marginTop: "8px" } }, h("span", { class: "small mutedt", style: { marginRight: "auto" } }, T("Τα ονόματα των ιδιοκτητών δεν καταχωρούνται.", "Owners' names are not stored.")), h("button", { class: "btn", onclick: (e) => save(e.target) }, T("Αποθήκευση πίνακα", "Save table")))));

  // ---- allocation of running costs per property
  const catTot = (p, k) => p.avg_annual[k] || 0;
  parts.push(h("div", { class: "card" }, h("h2", {}, T("Επιμερισμός κόστους λειτουργίας ανά ιδιοκτησία (μέσος όρος ανά έτος)", "Running cost per property (yearly average)")),
    h("div", { class: "scroll" }, h("table", { class: "small" },
      h("thead", {}, h("tr", {}, h("th", {}, T("Ιδιοκτησία", "Property")), ...CAT.map((c) => h("th", { class: "n" }, S.lang === "el" ? c[1] : c[2])), h("th", { class: "n" }, T("Σύνολο €/έτος", "Total €/year")), h("th", { class: "n" }, "€/m²·" + T("έτος", "y")), h("th", { class: "n" }, T("1ο έτος", "Year 1")), h("th", { class: "n" }, T(`Παρούσα αξία ${f.horizon} ετών`, `${f.horizon}-year present value`)), h("th", { class: "n" }, T("Ετήσια αναμενόμενη ζημιά", "Expected annual loss")))),
      h("tbody", {}, props.map((p) => h("tr", {}, h("td", {}, `${p.id} · ${S.lang === "el" ? p.name_el : p.name_en}`), ...CAT.map(([k]) => h("td", { class: "n" }, fmt(catTot(p, k)))), h("td", { class: "n", style: { fontWeight: 700 } }, fmt(p.avg_annual_total)), h("td", { class: "n" }, fmt(p.eur_per_m2_year, 1)), h("td", { class: "n" }, fmt(p.year1_total)), h("td", { class: "n" }, fmt(p.pv_total)), h("td", { class: "n" }, fmt(p.risk_eal)))),
        h("tr", { style: { fontWeight: 700 } }, h("td", {}, T("Σύνολο κτιρίου", "Building total")), ...CAT.map(([k]) => h("td", { class: "n" }, fmt(props.reduce((s, p) => s + catTot(p, k), 0)))), h("td", { class: "n" }, fmt(bldAvg)), h("td", {}), h("td", { class: "n" }, fmt(props.reduce((s, p) => s + p.year1_total, 0))), h("td", { class: "n" }, fmt(props.reduce((s, p) => s + p.pv_total, 0))), h("td", { class: "n" }, fmt(props.reduce((s, p) => s + p.risk_eal, 0))))))),
    h("p", { class: "small mutedt" }, T(`Έλεγχος: το σύνολο που επιμερίζεται στις ιδιοκτησίες (${eur(f.reconciliation.allocated_total)}) ισούται με το κόστος λειτουργίας του 5D στα ${f.horizon} έτη (${eur(f.reconciliation.building_running_total)}). Η ετήσια αναμενόμενη ζημιά από σεισμό, φωτιά και πλημμύρα (καρτέλα «7D Κίνδυνοι») μοιράζεται με τα χιλιοστά οικοπέδου και δεν προστίθεται στο σύνολο. Το ${fmt(f.common_energy_pct)}% της ενέργειας θεωρείται κοινόχρηστο (φωτισμός, ανελκυστήρας).`,
      `Check: the total allocated to the properties (${eur(f.reconciliation.allocated_total)}) equals the 5D running cost over ${f.horizon} years (${eur(f.reconciliation.building_running_total)}). The expected annual loss from earthquake, fire and flood ("7D Risks") is split by plot shares and is not added to the total. ${fmt(f.common_energy_pct)}% of the energy is taken as common (lighting, lift).`)),
    canvasBox("chFm")));

  // ---- who pays what: average year by key of the table
  const bt = Object.entries(f.by_target_avg).sort((a, b) => b[1] - a[1]);
  parts.push(h("div", { class: "grid g2" },
    h("div", { class: "card" }, h("h2", {}, T("Κοινόχρηστα και ιδιωτικά: μέσο έτος ανά κλειδί επιμερισμού", "Common and private: average year by allocation key")),
      h("table", { class: "small" }, h("tbody", {}, bt.map(([k, v]) => h("tr", {}, h("td", {}, KL(k)), h("td", { class: "n" }, eur(v))))))),
    h("div", { class: "card" }, h("h2", {}, T("Κόστος ανά m² και έτος", "Cost per m² and year")), canvasBox("chFm2", "short"))));

  // ---- asset register
  parts.push(h("div", { class: "card" }, h("h2", {}, T("Μητρώο εγκαταστάσεων και περιοδικές εργασίες", "Asset register and periodic tasks")),
    h("div", { class: "scroll" }, h("table", { class: "small" },
      h("thead", {}, h("tr", {}, h("th", {}, T("Εγκατάσταση", "Asset")), h("th", {}, T("Θέση", "Location")), h("th", {}, T("Περιοδικές εργασίες", "Periodic tasks")), h("th", { class: "n" }, T("Αξία", "Value")), h("th", { class: "n" }, T("Συντήρηση €/έτος", "Upkeep €/y")), h("th", { class: "n" }, T("Αντικατάσταση (έτη)", "Replace (years)")), h("th", {}, T("Ποιος πληρώνει", "Who pays")))),
      h("tbody", {}, f.assets.map((a) => h("tr", {}, h("td", {}, S.lang === "el" ? a.el : a.en), h("td", {}, (a.where === "common" ? T("Κοινόχρηστο", "Common") : T("Ιδιοκτησίες", "Properties")) + (a.storey ? " · " + (L2(STOREY[a.storey]) || a.storey) : "")),
        h("td", {}, (a.tasks || []).map((t) => h("div", {}, `${S.lang === "el" ? t.el : t.en} – ${t.every_months >= 12 ? T(`κάθε ${fmt(t.every_months / 12, t.every_months % 12 ? 1 : 0)} έτη`, `every ${fmt(t.every_months / 12, t.every_months % 12 ? 1 : 0)} y`) : T(`κάθε ${t.every_months} μήνες`, `every ${t.every_months} months`)}`, t.basis ? h("span", { class: "mutedt" }, ` (${t.basis})`) : null))),
        h("td", { class: "n" }, eur(a.initial_cost)), h("td", { class: "n" }, fmt(a.annual_maintenance)), h("td", { class: "n" }, a.replace_every ?? "–"),
        h("td", {}, Object.entries(a.allocation || {}).map(([k, v]) => `${KL(k)} ${fmt(v * 100)}%`).join(" · "))))))),
    h("p", { class: "small mutedt" }, T("Οι συχνότητες είναι ενδεικτικές· οι νομοθετικές αναφορές δίνονται για έλεγχο από τον διαχειριστή του κτιρίου. Η αξία και η συντήρηση προέρχονται από το 5D.", "Frequencies are indicative; the legal references are given for the building manager to check. Value and upkeep come from 5D."))));

  // ---- maintenance calendar
  const H = f.horizon, cal = f.calendar;
  const yrs = Array.from({ length: H }, (_, i) => i + 1);
  const shown = cal.filter((e) => e.year <= 30);
  parts.push(h("div", { class: "card" }, h("h2", {}, T("Ημερολόγιο επεμβάσεων: αντικαταστάσεις και επιθεωρήσεις", "Works calendar: replacements and inspections")), canvasBox("chCal", "short"),
    h("div", { class: "scroll", style: { maxHeight: "360px" } }, h("table", { class: "small" },
      h("thead", {}, h("tr", {}, h("th", { class: "n" }, T("Έτος", "Year")), h("th", {}, T("Στοιχείο", "Component")), h("th", {}, T("Εργασία", "Work")), h("th", { class: "n" }, T("Κόστος", "Cost")), h("th", {}, T("Ποιος πληρώνει", "Who pays")))),
      h("tbody", {}, shown.map((e) => h("tr", {}, h("td", { class: "n" }, e.year), h("td", {}, S.lang === "el" ? e.el : e.en), h("td", {}, e.action === "replacement" ? T("Αντικατάσταση", "Replacement") : T("Επιθεώρηση", "Inspection")), h("td", { class: "n" }, eur(e.cost)),
        h("td", {}, Object.entries(e.allocation || {}).map(([k, v]) => `${KL(k)} ${fmt(v * 100)}%`).join(" · "))))))),
    h("p", { class: "small mutedt" }, T(`Εμφανίζονται τα πρώτα 30 έτη (${shown.length} από ${cal.length} επεμβάσεις στα ${H} έτη). Τα κόστη είναι σε σημερινές τιμές.`, `First 30 years shown (${shown.length} of ${cal.length} works over ${H} years). Costs at today's prices.`))));

  out.replaceChildren(...parts);
  const show = props.filter((p) => p.type === "apartment" || p.avg_annual_total > 0);
  chart("chFm", { type: "bar", data: { labels: show.map((p) => p.id), datasets: CAT.map(([k, el, en], i) => ({ label: S.lang === "el" ? el : en, data: show.map((p) => Math.round(catTot(p, k))), backgroundColor: PAL[i], borderRadius: 2 })) },
    options: { scales: { x: { stacked: true, grid: { display: false } }, y: Object.assign(ax(T("€/έτος", "€/year")), { stacked: true }) } } });
  chart("chFm2", { type: "bar", data: { labels: show.map((p) => p.id), datasets: [{ data: show.map((p) => p.eur_per_m2_year), backgroundColor: show.map((p) => (p.type === "apartment" ? PAL[0] : PAL[6])), borderRadius: 3 }] },
    options: { plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: ax("€/m²·" + T("έτος", "y")) } } });
  const perYear = (act) => yrs.map((y) => Math.round(cal.filter((e) => e.year === y && e.action === act).reduce((s, e) => s + e.cost, 0) / 1000));
  chart("chCal", { type: "bar", data: { labels: yrs, datasets: [{ label: T("Αντικαταστάσεις", "Replacements"), data: perYear("replacement"), backgroundColor: PAL[3] }, { label: T("Επιθεωρήσεις", "Inspections"), data: perYear("inspection"), backgroundColor: PAL[2] }] },
    options: { scales: { x: Object.assign({ grid: { display: false } }, { stacked: true, title: { display: true, text: T("έτος λειτουργίας", "year in use") } }), y: Object.assign(ax("k€"), { stacked: true }) } } });
}
