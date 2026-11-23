"""7D engine: maintenance plan, life-cycle cost (LCC, EN 15459 style) and life-cycle assessment (LCA, EN 15978 modules A–D)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from . import energy as E

DATA = Path(__file__).parent / "data"


def load_maintenance() -> dict[str, Any]:
    return json.loads((DATA / "maintenance.json").read_text(encoding="utf-8"))


def load_materials() -> dict[str, Any]:
    return json.loads((DATA / "materials.json").read_text(encoding="utf-8"))


def merged_assumptions(project: dict[str, Any] | None = None) -> dict[str, Any]:
    mt = load_maintenance()
    a = dict(mt["defaults"])
    a.update((project or {}).get("lifecycle_assumptions") or {})
    return a


def components_with_cost(project: dict[str, Any], cost_res: dict[str, Any]) -> list[dict[str, Any]]:
    """Maintenance components with their initial cost (net, incl. overheads) and embodied carbon, taken from the cost model."""
    mt = load_maintenance()
    mats = load_materials()
    comps = copy.deepcopy(mt["components"])
    for ov in (project.get("maintenance_overrides") or []):
        for c in comps:
            if c["id"] == ov.get("id"):
                c.update({k: v for k, v in ov.items() if k != "id"})
    mult = cost_res["net"] / cost_res["direct"] if cost_res["direct"] else 1.0
    by_key = {l["key"]: l for l in cost_res["lines"]}
    upl = 1 + mats["uplift_A4_A5_pct"] / 100.0
    for c in comps:
        c["initial_cost"] = sum(by_key[k]["total"] for k in c["items"] if k in by_key) * mult
        c["embodied_kg"] = sum(by_key[k]["qty"] * mats["items"].get(k, {"kg": 0.0})["kg"] for k in c["items"] if k in by_key) * upl
    return comps


def lca(project: dict[str, Any], cost_res: dict[str, Any], quantities: dict[str, float], en_result: dict[str, Any] | None,
        horizon: int, comps: list[dict[str, Any]], measure_ids: list[str] | None = None, energy_areas: dict | None = None,
        retrofit_year: int = 0) -> dict[str, Any]:
    mats = load_materials()
    meas = E.load_measures()
    upl = 1 + mats["uplift_A4_A5_pct"] / 100.0
    gfa = float(quantities.get("gfa_m2") or 1.0)
    by_group: dict[str, float] = {}
    by_item = []
    a1a3 = 0.0
    rebar_kg = 0.0
    for l in cost_res["lines"]:
        m = mats["items"].get(l["key"])
        if not m or l["qty"] <= 0:
            continue
        kg = l["qty"] * m["kg"]
        a1a3 += kg
        by_group[m["group"]] = by_group.get(m["group"], 0.0) + kg
        if m.get("material") == "rebar":
            rebar_kg += kg
        by_item.append({"key": l["key"], "el": l["el"], "en": l["en"], "qty": l["qty"], "unit": l["unit"], "kg": kg, "group": m["group"]})
    by_item.sort(key=lambda r: -r["kg"])
    a4a5 = a1a3 * (upl - 1)
    # measures embodied carbon
    meas_kg = 0.0
    if measure_ids and energy_areas:
        for mid in measure_ids:
            f = mats["measures_kg"].get(mid)
            if not f:
                continue
            m = meas["measures"][mid]
            p = m["params"]
            if "per_kwp" in f:
                meas_kg += f["per_kwp"] * p.get("kwp", 0)
            elif "per_kw" in f:
                meas_kg += f["per_kw"] * p.get("kw_per_m2", 0) * energy_areas["area_m2"]
            else:
                a = energy_areas["roof_m2"] if m["cost"].get("area") == "roof_m2" else energy_areas["window_m2"] if m["cost"].get("area") == "window_m2" else energy_areas["wall_m2"]
                if m["type"] in ("mvhr", "bacs"):
                    a = energy_areas["area_m2"]
                meas_kg += a * (f.get("per_m2", 0) + f.get("per_cm_per_m2", 0) * p.get("thickness_cm", 0) if m["type"] == "wall_insulation" else f.get("per_m2", 0))
        meas_kg *= upl
    # B4 replacements
    b4 = 0.0
    repl_events = []
    for c in comps:
        if c.get("replace_every"):
            t = c["replace_every"]
            while t < horizon:
                kg = c["embodied_kg"] * c["co2_share"]
                b4 += kg
                repl_events.append({"year": t, "component": c["id"], "kg": kg})
                t += c["replace_every"]
    # B6 operational
    op = 0.0
    dec = mats["grid_decarbonisation_pct_per_year"] / 100.0
    op_series = []
    if en_result:
        af = en_result["area_m2"]
        el_f, gas_f = en_result["_co2"]["electricity"], en_result["_co2"]["natural_gas"]
        for y in range(1, horizon + 1):
            r = en_result["_series"](y)
            kg = (r["final_kwh_m2"]["electricity"] * el_f * (1 - dec) ** (y - 1) + r["final_kwh_m2"]["natural_gas"] * gas_f) * af
            kg -= r.get("pv_used_kwh", 0.0) * el_f * (1 - dec) ** (y - 1)
            op += kg
            op_series.append(round(kg, 0))
    c_eol = mats["end_of_life_kg_per_m2_gfa"] * gfa
    d_credit = -rebar_kg * mats["rebar_recycling_credit_pct"] / 100.0
    total = a1a3 + a4a5 + meas_kg + b4 + op + c_eol + d_credit
    return {"A1_A3_kg": round(a1a3), "A4_A5_kg": round(a4a5), "measures_kg": round(meas_kg), "B4_kg": round(b4), "B6_kg": round(op), "C_kg": round(c_eol),
            "D_kg": round(d_credit), "total_kg": round(total), "per_m2_gfa": round(total / gfa, 1), "per_m2_gfa_year": round(total / gfa / horizon, 2),
            "embodied_share_pct": round(100 * (a1a3 + a4a5 + meas_kg + b4 + c_eol + d_credit) / total, 1) if total else 0,
            "by_group": {k: round(v) for k, v in by_group.items()}, "groups": mats["groups"], "by_item": [dict(i, kg=round(i["kg"])) for i in by_item[:12]],
            "replacements": repl_events, "operational_series": op_series, "horizon": horizon}


def _energy_series_factory(base_res: dict[str, Any], pkg_res: dict[str, Any] | None, retrofit_year: int, tariffs: dict[str, float]):
    """Return a function year-> {energy cost, final energy, ...} switching from baseline to package at retrofit_year."""
    def at(y: int) -> dict[str, Any]:
        r = pkg_res if (pkg_res is not None and y > retrofit_year) else base_res
        pv_used = r["pv"]["used_in_services_kwh"] if r.get("pv") else 0.0
        return {"final_kwh_m2": r["final_kwh_m2"], "cost": r["energy_cost_eur_year"], "pv_used_kwh": pv_used}
    return at


def compute(project: dict[str, Any], cost_res: dict[str, Any], quantities: dict[str, float], en_study: dict[str, Any],
            with_measures: bool = True, assumptions: dict[str, Any] | None = None) -> dict[str, Any]:
    a = merged_assumptions(project)
    a.update(assumptions or {})
    H = int(a["horizon_years"])
    r = a["real_discount_pct"] / 100.0
    esc = a["energy_escalation_pct"] / 100.0
    comps = components_with_cost(project, cost_res)
    meas = E.load_measures()
    base_state = en_study["baseline_state"]
    areas = {"roof_m2": base_state["envelope"]["roof"]["A"], "wall_m2": base_state["envelope"]["walls"]["A"],
             "window_m2": base_state["envelope"]["windows"]["A"], "area_m2": base_state["area_m2"]}
    use_pkg = with_measures and bool(en_study["selected"])
    base_res = en_study["baseline"]
    pkg_res = en_study["package"] if use_pkg else None
    retro = int(a["retrofit_year"])
    ser = _energy_series_factory(base_res, pkg_res, retro, meas["tariffs_eur_per_kwh"])
    years = list(range(0, H + 1))
    rows = [{"year": y, "construction": 0.0, "retrofit": 0.0, "maintenance": 0.0, "replacement": 0.0, "energy": 0.0, "other": 0.0} for y in years]
    construction = cost_res["net"]
    rows[0]["construction"] = construction
    for c in comps:
        for y in range(1, H + 1):
            rows[y]["maintenance"] += c["initial_cost"] * c["annual_pct"] / 100.0
            if c.get("inspect_every") and y % c["inspect_every"] == 0:
                rows[y]["maintenance"] += c["initial_cost"] * c.get("inspect_pct", 0.0) / 100.0          # inspect_pct is a percentage
            if c.get("replace_every") and y % c["replace_every"] == 0 and y < H:
                rows[y]["replacement"] += c["initial_cost"] * c["replace_pct"]
    # measures: investment in retrofit year, maintenance, replacements at end of their life
    if use_pkg:
        rows[retro]["retrofit"] += en_study["package_cost_eur"]
        for mid in en_study["selected"]:
            m = meas["measures"][mid]
            cost_m = next(x["cost_eur"] for x in en_study["measures"] if x["id"] == mid)
            for y in range(retro + 1, H + 1):
                rows[y]["maintenance"] += cost_m * m.get("maintenance_pct", 0.0) / 100.0
            t = retro + m["life_years"]
            while t < H:
                rows[t]["replacement"] += cost_m
                t += m["life_years"]
            if m["type"] == "pv":
                t = retro + m.get("inverter_life_years", 12)
                while t < H:
                    rows[t]["replacement"] += m["params"]["kwp"] * m.get("inverter_cost_per_kwp", 140.0)
                    t += m.get("inverter_life_years", 12)
    gfa = float(quantities.get("gfa_m2") or 1.0)
    for y in range(1, H + 1):
        rows[y]["energy"] = ser(y)["cost"] * (1 + esc) ** (y - 1)
        rows[y]["other"] = construction * a["insurance_pct_of_construction"] / 100.0 + a["cleaning_eur_per_m2_gfa_year"] * gfa
    struct_cost = next((c["initial_cost"] for c in comps if c["id"] == "structure"), 0.0)
    residual = struct_cost * a["residual_value_pct_of_structure"] / 100.0
    cum = 0.0
    tot = {k: 0.0 for k in ("construction", "retrofit", "maintenance", "replacement", "energy", "other")}
    for row in rows:
        y = row["year"]
        d = 1.0 / (1 + r) ** y
        row["total"] = sum(row[k] for k in tot)
        row["discounted"] = row["total"] * d
        if y == H:
            row["residual"] = -residual
            row["discounted"] += -residual * d
        cum += row["discounted"]
        row["cumulative_discounted"] = cum
        for k in tot:
            tot[k] += row[k] * d
    # LCA
    energy_for_lca = None
    if True:
        energy_for_lca = {"area_m2": base_state["area_m2"], "_co2": meas["co2_factors_kg_per_kwh"], "_series": ser}
    lca_res = lca(project, cost_res, quantities, energy_for_lca, H, comps, en_study["selected"] if use_pkg else None, areas, retro)
    npv = cum
    return {
        "assumptions": a, "horizon": H, "npv_total": round(npv), "npv_breakdown": {k: round(v) for k, v in tot.items()}, "residual_discounted": round(-residual / (1 + r) ** H),
        "npv_per_m2_gfa": round(npv / gfa, 1), "annual_equivalent": round(npv * r / (1 - (1 + r) ** -H)) if r > 0 else round(npv / H),
        "undiscounted_total": round(sum(row["total"] for row in rows)),
        "series": [{k: (round(v, 0) if isinstance(v, float) else v) for k, v in row.items()} for row in rows],
        "components": [{"id": c["id"], "el": c["el"], "en": c["en"], "initial_cost": round(c["initial_cost"]), "annual_pct": c["annual_pct"], "replace_every": c.get("replace_every"),
                        "replace_pct": c.get("replace_pct"), "embodied_kg": round(c["embodied_kg"])} for c in comps],
        "lca": lca_res, "with_measures": use_pkg, "retrofit_year": retro,
        "energy_in_use": {"class": (pkg_res or base_res)["class"], "primary_kwh_m2": (pkg_res or base_res)["primary_kwh_m2"], "baseline_class": base_res["class"]},
    }


def compare(project, cost_res, quantities, en_study, assumptions=None):
    """Business-as-usual vs. package of upgrades, for the LCC/LCA comparison charts."""
    a = compute(project, cost_res, quantities, en_study, with_measures=False, assumptions=assumptions)
    b = compute(project, cost_res, quantities, en_study, with_measures=True, assumptions=assumptions) if en_study["selected"] else None
    return {"base": a, "upgrade": b}
