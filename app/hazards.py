"""Hazard scenarios for the use & maintenance phases: earthquake (3 scenarios), fire (internal + wildfire), flood.

All models are SCREENING-LEVEL (pre-design, portfolio-style) estimates with transparent, editable parameters in
`data/hazards.json`. They indicate order of magnitude and relative benefit of mitigation measures. They are NOT a
structural assessment (ΚΑΝ.ΕΠΕ./EC8-3), a fire-safety study (ΠΥΣ) or a hydraulic study.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

DATA = Path(__file__).parent / "data"
STRUCT_KINDS = {"column", "beam", "slab", "footing", "stair", "roof"}
NONSTRUCT_KINDS = {"wall", "window", "door", "railing"}
EXTERIOR_KINDS = {"pergola", "fence", "vegetation"}


def load() -> dict[str, Any]:
    return json.loads((DATA / "hazards.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------
# asset values
# ------------------------------------------------------------------------------------------------
def storey_areas(project: dict[str, Any]) -> dict[str, float]:
    a = project.get("areas") or {}
    out = {}
    for s in project["storeys"]:
        k = s.get("key")
        if k == "basement":
            v = a.get("parking_m2", 0) + a.get("storage_m2", 0) + a.get("basement_flat_m2", 0)
        elif k:
            v = a.get(f"{k}_m2", 0)
        else:
            v = 0.0
        if not v:                                            # generic project: plan area of the slabs of the storey
            v = sum(e["qty"].get("plan_area_m2", 0.0) for e in project["elements"] if e["kind"] == "slab" and e.get("storey") == s["id"])
        out[s["id"]] = float(v) or 1.0
    return out


def asset_values(project: dict[str, Any], cost_res: dict[str, Any], hz: dict[str, Any]) -> dict[str, Any]:
    t = cost_res["by_trade"]
    gfa = float(project["meta"]["gfa_m2"])
    contents = hz["flood"]["contents_eur_per_m2"] * gfa
    areas = storey_areas(project)
    tot = sum(areas.values())
    return {"structure": t.get("structure", 0.0), "envelope": t.get("envelope", 0.0), "finishes": t.get("finishes", 0.0), "mep": t.get("mep", 0.0),
            "site": t.get("site", 0.0), "contents": contents, "gfa": gfa, "storey_area": areas, "storey_weight": {k: v / tot for k, v in areas.items()},
            "total_replacement": cost_res["net"] + contents}


def _interp(curve: list[list[float]], x: float) -> float:
    xs, ys = zip(*curve)
    return float(np.interp(x, xs, ys))


def annuity(rate_pct: float, years: int) -> float:
    r = rate_pct / 100
    return years if r == 0 else (1 - (1 + r) ** -years) / r


def expected_annual(points: list[tuple[float, float]]) -> float:
    """Expected annual loss from (annual probability, loss) pairs by trapezoid integration of the loss–exceedance curve."""
    pts = sorted(points, key=lambda p: -p[0])
    if not pts:
        return 0.0
    eal = 0.0
    for (p1, l1), (p2, l2) in zip(pts, pts[1:]):
        eal += (p1 - p2) * (l1 + l2) / 2
    eal += pts[-1][0] * pts[-1][1]
    return eal


# ------------------------------------------------------------------------------------------------
# SEISMIC
# ------------------------------------------------------------------------------------------------
def pga_ambraseys(Ms: float, d_km: float, site: str = "B", percentile: float = 50.0) -> float:
    """Ambraseys et al. (1996): log10 a[g] = -1.48 + 0.266 Ms - 0.922 log10 sqrt(d^2 + 3.5^2) + 0.117 SA + 0.124 SS ; sigma = 0.25."""
    sa = 1.0 if site in ("B",) else 0.0
    ss = 1.0 if site in ("C", "D", "E") else 0.0
    log_a = -1.48 + 0.266 * Ms - 0.922 * math.log10(math.sqrt(d_km ** 2 + 3.5 ** 2)) + 0.117 * sa + 0.124 * ss
    z = {50: 0.0, 84: 1.0, 16: -1.0, 90: 1.2816}.get(int(percentile), 0.0)
    return 10 ** (log_a + 0.25 * z)


def mmi_from_pga(pga_g: float) -> float:
    """Wald et al. (1999) PGA -> Modified Mercalli intensity, blended across V–VII."""
    pga = max(pga_g * 981.0, 1e-3)
    lg = math.log10(pga)
    low, high = 2.20 * lg + 1.00, 3.66 * lg - 1.66
    if low <= 5.0:
        return low
    if high >= 7.0:
        return high
    l5, l7 = (5.0 - 1.0) / 2.2, (7.0 + 1.66) / 3.66
    t = (lg - l5) / (l7 - l5)
    return 5.0 + 2.0 * min(max(t, 0.0), 1.0)


def mean_damage_grade(I: float, V: float, Q: float) -> float:
    """Lagomarsino & Giovinazzi (2006) macroseismic vulnerability-index model (mean grade 0..5)."""
    return 2.5 * (1.0 + math.tanh((I + 6.25 * V - 13.1) / Q))


def binom_dist(mu: float, n: int = 5) -> list[float]:
    p = min(max(mu / n, 0.0), 1.0)
    return [math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(n + 1)]


def _eak_phi(T: float, T1: float, T2: float, b0: float) -> float:
    if T <= T1:
        return 1.0 + (b0 - 1.0) * T / T1
    if T <= T2:
        return b0
    return b0 * (T2 / T) ** (2.0 / 3.0)


def _storey_factors(project: dict[str, Any], hz: dict[str, Any], pilotis: bool) -> dict[str, float]:
    sw = hz["seismic"]["storey_weight"]
    above = [s for s in sorted(project["storeys"], key=lambda s: s["elevation_m"]) if s["elevation_m"] >= -0.01]
    out = {}
    n = max(len(above) - 1, 1)
    for i, s in enumerate(above):
        f = sw["bottom_factor"] + (sw["top_factor"] - sw["bottom_factor"]) * i / n
        if i == 0 and pilotis:
            f *= sw["pilotis_factor"]
        out[s["id"]] = f
    for s in project["storeys"]:
        if s["id"] not in out:
            out[s["id"]] = 0.5                           # basement boxed in by retaining walls
    areas = storey_areas(project)
    tot = sum(areas.values())
    mean = sum(out[k] * areas[k] / tot for k in out)
    return {k: v / mean for k, v in out.items()}


def seismic(project: dict[str, Any], cost_res: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    hz = load()
    sz = hz["seismic"]
    st = project["meta"]["structure"]
    sc_key = params.get("scenario", "moderate")
    sc = dict(sz["scenarios"].get(sc_key, sz["scenarios"]["moderate"]))
    lv = project.get("live") or {}
    hist = ((lv.get("seismic") or {}).get("scenario_rates") or {}).get(sc_key)
    if hist and (lv.get("use") or {}).get("seismic_rates"):
        sc["annual_probability"] = hist["annual_probability"]          # from the hazard curve of the site's earthquake history
        sc["probability_source"] = "history"
    Ms = float(params.get("Ms", sc["Ms"]))
    d = float(params.get("distance_km", sc["distance_km"]))
    if "scenario" not in params and ("Ms" in params or "distance_km" in params):      # the user's own earthquake
        sc_key = "custom"
        sc["el"] = f"Σεισμός Ms {Ms:.1f} @ {d:.0f} km".replace(".", ",")
        sc["en"] = f"Earthquake Ms {Ms:.1f} @ {d:.0f} km"
    site = params.get("soil", st.get("soil", "B"))
    pct = float(params.get("percentile", 50))
    pga = float(params["pga_g"]) if params.get("pga_g") else pga_ambraseys(Ms, d, site, pct)
    I = mmi_from_pga(pga)
    code = params.get("code_level") or ("static" if project["meta"].get("structural") else (st.get("code_level_default") or "high"))
    if code == "static" and not project["meta"].get("structural") and not project.get("elements"):
        code = st.get("code_level_default") or "high"                   # nothing to derive a capacity from
    fr = sz["fragility"]
    cap = None
    if code == "static":
        # capacity of THIS building from its static study (or, without one, from the member sections): see structural.py
        from . import structural
        cap = structural.for_project(project, params)
        V = sz["code_level_vulnerability"]["high"]
        med = list(cap["median_pga_g"])
    else:
        V = sz["code_level_vulnerability"][code]
        med = list(fr["median_pga_g"][code])
    pilotis = bool(params.get("pilotis", False))
    irregular = bool(params.get("plan_irregularity", False))
    ns_factor = 1.0
    mit = [m for m in params.get("mitigations", []) if m in sz["mitigations"]]
    mfac = 1.0
    for m in mit:
        mm = sz["mitigations"][m]
        V += mm.get("dV", 0.0)
        mfac *= mm.get("median_factor", 1.0)
        if mm.get("removes_pilotis"):
            pilotis = False
        ns_factor *= mm.get("nonstructural_factor", 1.0)
    mf = mfac * (fr["median_factor"]["pilotis"] if pilotis else 1.0) * (fr["median_factor"]["plan_irregularity"] if irregular else 1.0)
    med = [x * mf for x in med]
    beta = float(params.get("beta", fr["beta"]))
    V_eff = V + (sz["modifiers"]["pilotis"] if pilotis else 0.0) + (sz["modifiers"]["plan_irregularity"] if irregular else 0.0)
    Q = float(params.get("Q", sz["Q"]))
    mu_lm1 = mean_damage_grade(I, V_eff, Q)

    def frag_dist(a_g: float) -> list[float]:
        """P(grade = k), k = 0..5, from lognormal exceedance curves."""
        ex = [1.0] + [0.5 * (1 + math.erf(math.log(max(a_g, 1e-6) / m) / (beta * math.sqrt(2)))) for m in med] + [0.0]
        return [max(0.0, ex[k] - ex[k + 1]) for k in range(6)]

    dist = frag_dist(pga)
    mu = sum(k * p for k, p in enumerate(dist))
    av = asset_values(project, cost_res, hz)
    dr = hz["damage_ratio"]
    fac = _storey_factors(project, hz, pilotis)
    storeys = []
    loss = 0.0
    worst_mu = 0.0
    parts = {"structure": 0.0, "nonstructural_drift": 0.0, "nonstructural_accel": 0.0}
    nsd_val, nsa_val = av["envelope"] + av["finishes"], av["mep"]
    storey_dist: dict[str, list[float]] = {}
    storey_mu: dict[str, float] = {}
    worst_dist = dist
    for s in sorted(project["storeys"], key=lambda s: s["elevation_m"]):
        ds = frag_dist(pga * fac[s["id"]])
        mu_s = sum(k * p for k, p in enumerate(ds))
        storey_dist[s["id"]] = ds
        storey_mu[s["id"]] = mu_s
        r_str = sum(p * x for p, x in zip(ds, dr["structural"]))
        r_nsd = sum(p * x for p, x in zip(ds, dr["nonstructural_drift"])) * ns_factor
        r_nsa = sum(p * x for p, x in zip(ds, dr["nonstructural_accel"])) * ns_factor
        w = av["storey_weight"][s["id"]]
        l_s = w * (av["structure"] * r_str + nsd_val * r_nsd + nsa_val * r_nsa)
        parts["structure"] += w * av["structure"] * r_str
        parts["nonstructural_drift"] += w * nsd_val * r_nsd
        parts["nonstructural_accel"] += w * nsa_val * r_nsa
        loss += l_s
        if mu_s >= worst_mu:
            worst_mu, worst_dist = mu_s, ds
        storeys.append({"id": s["id"], "name_el": s["name_el"], "name_en": s["name_en"], "mean_grade": round(mu_s, 2), "dist": [round(x, 3) for x in ds],
                        "r_structural": round(r_str, 4), "r_nonstruct": round(r_nsd, 4), "loss_eur": round(l_s), "p_d3plus": round(sum(ds[3:]), 3), "p_d4plus": round(sum(ds[4:]), 3)})
    downtime = sum(p * x for p, x in zip(worst_dist, hz["downtime_days"]))
    # spectra and demand/capacity indicator
    T1, T2, b0 = st["T1"], st["T2"], st["beta0"]
    ag, q = st["a_g"], st["q"]
    Ts = [round(0.02 + 0.05 * i, 3) for i in range(0, 61)]
    design_el = [ag * _eak_phi(T, T1, T2, b0) for T in Ts]
    design_q = [x / q for x in design_el]
    scen = [pga * _eak_phi(T, T1, T2, b0) for T in Ts]
    omega = float(params.get("overstrength", sz["overstrength"]))
    if cap and cap.get("overstrength_total"):
        omega = float(cap["overstrength_total"])
    elif cap:
        omega = max(cap["pga_g"]["collapse"] / max(ag, 1e-6) * q / 2.24, 1.0)
    markers = []
    for name in ("Tx", "Ty"):
        T = st[name]
        sa = pga * _eak_phi(T, T1, T2, b0)
        cy = omega * ag * _eak_phi(T, T1, T2, b0) / q
        Rr = sa / cy
        mu_req = 1.0 if Rr <= 1 else (Rr if T >= T2 else (Rr ** 2 + 1) / 2)
        markers.append({"name": name, "T": T, "Sa_scenario_g": round(sa, 3), "Sd_design_g": round(ag * _eak_phi(T, T1, T2, b0) / q, 3), "capacity_Cy_g": round(cy, 3),
                        "demand_to_capacity": round(Rr, 2), "ductility_demand": round(mu_req, 2)})
    # element damage for the 3D viewer
    el_dmg = {}
    for e in project["elements"]:
        k = e["kind"]
        ds = storey_dist.get(e.get("storey"), dist)
        if k in STRUCT_KINDS or (k == "wall" and e.get("props", {}).get("retaining")):
            el_dmg[e["id"]] = round(sum(p * x for p, x in zip(ds, dr["structural"])), 3)
        elif k in NONSTRUCT_KINDS:
            el_dmg[e["id"]] = round(sum(p * x for p, x in zip(ds, dr["nonstructural_drift"])) * ns_factor, 3)
        else:
            el_dmg[e["id"]] = 0.0
    return {"type": "seismic", "scenario": sc_key, "label_el": sc["el"], "label_en": sc["en"], "Ms": Ms, "distance_km": d, "soil": site, "percentile": pct,
            "pga_g": round(pga, 3), "pga_over_design": round(pga / ag, 2), "intensity_mmi": round(I, 1), "vulnerability_index": round(V_eff, 3), "lm1_mean_grade": round(mu_lm1, 2), "lm1_distribution": [round(x, 3) for x in binom_dist(mu_lm1)], "median_pga_g": [round(x, 3) for x in med], "beta": beta, "code_level": code, "capacity": cap, "richter_note": "Ms (κλίμακα επιφανειακών κυμάτων, «Ρίχτερ»)",
            "pilotis": pilotis, "irregular": irregular, "mean_grade": round(mu, 2), "distribution": [round(x, 3) for x in dist], "storeys": storeys, "loss_eur": round(loss),
            "loss_ratio": round(loss / av["total_replacement"], 4), "loss_parts": {k: round(v) for k, v in parts.items()}, "downtime_days": round(downtime), "p_d3plus": round(sum(dist[3:]), 3),
            "p_collapse_d5": round(dist[5], 4), "spectrum": {"T": Ts, "design_elastic": [round(x, 4) for x in design_el], "design_q": [round(x, 4) for x in design_q], "scenario": [round(x, 4) for x in scen]},
            "markers": markers, "element_damage": el_dmg, "mitigations": mit, "replacement_value": round(av["total_replacement"]), "annual_probability": sc["annual_probability"],
            "probability_source": sc.get("probability_source", "assumed"),
            "model": "Ambraseys et al. 1996 (PGA) → lognormal fragility curves by code level; cross-check: Wald et al. 1999 intensity + Lagomarsino–Giovinazzi LM1"}


def historical_replay(project: dict[str, Any], cost_res: dict[str, Any], sq: dict[str, Any] | None, n: int = 5) -> dict[str, Any] | None:
    """Replay recorded earthquakes on THIS building: what damage each would cause if it happened again today.
    Two lists from the site catalogue (USGS): the n largest by magnitude and the n with the strongest shaking at the site.
    Same chain as the 7D scenarios: Ambraseys et al. (1996) median PGA at the event's distance → fragility of the building."""
    ev = (sq or {}).get("events") or []
    if not ev:
        return None

    def d_eff(e: dict[str, Any]) -> float:
        dep = float(e.get("depth_km") or 0)
        return math.hypot(e["dist_km"], dep) if dep > 30.0 else float(e["dist_km"])

    def replay(e: dict[str, Any]) -> dict[str, Any]:
        r = seismic(project, cost_res, {"Ms": e["mag"], "distance_km": d_eff(e)})
        dist = r["distribution"]
        return {"time": e["time"], "mag": e["mag"], "dist_km": e["dist_km"], "depth_km": e.get("depth_km"), "place": e.get("place", ""),
                "lat": e.get("lat"), "lon": e.get("lon"), "pga_g": r["pga_g"], "pga_over_design": r["pga_over_design"], "mmi": r["intensity_mmi"],
                "mean_grade": r["mean_grade"], "grade": int(max(range(6), key=lambda k: dist[k])), "distribution": dist,
                "p_d3plus": r["p_d3plus"], "p_d4plus": round(sum(dist[4:]), 4), "loss_eur": r["loss_eur"], "loss_ratio": r["loss_ratio"],
                "downtime_days": r["downtime_days"]}

    largest = sorted(ev, key=lambda e: (-e["mag"], -(e.get("pga_g") or 0)))[:n]
    big = [e for e in ev if e["mag"] >= 5.0] or ev                       # small near-by shocks give short, harmless peaks
    strongest = sorted(big, key=lambda e: -(e.get("pga_g") or 0))[:n]
    return {"largest": [replay(e) for e in largest], "strongest": [replay(e) for e in strongest],
            "grades_el": ["Καμία βλάβη", "Αμελητέα (D1)", "Μέτρια (D2)", "Σημαντική (D3)", "Πολύ βαριά (D4)", "Κατάρρευση (D5)"],
            "grades_en": ["None", "Slight (D1)", "Moderate (D2)", "Substantial (D3)", "Very heavy (D4)", "Collapse (D5)"],
            "note_el": "Ο κάθε καταγεγραμμένος σεισμός «ξαναπαίζεται» σήμερα πάνω στο συγκεκριμένο κτίριο: διάμεση επιτάχυνση στη θέση (Ambraseys et al. 1996) για την πραγματική απόσταση του επικέντρου και καμπύλες τρωτότητας του κτιρίου από τη στατική μελέτη. Τα μεγέθη των παλαιών σεισμών (πριν το ~1960) έχουν μεγάλη αβεβαιότητα.",
            "note_en": "Each recorded earthquake is replayed today on this building: median site acceleration (Ambraseys et al. 1996) at the actual epicentral distance and the building's fragility curves from its static study. Magnitudes of old events (before ~1960) are highly uncertain."}


