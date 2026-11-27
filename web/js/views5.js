// Περιοχή – live δεδομένα: Κτηματολόγιο, ιστορικό σεισμών (USGS) με καμπύλη επικινδυνότητας, ιστορικό κλίματος (Open-Meteo / ERA5).
import { S, T, api, h, fmt, eur, toast, chart, ax, canvasBox, kpi, spinner, PAL } from "./util.js";

const MON = () => (S.lang === "el" ? ["Ιαν", "Φεβ", "Μαρ", "Απρ", "Μάι", "Ιουν", "Ιουλ", "Αυγ", "Σεπ", "Οκτ", "Νοε", "Δεκ"] : ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]);
const when = (iso) => (iso ? iso.slice(0, 16).replace("T", " ") + " UTC" : "–");
const g3 = (x) => (x == null ? "–" : fmt(x, 3) + " g");

export async function siteView(root) {
  root.append(h("h1", {}, T("Περιοχή – live δεδομένα", "Site – live data")),
    h("p", { class: "lead" }, T("Δεδομένα που η εφαρμογή φέρνει live από δημόσιες υπηρεσίες για τη θέση του έργου: το γεωτεμάχιο από το Κτηματολόγιο, το ιστορικό των σεισμών της περιοχής από το 1900 (USGS) και το ιστορικό του κλίματος των τελευταίων 30 ετών (Open-Meteo, ERA5). Ανανεώνονται αυτόματα όταν ανοίγει η εφαρμογή (αν είναι παλαιότερα από 7 ημέρες) ή με το κουμπί. Από αυτά υπολογίζονται η σεισμική επικινδυνότητα της θέσης, που μπορεί να τροφοδοτήσει τους κινδύνους του 7D, και το κλίμα της θέσης, που μπορεί να τροφοδοτήσει την ενεργειακή ανάλυση του 6D.",
      "Data the app fetches live from public services for the project site: the parcel from the Hellenic Cadastre, the earthquake history of the area since 1900 (USGS) and the climate history of the last 30 years (Open-Meteo, ERA5). They refresh automatically when the app opens (if older than 7 days) or with the button. From them the app computes the seismic hazard of the site, which can feed the 7D risks, and the site climate, which can feed the 6D energy analysis.")));
  const out = h("div", {}, h("div", { class: "card" }, spinner(), " " + T("Φόρτωση…", "Loading…")));
  root.append(out);
  let R;
  const load = async () => { R = await api(`/projects/${S.pid}/live`); draw(); };
  const refresh = async (what, btn, extra = {}) => {
    if (btn) btn.disabled = true;
    const st = document.getElementById("liveStatus");
    if (st) st.replaceChildren(spinner(), " " + T("Λήψη από τις υπηρεσίες… (έως 1 λεπτό)", "Fetching from the services… (up to 1 minute)"));
    try {
      const r = await api(`/projects/${S.pid}/live/refresh`, { method: "POST", body: { what, ...extra } });
      const bad = Object.entries(r.status).filter(([, v]) => !v.ok);
      toast(bad.length ? T("Δεν ενημερώθηκαν: ", "Not updated: ") + bad.map(([k, v]) => `${k} (${v.error})`).join(" · ") : T("Τα live δεδομένα ενημερώθηκαν", "Live data updated"), bad.length > 0);
      S.cache = {};
      R = r; draw();
    } catch (e) { toast(e.message, true); if (btn) btn.disabled = false; if (st) st.textContent = ""; }
  };
  const setUse = async (patch) => { await api(`/projects/${S.pid}/live/use`, { method: "PATCH", body: patch }); S.cache = {}; await load(); toast(T("Αποθηκεύτηκε", "Saved")); };

  function draw() {
    const lv = R.live || {}, use = lv.use || {}, err = lv.errors || {};
    const head = h("div", { class: "card" },
      h("div", { class: "row", style: { justifyContent: "space-between" } },
        h("div", {}, h("b", {}, T("Θέση έργου: ", "Project site: ")), `${fmt(R.site[0], 5)}, ${fmt(R.site[1], 5)}`,
          h("span", { class: "small mutedt" }, ` · ${T("τελευταία ενημέρωση", "last update")}: ${when(lv.updated)}`), R.auto && R.auto.running ? h("span", { class: "pill", style: { marginLeft: "8px" } }, T("αυτόματη ενημέρωση σε εξέλιξη…", "automatic refresh running…")) : null),
        h("button", { class: "btn", onclick: (e) => refresh(["cadastre", "seismic", "climate"], e.target) }, "⟳ " + T("Ανανέωση όλων (live)", "Refresh all (live)"))),
      h("div", { id: "liveStatus", class: "small mutedt", style: { marginTop: "6px" } }),
      R.offline ? h("div", { class: "warnbox" }, T("Η εφαρμογή τρέχει χωρίς σύνδεση (BIM7D_OFFLINE=1).", "The app runs offline (BIM7D_OFFLINE=1).")) : null,
      !lv.updated ? h("div", { class: "warnbox" }, T("Δεν έχουν ληφθεί ακόμα live δεδομένα. Πατήστε «Ανανέωση όλων» (χρειάζεται σύνδεση στο internet).", "No live data yet. Press “Refresh all” (needs an internet connection).")) : null);
    out.replaceChildren(head, cadastreCard(lv.cadastre, err.cadastre), seismicCard(lv.seismic, err.seismic, use), climateCard(lv.climate, err.climate, use));
    drawCharts(lv);
  }

  // ---------------------------------------------------------------- cadastre
  function cadastreCard(c, err) {
    const inp = h("input", { value: c ? c.kaek_fmt : "05 069 35 10 008", style: { width: "170px" } });
    const top = h("div", { class: "row", style: { justifyContent: "space-between", marginBottom: "8px" } },
      h("h2", { style: { margin: 0 } }, T("Κτηματολόγιο – γεωτεμάχιο", "Cadastre – parcel")),
      h("div", { class: "row" }, h("span", { class: "small" }, "ΚΑΕΚ"), inp, h("button", { class: "btn small", onclick: (e) => refresh(["cadastre"], e.target, { kaek: inp.value }) }, T("Αναζήτηση live", "Live lookup"))));
    const box = h("div", { class: "card" }, top);
    if (err) box.append(h("div", { class: "warnbox" }, T("Τελευταία προσπάθεια: ", "Last attempt: ") + err));
    if (!c) { box.append(h("p", { class: "mutedt" }, T("Δεν υπάρχουν ακόμα στοιχεία.", "No data yet."))); return box; }
    const a = c.attributes || {};
    const rows = [[T("ΚΑΕΚ", "KAEK"), c.kaek_fmt], [T("Εμβαδόν (Κτηματολόγιο)", "Area (Cadastre)"), fmt(c.area_m2, 2) + " m²"], [T("Περίμετρος", "Perimeter"), fmt(c.perimeter_m, 2) + " m"],
      [T("Περιγραφή", "Description"), a.DESCR || "–"], [T("Οριζόντιες ιδιοκτησίες", "Horizontal properties"), a.PROP_HOR ?? "–"], [T("Κάθετες ιδιοκτησίες", "Vertical properties"), a.PROP_VERT ?? "–"],
      [T("Δήμος", "Municipality"), (c.ota && c.ota.OTA_NAME) || "–"], [T("Νομός", "Prefecture"), (c.ota && c.ota.NOMOS_NAME) || "–"], [T("Κατάσταση", "Status"), c.layer],
      [T("Κέντρο (WGS84)", "Centre (WGS84)"), `${fmt(c.lat, 6)}, ${fmt(c.lon, 6)}`]];
    box.append(h("div", { class: "grid g2" },
      h("div", {}, h("table", {}, h("tbody", {}, rows.map(([k, v]) => h("tr", {}, h("td", { class: "mutedt" }, k), h("td", {}, h("b", {}, String(v))))))),
        h("p", { class: "small mutedt" }, `${c.source} · ${T("λήψη", "fetched")} ${when(c.fetched)} · `, h("a", { href: "https://maps.ktimatologio.gr", target: "_blank" }, "maps.ktimatologio.gr"))),
      parcelMap(c)));
    return box;
  }

  function parcelMap(c) {
    // OpenStreetMap tiles (zoom 18) with the parcel outline from the Cadastre on top
    const z = 18, n = 2 ** z, TS = 256;
    const px = (lon, lat) => [((lon + 180) / 360) * n * TS, ((1 - Math.log(Math.tan((lat * Math.PI) / 180) + 1 / Math.cos((lat * Math.PI) / 180)) / Math.PI) / 2) * n * TS];
    const [cx, cy] = px(c.lon, c.lat), W = 420, H = 300, x0 = cx - W / 2, y0 = cy - H / 2;
    const tiles = [];
    for (let tx = Math.floor(x0 / TS); tx <= Math.floor((x0 + W) / TS); tx++)
      for (let ty = Math.floor(y0 / TS); ty <= Math.floor((y0 + H) / TS); ty++)
        tiles.push(h("img", { src: `https://tile.openstreetmap.org/${z}/${tx}/${ty}.png`, style: { position: "absolute", left: `${tx * TS - x0}px`, top: `${ty * TS - y0}px`, width: TS + "px", height: TS + "px" }, alt: "" }));
    const pts = c.ring_wgs84.map(([lo, la]) => px(lo, la)).map(([x, y]) => `${(x - x0).toFixed(1)},${(y - y0).toFixed(1)}`).join(" ");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("width", W); svg.setAttribute("height", H); svg.style.position = "absolute"; svg.style.left = "0"; svg.style.top = "0";
    svg.innerHTML = `<polygon points="${pts}" fill="rgba(235,104,52,.18)" stroke="#eb6834" stroke-width="2.5"/>`;
    return h("div", {}, h("div", { style: { position: "relative", width: W + "px", height: H + "px", overflow: "hidden", borderRadius: "8px", border: "1px solid #dcdcd8", background: "#eef0ea" } }, tiles, svg),
      h("div", { class: "small mutedt" }, "© OpenStreetMap contributors · " + T("όριο γεωτεμαχίου: Κτηματολόγιο", "parcel boundary: Hellenic Cadastre")));
  }

  // ---------------------------------------------------------------- earthquakes
  function seismicCard(s, err, use) {
    const box = h("div", { class: "card" }, h("div", { class: "row", style: { justifyContent: "space-between", marginBottom: "8px" } },
      h("h2", { style: { margin: 0 } }, T("Ιστορικό σεισμών και σεισμική επικινδυνότητα της θέσης", "Earthquake history and seismic hazard of the site")),
      h("button", { class: "btn small", onclick: (e) => refresh(["seismic"], e.target) }, "⟳ " + T("Ανανέωση", "Refresh"))));
    if (err) box.append(h("div", { class: "warnbox" }, T("Τελευταία προσπάθεια: ", "Last attempt: ") + err));
    if (!s || !s.n) { box.append(h("p", { class: "mutedt" }, T("Δεν υπάρχουν ακόμα στοιχεία.", "No data yet."))); return box; }
    const gr = s.gr || {}, hz = gr.hazard || {}, rp = hz.pga_for_return_period || {};
    const hs = R.historical_scenario;
    box.append(h("div", { class: "grid g4" },
      kpi(fmt(s.n), T(`σεισμοί M≥4 σε ${fmt(s.radius_km)} km`, `earthquakes M≥4 within ${fmt(s.radius_km)} km`), `${s.period[0].slice(0, 4)}–${s.period[1].slice(0, 4)}`),
      kpi("M " + fmt(s.largest.mag, 1), T("Μεγαλύτερος σεισμός", "Largest earthquake"), `${s.largest.time} · ${fmt(s.largest.dist_km)} km`),
      kpi(g3(s.strongest_at_site.pga_g), T("Ισχυρότερη επιτάχυνση στη θέση (σεισμοί M≥5)", "Strongest acceleration at the site (M≥5 events)"), `M ${fmt(s.strongest_at_site.mag, 1)} · ${s.strongest_at_site.time} · ${fmt(s.strongest_at_site.dist_km)} km`),
      kpi(g3(rp["475"]), T("PGA 475 ετών (10 % σε 50 χρόνια)", "475-year PGA (10 % in 50 years)"), T("ΕΑΚ ζώνη ΙΙ: 0,24 g", "Greek code zone II: 0.24 g"))));
    box.append(h("div", { class: "grid g2" },
      h("div", {}, h("h3", {}, T("Οι σεισμοί στον χρόνο (μέγεθος)", "Earthquakes over time (magnitude)")), canvasBox("chQ")),
      h("div", {}, h("h3", {}, T("Καμπύλη σεισμικής επικινδυνότητας της θέσης", "Seismic hazard curve of the site")), canvasBox("chHz"))));
    box.append(h("div", { class: "grid g2" },
      h("div", {}, h("h3", {}, T("Επικέντρα γύρω από το έργο", "Epicentres around the project")), quakeMap(s)),
      h("div", {}, h("h3", {}, "Gutenberg–Richter"), h("p", { class: "small" }, `b = ${fmt(gr.b, 2)} ± ${fmt(gr.b_se, 2)} · a = ${fmt(gr.a, 2)} · ${T("πλήρης κατάλογος M≥", "complete catalogue M≥")}${fmt(gr.Mc, 1)} ${T("από", "since")} ${gr.from_year} (${fmt(gr.n)} ${T("σεισμοί", "events")})`),
        h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "M ≥"), h("th", { class: "n" }, T("σεισμοί/έτος (G–R)", "events/year (G–R)")), h("th", { class: "n" }, T("παρατηρημένοι/έτος", "observed/year")), h("th", { class: "n" }, T("περίοδος επαναφοράς", "return period")), h("th", { class: "n" }, T("πιθαν. σε 50 έτη", "prob. in 50 y")))),
          h("tbody", {}, (gr.rates || []).map((r) => h("tr", {}, h("td", {}, fmt(r.M, 1)), h("td", { class: "n" }, fmt(r.rate_gr, 3)), h("td", { class: "n" }, fmt(r.rate_obs, 3)), h("td", { class: "n" }, r.return_period_y ? fmt(r.return_period_y, 1) + T(" έτη", " y") : "–"), h("td", { class: "n" }, fmt(r.p50y * 100, 1) + "%"))))),
        h("p", { class: "small mutedt" }, T("Περιοχή 150 km· στους πολύ μεγάλους σεισμούς ο κατάλογος (μικτές κλίμακες μεγέθους) υποεκτιμά/υπερεκτιμά· τα αποτελέσματα είναι ενδεικτικά.", "150 km region; with mixed magnitude scales the largest events are uncertain; results are indicative.")))));
    // 7D link
    const sr = s.scenario_rates || {};
    box.append(h("h3", {}, T("Σύνδεση με τους κινδύνους (7D)", "Link to the risks (7D)")),
      h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, T("Σενάριο 7D", "7D scenario")), h("th", { class: "n" }, "Ms @ km"), h("th", { class: "n" }, "PGA"), h("th", { class: "n" }, T("ετήσια πιθανότητα – παραδοχή", "annual probability – assumed")), h("th", { class: "n" }, T("ετήσια πιθανότητα – από το ιστορικό", "annual probability – from history")), h("th", { class: "n" }, T("περίοδος επαναφοράς", "return period")))),
        h("tbody", {}, Object.entries(sr).map(([k, r]) => h("tr", {}, h("td", {}, (R.scenarios[k] || {})[S.lang === "el" ? "el" : "en"] || k), h("td", { class: "n" }, `${fmt(r.Ms, 1)} @ ${fmt(r.distance_km)}`), h("td", { class: "n" }, g3(r.pga_g)),
          h("td", { class: "n" }, fmt((r.assumed || 0) * 100, 2) + "%"), h("td", { class: "n" }, h("b", {}, fmt(r.annual_probability * 100, 3) + "%")), h("td", { class: "n" }, r.return_period_y ? fmt(r.return_period_y) + T(" έτη", " y") : "–"))))),
      h("label", { class: "chk", style: { marginTop: "8px" } }, h("input", { type: "checkbox", checked: !!use.seismic_rates, onchange: (e) => setUse({ seismic_rates: e.target.checked }) }),
        T("Χρήση των πιθανοτήτων από το ιστορικό στο 7D (αναμενόμενη ετήσια απώλεια, ασφάλιστρα, επιμερισμός)", "Use the probabilities from history in 7D (expected annual loss, insurance, allocation)")));
    if (hs) box.append(h("div", { class: "card", style: { background: "#fbfaf7", marginTop: "10px" } },
      h("b", {}, T("Αν ξανασυνέβαινε ο σεισμός με την ισχυρότερη επίδραση στη θέση", "If the earthquake with the strongest effect at the site happened again")),
      h("p", {}, `M ${fmt(hs.event.mag, 1)} · ${hs.event.time} · ${fmt(hs.event.dist_km)} km → PGA ${g3(hs.pga_g)} · MMI ${fmt(hs.mmi, 1)} · ${T("μέσος βαθμός βλάβης", "mean damage grade")} ${fmt(hs.mean_grade, 2)} · ${T("ζημιά", "loss")} ${eur(hs.loss_eur)} (${fmt((hs.loss_ratio || 0) * 100, 1)}% ${T("της αξίας αντικατάστασης", "of replacement value")}) · ${T("διακοπή χρήσης", "downtime")} ~${fmt(hs.downtime_days)} ${T("ημέρες", "days")}`)));
    if (R.historical_replay) box.append(replayCard(R.historical_replay));
    box.append(h("details", {}, h("summary", {}, T("Οι 15 σεισμοί με τη μεγαλύτερη επίδραση στη θέση", "The 15 earthquakes with the strongest effect at the site")),
      h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, T("Ημερομηνία", "Date")), h("th", { class: "n" }, "M"), h("th", { class: "n" }, T("απόσταση", "distance")), h("th", { class: "n" }, T("βάθος", "depth")), h("th", { class: "n" }, "PGA"), h("th", { class: "n" }, "MMI"), h("th", {}, T("Περιοχή", "Place")))),
        h("tbody", {}, s.top_site.map((e) => h("tr", {}, h("td", {}, e.url ? h("a", { href: e.url, target: "_blank" }, e.time) : e.time), h("td", { class: "n" }, fmt(e.mag, 1)), h("td", { class: "n" }, fmt(e.dist_km) + " km"), h("td", { class: "n" }, fmt(e.depth_km) + " km"), h("td", { class: "n" }, g3(e.pga_g)), h("td", { class: "n" }, fmt(e.mmi_site, 1)), h("td", { class: "small" }, e.place)))))),
      h("p", { class: "small mutedt" }, `${s.source} · ${T("λήψη", "fetched")} ${when(s.fetched)} · ${s.model}`));
    return box;
  }

  // what the recorded earthquakes would do to THIS building if they happened again today
  function replayCard(hr) {
    const G = S.lang === "el" ? hr.grades_el : hr.grades_en;
    const col = ["#7a7974", "#2a78d6", "#eda100", "#eb6834", "#e34948", "#a1181c"];
    const chip = (e) => { const k = Math.min(5, Math.round(e.mean_grade)); return h("span", { style: { display: "inline-block", padding: "1px 8px", borderRadius: "10px", border: `1px solid ${col[k]}`, color: "#2b2a27", fontSize: "12px", whiteSpace: "nowrap" } }, h("span", { style: { display: "inline-block", width: "8px", height: "8px", borderRadius: "4px", background: col[k], marginRight: "5px" } }), G[k]); };
    const table = (rows) => h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "#"), h("th", {}, T("Ημερομηνία", "Date")), h("th", { class: "n" }, "M"), h("th", { class: "n" }, T("απόσταση", "distance")), h("th", {}, T("Περιοχή", "Place")),
        h("th", { class: "n" }, T("PGA στο έργο", "PGA at site")), h("th", { class: "n" }, "MMI"), h("th", {}, T("Βλάβη κτιρίου", "Building damage")), h("th", { class: "n" }, T("πιθαν. D3+", "prob. D3+")), h("th", { class: "n" }, T("ζημιά", "loss")), h("th", { class: "n" }, T("διακοπή χρήσης", "downtime")))),
      h("tbody", {}, rows.map((e, i) => h("tr", {}, h("td", {}, String(i + 1)), h("td", {}, e.time), h("td", { class: "n" }, fmt(e.mag, 1)), h("td", { class: "n" }, fmt(e.dist_km) + " km"), h("td", { class: "small" }, e.place),
        h("td", { class: "n" }, g3(e.pga_g)), h("td", { class: "n" }, fmt(e.mmi, 1)), h("td", {}, chip(e)), h("td", { class: "n" }, fmt(e.p_d3plus * 100, 1) + "%"),
        h("td", { class: "n" }, `${eur(e.loss_eur)} (${fmt(e.loss_ratio * 100, 1)}%)`), h("td", { class: "n" }, `~${fmt(e.downtime_days)} ${T("ημ.", "d")}`)))));
    const L = hr.largest || [], Sx = hr.strongest || [];
    const dmin = Math.min(...L.map((e) => e.dist_km)), worst = Sx[0];
    const msg = T(`Οι 5 μεγαλύτεροι σεισμοί της περιοχής έγιναν όλοι μακριά από το έργο (από ${fmt(dmin)} km και πάνω), γι' αυτό ακόμη και με M ${fmt(L[0] && L[0].mag, 1)} το κτίριο θα είχε ελάχιστη ή καμία βλάβη. `
        + (worst ? `Πιο επικίνδυνος για το οικόπεδο είναι ένας μικρότερος αλλά κοντινός σεισμός: M ${fmt(worst.mag, 1)} το ${worst.time.slice(0, 4)} στα ${fmt(worst.dist_km)} km, που σήμερα θα προκαλούσε ζημιά περίπου ${eur(worst.loss_eur)} (${fmt(worst.loss_ratio * 100, 1)}% της αξίας)${worst.p_d4plus < 0.01 ? " χωρίς ουσιαστικό κίνδυνο κατάρρευσης" : `, με πιθανότητα πολύ βαριάς βλάβης ${fmt(worst.p_d4plus * 100, 1)}%`}. ` : "")
        + "Η απόσταση μετράει περισσότερο από τα Ρίχτερ.",
      `The 5 largest earthquakes of the area all happened far from the site (${fmt(dmin)} km or more), so even with M ${fmt(L[0] && L[0].mag, 1)} the building would have little or no damage. `
        + (worst ? `More dangerous for the site is a smaller but close event: M ${fmt(worst.mag, 1)} in ${worst.time.slice(0, 4)} at ${fmt(worst.dist_km)} km, which today would cause about ${eur(worst.loss_eur)} of damage (${fmt(worst.loss_ratio * 100, 1)}% of the value)${worst.p_d4plus < 0.01 ? " with no real risk of collapse" : `, with a ${fmt(worst.p_d4plus * 100, 1)}% chance of very heavy damage`}. ` : "")
        + "Distance matters more than magnitude.");
    return h("div", { class: "card", style: { marginTop: "10px" } },
      h("h3", { style: { marginTop: 0 } }, T("Αν ξαναγίνονταν σήμερα οι ιστορικοί σεισμοί", "If the historical earthquakes happened again today")),
      h("p", {}, msg),
      h("h4", {}, T("Οι 5 μεγαλύτεροι καταγεγραμμένοι σεισμοί (μέγεθος)", "The 5 largest recorded earthquakes (magnitude)")), table(L),
      h("h4", {}, T("Οι 5 σεισμοί με την ισχυρότερη επίδραση στο οικόπεδο", "The 5 earthquakes with the strongest effect at the site")), table(Sx),
      h("p", { class: "small mutedt" }, (S.lang === "el" ? hr.note_el : hr.note_en) + T(" D3+ = σημαντική βλάβη ή χειρότερη.", " D3+ = substantial damage or worse.")));
  }

  function quakeMap(s) {
    const W = 420, H = 320, R0 = s.radius_km, kx = Math.cos((s.lat * Math.PI) / 180) * 111.32;
    const sc = (Math.min(W, H) / 2 - 10) / R0;
    const xy = (la, lo) => [W / 2 + (lo - s.lon) * kx * sc, H / 2 - (la - s.lat) * 110.57 * sc];
    let body = "";
    for (const r of [50, 100, 150].filter((r) => r <= R0)) body += `<circle cx="${W / 2}" cy="${H / 2}" r="${r * sc}" fill="none" stroke="#d6d4cf" stroke-dasharray="4 4"/><text x="${W / 2 + r * sc - 4}" y="${H / 2 - 4}" font-size="10" fill="#8a8984" text-anchor="end">${r} km</text>`;
    const ev = s.events.filter((e) => e.mag >= 4.5).sort((a, b) => a.mag - b.mag);
    for (const e of ev) {
      const [x, y] = xy(e.lat, e.lon); const r = Math.max(1.5, (e.mag - 4) * 3.2);
      const c = e.mag >= 6 ? "#e34948" : e.mag >= 5 ? "#eb6834" : "#eda100";
      body += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}" fill="${c}" fill-opacity=".35" stroke="${c}" stroke-width=".8"><title>M ${e.mag} · ${e.time} · ${e.dist_km} km</title></circle>`;
    }
    body += `<path d="M${W / 2 - 7} ${H / 2} h14 M${W / 2} ${H / 2 - 7} v14" stroke="#2a78d6" stroke-width="3"/><text x="${W / 2 + 9}" y="${H / 2 + 14}" font-size="11" fill="#2a78d6" font-weight="700">${T("έργο", "site")}</text>`;
    body += `<text x="8" y="${H - 8}" font-size="10" fill="#52514e">● M4.5–5  ● M5–6  ● M≥6 · N ↑</text>`;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("width", "100%"); svg.style.maxWidth = W + "px"; svg.style.background = "#fbfaf7"; svg.style.borderRadius = "8px";
    svg.innerHTML = body;
    return svg;
  }

  // ---------------------------------------------------------------- climate
  function climateCard(c, err, use) {
    const box = h("div", { class: "card" }, h("div", { class: "row", style: { justifyContent: "space-between", marginBottom: "8px" } },
      h("h2", { style: { margin: 0 } }, T("Ιστορικό κλίματος της θέσης", "Climate history of the site")),
      h("button", { class: "btn small", onclick: (e) => refresh(["climate"], e.target) }, "⟳ " + T("Ανανέωση", "Refresh"))));
    if (err) box.append(h("div", { class: "warnbox" }, T("Τελευταία προσπάθεια: ", "Last attempt: ") + err));
    if (!c || !c.years) { box.append(h("p", { class: "mutedt" }, T("Δεν υπάρχουν ακόμα στοιχεία.", "No data yet."))); return box; }
    const m = c.mean, tr = c.trend_per_decade, sgn = (x, d) => (x >= 0 ? "+" : "") + fmt(x, d);
    box.append(h("div", { class: "grid g4" },
      kpi(fmt(m.t_mean, 1) + " °C", T("Μέση ετήσια θερμοκρασία", "Mean annual temperature"), `${sgn(tr.t_mean, 2)} °C ${T("ανά δεκαετία", "per decade")} · ${c.period[0]}–${c.period[1]}`),
      kpi(fmt(m.hdd), T("Βαθμοημέρες θέρμανσης (HDD)", "Heating degree days (HDD)"), `${sgn(tr.hdd, 0)} ${T("ανά δεκαετία", "per decade")}`),
      kpi(fmt(m.cdd), T("Βαθμοημέρες ψύξης (CDD)", "Cooling degree days (CDD)"), `${sgn(tr.cdd, 0)} ${T("ανά δεκαετία", "per decade")}`),
      kpi(fmt(m.hot_days_35, 1), T("Ημέρες καύσωνα (Tmax ≥ 35 °C) / έτος", "Heatwave days (Tmax ≥ 35 °C) / year"), `${T("τροπικές νύχτες", "tropical nights")} ${fmt(m.tropical_nights)} · ${T("μέγιστη", "max")} ${fmt(c.extremes.t_max.t_max, 1)} °C (${c.extremes.t_max.year})`)));
    box.append(h("div", { class: "grid g2" },
      h("div", {}, h("h3", {}, T("Μηνιαία θερμοκρασία: θέση έργου και τυπικό κλίμα της μελέτης", "Monthly temperature: site vs the study's design climate")), canvasBox("chClM")),
      h("div", {}, h("h3", {}, T("Βαθμοημέρες ανά έτος", "Degree days per year")), canvasBox("chClDD"))));
    box.append(h("div", { class: "grid g2" },
      h("div", {}, h("h3", {}, T("Μέση θερμοκρασία ανά έτος και τάση", "Mean temperature per year and trend")), canvasBox("chClT")),
      h("div", {}, h("h3", {}, T("Βροχή: ετήσια και μέγιστη ημερήσια", "Rain: annual and maximum daily")), canvasBox("chClR"))));
    const ec = R.energy_compare;
    box.append(h("h3", {}, T("Σύνδεση με το 6D (ενέργεια)", "Link to 6D (energy)")),
      ec ? h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, T("Κλίμα υπολογισμού", "Climate used")), h("th", { class: "n" }, T("Πρωτογενής ενέργεια", "Primary energy")), h("th", { class: "n" }, T("Θέρμανση", "Heating")), h("th", { class: "n" }, T("Ψύξη", "Cooling")), h("th", { class: "n" }, T("Κόστος ενέργειας/έτος", "Energy cost/year")), h("th", {}, T("Κλάση", "Class")))),
        h("tbody", {}, [["design", T("Τυπικό κλίμα ζώνης Β (μελέτη ΚΕΝΑΚ)", "Typical zone-B climate (KENAK study)")], ["site", T(`Κλίμα της θέσης ${c.period[0]}–${c.period[1]}`, `Site climate ${c.period[0]}–${c.period[1]}`)]].map(([k, lb]) => { const e = ec[k] || {}; return h("tr", {}, h("td", {}, lb), h("td", { class: "n" }, fmt(e.primary_kwh_m2, 1) + " kWh/m²"), h("td", { class: "n" }, fmt(e.heating_kwh_m2, 1)), h("td", { class: "n" }, fmt(e.cooling_kwh_m2, 1)), h("td", { class: "n" }, eur(e.energy_cost_eur_year)), h("td", {}, e.class || "–")); }))) : null,
      h("label", { class: "chk", style: { marginTop: "8px" } }, h("input", { type: "checkbox", checked: !!use.climate, onchange: (e) => setUse({ climate: e.target.checked }) }),
        T("Χρήση του κλίματος της θέσης στο 6D (και στο κόστος ενέργειας του 5D/7D)", "Use the site climate in 6D (and in the energy cost of 5D/7D)")),
      h("p", { class: "small mutedt" }, `${c.source} · ${T("υψόμετρο σημείου πλέγματος", "grid point elevation")} ${fmt(c.elevation_m)} m · ${T("λήψη", "fetched")} ${when(c.fetched)} · ${c.definitions}`));
    return box;
  }

  function drawCharts(lv) {
    const s = lv.seismic, c = lv.climate;
    if (s && s.n) {
      const col = (m) => (m >= 6 ? "#e34948" : m >= 5 ? "#eb6834" : "#eda100");
      chart("chQ", { type: "scatter", data: { datasets: [{ data: s.events.map((e) => ({ x: e.year, y: e.mag })), pointRadius: s.events.map((e) => Math.max(1.5, (e.mag - 3.8) * 2.2)), backgroundColor: s.events.map((e) => col(e.mag) + "88"), borderColor: s.events.map((e) => col(e.mag)), borderWidth: 0.6 }] },
        options: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => { const e = s.events[ctx.dataIndex]; return `M ${e.mag} · ${e.time} · ${e.dist_km} km`; } } } }, scales: { x: ax(T("έτος", "year"), { min: 1900, ticks: { callback: (v) => String(v) } }), y: ax(T("μέγεθος M", "magnitude M"), { min: 4 }) } } });
      const hz = s.gr && s.gr.hazard;
      if (hz) chart("chHz", { type: "line", data: { datasets: [
          { label: T("ετήσια συχνότητα υπέρβασης", "annual exceedance rate"), data: hz.pga_g.map((x, i) => ({ x, y: hz.annual_rate[i] })), borderColor: PAL[0], borderWidth: 2.4, pointRadius: 0, tension: 0.2 },
          { label: T("475 έτη (10 % σε 50 χρόνια)", "475 years (10 % in 50 years)"), data: [{ x: 0.01, y: 1 / 475 }, { x: 1, y: 1 / 475 }], borderColor: PAL[1], borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0 },
          { label: T("ΕΑΚ ζώνη ΙΙ: 0,24 g", "Greek code zone II: 0.24 g"), data: [{ x: 0.24, y: 1e-5 }, { x: 0.24, y: 1 }], borderColor: PAL[2], borderDash: [2, 3], borderWidth: 1.5, pointRadius: 0 }] },
        options: { parsing: false, scales: { x: ax("PGA (g)", { type: "logarithmic", min: 0.01, max: 1, ticks: { autoSkip: false, maxRotation: 0, callback: (v) => ([0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1].some((t) => Math.abs(t - v) < 1e-9) ? String(v).replace(".", S.lang === "el" ? "," : ".") : "") } }),
          y: ax(T("συχνότητα / έτος", "rate / year"), { type: "logarithmic", min: 1e-5, max: 1, ticks: { autoSkip: false, callback: (v) => { const e = Math.log10(v); return Math.abs(e - Math.round(e)) < 1e-9 ? "10" + String(Math.round(e)).replace("-", "⁻").replace(/\d/g, (d) => "⁰¹²³⁴⁵⁶⁷⁸⁹"[d]) : ""; } } }) } } });
    }
    if (c && c.years) {
      const ys = c.years.map((r) => r.year);
      chart("chClM", { type: "line", data: { labels: MON(), datasets: [
          { label: T("θέση έργου (μέση)", "site (mean)"), data: c.monthly.map((m) => m.t_mean), borderColor: PAL[1], borderWidth: 2.4, pointRadius: 2 },
          { label: T("θέση: μέση μέγιστη", "site: mean max"), data: c.monthly.map((m) => m.t_max_mean), borderColor: PAL[1], borderDash: [4, 4], borderWidth: 1.2, pointRadius: 0 },
          { label: T("θέση: μέση ελάχιστη", "site: mean min"), data: c.monthly.map((m) => m.t_min_mean), borderColor: PAL[0], borderDash: [4, 4], borderWidth: 1.2, pointRadius: 0 },
          { label: T("τυπικό κλίμα μελέτης", "design climate"), data: R.design_climate.T_ext, borderColor: "#8a8984", borderWidth: 2, pointRadius: 0 }] }, options: { scales: { y: ax("°C") } } });
      chart("chClDD", { type: "bar", data: { labels: ys, datasets: [{ label: "HDD", data: c.years.map((r) => r.hdd), backgroundColor: PAL[0], borderRadius: 2 }, { label: "CDD", data: c.years.map((r) => r.cdd), backgroundColor: PAL[1], borderRadius: 2 }] }, options: { scales: { y: ax(T("βαθμοημέρες", "degree days")) } } });
      const tr = c.trend_per_decade.t_mean / 10, my = ys.reduce((a, b) => a + b, 0) / ys.length, mt = c.mean.t_mean;
      chart("chClT", { type: "line", data: { labels: ys, datasets: [{ label: T("μέση θερμοκρασία έτους", "annual mean temperature"), data: c.years.map((r) => r.t_mean), borderColor: PAL[1], borderWidth: 2, pointRadius: 2 },
          { label: T(`τάση ${tr >= 0 ? "+" : ""}${fmt(tr * 10, 2)} °C/δεκαετία`, `trend ${tr >= 0 ? "+" : ""}${fmt(tr * 10, 2)} °C/decade`), data: ys.map((y) => mt + tr * (y - my)), borderColor: "#52514e", borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0 }] }, options: { scales: { y: ax("°C") } } });
      chart("chClR", { type: "bar", data: { labels: ys, datasets: [{ label: T("ετήσια βροχή (mm)", "annual rain (mm)"), data: c.years.map((r) => r.rain_mm), backgroundColor: PAL[0] + "aa", borderRadius: 2, yAxisID: "y" },
          { type: "line", label: T("μέγιστη ημερήσια (mm)", "max daily (mm)"), data: c.years.map((r) => r.rain_max_day_mm), borderColor: PAL[7], borderWidth: 2, pointRadius: 2, yAxisID: "y1" }] },
        options: { scales: { y: ax("mm/" + T("έτος", "year")), y1: ax("mm/" + T("ημέρα", "day"), { position: "right", grid: { display: false } }) } } });
    }
  }

  await load();
}
