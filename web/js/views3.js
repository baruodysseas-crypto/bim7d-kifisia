import { S, T, api, h, fmt, eur, pct, toast, chart, ax, canvasBox, kpi, numInput, field, spinner, download, PAL } from "./util.js";

// ------------------------------------------------------------------ PRICES
export async function pricesView(root) {
  root.append(h("h1", {}, T("Τιμές αγοράς και δείκτες", "Market prices and indices")), h("p", { class: "lead" }, T("Οι τιμές μονάδας του κοστολογίου πολλαπλασιάζονται με το λόγο τρέχουσα/βάση κάθε ομάδας δεικτών. Οι τιμές ανανεώνονται live (και αυτόματα κάθε φορά που ανοίγει η εφαρμογή, αν είναι παλαιότερες από 12 ώρες): συμβόλαια χάλυβα (HRC), αλουμινίου, χαλκού και Brent από το Yahoo Finance, ο δείκτης κόστους κατασκευής νέων κατοικιών της Ελλάδας από τη Eurostat, το ρεύμα από το ENTSO-E (με token). Μαζί κατεβαίνει και το ιστορικό 10 ετών κάθε σειράς, από το οποίο υπολογίζονται η τάση και η μεταβλητότητα των τιμών για τα σενάρια κόστους. Αν μια πηγή αποτύχει, μένει η τελευταία τιμή.", "Unit prices in the cost estimate are multiplied by the current/base ratio of each index group. Prices refresh live (and automatically each time the app opens, if older than 12 hours): steel (HRC), aluminium, copper and Brent futures from Yahoo Finance, the Greek construction cost index for new dwellings from Eurostat, power from ENTSO-E (with a token). The 10-year history of every series is downloaded too and gives the drift and volatility used in the cost scenarios. If a source fails, the last value is kept.")));
  const body = h("div"); root.append(body);
  let R = await api("/prices");
  const draw = async () => {
    const st = R.state, beh = R.behaviour;
    const bmap = Object.fromEntries(beh.map((b) => [b.group, b]));
    const upd = async (g, patch) => { await api(`/prices/group/${g}`, { method: "PATCH", body: patch }); R = await api("/prices"); S.cache = {}; paths = null; draw(); };
    const rows = Object.entries(st.groups).map(([k, g]) => h("tr", {},
      h("td", {}, h("b", {}, g[S.lang === "el" ? "el" : "en"]), h("div", { class: "small mutedt" }, g.source)),
      h("td", { class: "n" }, g.unit), h("td", { class: "n" }, numInput(g.base, (v) => v > 0 && upd(k, { base: v }), { w: "84px" })),
      h("td", { class: "n" }, numInput(Number(g.value.toFixed(3)), (v) => v != null && upd(k, { value: v }), { w: "84px", cls: g.mode === "manual" ? "" : "ov" })),
      h("td", { class: "n" }, h("b", {}, (bmap[k].ratio_now >= 1 ? "+" : "") + fmt((bmap[k].ratio_now - 1) * 100, 1) + "%")),
      h("td", {}, g.error ? h("span", { class: "bad small", title: g.error }, T("σφάλμα πηγής", "source error")) : (g.updated ? h("span", { class: "small mutedt" }, g.updated.slice(0, 16).replace("T", " ")) : h("span", { class: "small mutedt" }, T("αρχικό", "seed"))), g.provider ? h("span", { class: "pill", style: { marginLeft: "6px" } }, g.provider.type) : null)));
    const cfg = st.settings;
    const keyIn = h("input", { type: "password", placeholder: cfg.tradingeconomics_key ? "•••• " + T("αποθηκευμένο", "saved") : "client:secret", style: { width: "200px" } });
    const tokIn = h("input", { type: "password", placeholder: cfg.entsoe_token ? "•••• " + T("αποθηκευμένο", "saved") : "token", style: { width: "200px" } });
    const status = h("div", { class: "small mutedt", style: { marginTop: "8px" } });
    body.replaceChildren(
      h("div", { class: "card" }, h("div", { class: "row", style: { justifyContent: "space-between", marginBottom: "8px" } }, h("h2", { style: { margin: 0 } }, T("Ομάδες δεικτών τιμών", "Price index groups")),
        h("button", { class: "btn", onclick: async (e) => { e.target.disabled = true; status.replaceChildren(spinner(), " " + T("Ανανέωση…", "Refreshing…")); try { const r = await api("/prices/refresh", { method: "POST" }); R = await api("/prices"); const ok = Object.values(r.result).filter((x) => x.ok).length, bad = Object.values(r.result).length - ok, hok = Object.values(r.history || {}).filter((x) => x.ok).length; toast(`${ok} ${T("ενημερώθηκαν", "updated")}, ${bad} ${T("απέτυχαν (κρατήθηκε η προηγούμενη τιμή)", "failed (previous value kept)")} · ${hok} ${T("ιστορικές σειρές", "history series")}`, bad > 0 && ok === 0); S.cache = {}; paths = null; draw(); } catch (er) { toast(er.message, true); e.target.disabled = false; } } }, T("Ανανέωση live τιμών και ιστορικού", "Refresh live prices and history"))),
        h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, T("Ομάδα", "Group")), h("th", { class: "n" }, T("Μονάδα", "Unit")), h("th", { class: "n" }, T("Βάση", "Base")), h("th", { class: "n" }, T("Τρέχουσα τιμή", "Current")), h("th", { class: "n" }, T("Μεταβολή", "Change")), h("th", {}, T("Ενημέρωση", "Updated")))), h("tbody", {}, rows))), status),
      historyCard(st, beh),
      h("div", { class: "card" }, h("h2", {}, T("Σύνδεση με πηγές (προαιρετικό)", "Source connections (optional)")), h("div", { class: "row" }, field("ENTSO-E token", tokIn), h("button", { class: "btn small", onclick: async () => { const b = {}; if (tokIn.value) b.entsoe_token = tokIn.value; await api("/prices/settings", { method: "PATCH", body: b }); toast(T("Αποθηκεύτηκε", "Saved")); R = await api("/prices"); draw(); } }, T("Αποθήκευση", "Save"))),
        h("p", { class: "small mutedt" }, T("Τα κλειδιά αποθηκεύονται τοπικά στον φάκελο δεδομένων. Το Yahoo Finance και η Eurostat δεν χρειάζονται κλειδί (το Yahoo είναι ανεπίσημη πηγή)· τα συμβόλαια μετάλλων/Brent παρακολουθούνται ως σχετική μεταβολή από την πρώτη λήψη, πάνω στο επίπεδο της ΕΛΣΤΑΤ. Το TradingEconomics δεν χρειάζεται πλέον.", "Keys are stored locally in the data folder. Yahoo Finance and Eurostat need no key (Yahoo is an unofficial source); metal/Brent futures are tracked as relative change since the first fetch, on top of the ELSTAT level. TradingEconomics is no longer needed."))),
      h("div", { class: "card" }, h("h2", {}, T("Πώς συμπεριφέρονται οι τιμές: τάση και μεταβλητότητα", "How prices behave: drift and volatility")), h("p", { class: "small mutedt" }, T("Μοντέλο GBM ανά ομάδα με κοινό παράγοντα αγοράς. Οι τιμές μ/σ είναι βαθμονομημένες σε ιστορική συμπεριφορά (π.χ. ράβδοι χάλυβα ±20–25% ετησίως, ρεύμα ~30%) και επεξεργάζονται. Η αβεβαιότητα 1 έτους (P10–P90) τροφοδοτεί το Monte-Carlo του κοστολογίου.", "GBM model per group with a common market factor. The μ/σ values are calibrated to historical behaviour (e.g. rebar ±20–25% a year, power ~30%) and editable. The 1-year uncertainty (P10–P90) feeds the Monte-Carlo in the cost tab.")),
        h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, T("Ομάδα", "Group")), h("th", { class: "n" }, T("Τάση μ %/έτος", "Drift μ %/y")), h("th", { class: "n" }, T("Μεταβλητότητα σ %", "Volatility σ %")), h("th", { class: "n" }, "P10 1y"), h("th", { class: "n" }, "P50 1y"), h("th", { class: "n" }, "P90 1y"))),
          h("tbody", {}, beh.map((b) => h("tr", {}, h("td", {}, b[S.lang === "el" ? "label_el" : "label_en"], b.calibrated ? h("span", { class: "pill", style: { marginLeft: "6px" } }, T("από ιστορικό", "from history")) : null), h("td", { class: "n" }, numInput(+(b.mu * 100).toFixed(2), (v) => upd(b.group, { dynamics: { mu: v / 100 } }), { w: "70px", step: 0.1 })), h("td", { class: "n" }, numInput(+(b.sigma * 100).toFixed(2), (v) => upd(b.group, { dynamics: { sigma: v / 100 } }), { w: "70px", step: 0.5 })), h("td", { class: "n" }, "×" + fmt(b.p10_1y, 2)), h("td", { class: "n" }, "×" + fmt(b.p50_1y, 2)), h("td", { class: "n" }, "×" + fmt(b.p90_1y, 2))))))),
        h("div", { class: "row", style: { marginTop: "12px" } }, field(T("Ομάδα για διάγραμμα", "Group to chart"), (() => { const s = h("select", { id: "pgSel" }, Object.entries(st.groups).map(([k, g]) => h("option", { value: k }, g[S.lang === "el" ? "el" : "en"]))); s.value = "steel_rebar"; s.onchange = () => fan(); return s; })())), canvasBox("chFan")));
    await fan();
  };
  let paths = null;
  function historyCard(st, beh) {
    const ser = st.series || {}, cal = st.calibration || {};
    const keys = Object.keys(st.groups).filter((k) => ser[k]);
    const card = h("div", { class: "card" }, h("h2", {}, T("Ιστορικά δεδομένα αγοράς (10 έτη)", "Market history (10 years)")));
    if (!keys.length) { card.append(h("p", { class: "mutedt" }, T("Δεν έχει κατέβει ακόμα ιστορικό. Πατήστε «Ανανέωση live τιμών και ιστορικού» (χρειάζεται internet).", "No history downloaded yet. Press “Refresh live prices and history” (needs internet)."))); return card; }
    const useCal = st.settings.use_calibrated !== false;
    const sel = h("select", {}, keys.map((k) => h("option", { value: k }, st.groups[k][S.lang === "el" ? "el" : "en"])));
    sel.value = keys.includes("steel_rebar") ? "steel_rebar" : keys[0];
    const info = h("div", { class: "small", style: { margin: "6px 0" } });
    const drawH = () => {
      const k = sel.value, sr = ser[k], c = cal[k] || {}, a = (st.dynamics_assumed || {})[k] || {};
      info.replaceChildren(`${sr.src} · ${sr.unit} · ${c.from || sr.t[0]} – ${c.to || sr.t[sr.t.length - 1]} · ${T("ελάχιστο", "min")} ${fmt(c.min, 2)} · ${T("μέγιστο", "max")} ${fmt(c.max, 2)} · ${T("μέση ετήσια μεταβολή", "average annual change")} ${c.cagr != null ? fmt(c.cagr * 100, 1) + "%" : "–"}`);
      chart("chHist", { type: "line", data: { labels: sr.t, datasets: [{ label: `${st.groups[k][S.lang === "el" ? "el" : "en"]} (${sr.unit})`, data: sr.v, borderColor: PAL[0], backgroundColor: "rgba(42,120,214,.08)", fill: true, borderWidth: 2, pointRadius: 0, tension: 0.15 }] }, options: { plugins: { legend: { display: false } }, scales: { x: ax(""), y: ax(sr.unit) } } });
    };
    sel.onchange = drawH;
    const rows = keys.map((k) => { const c = cal[k] || {}, a = (st.dynamics_assumed || {})[k] || {}; return h("tr", {}, h("td", {}, st.groups[k][S.lang === "el" ? "el" : "en"]), h("td", { class: "n" }, c.from ? `${c.from} – ${c.to}` : "–"),
      h("td", { class: "n" }, fmt((c.mu || 0) * 100, 1) + "%"), h("td", { class: "n" }, fmt((c.sigma || 0) * 100, 1) + "%"), h("td", { class: "n mutedt" }, fmt((a.mu || 0) * 100, 1) + "%"), h("td", { class: "n mutedt" }, fmt((a.sigma || 0) * 100, 1) + "%")); });
    const sw = async (use) => { await api("/prices/dynamics", { method: "POST", body: { use } }); R = await api("/prices"); paths = null; S.cache = {}; draw(); toast(T("Αποθηκεύτηκε", "Saved")); };
    card.append(h("div", { class: "row" }, field(T("Σειρά", "Series"), sel)), info, canvasBox("chHist"),
      h("h3", {}, T("Τάση και μεταβλητότητα: από το ιστορικό ή από παραδοχές", "Drift and volatility: from history or assumed")),
      h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, T("Ομάδα", "Group")), h("th", { class: "n" }, T("Περίοδος", "Period")), h("th", { class: "n" }, T("μ ιστορικό", "μ history")), h("th", { class: "n" }, T("σ ιστορικό", "σ history")), h("th", { class: "n" }, T("μ παραδοχή", "μ assumed")), h("th", { class: "n" }, T("σ παραδοχή", "σ assumed")))), h("tbody", {}, rows)),
      h("div", { class: "row", style: { marginTop: "8px" } },
        h("button", { class: useCal ? "btn small" : "btn ghost small", onclick: () => sw("calibrated") }, (useCal ? "✓ " : "") + T("Χρήση τιμών από το ιστορικό", "Use values from history")),
        h("button", { class: useCal ? "btn ghost small" : "btn small", onclick: () => sw("assumed") }, (useCal ? "" : "✓ ") + T("Χρήση παραδοχών", "Use assumptions"))),
      h("p", { class: "small mutedt" }, T("μ, σ από τις λογαριθμικές μεταβολές της σειράς (μηνιαίες για τα συμβόλαια σε €, τριμηνιαίες για τον δείκτη της Eurostat)· η τάση που χρησιμοποιείται για το μέλλον περιορίζεται στο −5…+10 %/έτος.", "μ, σ from the log changes of the series (monthly for futures in €, quarterly for the Eurostat index); the drift used for the future is limited to −5…+10 %/year.")));
    setTimeout(drawH, 0);
    return card;
  }
  async function fan() {
    if (!paths) paths = await api("/prices/paths?years=3&n=600");
    const g = document.getElementById("pgSel")?.value || "steel_rebar"; const p = paths.paths[g]; if (!p) return;
    const lbl = p.p50.map((_, i) => i);
    const ln = (label, d, c, dash) => ({ label, data: d, borderColor: c, borderWidth: 2.2, pointRadius: 0, borderDash: dash ? [5, 4] : [], tension: 0.2 });
    chart("chFan", { type: "line", data: { labels: lbl, datasets: [ln("P90", p.p90, PAL[1], true), ln("P50", p.p50, PAL[0]), ln("P10", p.p10, PAL[2], true)] }, options: { scales: { x: ax(T("μήνες από σήμερα", "months from today")), y: ax(T("λόγος τιμής προς σήμερα", "price ratio vs today")) } } });
  }
  await draw();
}

