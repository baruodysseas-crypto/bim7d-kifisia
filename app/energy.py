"""6D energy engine: monthly quasi-steady heat balance + upgrade measures + energy class (KENAK-style).

How results are anchored
------------------------
The monthly balance (ISO 13790 utilisation-factor method, simplified) is used to compute *relative* changes
caused by measures. The absolute level is anchored to the project's certified baseline (e.g. the KENAK study):

    E_use,new = E_use,cert * (Q_new / Q_base) * (plant_factor_new / plant_factor_base)

so the baseline reproduces the certificate exactly and measures move it proportionally.
This is a design-stage *indicative* tool, not an official energy certificate (those require ΤΕΕ-ΚΕΝΑΚ)."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

DATA = Path(__file__).parent / "data"
DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
HOURS = [d * 24 for d in DAYS]

# Athens (ΚΕΝΑΚ study table 5.3): monthly horizontal and 45-degree irradiation, kWh/m2 per month
G_H = [63.3, 77.7, 118.9, 152.7, 190.4, 207.4, 214.5, 198.6, 156.0, 111.1, 68.1, 54.4]
G_45 = [90.7, 94.5, 127.4, 145.2, 168.9, 177.8, 186.8, 186.0, 162.4, 131.7, 94.7, 81.7]
# typical monthly mean outdoor temperature, Athens area (zone B) - editable in project["energy"]["climate"]
T_EXT = [9.9, 10.5, 12.4, 16.3, 21.2, 25.9, 28.4, 28.2, 24.2, 19.3, 14.8, 11.3]
K_VERT = [0.80, 0.75, 0.65, 0.55, 0.50, 0.45, 0.47, 0.52, 0.60, 0.70, 0.80, 0.85]   # vertical-average / horizontal irradiance

CLIMATE = {"T_ext": T_EXT, "G_h": G_H, "G_45": G_45, "k_vert": K_VERT}


def load_measures() -> dict[str, Any]:
    return json.loads((DATA / "measures.json").read_text(encoding="utf-8"))


def default_baseline(project: dict[str, Any]) -> dict[str, Any]:
    """Baseline energy model: envelope from the KENAK study (table 4.6) + certified results. Used by the demo
    and as a starting point for any project (user edits the numbers in the UI)."""
    meta = project["meta"]
    af = float(meta.get("conditioned_area_m2") or 600.0)
    return {
        "climate": copy.deepcopy(CLIMATE),
        "area_m2": af, "volume_m3": round(af * 2.9, 1),
        "envelope": {
            "walls": {"A": 886.2, "U": 0.243, "alpha": 0.40},          # vertical opaque, incl. beams/columns (b-factor included)
            "roof": {"A": 487.7, "U": 0.299, "alpha": 0.60},           # horizontal opaque elements
            "windows": {"A": 192.2, "U": 1.527, "g": 0.55, "frame_frac": 0.25, "fsh_summer": 0.70, "fsh_winter": 0.80},
            "thermal_bridges_WK": 191.4,
        },
        "ventilation": {"ach": 0.6, "recovery": 0.0, "fan_kwh_m2": 0.0},
        "internal_gains_W_m2": 4.0, "setpoint_heating": 20.0, "setpoint_cooling": 26.0, "thermal_mass_kJ_m2K": 260.0,
        "plant": {"heating": {"fuel": "natural_gas", "efficiency": 0.92}, "cooling": {"fuel": "electricity", "efficiency": 4.5},
                  "dhw": {"fuel": "natural_gas", "efficiency": 0.92, "solar_fraction": 0.90}},
        "certificate": {"class": "A+", "primary_kwh_m2": 26.2, "reference_kwh_m2": 91.5, "Um": 0.540, "Um_max": 0.827, "climate_zone": "B",
                        "by_use": {"heating": 8.7, "cooling": 15.3, "dhw": 2.2, "lighting": 0.0},
                        "reference_by_use": {"heating": 38.1, "cooling": 33.0, "dhw": 20.4, "lighting": 0.0},
                        "final_kwh_m2": {"electricity": 5.3, "natural_gas": 11.0, "solar": 18.9}},
        "common_electricity_kwh_m2": 6.0, "household_electricity_kwh_apt": 2200.0,
    }


_CAL: dict[str, float] = {}


def _calibration() -> dict[str, float]:
    """Usage/standard-profile factors (KENAK vs raw monthly model) derived once from the certified Kifisia building."""
    if not _CAL:
        base = default_baseline({"meta": {"conditioned_area_m2": 618.51}})
        b = monthly_balance(base)
        c = base["certificate"]["by_use"]
        pf_g, pf_e = 1.1, 2.9
        need_h = c["heating"] * base["plant"]["heating"]["efficiency"] / pf_g
        need_c = c["cooling"] * base["plant"]["cooling"]["efficiency"] / pf_e
        _CAL["heating"] = need_h / b["heating_kwh_m2"]
        _CAL["cooling"] = need_c / b["cooling_kwh_m2"]
    return _CAL


def _primary_generic(state: dict[str, Any]) -> dict[str, float]:
    meas = load_measures()
    cal = _calibration()
    b = monthly_balance(state)
    pl = state["plant"]
    h = cal["heating"] * b["heating_kwh_m2"] / pl["heating"]["efficiency"] * _pf(meas, pl["heating"]["fuel"])
    c = cal["cooling"] * b["cooling_kwh_m2"] / pl["cooling"]["efficiency"] * _pf(meas, pl["cooling"]["fuel"])
    d = 18.4 * (1 - pl["dhw"]["solar_fraction"]) / pl["dhw"]["efficiency"] * _pf(meas, pl["dhw"]["fuel"])
    return {"heating": h, "cooling": c, "dhw": d, "lighting": 0.0}


def generic_baseline(project: dict[str, Any], q: dict[str, float] | None) -> dict[str, Any]:
    """Baseline for projects without a certificate: envelope from the model quantities, code-level U-values (editable),
    certificate-equivalent results from the calibrated monthly model, reference building with Umax."""
    q = q or {}
    af = float(project["meta"].get("conditioned_area_m2") or 0.6 * project["meta"].get("gfa_m2", 500.0))
    gross = float(q.get("masonry_external_m2", 0.0)) or 1.2 * af
    win = float(q.get("window_area_m2", 0.0)) or 0.2 * gross
    st = default_baseline({"meta": {"conditioned_area_m2": af}})
    st["envelope"]["walls"] = {"A": round(gross, 1), "U": 0.40, "alpha": 0.40}
    st["envelope"]["roof"] = {"A": round(float(q.get("roof_area_m2", 0.0)) or af / 3, 1), "U": 0.35, "alpha": 0.60}
    st["envelope"]["windows"].update(A=round(win, 1), U=2.0, g=0.55)
    ua = 0.40 * gross + 0.35 * st["envelope"]["roof"]["A"] + 2.0 * win
    st["envelope"]["thermal_bridges_WK"] = round(0.12 * ua, 1)
    st["plant"]["dhw"]["solar_fraction"] = 0.0
    prim = _primary_generic(st)
    ref = copy.deepcopy(st)
    ref["envelope"]["walls"].update(U=0.45)
    ref["envelope"]["roof"].update(U=0.40)
    ref["envelope"]["windows"].update(U=2.60, g=0.55)
    ref["plant"]["heating"] = {"fuel": "natural_gas", "efficiency": 0.90}
    ref["plant"]["cooling"] = {"fuel": "electricity", "efficiency": 3.2}
    ref["plant"]["dhw"] = {"fuel": "natural_gas", "efficiency": 0.90, "solar_fraction": 0.0}
    rp = _primary_generic(ref)
    tot = sum(prim.values())
    rtot = 91.5          # KENAK reference building, climate zone B, residential (certified Kifisia study) - editable in the baseline
    st["certificate"] = {"class": class_of(tot / rtot), "primary_kwh_m2": round(tot, 1), "reference_kwh_m2": rtot, "by_use": {k: round(v, 2) for k, v in prim.items()},
                         "reference_by_use": {k: round(v, 2) for k, v in rp.items()}, "generic": True}
    return st


def baseline_for(project: dict[str, Any], q: dict[str, float] | None = None) -> dict[str, Any]:
    if project.get("energy_baseline"):
        return copy.deepcopy(project["energy_baseline"])
    if project["meta"].get("synthetic_geometry") or project["id"].startswith("demo"):
        return default_baseline(project)
    return generic_baseline(project, q)


PRESETS = {
    "as_certified": {"el": "Όπως πιστοποιήθηκε (ΚΕΝΑΚ)", "en": "As certified (KENAK)"},
    "pre_2010": {"el": "Υφιστάμενο κτίριο πριν το 2010 (χωρίς μόνωση)", "en": "Existing pre-2010 building (uninsulated)"},
    "pre_1980": {"el": "Υφιστάμενο κτίριο πριν το 1980", "en": "Existing pre-1980 building"},
}


def apply_preset(base: dict[str, Any], preset: str) -> dict[str, Any]:
    """Return a copy of the baseline with the envelope/plant of an older building. The certificate (calibration anchor) is kept."""
    st = copy.deepcopy(base)
    if preset == "as_certified":
        return st
    e = st["envelope"]
    if preset == "pre_2010":
        e["walls"].update(U=0.85, alpha=0.50)
        e["roof"].update(U=1.60, alpha=0.70)
        e["windows"].update(U=3.60, g=0.75, frame_frac=0.25, fsh_summer=0.85, fsh_winter=0.90)
        e["thermal_bridges_WK"] = base["envelope"]["thermal_bridges_WK"] * 2.2
        st["ventilation"]["ach"] = 0.9
        st["plant"]["heating"] = {"fuel": "natural_gas", "efficiency": 0.80}
        st["plant"]["cooling"] = {"fuel": "electricity", "efficiency": 3.0}
        st["plant"]["dhw"] = {"fuel": "electricity", "efficiency": 0.95, "solar_fraction": 0.0}
    elif preset == "pre_1980":
        e["walls"].update(U=1.35, alpha=0.55)
        e["roof"].update(U=2.40, alpha=0.75)
        e["windows"].update(U=5.00, g=0.80, frame_frac=0.20, fsh_summer=0.90, fsh_winter=0.95)
        e["thermal_bridges_WK"] = base["envelope"]["thermal_bridges_WK"] * 3.0
        st["ventilation"]["ach"] = 1.2
        st["plant"]["heating"] = {"fuel": "natural_gas", "efficiency": 0.70}
        st["plant"]["cooling"] = {"fuel": "electricity", "efficiency": 2.6}
        st["plant"]["dhw"] = {"fuel": "electricity", "efficiency": 0.95, "solar_fraction": 0.0}
    return st


# ------------------------------------------------------------------------------------------------
def _eta(gamma: float, a: float) -> float:
    if abs(gamma - 1.0) < 1e-6:
        return a / (a + 1.0)
    if gamma <= 0:
        return 1.0
    return (1 - gamma ** a) / (1 - gamma ** (a + 1))


def monthly_balance(state: dict[str, Any]) -> dict[str, Any]:
    """Return monthly heating/cooling needs (kWh) for an energy state."""
    c = state["climate"]
    env = state["envelope"]
    af, vol = state["area_m2"], state["volume_m3"]
    w = env["windows"]
    vent = state["ventilation"]
    h_ve = 0.33 * vent["ach"] * vol * (1 - vent.get("recovery", 0.0))
    th, tc = state["setpoint_heating"], state["setpoint_cooling"]
    qint = state["internal_gains_W_m2"] * af
    cm = state["thermal_mass_kJ_m2K"] * 1000 * af                        # J/K
    qh, qc = [], []
    res = {"months": []}
    for m in range(12):
        hrs = HOURS[m]
        te = c["T_ext"][m]
        gh_w = c["G_h"][m] * 1000 / hrs                                    # mean horizontal irradiance W/m2
        gv_w = gh_w * c["k_vert"][m]
        dts_roof = env["roof"]["alpha"] * gh_w / 25.0                      # solar-air temperature rise (h_e = 25 W/m2K)
        dts_wall = env["walls"]["alpha"] * gv_w / 25.0
        fsh = w["fsh_summer"] if m in (4, 5, 6, 7, 8, 9) else w["fsh_winter"]
        qsol = w["A"] * (1 - w["frame_frac"]) * w["g"] * 0.9 * fsh * gv_w   # W
        h_tr_w = env["walls"]["U"] * env["walls"]["A"]
        h_tr_r = env["roof"]["U"] * env["roof"]["A"]
        h_tr_o = w["U"] * w["A"] + env["thermal_bridges_WK"]
        h = h_tr_w + h_tr_r + h_tr_o + h_ve
        tau = cm / h / 3600.0
        a = 1.0 + tau / 15.0
        # heating
        loss_h = (h_tr_o + h_ve) * (th - te) + h_tr_w * (th - te - dts_wall) + h_tr_r * (th - te - dts_roof)
        gain = qint + qsol
        if loss_h > 0:
            g = gain / loss_h
            q_h = max(0.0, (loss_h - _eta(g, a) * gain)) * hrs / 1000
        else:
            q_h = 0.0
        # cooling
        loss_c = (h_tr_o + h_ve) * (tc - te) + h_tr_w * (tc - te - dts_wall) + h_tr_r * (tc - te - dts_roof)
        if gain > 0 and tc - te < 12:
            if loss_c <= 0:
                q_c = (gain - loss_c) * hrs / 1000
            else:
                g = gain / loss_c
                eta_ls = _eta(1.0 / g, a) if g > 0 else 0.0
                q_c = max(0.0, gain - eta_ls * loss_c) * hrs / 1000
        else:
            q_c = 0.0
        qh.append(q_h)
        qc.append(q_c)
    return {"heating_kwh_m": [round(x, 1) for x in qh], "cooling_kwh_m": [round(x, 1) for x in qc],
            "heating_kwh": sum(qh), "cooling_kwh": sum(qc), "heating_kwh_m2": sum(qh) / af, "cooling_kwh_m2": sum(qc) / af,
            "UA_total_WK": h_tr_w + h_tr_r + h_tr_o}


# ------------------------------------------------------------------------------------------------
def apply_measure(state: dict[str, Any], mid: str, m: dict[str, Any], params: dict[str, Any]) -> None:
    env = state["envelope"]
    t = m["type"]
    p = dict(m["params"])
    p.update(params or {})
    if t == "roof_insulation":
        r = env["roof"]
        r["U"] = 1.0 / (1.0 / r["U"] + p["thickness_cm"] / 100.0 / p["lambda"])
    elif t == "wall_insulation":
        wl = env["walls"]
        wl["U"] = 1.0 / (1.0 / wl["U"] + p["thickness_cm"] / 100.0 / p["lambda"])
    elif t == "windows":
        share = p.get("share_pct", 100.0) / 100.0
        w = env["windows"]
        w["U"] = w["U"] * (1 - share) + p["U_new"] * share
        w["g"] = w["g"] * (1 - share) + p["g_new"] * share
    elif t == "cool_roof":
        env["roof"]["alpha"] = min(env["roof"]["alpha"], p["alpha_new"])
    elif t == "shading":
        w = env["windows"]
        w["fsh_summer"] = min(w["fsh_summer"], p["fsh_summer"])
        w["fsh_winter"] = min(w["fsh_winter"], p["fsh_winter"])
    elif t == "mvhr":
        state["ventilation"]["recovery"] = max(state["ventilation"].get("recovery", 0.0), p["efficiency"])
        state["ventilation"]["fan_kwh_m2"] = state["ventilation"].get("fan_kwh_m2", 0.0) + p["fan_kwh_m2"]
    elif t == "heat_pump":
        pl = state["plant"]
        pl["heating"] = {"fuel": "electricity", "efficiency": p["scop"]}
        pl["cooling"] = {"fuel": "electricity", "efficiency": p["seer"]}
        pl["dhw"] = dict(pl["dhw"], fuel="electricity", efficiency=p["scop"] * 0.85)
    elif t == "bacs":
        state.setdefault("factors", {})["heating"] = state.get("factors", {}).get("heating", 1.0) * p["heating_factor"]
        state.setdefault("factors", {})["cooling"] = state.get("factors", {}).get("cooling", 1.0) * p["cooling_factor"]
    elif t == "pv":
        state.setdefault("pv", {"kwp": 0.0, "pr": p["pr"]})
        state["pv"]["kwp"] += p["kwp"]
        state["pv"]["pr"] = p["pr"]


def _pf(meas: dict, fuel: str) -> float:
    return meas["primary_energy_factors"].get(fuel, 1.0)


def evaluate(state: dict[str, Any], base_state: dict[str, Any] | None = None, apartments: int = 5) -> dict[str, Any]:
    """Primary energy (kWh/m2.y) per end-use, class and totals for `state`, anchored to the baseline certificate."""
    meas = load_measures()
    base = base_state or state
    cert = base["certificate"]
    bal_b = monthly_balance(base)
    bal_n = monthly_balance(state)
    af = state["area_m2"]
    fac = state.get("factors", {})

    def plant_factor(st, use):
        pl = st["plant"][use]
        return _pf(meas, pl["fuel"]) / pl["efficiency"]

    h_cert, c_cert, d_cert = cert["by_use"]["heating"], cert["by_use"]["cooling"], cert["by_use"]["dhw"]
    e_h = h_cert * (bal_n["heating_kwh"] / max(bal_b["heating_kwh"], 1e-9)) * (plant_factor(state, "heating") / plant_factor(base, "heating")) * fac.get("heating", 1.0)
    e_c = c_cert * (bal_n["cooling_kwh"] / max(bal_b["cooling_kwh"], 1e-9)) * (plant_factor(state, "cooling") / plant_factor(base, "cooling")) * fac.get("cooling", 1.0)
    dh_b, dh_n = base["plant"]["dhw"], state["plant"]["dhw"]
    e_d = d_cert * ((1 - dh_n["solar_fraction"]) / max(1 - dh_b["solar_fraction"], 1e-6)) * (plant_factor(state, "dhw") / plant_factor(base, "dhw"))
    e_v = state["ventilation"].get("fan_kwh_m2", 0.0) * _pf(meas, "electricity") - base["ventilation"].get("fan_kwh_m2", 0.0) * _pf(meas, "electricity")

    # useful needs (kWh/m2) -> final energy by carrier
    need_h = bal_n["heating_kwh_m2"] * fac.get("heating", 1.0) * (h_cert / (_pf(meas, base["plant"]["heating"]["fuel"]) / base["plant"]["heating"]["efficiency"])) / max(bal_b["heating_kwh_m2"], 1e-9)
    need_c = bal_n["cooling_kwh_m2"] * fac.get("cooling", 1.0) * (c_cert / (_pf(meas, base["plant"]["cooling"]["fuel"]) / base["plant"]["cooling"]["efficiency"])) / max(bal_b["cooling_kwh_m2"], 1e-9)
    # need_* here are "useful energy at the same scale as the certificate" (kWh/m2)
    final = {"electricity": 0.0, "natural_gas": 0.0}
    el_use = {"heating": 0.0, "cooling": 0.0, "dhw": 0.0, "fans": 0.0}        # electric part per use (kWh/m2)
    for use, need in (("heating", need_h), ("cooling", need_c)):
        pl = state["plant"][use]
        final[pl["fuel"]] += need / pl["efficiency"]
        if pl["fuel"] == "electricity":
            el_use[use] += need / pl["efficiency"]
    dhw_need = d_cert / (_pf(meas, base["plant"]["dhw"]["fuel"]) / base["plant"]["dhw"]["efficiency"]) * base["plant"]["dhw"]["efficiency"] / max(1 - dh_b["solar_fraction"], 1e-6)
    d_final = dhw_need * (1 - dh_n["solar_fraction"]) / dh_n["efficiency"]
    final[dh_n["fuel"]] += d_final
    if dh_n["fuel"] == "electricity":
        el_use["dhw"] += d_final
    final["electricity"] += state["ventilation"].get("fan_kwh_m2", 0.0)
    el_use["fans"] += state["ventilation"].get("fan_kwh_m2", 0.0)

    # PV
    pv_gen = pv_used = pv_credit = 0.0
    pv = state.get("pv")
    pv_monthly = []
    if pv and pv["kwp"] > 0:
        gen_m = [pv["kwp"] * pv["pr"] * g for g in state["climate"]["G_45"]]
        pv_gen = sum(gen_m)
        hm, cm_ = bal_n["heating_kwh_m"], bal_n["cooling_kwh_m"]
        sh, sc = max(sum(hm), 1e-9), max(sum(cm_), 1e-9)
        for m in range(12):                                   # monthly matching of generation and building electricity demand
            dem = (el_use["heating"] * hm[m] / sh + el_use["cooling"] * cm_[m] / sc + (el_use["dhw"] + el_use["fans"]) / 12.0) * af
            pv_used += min(gen_m[m] * 0.90, dem)              # 10 % losses/ non-coincidence
        pv_credit = pv_used * _pf(meas, "electricity") / af
        pv_monthly = [round(x, 1) for x in gen_m]
    total = e_h + e_c + e_d + e_v + cert["by_use"].get("lighting", 0.0) - pv_credit
    total = max(total, 0.0)
    ref = cert["reference_kwh_m2"]
    ratio = total / ref
    cls = class_of(ratio, meas)
    co2 = {k: final[k] * meas["co2_factors_kg_per_kwh"][k] for k in final}
    co2_total = sum(co2.values()) - (pv_used / af) * meas["co2_factors_kg_per_kwh"]["electricity"]
    tar = meas["tariffs_eur_per_kwh"]
    cost_eur = (final["electricity"] * tar["electricity"] + final["natural_gas"] * tar["natural_gas"]) * af - (pv_gen * 0.5 * tar["electricity"] if pv_gen else 0.0)
    return {
        "by_use": {"heating": round(e_h, 2), "cooling": round(e_c, 2), "dhw": round(e_d, 2), "ventilation_fans": round(e_v, 2),
                   "lighting": cert["by_use"].get("lighting", 0.0), "pv_credit": round(-pv_credit, 2)},
        "primary_kwh_m2": round(total, 2), "reference_kwh_m2": ref, "ratio": round(ratio, 3), "class": cls,
        "final_kwh_m2": {k: round(v, 2) for k, v in final.items()}, "co2_kg_m2": round(co2_total, 2),
        "needs": {"heating_kwh_m2": round(bal_n["heating_kwh_m2"], 2), "cooling_kwh_m2": round(bal_n["cooling_kwh_m2"], 2),
                  "heating_month": bal_n["heating_kwh_m"], "cooling_month": bal_n["cooling_kwh_m"], "UA_total_WK": round(bal_n["UA_total_WK"], 1)},
        "pv": {"generation_kwh": round(pv_gen, 0), "used_in_services_kwh": round(pv_used, 0), "monthly_kwh": pv_monthly},
        "energy_cost_eur_year": round(cost_eur, 0), "area_m2": af,
    }


def class_of(ratio: float, meas: dict | None = None) -> str:
    meas = meas or load_measures()
    for name, thr in meas["classes"]:
        if ratio <= thr:
            return name
    return meas["classes"][-1][0]


def measure_cost(mid: str, m: dict[str, Any], params: dict[str, Any], areas: dict[str, float]) -> float:
    c = m["cost"]
    p = dict(m["params"])
    p.update(params or {})
    t = m["type"]
    if t in ("roof_insulation", "wall_insulation"):
        a = areas["roof_m2" if c["area"] == "roof_m2" else "wall_m2"]
        return a * (c["fixed_per_m2"] + c["per_cm_per_m2"] * p["thickness_cm"])
    if t == "windows":
        return areas["window_m2"] * c["per_m2"] * p.get("share_pct", 100.0) / 100.0
    if t in ("cool_roof",):
        return areas["roof_m2"] * c["per_m2"]
    if t == "shading":
        return areas["window_m2"] * c["per_m2"]
    if t == "pv":
        return p["kwp"] * c["per_kwp"]
    if t == "heat_pump":
        return p["kw_per_m2"] * areas["area_m2"] * c["per_kw"]
    if t in ("mvhr", "bacs"):
        return areas["area_m2"] * c["per_m2_conditioned"]
    return 0.0


def study(project: dict[str, Any], selected: dict[str, dict[str, Any]] | None = None, index_ratio: float = 1.0, preset: str = "as_certified",
          quantities: dict[str, float] | None = None) -> dict[str, Any]:
    """Baseline vs selected measures: per-measure marginal effects, package result, costs, paybacks."""
    meas = load_measures()
    base = baseline_for(project, quantities)
    for k, v in (project.get("energy_overrides") or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k].update(v)
    areas = {"roof_m2": base["envelope"]["roof"]["A"], "wall_m2": base["envelope"]["walls"]["A"],
             "window_m2": base["envelope"]["windows"]["A"], "area_m2": base["area_m2"]}
    cert_state = base                                   # calibration anchor: the certified building
    base = apply_preset(cert_state, preset)             # starting point chosen by the user
    lv = project.get("live") or {}
    site_cl = (lv.get("climate") or {}).get("energy_climate")
    climate_source = "design"
    if site_cl and (lv.get("use") or {}).get("climate"):
        base = copy.deepcopy(base)                      # the certificate stays on the design climate; the building now sees the site's measured climate
        base["climate"].update(site_cl)
        climate_source = "site_history"
    base_res = evaluate(base, cert_state)
    out_measures = []
    tar = meas["tariffs_eur_per_kwh"]
    for mid, m in meas["measures"].items():
        params = (selected or {}).get(mid, {}).get("params", {}) if selected else {}
        st = copy.deepcopy(base)
        apply_measure(st, mid, m, params)
        r = evaluate(st, cert_state)
        cost = measure_cost(mid, m, params, areas) * index_ratio
        d_cost_year = base_res["energy_cost_eur_year"] - r["energy_cost_eur_year"]
        out_measures.append({"id": mid, "el": m["el"], "en": m["en"], "hint_el": m["hint_el"], "hint_en": m["hint_en"], "params": {**m["params"], **params},
                             "primary_kwh_m2": r["primary_kwh_m2"], "delta_kwh_m2": round(base_res["primary_kwh_m2"] - r["primary_kwh_m2"], 2),
                             "class": r["class"], "ratio": r["ratio"], "cost_eur": round(cost, 0), "saving_eur_year": round(d_cost_year, 0),
                             "payback_years": round(cost / d_cost_year, 1) if d_cost_year > 1 else None, "life_years": m["life_years"]})
    pkg_state = copy.deepcopy(base)
    chosen = []
    pkg_cost = 0.0
    for mid, sel in (selected or {}).items():
        if not sel.get("enabled", True) or mid not in meas["measures"]:
            continue
        apply_measure(pkg_state, mid, meas["measures"][mid], sel.get("params", {}))
        pkg_cost += measure_cost(mid, meas["measures"][mid], sel.get("params", {}), areas) * index_ratio
        chosen.append(mid)
    pkg = evaluate(pkg_state, cert_state)
    sav = base_res["energy_cost_eur_year"] - pkg["energy_cost_eur_year"]
    return {"baseline": base_res, "package": pkg, "measures": out_measures, "selected": chosen, "package_cost_eur": round(pkg_cost, 0),
            "package_saving_eur_year": round(sav, 0), "package_payback_years": round(pkg_cost / sav, 1) if sav > 1 else None,
            "classes": meas["classes"], "tariffs": tar, "baseline_state": base, "preset": preset, "presets": PRESETS, "climate_source": climate_source}


def class_scale(meas: dict | None = None) -> list[dict[str, Any]]:
    meas = meas or load_measures()
    return [{"class": n, "max_ratio": t} for n, t in meas["classes"]]