def seismic_all(project: dict[str, Any], cost_res: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    hz = load()
    runs = {}
    for k in hz["seismic"]["scenarios"]:
        p = dict(params)
        p["scenario"] = k
        runs[k] = seismic(project, cost_res, p)
    eal = expected_annual([(r["annual_probability"], r["loss_eur"]) for r in runs.values()])
    return {"runs": runs, "eal_eur": round(eal)}


# ------------------------------------------------------------------------------------------------
# FIRE – internal
# ------------------------------------------------------------------------------------------------
def _r_provided(project: dict[str, Any], storey: str, hz: dict[str, Any], axis_mm: float, R_req: float = 60.0) -> tuple[float, float, float]:
    """Fire rating (min) of the median column of the storey from simplified EN 1992-1-2 tabulated data, minimum dimension and
    share of columns meeting the required rating."""
    cols = [e for e in project["elements"] if e["kind"] == "column" and e.get("storey") == storey]
    dims = sorted(min(e["qty"].get("width_m", 0.3), e["qty"].get("depth_m", 0.3)) * 1000 for e in cols) or [300.0]

    def rating(dmin: float) -> float:
        best = 0.0
        for R, dim, a in hz["fire"]["internal"]["r_table_columns"]:
            if dmin >= dim and axis_mm >= a:
                best = max(best, float(R))
        return best

    med = dims[len(dims) // 2]
    ok = sum(1 for d in dims if rating(d) >= R_req) / len(dims)
    return rating(med), dims[0], ok


def _std_fire_curve(minutes: np.ndarray) -> np.ndarray:
    return 20 + 345 * np.log10(8 * minutes + 1)


def default_fire_storey(project: dict[str, Any], wanted: str | None = None) -> str:
    """Storey where an internal fire starts: the requested one if it exists, else the first storey above ground that has columns."""
    ids = [s["id"] for s in project["storeys"]]
    if wanted in ids:
        return wanted
    upper = [s for s in sorted(project["storeys"], key=lambda s: s["elevation_m"]) if s["elevation_m"] >= 0]
    with_cols = [s["id"] for s in upper if any(e["kind"] == "column" and e.get("storey") == s["id"] for e in project["elements"])]
    if with_cols:
        return with_cols[1] if len(with_cols) > 1 else with_cols[0]
    return (upper or project["storeys"])[0]["id"]


def fire_internal(project: dict[str, Any], cost_res: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    hz = load()
    fz = hz["fire"]["internal"]
    storey = default_fire_storey(project, params.get("storey"))
    sdef = next(s for s in project["storeys"] if s["id"] == storey)
    sarea = storey_areas(project).get(storey) or 100.0
    Af = float(params.get("compartment_area_m2", min(110.0, sarea)))
    h = fz["compartment_height_m"]
    av_ratio = float(params.get("opening_ratio", 0.18))
    Av = Af * av_ratio
    ratio = 1.5
    P = 2 * (math.sqrt(ratio * Af) + math.sqrt(Af / ratio))
    At = 2 * Af + P * h
    heq = 1.4
    O = min(0.20, max(0.02, Av * math.sqrt(heq) / At))
    qfk = float(params.get("q_fk", fz["q_fk_MJ_m2"]))
    sprinkler = bool(params.get("sprinkler", False))
    detector = bool(params.get("detector", False))
    spread_factor = 1.0
    for mname in params.get("mitigations", []):
        mm = fz["mitigations"].get(mname)
        if not mm:
            continue
        sprinkler = sprinkler or mm.get("sprinkler", False)
        detector = detector or mm.get("detector", False)
        spread_factor *= mm.get("spread_factor", 1.0)
    dq1 = float(np.interp(Af, [25, 250, 2500, 5000], [1.1, 1.5, 1.9, 2.0]))
    dn = (hz["fire"]["internal"]["sprinkler_delta_n"] if sprinkler else 1.0) * (fz["detector_delta_n"] if detector else 1.0)
    qfd = qfk * fz["m_combustion"] * dq1 * fz["delta_q2"] * dn
    qtd = qfd * Af / At
    b = float(params.get("b", fz["b_default"]))
    gamma = (O / b) ** 2 / (0.04 / 1160) ** 2
    t_lim = 25 / 60
    tmax_h = max(0.2e-3 * qtd / O, t_lim)
    tstar_max = tmax_h * gamma
    theta_max = 20 + 1325 * (1 - 0.324 * math.exp(-0.2 * tstar_max) - 0.204 * math.exp(-1.7 * tstar_max) - 0.472 * math.exp(-19 * tstar_max))
    # time-temperature curve (heating + cooling, EN 1991-1-2 Annex A)
    tt = np.arange(0, 241, 1.0)
    tstar = tt / 60 * gamma
    th = 20 + 1325 * (1 - 0.324 * np.exp(-0.2 * tstar) - 0.204 * np.exp(-1.7 * tstar) - 0.472 * np.exp(-19 * tstar))
    x = 1.0
    if tstar_max <= 0.5:
        slope = 625
    elif tstar_max < 2:
        slope = 250 * (3 - tstar_max)
    else:
        slope = 250
    tcool = tstar - tstar_max * x
    curve = np.where(tt / 60 <= tmax_h, th, np.maximum(20, theta_max - slope * tcool))
    # suppression
    resp = float(params.get("brigade_response_min", 12.0))
    t_flash = 10.0
    t_supp = (6.0 if sprinkler else resp - (4.0 if detector else 0.0) + 15.0)
    sp_eff = 0.9 if sprinkler else 0.0
    flash_prob = 1.0 - sp_eff
    full_min = max(0.0, t_supp - t_flash)
    frac_burn = min(1.0, full_min / max(tmax_h * 60, 1e-6))
    # equivalent standard-fire duration (EN 1991-1-2 Annex E)
    alpha_v = min(0.25, max(0.025, av_ratio))
    bv = max(10.0, 12.5 * (1 + 10 * alpha_v - alpha_v ** 2))
    wf = max(0.5, (6 / h) ** 0.3 * (0.62 + 90 * (0.4 - alpha_v) ** 4 / (1 + bv * 0.0)))
    kb = 0.07
    te = qfd * kb * wf
    te_eff = te * frac_burn
    axis = float(params.get("axis_mm", 48.0))
    R_req = float(params.get("required_R", fz["required_R_default_min"]))
    R_prov, dmin, share_ok = _r_provided(project, storey, hz, axis, R_req)
    R_eff = max(R_prov, 15.0)
    rho = te_eff / R_eff
    thr = [0.4, 0.7, 1.0, 1.3, 1.7]
    grade_fd = sum(rho >= t for t in thr)             # structural grade if flashover occurs
    dr = hz["damage_ratio"]
    av_val = asset_values(project, cost_res, hz)
    g = av_val["gfa"]
    fin_m2 = (av_val["envelope"] * 0.0 + av_val["finishes"]) / g
    mep_m2 = av_val["mep"] / g
    str_m2 = av_val["structure"] / g
    cont_m2 = hz["flood"]["contents_eur_per_m2"]
    od = fz["damage_origin_compartment"]
    loc = 0.15        # damage fraction of the origin compartment when the fire is suppressed before flashover
    comp_full = Af * (fin_m2 * od["finishes"] + mep_m2 * od["mep"] + cont_m2 * od["contents"] + str_m2 * dr["structural"][grade_fd] * 1.5)
    comp_local = Af * (fin_m2 + mep_m2 + cont_m2) * loc
    loss_origin = flash_prob * comp_full + (1 - flash_prob) * comp_local
    pv, ph = fz["spread_probability_vertical"] * spread_factor, fz["spread_probability_horizontal"] * spread_factor
    pv, ph = pv * flash_prob, ph * flash_prob
    loss_spread = pv * comp_full * 0.6 + ph * comp_full * 0.6        # neighbouring compartments: smoke/heat/water damage, no full flashover assumed
    water_smoke = (1 - pv) * (1 - ph) * 0.0
    total = loss_origin + loss_spread + water_smoke
    downtime = round(15 + 120 * min(1.0, (grade_fd / 3.0)) * flash_prob + 20 * (1 - flash_prob))
    el_dmg = {}
    share = min(1.0, Af / sarea)
    for e in project["elements"]:
        k = e["kind"]
        if e.get("storey") == storey:
            if k in STRUCT_KINDS:
                el_dmg[e["id"]] = round(dr["structural"][grade_fd] * flash_prob * share, 3)
            elif k in NONSTRUCT_KINDS:
                el_dmg[e["id"]] = round(share * (flash_prob * 1.0 + (1 - flash_prob) * loc), 3)
            else:
                el_dmg[e["id"]] = 0.0
        else:
            el_dmg[e["id"]] = 0.0
    return {"type": "fire_internal", "storey": storey, "storey_name_el": sdef["name_el"], "storey_name_en": sdef["name_en"], "compartment_area_m2": round(Af, 1),
            "opening_factor": round(O, 3), "q_fd_MJ_m2": round(qfd, 0), "q_td_MJ_m2": round(qtd, 0), "gamma": round(gamma, 2), "t_max_min": round(tmax_h * 60, 1),
            "theta_max_C": round(theta_max), "t_e_min": round(te, 1), "t_e_effective_min": round(te_eff, 1), "R_provided_min": R_prov, "R_required_min": R_req, "min_column_dim_mm": round(dmin), "columns_meeting_R_share": round(share_ok, 2),
            "meets_required_R": bool(R_prov >= R_req), "rho": round(rho, 2), "structural_grade_if_flashover": int(grade_fd), "sprinkler": sprinkler, "detector": detector,
            "flashover_probability": round(flash_prob, 2), "suppression_min": t_supp, "curve": {"t_min": [int(x) for x in tt[::2]], "gas_C": [round(float(x)) for x in curve[::2]],
            "standard_C": [round(float(x)) for x in _std_fire_curve(np.maximum(tt[::2], 0.0))]}, "spread": {"vertical": round(pv, 3), "horizontal": round(ph, 3)},
            "loss_eur": round(total), "loss_origin_eur": round(loss_origin), "loss_spread_eur": round(loss_spread), "loss_ratio": round(total / av_val["total_replacement"], 4),
            "downtime_days": downtime, "element_damage": el_dmg, "mitigations": params.get("mitigations", []),
            "annual_probability": fz["ignition_annual_probability_per_dwelling"], "model": "EN 1991-1-2 parametric fire (Annex A) + equivalent standard-fire duration (Annex E)"}


# ------------------------------------------------------------------------------------------------
# FIRE – wildfire
# ------------------------------------------------------------------------------------------------
def _view_corner(X: float, Y: float) -> float:
    s1, s2 = math.sqrt(1 + X * X), math.sqrt(1 + Y * Y)
    return (1 / (2 * math.pi)) * (X / s1 * math.atan(Y / s1) + Y / s2 * math.atan(X / s2))


def bal_index(q: float, thr: list[float]) -> int:
    return sum(q >= t for t in thr)


_DIRS = {"N": (0, 1), "NE": (0.7071, 0.7071), "E": (1, 0), "SE": (0.7071, -0.7071), "S": (0, -1), "SW": (-0.7071, -0.7071), "W": (-1, 0), "NW": (-0.7071, 0.7071)}


def wildfire(project: dict[str, Any], cost_res: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    hz = load()
    wz = hz["fire"]["wildfire"]
    cls = params.get("intensity_class", "high")
    I = float(params.get("intensity_kW_m", wz["intensity_classes"].get(cls, 10000)))
    d = float(params.get("distance_m", 12.0))
    slope = float(params.get("slope_deg", 10.0))
    wind = float(params.get("wind_kmh", 35.0))
    direction = params.get("direction", "N")
    env_f = ember_f = 1.0
    mit = [m for m in params.get("mitigations", []) if m in wz["mitigations"]]
    for m in mit:
        mm = wz["mitigations"][m]
        d += mm.get("distance_add_m", 0.0)
        env_f *= mm.get("envelope_factor", 1.0)
        ember_f *= mm.get("ember_factor", 1.0)
    L = 0.0775 * I ** 0.46                                   # Byram flame length (m), I in kW/m
    U = wind / 3.6
    tilt = min(math.radians(70), math.atan(U / math.sqrt(wz["gravity"] * L)))
    slope_f = max(0.6, 1 - 0.012 * slope)
    d_eff = max(1.0, d * slope_f - L * math.sin(tilt))
    W = wz["front_width_m"]
    F = min(1.0, 2 * _view_corner(W / 2 / d_eff, L / d_eff))
    q = F * wz["flame_emissive_power_kW_m2"]
    thr = wz["bal_thresholds_kW_m2"]
    bi = bal_index(q, thr)
    rd = wz["radiant_damage"]
    av = asset_values(project, cost_res, hz)
    ext_val = av["site"] * 0.5 + sum(l["total"] for l in cost_res["lines"] if l["key"] in ("pergolas", "railings"))
    ext_val *= cost_res["net"] / cost_res["direct"] if cost_res["direct"] else 1.0
    env_loss = av["envelope"] * rd["envelope"][bi] * env_f
    ext_loss = ext_val * rd["exterior_items"][bi]
    int_loss = (av["finishes"] + av["mep"]) * rd["interior"][bi]
    str_loss = av["structure"] * rd["structure"][bi]
    # embers
    d0 = wz["ember_d0_m"] + wz["ember_d0_per_kmh_m"] * wind
    p_ember = min(1.0, math.exp(-d / d0)) * wz["ember_ignition_given_attack"] * ember_f
    p_ember *= float(params.get("ember_exposure", 1.0))
    ember_loss = p_ember * wz["ember_loss_given_ignition"] * (av["envelope"] + av["finishes"] + av["mep"] + av["contents"])
    total = env_loss + ext_loss + int_loss + str_loss + ember_loss
    # element damage (face exposed to the fire gets full ratio)
    dx, dy = _DIRS.get(direction, (0, 1))
    boxes = [e["bbox"] for e in project["elements"] if e["kind"] not in ("site",)]
    proj_vals = []
    for b in boxes:
        proj_vals.append(((b[0] + b[3]) / 2) * dx + ((b[1] + b[4]) / 2) * dy)
    pmin, pmax = (min(proj_vals), max(proj_vals)) if proj_vals else (0.0, 1.0)      # projects without a 3D model (new-build estimate) have no elements
    el_dmg = {}
    for e in project["elements"]:
        b = e["bbox"]
        pv_ = ((b[0] + b[3]) / 2) * dx + ((b[1] + b[4]) / 2) * dy
        t = (pv_ - pmin) / max(pmax - pmin, 1e-6)
        face = 0.25 + 0.75 * t
        k = e["kind"]
        if k in EXTERIOR_KINDS or k == "railing":
            r = rd["exterior_items"][bi] * face
        elif k in ("window", "door", "wall") and not e.get("props", {}).get("retaining"):
            r = rd["envelope"][bi] * env_f * face
        elif k in STRUCT_KINDS:
            r = rd["structure"][bi] * face
        else:
            r = 0.0
        el_dmg[e["id"]] = round(min(1.0, r + 0.5 * p_ember * wz["ember_loss_given_ignition"] * (1 if k in ("window", "door", "pergola", "railing") else 0.3)), 3) if k != "site" else 0.0
    materials = [{"id": m["id"], "el": m["el"], "en": m["en"], "threshold_kW_m2": m["q"], "exceeded": bool(q >= m["q"])} for m in wz["material_thresholds_kW_m2"]]
    # sensitivity of flux with distance (chart)
    dist_curve = []
    for dd in range(5, 81, 5):
        de = max(1.0, dd * slope_f - L * math.sin(tilt))
        dist_curve.append({"d": dd, "q": round(min(1.0, 2 * _view_corner(W / 2 / de, L / de)) * wz["flame_emissive_power_kW_m2"], 1)})
    return {"type": "wildfire", "intensity_kW_m": I, "intensity_class": cls, "flame_length_m": round(L, 1), "tilt_deg": round(math.degrees(tilt), 1), "distance_m": round(d, 1), "effective_distance_m": round(d_eff, 1),
            "view_factor": round(F, 3), "flux_kW_m2": round(q, 1), "bal": wz["bal_names"][bi], "bal_index": bi, "materials": materials, "ember_probability": round(p_ember, 3),
            "loss_eur": round(total), "loss_parts": {"envelope": round(env_loss), "exterior": round(ext_loss), "interior": round(int_loss), "structure": round(str_loss), "embers": round(ember_loss)},
            "loss_ratio": round(total / av["total_replacement"], 4), "downtime_days": round(10 + 300 * min(1, total / max(av["total_replacement"], 1) * 3)), "distance_curve": dist_curve,
            "element_damage": el_dmg, "direction": direction, "mitigations": mit, "annual_probability": wz["annual_probability"], "replacement_value": round(av["total_replacement"]),
            "model": "Byram flame length + solid-flame view factor (Stefan–Boltzmann, 76 kW/m²) + BAL classes (AS 3959) + ember exposure"}


# ------------------------------------------------------------------------------------------------
# FLOOD
# ------------------------------------------------------------------------------------------------
def flood(project: dict[str, Any], cost_res: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    hz = load()
    fz = hz["flood"]
    sc_key = params.get("scenario", "moderate")
    sc = fz["scenarios"].get(sc_key, fz["scenarios"]["moderate"])
    depth = float(params.get("depth_m", sc["depth_m"]))
    vel = float(params.get("velocity_ms", sc["velocity_ms"]))
    mit = [m for m in params.get("mitigations", []) if m in fz["mitigations"]]
    d_eff = depth
    bf = mf = 1.0
    for m in mit:
        mm = fz["mitigations"][m]
        d_eff = max(0.0, d_eff - mm.get("depth_reduction_m", 0.0))
        bf *= mm.get("basement_factor", 1.0)
        mf *= mm.get("mep_factor", 1.0)
    av = asset_values(project, cost_res, hz)
    nsd_val, nsa_val = av["envelope"] * 0.5 + av["finishes"], av["mep"]
    cont = av["contents"]
    loss = 0.0
    storeys = []
    sh: dict[str, float] = {}
    for s in sorted(project["storeys"], key=lambda s: s["elevation_m"]):
        z0, hgt = s["elevation_m"], s["height_m"]
        if z0 < 0:
            ramp = min(1.0, max(0.0, (d_eff - fz["basement_entry_threshold_m"]) / 0.5)) if d_eff > fz["basement_entry_threshold_m"] else 0.0
            h = hgt * ramp
            fac = 0.6 * bf                                      # basement: car park & storage, lower finish value per m2
        else:
            h = min(max(d_eff - z0, 0.0), hgt)
            fac = 1.0
        sh[s["id"]] = h
        r = min(1.0, _interp(fz["depth_damage"], h) * fz["contamination_factor"]) if h > 0 else 0.0
        w = av["storey_weight"][s["id"]]
        l_s = w * fac * (nsd_val * r + nsa_val * r * mf + cont * r)
        loss += l_s
        storeys.append({"id": s["id"], "name_el": s["name_el"], "name_en": s["name_en"], "water_depth_m": round(h, 2), "damage_ratio": round(r * fac, 3), "loss_eur": round(l_s)})
    struct_loss = 0.0
    if vel >= fz["velocity_structural_threshold_ms"]:
        struct_loss = av["structure"] * 0.02 * min(2.0, vel / fz["velocity_structural_threshold_ms"]) * (1 if d_eff > 0.2 else 0.0)
    total = loss + struct_loss
    max_h = max(sh.values()) if sh else 0.0
    downtime = round(max(0.0, fz["downtime_days_per_m_depth"] * max_h + (7 if total > 0 else 0)))
    el_dmg = {}
    ratio_by_storey = {s["id"]: s["damage_ratio"] for s in storeys}
    for e in project["elements"]:
        k = e["kind"]
        r = ratio_by_storey.get(e.get("storey"), 0.0)
        if k in NONSTRUCT_KINDS and not e.get("props", {}).get("retaining"):
            el_dmg[e["id"]] = round(r, 3)
        elif k in STRUCT_KINDS:
            el_dmg[e["id"]] = round(0.02 if (struct_loss > 0 and r > 0) else 0.0, 3)
        else:
            el_dmg[e["id"]] = 0.0
    curve = [{"depth": x[0], "ratio": x[1]} for x in fz["depth_damage"]]
    return {"type": "flood", "scenario": sc_key, "label_el": sc["el"], "label_en": sc["en"], "depth_m": depth, "effective_depth_m": round(d_eff, 2), "velocity_ms": vel, "storeys": storeys,
            "loss_eur": round(total), "loss_structural_eur": round(struct_loss), "loss_ratio": round(total / av["total_replacement"], 4), "downtime_days": downtime,
            "basement_flooded_m": round(max((sh[x["id"]] for x in project["storeys"] if x["elevation_m"] < 0), default=0.0), 2), "curve": curve, "element_damage": el_dmg, "mitigations": mit,
            "annual_probability": sc["annual_probability"], "replacement_value": round(av["total_replacement"]),
            "model": "Depth–damage curve (JRC-type residential, Europe) per storey + basement flooding ramp + velocity check"}


def flood_all(project: dict[str, Any], cost_res: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
    hz = load()
    runs = {}
    for k in hz["flood"]["scenarios"]:
        p = dict(params or {})
        p["scenario"] = k
        p.pop("depth_m", None)
        runs[k] = flood(project, cost_res, p)
    return {"runs": runs, "eal_eur": round(expected_annual([(r["annual_probability"], r["loss_eur"]) for r in runs.values()]))}


# ------------------------------------------------------------------------------------------------
# dispatcher + mitigation cost–benefit
# ------------------------------------------------------------------------------------------------
def run(project: dict[str, Any], cost_res: dict[str, Any], kind: str, params: dict[str, Any]) -> dict[str, Any]:
    if kind == "seismic":
        return seismic(project, cost_res, params)
    if kind == "fire_internal":
        return fire_internal(project, cost_res, params)
    if kind == "wildfire":
        return wildfire(project, cost_res, params)
    if kind == "flood":
        return flood(project, cost_res, params)
    raise ValueError(f"unknown hazard kind {kind}")


def mitigation_catalog(project: dict[str, Any]) -> dict[str, Any]:
    hz = load()
    gfa = float(project["meta"]["gfa_m2"])
    out: dict[str, Any] = {}
    for kind, sect in (("seismic", hz["seismic"]["mitigations"]), ("fire_internal", hz["fire"]["internal"]["mitigations"]),
                       ("wildfire", hz["fire"]["wildfire"]["mitigations"]), ("flood", hz["flood"]["mitigations"])):
        out[kind] = {k: {"el": v["el"], "en": v["en"]} for k, v in sect.items()}
    return out


def mitigation_cost(project: dict[str, Any], quantities: dict[str, float], kind: str, mid: str) -> float:
    hz = load()
    sect = {"seismic": hz["seismic"]["mitigations"], "fire_internal": hz["fire"]["internal"]["mitigations"], "wildfire": hz["fire"]["wildfire"]["mitigations"], "flood": hz["flood"]["mitigations"]}[kind]
    m = sect[mid]
    gfa = float(project["meta"]["gfa_m2"])
    c = m.get("cost_fixed", 0.0) + m.get("cost_per_m2_gfa", 0.0) * gfa + m.get("cost_per_m2_window", 0.0) * quantities.get("window_area_m2", 0.0)
    c += m.get("cost_per_m2_facade", 0.0) * quantities.get("insulation_wall_m2", 0.0)
    return c


def _eal(project, cost_res, kind: str, mits: list[str], base_params: dict[str, Any]) -> float:
    p = dict(base_params)
    p["mitigations"] = mits
    if kind == "seismic":
        return seismic_all(project, cost_res, p)["eal_eur"]
    if kind == "flood":
        return flood_all(project, cost_res, p)["eal_eur"]
    r = run(project, cost_res, kind, p)
    return r["loss_eur"] * r["annual_probability"]


def risk_summary(project: dict[str, Any], cost_res: dict[str, Any], quantities: dict[str, float], base_params: dict[str, dict[str, Any]] | None = None,
                 horizon: int = 50, rate_pct: float = 3.0, exposure: dict[str, float] | None = None) -> dict[str, Any]:
    """Expected annual loss per hazard and cost–benefit ranking of mitigation measures (benefit = reduction of EAL over the horizon)."""
    base_params = base_params or {}
    hz = load()
    exp = dict(hz["site_exposure_default"])
    exp.update(exposure or {})
    out: dict[str, Any] = {"hazards": {}, "mitigations": [], "exposure": {k: v for k, v in exp.items() if not k.startswith("_")}}
    ann = annuity(rate_pct, horizon)
    for kind in ("seismic", "fire_internal", "wildfire", "flood"):
        bp = base_params.get(kind, {})
        xf = float(exp.get(kind, 1.0))
        e0 = _eal(project, cost_res, kind, bp.get("mitigations", []), bp) * xf
        out["hazards"][kind] = round(e0)
        sect = {"seismic": hz["seismic"]["mitigations"], "fire_internal": hz["fire"]["internal"]["mitigations"], "wildfire": hz["fire"]["wildfire"]["mitigations"], "flood": hz["flood"]["mitigations"]}[kind]
        for mid, m in sect.items():
            e1 = _eal(project, cost_res, kind, list(set(bp.get("mitigations", []) + [mid])), bp) * xf
            cost = mitigation_cost(project, quantities, kind, mid)
            ben = (e0 - e1) * ann
            out["mitigations"].append({"hazard": kind, "id": mid, "el": m["el"], "en": m["en"], "cost_eur": round(cost), "eal_reduction_eur_year": round(e0 - e1),
                                       "benefit_eur": round(ben), "bcr": round(ben / cost, 2) if cost > 0 else None})
    out["total_eal_eur"] = sum(out["hazards"].values())
    out["mitigations"].sort(key=lambda r: -(r["bcr"] or 0))
    return out


def defaults(project: dict[str, Any]) -> dict[str, Any]:
    hz = load()
    return {"seismic": {"scenarios": hz["seismic"]["scenarios"], "code_levels": hz["seismic"]["code_level_labels"], "code_levels_en": hz["seismic"].get("code_level_labels_en", hz["seismic"]["code_level_labels"])},
            "fire": {"intensity_classes": hz["fire"]["wildfire"]["intensity_classes"], "bal_names": hz["fire"]["wildfire"]["bal_names"], "R_default": hz["fire"]["internal"]["required_R_default_min"]},
            "flood": {"scenarios": hz["flood"]["scenarios"]}, "mitigations": mitigation_catalog(project), "damage_grades": hz["damage_grades"]}
