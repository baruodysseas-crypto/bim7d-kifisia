"""7D – facility and asset management: the properties of the building (σύσταση οριζόντιας ιδιοκτησίας), the asset register with its
periodic tasks, and the allocation of the building's running costs to each property.

The costs are not estimated again here: every euro comes from the 5D life-cycle cost (`lifecycle.compute`): maintenance, inspections
and replacements of each component, the energy, the insurance and the cleaning. They are split
  * to the columns of the table of shares (lighting, lift, cleaning, maintenance, plot shares, garden) for the common parts, and
  * to the apartments by their area for the private parts (windows, floors, kitchens, own heating/cooling, own energy).
So the sum over the properties equals the building's total of the 5D, year by year.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from . import lifecycle

DATA = Path(__file__).parent / "data"
KEYS = ["votes", "lighting", "lift", "cleaning", "maintenance", "plot", "garden"]
CATS = ["maintenance", "replacement", "energy", "insurance", "cleaning", "measures"]


def load_assets() -> dict[str, Any]:
    return json.loads((DATA / "assets.json").read_text(encoding="utf-8"))


def demo_properties() -> dict[str, Any]:
    """The table of shares of the demo building (Ποταμού 4, Κηφισιά), without owners' names."""
    return json.loads((DATA / "properties_kifisia.json").read_text(encoding="utf-8"))


def properties_of(project: dict[str, Any]) -> dict[str, Any]:
    pr = project.get("properties")
    if pr and pr.get("properties"):
        return pr
    # no table: one property per apartment of the project, shares by area
    apts = project.get("apartments") or []
    tot = sum(a.get("area_m2", 0.0) for a in apts) or 1.0
    rows = [{"id": a["id"], "name_el": a.get("name_el", a["id"]), "name_en": a.get("name_en", a["id"]), "type": "apartment", "storey": a.get("storey"),
             "area_m2": a.get("area_m2", 0.0), "total_m2": a.get("area_m2", 0.0), "volume_m3": 0.0,
             "keys": {k: round(1000 * a.get("area_m2", 0.0) / tot) for k in KEYS}} for a in apts]
    return {"_source": "Εκτίμηση από τα εμβαδά των διαμερισμάτων (δεν έχει δοθεί πίνακας ποσοστών)", "_source_en": "Estimated from the apartment areas (no table of shares given)",
            "keys": demo_properties()["keys"], "properties": rows, "common_areas": [], "estimated": True}


def check_table(table: dict[str, Any]) -> list[dict[str, Any]]:
    """Each column of the table of shares must add up to 1000 ‰."""
    out = []
    for k in KEYS:
        s = sum(float(r["keys"].get(k, 0) or 0) for r in table["properties"])
        out.append({"key": k, "sum": round(s, 3), "ok": abs(s - 1000) < 0.5})
    return out


def _component_rows(comps: list[dict[str, Any]], H: int) -> dict[str, list[dict[str, float]]]:
    """Year-by-year maintenance (incl. inspections) and replacement cost of each component (same rules as the LCC)."""
    out = {}
    for c in comps:
        rows = [{"maintenance": 0.0, "replacement": 0.0} for _ in range(H + 1)]
        for y in range(1, H + 1):
            rows[y]["maintenance"] += c["initial_cost"] * c["annual_pct"] / 100.0
            if c.get("inspect_every") and y % c["inspect_every"] == 0:
                rows[y]["maintenance"] += c["initial_cost"] * c.get("inspect_pct", 0.0) / 100.0          # inspect_pct is a percentage
            if c.get("replace_every") and y % c["replace_every"] == 0 and y < H:
                rows[y]["replacement"] += c["initial_cost"] * c["replace_pct"]
        out[c["id"]] = rows
    return out


