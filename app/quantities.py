"""Quantity take-off from the BIM elements (3D -> 5D/6D inputs).

Everything is derived from the element list plus a small set of *assumptions* that the user can edit
(rebar ratios, internal-wall ratio, plot usage ...)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

DEFAULT_ASSUMPTIONS: dict[str, float] = {
    # reinforcement ratios kg per m3 of concrete
    "rebar_kg_m3_footing": 85.0, "rebar_kg_m3_slab": 95.0, "rebar_kg_m3_column": 190.0, "rebar_kg_m3_beam": 160.0,
    "rebar_kg_m3_wall": 100.0, "rebar_kg_m3_roof": 90.0, "rebar_kg_m3_stair": 110.0,
    # envelope layering
    "wall_insulation_cm": 10.0,
    "internal_wall_m2_per_m2": 0.85,          # internal masonry per m2 of conditioned floor
    "excavation_margin_m": 1.0,               # working space around the basement (used only without an excavation outline)
    "excavation_extra_depth_m": 0.35,         # blinding + raft bed below the basement floor level
    "excavation_swell": 1.25,                 # loose-volume factor of the excavated soil taken away by trucks
    "waterproof_raft_share": 1.0,             # share of the raft plan area that gets an under-slab membrane
    "doors_per_apartment": 8.0,
    "elevators": 1.0,
    "paving_share_of_site": 0.30, "planting_share_of_site": 0.35,
    "ceiling_paint_factor": 1.0,
}

CONCRETE_KINDS = ("footing", "slab", "column", "beam", "roof", "stair")


LANDSCAPE_KEYS = ("ramp_m2", "ramp_wall_m2", "fence_wall_m", "gate_garage", "gate_pedestrian", "entrance_canopy", "marble_m2", "hedge_m", "trees",
                  "planter_m", "frame_m3", "wood_cladding_m2")


def compute(project: dict[str, Any], assumptions: dict[str, float] | None = None) -> dict[str, Any]:
    a = dict(DEFAULT_ASSUMPTIONS)
    a.update(project.get("assumptions", {}) or {})
    a.update(assumptions or {})
    meta = project["meta"]
    els = project["elements"]
    storeys = {s["id"]: s for s in project["storeys"]}

    vol: dict[str, float] = defaultdict(float)
    cnt: dict[str, int] = defaultdict(int)
    by_storey: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    formwork_struct = formwork_found = 0.0
    rebar_struct = rebar_found = 0.0
    conc_struct = conc_found = 0.0
    wall_gross = wall_net_masonry = 0.0
    wall_int_gross = 0.0
    glazing = 0.0
    ext_open_area = 0.0                     # exterior doors / windows area (for models whose walls are not cut)
    reveal_plaster = 0.0                    # plaster on the reveals (špaletes) of the exterior openings
    n_windows = n_balcony = n_entrance = n_garage = n_int_doors = n_apt_doors = 0
    garage_area = 0.0
    lintel_n = 0
    land: dict[str, float] = dict((project.get("meta") or {}).get("landscape_qty") or {})
    lintel_len = lintel_vol = lintel_fw = lintel_rebar = 0.0
    railing_len = 0.0
    pergola_area = 0.0
    roof_plan = 0.0
    slab_plan_total = 0.0
    rebar_real = 0.0

    for e in els:
        k, q, sid = e["kind"], e["qty"], e.get("storey")
        pr = e.get("props") or {}
        if pr.get("landscape"):                             # surroundings, ramp, planters, cladding: their own cost lines
            bb = e.get("bbox") or [0] * 6
            dx, dy, dz = bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]
            m = pr.get("measure")
            val = {"plan": dx * dy, "slope": dx * (dy ** 2 + dz ** 2) ** 0.5, "face": max(dx, dy) * dz, "face_x": dx * dz, "length": max(dx, dy),
                   "count": 1.0, "volume": q.get("volume_m3", 0.0), "half_area": q.get("surface_m2", 0.0) / 2}.get(m, 0.0)
            land[pr["landscape"]] = land.get(pr["landscape"], 0.0) + val
            cnt[k] += 1
            vol[k] += q.get("volume_m3", 0.0)
            continue
        if pr.get("lintel"):                                # lintels (πρέκια) are priced on their own line
            lintel_n += 1
            lintel_len += q.get("length_m", 0.0)
            lintel_vol += q.get("volume_m3", 0.0)
            lintel_fw += (q.get("width_m", 0.0) + 2 * q.get("depth_m", 0.0)) * q.get("length_m", 0.0)
            lintel_rebar += q.get("volume_m3", 0.0) * a.get("rebar_kg_m3_beam", 160.0)
            cnt["lintel"] += 1
            vol["lintel"] += q.get("volume_m3", 0.0)
            continue
        cnt[k] += 1
        v = q.get("volume_m3", 0.0)
        vol[k] += v
        if sid:
            by_storey[sid][f"{k}_count"] += 1
            by_storey[sid][f"{k}_volume_m3"] += v
        if k in CONCRETE_KINDS or (k == "wall" and e.get("material") == "concrete"):
            kk = "wall" if k == "wall" else k
            ratio = a.get(f"rebar_kg_m3_{kk}", 100.0)
            real = rebar_from_drawings(e)                   # real bars of the formwork drawings, when known
            if real is not None and v > 0:
                ratio = real / v
                rebar_real += real
            fw = 0.0
            if k == "column":
                fw = (pr.get("perimeter_m") or 2 * (q.get("width_m", 0) + q.get("depth_m", 0))) * q.get("height_m", 0)
            elif k == "beam":
                fw = (q.get("width_m", 0) + 2 * q.get("depth_m", 0)) * q.get("length_m", 0)
            elif k in ("slab", "roof"):
                fw = q.get("plan_area_m2", 0) + q.get("perimeter_m", 0) * q.get("thickness_m", 0)
            elif k == "footing":
                fw = q.get("perimeter_m", 0) * q.get("thickness_m", 0)      # side faces only (the raft is cast on blinding)
            elif k == "wall":
                fw = 2 * q.get("face_area_m2", 0)
            if k == "footing":
                conc_found += v; rebar_found += v * ratio; formwork_found += fw
            else:
                conc_struct += v; rebar_struct += v * ratio; formwork_struct += fw
        if k == "wall" and e.get("material") != "concrete":
            if pr.get("internal"):
                wall_int_gross += q.get("face_area_m2", 0.0)
            else:
                wall_gross += q.get("face_area_m2", 0.0)
        if k == "window":
            glazing += q.get("area_m2", 0.0)
            ext_open_area += q.get("area_m2", 0.0)
            typ = pr.get("opening", "window")
            n_windows += typ == "window"
            n_balcony += typ == "balcony_door"
            n_entrance += typ == "entrance"
            if pr.get("w_m") and pr.get("h_m"):
                reveal_plaster += (2 * pr["h_m"] + 2 * pr["w_m"]) * 0.20
        if k == "door":
            typ = pr.get("opening", "interior_door")
            if typ == "garage_door":
                n_garage += 1
                garage_area += q.get("area_m2", 0.0)
                ext_open_area += q.get("area_m2", 0.0)
            elif typ == "apartment_entrance":
                n_apt_doors += 1
            else:
                n_int_doors += 1
        if k == "railing":
            railing_len += q.get("length_m", 0.0)
        if k == "pergola":
            pergola_area += q.get("plan_area_m2", 0.0)
        if k == "roof":
            roof_plan += q.get("plan_area_m2", 0.0)
        if k == "slab":
            slab_plan_total += q.get("plan_area_m2", 0.0)

    # openings are subtracted from the gross external wall area (unless the model walls are already cut around the openings)
    walls_cut = bool(meta.get("walls_net_of_openings"))
    wall_net_masonry = wall_gross if walls_cut else max(wall_gross - ext_open_area, 0.0)
    terrace_area = sum((project.get("geometry3d", {}).get("terraces") or {}).values())
    gfa = float(meta.get("gfa_m2") or 0.0) or slab_plan_total
    cond = float(meta.get("conditioned_area_m2") or 0.0) or 0.6 * gfa
    apartments = float(meta.get("apartments", 1))
    plot = float(meta.get("plot_area_m2") or 0.0)
    # coverage (κάλυψη): declared by the permit (ground floor + semi-open spaces) or taken from the model
    coverage = float(meta.get("coverage_m2") or 0.0) or _footprint_of_lowest(els)
    site_area = max(plot - coverage, 0.0)
    planting = float(meta.get("planting_m2") or 0.0) or site_area * a["planting_share_of_site"]
    paving = max(site_area - planting, 0.0) if meta.get("planting_m2") else site_area * a["paving_share_of_site"]
    rafts = [e["qty"].get("plan_area_m2", 0.0) for e in els if e["kind"] == "footing" and e.get("props", {}).get("raft")]
    basement_plan = sum(rafts) if rafts else max((e["qty"].get("plan_area_m2", 0.0) for e in els if e["kind"] == "footing"), default=0.0)
    basement_depth = _basement_depth(project)
    exc_info = meta.get("excavation") or {}
    exc_area = float(exc_info.get("area_m2") or 0.0)
    depth_total = float(exc_info.get("depth_m") or 0.0) or (basement_depth + a["excavation_extra_depth_m"])
    if exc_area > 0:                                       # outline of the excavation diagram x depth below the natural ground
        exc = exc_area * depth_total
        backfill = max(exc - basement_plan * depth_total, 0.0)      # working space around the basement walls
    else:                                                  # no diagram: basement plan + working space all round
        exc = (basement_plan + 2 * a["excavation_margin_m"] * (basement_plan ** 0.5) * 2) * depth_total
        backfill = max(exc - basement_plan * depth_total, 0.0)
    haul = max(exc - backfill, 0.0) * a["excavation_swell"]
    retaining = sum(e["qty"].get("face_area_m2", 0.0) for e in els if e["kind"] == "wall" and e.get("props", {}).get("retaining"))
    waterproof_basement = retaining + basement_plan * a["waterproof_raft_share"]
    fence_len = sum(e["qty"].get("length_m", 0.0) for e in els if e["kind"] == "fence")
    basement_finished = float(meta.get("basement_finished_m2") or 0.0)
    common = float(meta.get("common_area_m2") or 0.0)
    finished = cond + basement_finished + common            # areas that receive plaster, paint and floor finishes
    g3 = project.get("geometry3d", {}) or {}
    terr_up = sum(v for k, v in (g3.get("terraces") or {}).items() if k != "ground")          # balconies + roof terraces (not the yard slab)
    tiled = sum((g3.get("balconies") or {}).values()) + sum((g3.get("semi_open") or {}).values())
    terrace_finish = tiled + 0.25 * max(terr_up - tiled, 0.0) if tiled else 0.25 * terr_up     # roof terraces are partly planted / gravel
    basement_floor = max(basement_plan - basement_finished, 0.0)

    internal_masonry = wall_int_gross if wall_int_gross > 0 else a["internal_wall_m2_per_m2"] * (cond + basement_finished)     # plan partitions or ratio
    plaster = 2 * internal_masonry + wall_net_masonry + finished * 1.0 + max(gfa - finished - basement_floor, 0.0) * 0.4 + reveal_plaster
    paint = plaster * a["ceiling_paint_factor"]
    floor_finish = finished + terrace_finish

    q = {
        "excavation_m3": exc, "backfill_m3": backfill,
        "concrete_foundation_m3": conc_found, "formwork_foundation_m2": formwork_found, "rebar_foundation_kg": rebar_found,
        "concrete_structure_m3": conc_struct, "formwork_structure_m2": formwork_struct, "rebar_structure_kg": rebar_struct,
        "masonry_external_m2": wall_net_masonry, "masonry_internal_m2": internal_masonry,
        "insulation_wall_m2": wall_net_masonry + 0.9 * (_column_beam_face(els)),
        "plaster_m2": plaster, "paint_m2": paint, "floor_finish_m2": floor_finish,
        "window_area_m2": glazing, "apartments": apartments,
        "interior_doors": float(n_int_doors) if n_int_doors else a["doors_per_apartment"] * apartments,
        "security_doors": float(n_apt_doors) if n_apt_doors else apartments,
        "garage_door_area_m2": garage_area, "reveal_plaster_m2": reveal_plaster,
        "window_count": float(n_windows), "balcony_door_count": float(n_balcony), "entrance_glazing_count": float(n_entrance), "garage_door_count": float(n_garage),
        "lintel_count": float(lintel_n), "lintel_length_m": lintel_len, "lintel_concrete_m3": lintel_vol, "lintel_formwork_m2": lintel_fw, "lintel_rebar_kg": lintel_rebar,
        "masonry_internal_gross_m2": wall_int_gross,
        "railing_length_m": railing_len, "pergola_area_m2": pergola_area,
        "roof_area_m2": roof_plan + terrace_area, "gfa_m2": gfa, "conditioned_area_m2": cond, "common_areas_m2": max(gfa - cond, 0.0),
        "excavation_haul_m3": haul, "waterproof_basement_m2": waterproof_basement, "basement_floor_m2": basement_floor, "fence_length_m": fence_len,
        "excavation_area_m2": exc_area, "excavation_depth_m": depth_total, "coverage_m2": coverage, "planting_area_m2": planting,
        "elevators": a["elevators"], "site_area_m2": site_area,
        "paving_m2": paving, "planting_m2": planting,
    }
    for k_ in LANDSCAPE_KEYS:                               # surroundings and facade extras (0 when the model has none)
        q[k_] = land.get(k_, 0.0)
    q = {k: round(float(v), 3) for k, v in q.items()}
    concrete_total = conc_found + conc_struct
    return {
        "quantities": q,
        "assumptions": a,
        "by_kind": {k: {"count": cnt[k], "volume_m3": round(vol[k], 3)} for k in cnt},
        "by_storey": {sid: {k: round(v, 3) for k, v in d.items()} for sid, d in by_storey.items()},
        "totals": {"concrete_m3": round(concrete_total, 2), "rebar_kg": round(rebar_found + rebar_struct, 0),
                   "rebar_kg_per_m3": round((rebar_found + rebar_struct) / max(concrete_total, 1e-6), 1),
                   "concrete_m3_per_m2_gfa": round(concrete_total / max(gfa, 1e-6), 3),
                   "terrace_area_m2": round(terrace_area, 1), "wall_gross_m2": round(wall_gross, 1), "glazing_m2": round(glazing, 1),
                   "glazing_ratio": round(glazing / max(wall_gross, 1e-6), 3)},
    }


def _footprint_of_lowest(els) -> float:
    ground = [e for e in els if e["kind"] == "slab" and e["storey"]]
    if not ground:
        return 0.0
    # footprint of the building above the basement ~ plan area of the slab under the first floor above ground
    by_s: dict[str, float] = defaultdict(float)
    for e in ground:
        by_s[e["storey"]] += e["qty"].get("plan_area_m2", 0.0)
    keys = sorted(by_s)
    return by_s[keys[1]] if len(keys) > 1 else by_s[keys[0]]


def _basement_depth(project: dict) -> float:
    st = project["storeys"]
    below = [s for s in st if s["elevation_m"] < -0.5]
    return float(sum(s["height_m"] for s in below)) if below else 0.0


def _column_beam_face(els) -> float:
    """Exposed concrete frame faces that also receive insulation (approximation: 18% of perimeter columns/beams surface)."""
    s = 0.0
    for e in els:
        if e["kind"] in ("column", "beam"):
            s += e["qty"].get("surface_m2", 0.0) * 0.06
    return s


STEEL = 7850.0          # kg/m3


def _bars(txt: str) -> list[tuple[int, int]]:
    import re
    return [(int(n), int(d)) for n, d in re.findall(r"(\d+)Φ(\d+)", txt or "")]


def rebar_from_drawings(e: dict) -> float | None:
    """Steel [kg] of a column / beam from the bars written on the formwork drawings (props rebar / stirrups):
    longitudinal bars over the element length (+10 % laps and anchorages) and stirrups along it (cover 3 cm, hooks +10 %)."""
    import math
    import re
    pr = e.get("props") or {}
    q = e.get("qty") or {}
    if not pr.get("rebar") or e["kind"] not in ("column", "beam", "footing"):
        return None
    area = lambda bars: sum(n * math.pi * (d / 1000) ** 2 / 4 for n, d in bars)
    m = re.search(r"Φ(\d+)/(\d+)", pr.get("stirrups") or "")
    legs = 2.0
    mm = re.search(r"Σ\s*(\d+)Φ", pr.get("stirrups") or "")
    if mm:
        legs = 2.0 * int(mm.group(1))                     # e.g. «Σ 2Φ10/12» = two closed stirrups (4 legs)
    if e["kind"] == "column":
        L = q.get("height_m", 0.0)
        As = area(_bars(pr["rebar"]))
        long_kg = As * L * 1.10 * STEEL
        per = (pr.get("perimeter_m") or 2 * (q.get("width_m", 0) + q.get("depth_m", 0))) - 8 * 0.03
        st_kg = 0.0
        if m:
            d, s_ = int(m.group(1)), int(m.group(2)) / 100
            st_kg = per * 1.10 * (L / s_) * math.pi * (d / 1000) ** 2 / 4 * STEEL * 1.25      # +25 % internal ties of long sections
        return long_kg + st_kg
    bb = e.get("bbox") or [0] * 6
    dx, dy, dz = bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]
    L = q.get("length_m") or max(dx, dy)
    bars = _bars(pr["rebar"])
    As = area(bars)
    long_kg = As * (L + 0.8) * 1.10 * STEEL
    b, h = (q.get("width_m") or min(dx, dy) or 0.25), (q.get("depth_m") or dz or 0.5)
    st_kg = 0.0
    if m:
        d, s_ = int(m.group(1)), int(m.group(2)) / 100
        st_kg = (2 * (b + h) - 8 * 0.03) * 1.10 * (L / s_) * (legs / 2) * math.pi * (d / 1000) ** 2 / 4 * STEEL
    return long_kg + st_kg