// ------------------------------------------------------------------ REPORT
export async function reportView(root) {
  const p = S.project;
  root.append(h("h1", {}, T("Έκθεση PDF της μελέτης", "Study report (PDF)")), h("p", { class: "lead" }, T("Δημιουργεί πλήρη μελέτη PDF με τα τρέχοντα δεδομένα: ποσότητες (με τις τροποποιήσεις σας), κοστολόγιο, χρονοδιάγραμμα 4D, ενεργειακή μελέτη, κύκλο ζωής και σενάρια κινδύνων. Ό,τι αλλάξατε στις υπόλοιπες καρτέλες περνά στην έκθεση.", "Builds a complete PDF study from the current data: quantities (with your edits), cost estimate, 4D schedule, energy study, life cycle and hazard scenarios. Whatever you changed in the other tabs flows into the report.")));
  const secs = [["summary", T("Σύνοψη", "Summary")], ["model", T("3D Μοντέλο BIM", "3D BIM model")], ["site", T("Περιοχή – live δεδομένα", "Site – live data")], ["quantities", T("Προμέτρηση", "Quantities")], ["cost", T("5D Κόστος κατασκευής", "5D Construction cost")], ["schedule", T("4D Χρονοδιάγραμμα", "4D Schedule")], ["energy", T("6D Βιωσιμότητα: ενέργεια", "6D Sustainability: energy")], ["lifecycle", T("5D Κόστος στον χρόνο και 6D αποτύπωμα", "5D Cost over time and 6D footprint")], ["fm", T("7D Διαχείριση εγκαταστάσεων και ιδιοκτησιών", "7D Facility and property management")], ["hazards", T("7D Κίνδυνοι και ανθεκτικότητα", "7D Risk and resilience")], ["assumptions", T("Παραδοχές και πηγές", "Assumptions and sources")]];
  const on = Object.fromEntries(secs.map(([k]) => [k, true]));
  let lang = S.lang;
  const author = h("input", { placeholder: T("π.χ. Μπαρούτης Οδυσσέας, Πολιτικός Μηχανικός", "e.g. name, civil engineer"), style: { width: "100%" } }), notes = h("textarea", { rows: 4, placeholder: T("Σημειώσεις που θα εμφανιστούν στην έκθεση…", "Notes to appear in the report…"), style: { width: "100%" } });
  const status = h("div", { class: "small mutedt", style: { marginTop: "10px" } });
  const btn = h("button", { class: "btn", onclick: async () => {
    btn.disabled = true; status.replaceChildren(spinner(), " " + T("Δημιουργία PDF (10–40 δευτ.)…", "Building PDF (10–40 s)…"));
    try { const r = await api(`/projects/${S.pid}/report`, { method: "POST", raw: true, body: { lang, sections: Object.keys(on).filter((k) => on[k]), notes: notes.value, author: author.value } }); const blob = await r.blob(); download(blob, `${S.pid}_${lang}.pdf`); status.textContent = "✓ " + T("Το PDF κατέβηκε", "PDF downloaded") + ` (${fmt(blob.size / 1024)} KB)`; }
    catch (e) { status.textContent = ""; toast(e.message, true); } btn.disabled = false; } }, "⬇ " + T("Δημιουργία και λήψη PDF", "Build and download PDF"));
  root.append(h("div", { class: "grid g2" }, h("div", { class: "card" }, h("h2", {}, T("Ενότητες", "Sections")), h("div", { class: "grid g2" }, secs.map(([k, l]) => h("label", { class: "chk" }, h("input", { type: "checkbox", checked: true, onchange: (e) => (on[k] = e.target.checked) }), l))),
      h("div", { class: "row", style: { marginTop: "12px" } }, field(T("Γλώσσα έκθεσης", "Report language"), (() => { const s = h("select", {}, h("option", { value: "el" }, "Ελληνικά"), h("option", { value: "en" }, "English")); s.value = lang; s.onchange = () => (lang = s.value); return s; })()))),
    h("div", { class: "card" }, h("h2", {}, T("Στοιχεία έκθεσης", "Report details")), field(T("Συντάκτης", "Author"), author), field(T("Σημειώσεις", "Notes"), notes), h("div", { class: "row end", style: { marginTop: "10px" } }, btn), status)),
    h("div", { class: "warnbox" }, T("Η έκθεση περιέχει σαφή αποποίηση ευθύνης: τα σενάρια κινδύνων και η ενεργειακή κλάση είναι ενδεικτικά (προμελέτης) και δεν υποκαθιστούν στατική μελέτη, μελέτη πυροπροστασίας, ΠΕΑ ή επίσημη προμέτρηση.", "The report carries a clear disclaimer: hazard scenarios and the energy class are indicative (pre-design) and do not replace structural design, fire-safety design, an official EPC or a certified bill of quantities.")), p.meta.synthetic_geometry ? h("div", { class: "warnbox" }, T("Το έργο έχει συνθετική γεωμετρία 3D (demo) — οι ποσότητες είναι ενδεικτικές.", "This project has synthetic 3D geometry (demo); quantities are indicative.")) : null);
}