def compute(project: dict[str, Any], cost_res: dict[str, Any], lcc: dict[str, Any], risk: dict[str, Any] | None = None) -> dict[str, Any]:
    """Allocation of the life-cycle running costs (years 1..H) to the properties, asset register and maintenance calendar.
    `lcc` is one result of `lifecycle.compute` (the case in use: with or without the energy upgrades)."""
    table = properties_of(project)
    props = table["properties"]
    reg = load_assets()
    alloc = copy.deepcopy(reg["allocation"])
    alloc.update((project.get("settings") or {}).get("fm_allocation") or {})
    H = int(lcc["horizon"])
    r = lcc["assumptions"]["real_discount_pct"] / 100.0
    comps = lifecycle.components_with_cost(project, cost_res)
    comp_rows = _component_rows(comps, H)
    series = lcc["series"]
    a = lcc["assumptions"]
    gfa = float(project["meta"].get("gfa_m2") or 0.0) or 1.0
    insurance = cost_res["net"] * a["insurance_pct_of_construction"] / 100.0
    ce = float(reg.get("common_energy_pct", 10.0)) / 100.0
    apts = [p for p in props if p.get("type") == "apartment"]
    a_tot = sum(float(p.get("total_m2") or p.get("area_m2") or 0.0) for p in apts) or 1.0
    w_area = {p["id"]: float(p.get("total_m2") or p.get("area_m2") or 0.0) / a_tot for p in apts}

    def share(target: str, pid: str) -> float:
        if target in ("private", "private_energy"):
            return w_area.get(pid, 0.0)
        p = next(x for x in props if x["id"] == pid)
        return float(p["keys"].get(target, 0) or 0) / 1000.0

    # building totals per category and target (year by year)
    tgt_year: list[dict[tuple[str, str], float]] = [dict() for _ in range(H + 1)]

    def put(y: int, cat: str, split: dict[str, float], amount: float) -> None:
        if not amount:
            return
        for t, f in split.items():
            if t.startswith("_"):
                continue
            tgt_year[y][(cat, t)] = tgt_year[y].get((cat, t), 0.0) + amount * f

    for y in range(1, H + 1):
        comp_m = comp_r = 0.0
        for c in comps:
            sp = alloc.get(c["id"], {"maintenance": 1.0})
            put(y, "maintenance", sp, comp_rows[c["id"]][y]["maintenance"])
            put(y, "replacement", sp, comp_rows[c["id"]][y]["replacement"])
            comp_m += comp_rows[c["id"]][y]["maintenance"]
            comp_r += comp_rows[c["id"]][y]["replacement"]
        row = series[y]
        rest = row["maintenance"] + row["replacement"] + row.get("retrofit", 0.0) - comp_m - comp_r     # upgrade package: investment, upkeep, renewals
        put(y, "measures", alloc["_measures"], rest)
        put(y, "energy", alloc["_energy_common"], row["energy"] * ce)
        put(y, "energy", alloc["_energy_private"], row["energy"] * (1 - ce))
        put(y, "insurance", alloc["_insurance"], insurance)
        put(y, "cleaning", alloc["_cleaning"], row["other"] - insurance)
    # per property
    out_props = []
    for p in props:
        pid = p["id"]
        by_cat = {k: 0.0 for k in CATS}
        y1 = {k: 0.0 for k in CATS}
        pv = 0.0
        for y in range(1, H + 1):
            d = 1.0 / (1 + r) ** y
            for (cat, t), amt in tgt_year[y].items():
                v = amt * share(t, pid)
                by_cat[cat] += v
                pv += v * d
                if y == 1:
                    y1[cat] += v
        avg = {k: v / H for k, v in by_cat.items()}
        area = float(p.get("total_m2") or p.get("area_m2") or 0.0)
        eal = (risk or {}).get("total_eal_eur", 0.0) * float(p["keys"].get("plot", 0) or 0) / 1000.0
        out_props.append({**{k: p.get(k) for k in ("id", "name_el", "name_en", "type", "storey", "area_m2", "total_m2", "volume_m3", "note")}, "keys": p["keys"],
                          "year1": {k: round(v, 2) for k, v in y1.items()}, "year1_total": round(sum(y1.values()), 2),
                          "avg_annual": {k: round(v, 2) for k, v in avg.items()}, "avg_annual_total": round(sum(avg.values()), 2),
                          "eur_per_m2_year": round(sum(avg.values()) / area, 2) if area else None,
                          "pv_total": round(pv, 0), "replacement_value": round(cost_res["net"] * float(p["keys"].get("plot", 0) or 0) / 1000.0, 0),
                          "risk_eal": round(eal, 0)})
    # building totals, for the reconciliation with the 5D
    bld_running = sum(series[y]["total"] for y in range(1, H + 1))
    alloc_total = sum(sum(pp["avg_annual"].values()) for pp in out_props) * H
    # who pays what, per column of the table (average year)
    by_target: dict[str, float] = {}
    for y in range(1, H + 1):
        for (cat, t), amt in tgt_year[y].items():
            by_target[t] = by_target.get(t, 0.0) + amt / H
    # asset register: tasks + the cost of the linked component
    cmap = {c["id"]: c for c in comps}
    assets = []
    for asst in reg["assets"]:
        c = cmap.get(asst["component"])
        rows = comp_rows.get(asst["component"])
        nxt = None
        if c and c.get("replace_every"):
            nxt = int(c["replace_every"])
        assets.append({**asst, "initial_cost": round(c["initial_cost"]) if c else None, "annual_maintenance": round(rows[1]["maintenance"]) if rows else None,
                       "replace_every": c.get("replace_every") if c else None, "next_replacement_year": nxt,
                       "allocation": alloc.get(asst["component"], {})})
    # maintenance calendar: inspections / replacements over the horizon
    cal = []
    for c in comps:
        for y in range(1, H + 1):
            if c.get("replace_every") and y % c["replace_every"] == 0 and y < H:
                cal.append({"year": y, "component": c["id"], "el": c["el"], "en": c["en"], "action": "replacement", "cost": round(c["initial_cost"] * c["replace_pct"]),
                            "allocation": alloc.get(c["id"], {})})
            if c.get("inspect_every") and y % c["inspect_every"] == 0:
                cal.append({"year": y, "component": c["id"], "el": c["el"], "en": c["en"], "action": "inspection", "cost": round(c["initial_cost"] * c.get("inspect_pct", 0.0) / 100.0),
                            "allocation": alloc.get(c["id"], {})})
    cal.sort(key=lambda e: (e["year"], -e["cost"]))
    # service life of each component (for the 4D life timeline)
    life = [{"id": c["id"], "el": c["el"], "en": c["en"], "replace_every": c.get("replace_every"), "replace_pct": c.get("replace_pct"),
             "initial_cost": round(c["initial_cost"])} for c in comps]
    return {"source": table.get("_source"), "source_en": table.get("_source_en"), "estimated": bool(table.get("estimated")), "keys": table["keys"],
            "checks": check_table(table), "common_areas": table.get("common_areas", []), "properties": out_props, "horizon": H,
            "by_target_avg": {k: round(v, 2) for k, v in by_target.items()},
            "reconciliation": {"building_running_total": round(bld_running, 0), "allocated_total": round(alloc_total, 0)},
            "assets": assets, "calendar": cal, "service_life": life, "common_energy_pct": reg.get("common_energy_pct", 10.0),
            "risk_total_eal": (risk or {}).get("total_eal_eur")}
