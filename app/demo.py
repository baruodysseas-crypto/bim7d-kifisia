"""Demo project: residential building with basement, Potamou 4, Nea Kifisia (building permit 833237, 18/10/2023).

The 3D massing is *synthetic* but built on the real permit data: the footprints are taken from the survey/coverage diagram
(coordinate tables of the basement and ground floor, ΕΓΣΑ87, rotated into a local frame), the floor outlines from the area
calculation sheet (Δ.01), the levels from sections A-A'/B-B', the excavation outline from diagram A.14 and the 49 windows from
the energy study. The openings (windows, balcony doors, doors), the interior partitions and the door positions are read from the floor
plans of the permit drawings (data/openings.json, see tools/extract_openings.py). Column positions and member sections are generated,
so replace the demo by uploading the real 3D export (GLB/OBJ/IFC) of the project when you have it.

Local frame: x along the street front (left to right), y towards the back of the plot, origin at the front-left corner of the
basement. z = 0.00 is the ground floor level (+1.00 on the drawings; natural ground = ground floor level)."""
from __future__ import annotations

import json
import re
import math
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from shapely.geometry import MultiPolygon, Point, Polygon, box as sbox
from shapely.ops import unary_union

from . import fm, ingest, structural

DATA = Path(__file__).parent / "data"
DEMO_REV = 26

# levels relative to the ground floor top (drawings: -2.00 / +1.00 / +4.05 / +7.10 / +10.30 / ridge +13.50)
LEVELS = {"basement": -3.00, "ground": 0.0, "first": 3.05, "second": 6.10, "attic": 9.30, "roof": 12.50}
KNEE = 1.45                       # attic knee wall height (volume calculation of the permit: 1.45 + gable)
OPENINGS = json.loads((DATA / "openings.json").read_text(encoding="utf-8"))
LINTEL_B = 0.20                   # lintel (πρέκι) width = inner masonry leaf; the outer 0.10 m of the wall is the insulation
LINTEL_H = 0.20                   # lintel depth over exterior openings
LINTEL_H_INT = 0.15               # lintel depth over interior doors
LINTEL_BEARING = 0.20             # bearing length on each side of the opening
DOOR_H = 2.10                     # interior / security door height
SLAB_T = 0.20
RAFT_T = 0.25
BLINDING_T = 0.10
PLOT_AREA = 1023.47
W = 18.30                         # width of the building (front line of the basement)


def _mirror(r):
    x0, y0, x1, y1 = r
    return (round(W - x1, 4), y0, round(W - x0, 4), y1)


def _sym(rects):
    return list(rects) + [_mirror(r) for r in rects]


# enclosed floor outlines (rectangles x0,y0,x1,y1). Two mirrored wings (5.75 m + 1.50 m strip) joined by the central core.
G = {
    "basement": _sym([(0, 0, 1.5, 15.55), (1.5, 0, 7.25, 20.35)]) + [(7.25, 0, 11.05, 16.65)],            # 343.9 m2 (330.27 + 13.68)
    "ground": _sym([(0, 5.25, 1.5, 15.55), (1.5, 5.25, 7.25, 20.35)]) + [(7.25, 6.85, 11.05, 16.65)],     # 241.79 m2
    "first": _sym([(0, 6.90, 1.5, 13.10), (1.5, 6.90, 7.25, 17.70)]) + [(7.25, 6.90, 11.05, 13.35)],      # 167.31 m2
    "second": _sym([(0, 5.25, 1.5, 13.10), (1.5, 5.25, 7.25, 17.70)]) + [(7.25, 5.25, 11.05, 10.35)],     # 186.11 m2
    "attic": [(0, 5.25, 7.25, 13.10), (11.05, 5.25, 18.30, 13.10)],                                      # 2 x 56.9 m2 (81.23 m2 with height >= 1.80 m)
}
# semi-open spaces (ημιυπαίθριοι) and balconies (εξώστες) of the area calculation
SEMI_OPEN = {"ground": [(7.35, 5.25, 10.95, 6.85)], "first": _sym([(0.5, 5.25, 7.25, 6.90)]), "second": [(7.35, 10.35, 10.95, 11.70)]}
BALCONY_TARGET = {"first": 58.92, "second": 96.06}


def _balconies() -> dict[str, list[tuple]]:
    side = _sym([(-1.1, 5.25, 0.0, 13.10)])
    first_other = side + _sym([(-1.1, 13.10, 1.5, 15.80)])
    d1 = (BALCONY_TARGET["first"] - sum((r[2] - r[0]) * (r[3] - r[1]) for r in first_other)) / (W + 2.2)
    second_other = side + _sym([(0.0, 17.70, 7.25, 20.35)])
    d2 = (BALCONY_TARGET["second"] - sum((r[2] - r[0]) * (r[3] - r[1]) for r in second_other)) / (W + 2.2)
    return {"first": first_other + [(-1.1, round(5.25 - d1, 3), W + 1.1, 5.25)],
            "second": second_other + [(-1.1, round(5.25 - d2, 3), W + 1.1, 5.25)]}


BALCONY = _balconies()
STOREY_ORDER = ["basement", "ground", "first", "second", "attic"]
MEMBER_SHEET = {"basement": "basement_roof", "ground": "ground_roof", "first": "first_floor", "second": "second_floor", "attic": "attic"}

# excavation outline of diagram A.14 (432.58 m2, perimeter 92.69 m), local frame (about 1 m working space around the basement)
EXC_OUTLINE = [(-1.0, -1.0), (19.3, -1.0), (19.3, 16.57), (17.8, 16.57), (17.8, 21.36), (10.05, 21.36), (10.05, 17.65), (8.25, 17.65),
               (8.25, 21.36), (0.5, 21.36), (0.5, 16.55), (-1.0, 16.55)]
EXC_AREA = 432.58
EXC_PERIMETER = 92.69
# plot (A,B,Γ,Δ) in the local frame; the street (Ποταμού) is the A-Δ side at y = -6.99
PLOT = [(-3.16, -6.99), (-3.14, 34.11), (23.25, 30.08), (22.78, -6.99)]

APARTMENTS = [
    {"id": "D1", "storey": "ground", "area_m2": 109.78, "permille": 154, "name_el": "Διαμέρισμα Δ1", "name_en": "Apartment D1"},
    {"id": "D2", "storey": "ground", "area_m2": 109.78, "permille": 154, "name_el": "Διαμέρισμα Δ2", "name_en": "Apartment D2"},
    {"id": "D3", "storey": "first", "area_m2": 149.45, "permille": 197, "name_el": "Διαμέρισμα Δ3", "name_en": "Apartment D3"},
    {"id": "D4", "storey": "second", "area_m2": 124.75, "permille": 198, "name_el": "Διαμέρισμα Δ4 (με σοφίτα)", "name_en": "Apartment D4 (with attic)"},
    {"id": "D5", "storey": "second", "area_m2": 124.75, "permille": 198, "name_el": "Διαμέρισμα Δ5 (με σοφίτα)", "name_en": "Apartment D5 (with attic)"},
]
# areas by use (fire-protection study, May 2023) - used by the fire module
AREAS = {"parking_m2": 184.08, "storage_m2": 96.11, "basement_flat_m2": 64.07, "ground_m2": 241.79, "first_m2": 167.31,
         "second_m2": 185.93, "attic_m2": 133.20, "gfa_total_m2": 1072.49, "height_m": 12.50, "population": 43}
# data of the coverage/area calculation sheet Δ.01 (permit drawings)
PERMIT = {
    "limits": {"coverage_pct": 40.0, "far": 0.50, "far_bonus_pct": 5.0, "volume_factor": 5.0, "height_m": 10.50, "roof_extra_m": 2.00,
               "side_setback_m": 3.025, "green_share_of_uncovered": 2 / 3, "semi_open_pct": 20.0, "balconies_pct": 40.0},
    "declared": {"coverage_m2": 247.55, "far_area_m2": 537.26, "volume_m3": 2207.33, "height_m": 12.30, "side_setback_m": 3.15,
                 "planting_m2": 530.61, "parking_spaces": 6, "semi_open_m2": 32.90, "balconies_m2": 154.98, "basement_excluded_m2": 330.27,
                 "floors_far_m2": {"ground": 219.56, "first": 149.45, "second": 168.25}, "stairwell_m2": {"ground": 22.23, "first": 17.86, "second": 17.86},
                 "attic_m2": 81.23, "volumes_m3": {"ground": 755.028, "first": 578.25, "second": 606.57, "attic": 267.48},
                 # areas of every level as listed on sheet Δ.01 (basement = 330.27 + 13.68 stairwell; attic = area outside the building factor)
                 "areas_m2": {"basement": 343.95, "ground": 241.79, "first": 167.31, "second": 186.11, "attic": 81.23},
                 "basement_stairwell_m2": 13.68, "floors_nok": 3, "mandatory_split_coverage_m2": 350.0,
                 "trees": {"front_required": 7, "front_provided": 14, "total_required": 5, "total_provided": 9}},
}


def _poly(rects):
    return unary_union([sbox(*r) for r in rects])


def _box_mesh(x0, y0, z0, x1, y1, z1) -> trimesh.Trimesh:
    m = trimesh.creation.box(extents=(abs(x1 - x0), abs(y1 - y0), abs(z1 - z0)))
    m.apply_translation(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    return m


def _rects_of(poly) -> list[tuple[float, float, float, float]]:
    """Decompose a rectilinear polygon into few axis-aligned rectangles (no triangulation library needed)."""
    out: list[tuple[float, float, float, float]] = []
    for g in (poly.geoms if isinstance(poly, MultiPolygon) else [poly]):
        if g.is_empty:
            continue
        xs = sorted({round(c[0], 4) for r in [g.exterior, *g.interiors] for c in r.coords})
        ys = sorted({round(c[1], 4) for r in [g.exterior, *g.interiors] for c in r.coords})
        strips = []
        for j in range(len(ys) - 1):
            run = None
            for i in range(len(xs) - 1):
                inside = g.contains(Point((xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2))
                if inside and run is None:
                    run = [xs[i], xs[i + 1]]
                elif inside:
                    run[1] = xs[i + 1]
                elif run is not None:
                    strips.append((run[0], ys[j], run[1], ys[j + 1])); run = None
            if run is not None:
                strips.append((run[0], ys[j], run[1], ys[j + 1]))
        strips.sort(key=lambda r: (r[0], r[2], r[1]))
        merged: list[tuple[float, float, float, float]] = []
        for r in strips:
            if merged and merged[-1][0] == r[0] and merged[-1][2] == r[2] and abs(merged[-1][3] - r[1]) < 1e-6:
                merged[-1] = (r[0], merged[-1][1], r[2], r[3])
            else:
                merged.append(r)
        out += merged
    return out


def _slab_mesh(poly, z0, z1) -> trimesh.Trimesh:
    """One mesh (union of boxes) for a rectilinear slab polygon."""
    return trimesh.util.concatenate([_box_mesh(r[0], r[1], z0, r[2], r[3], z1) for r in _rects_of(poly)])


def _prism(section: list[tuple[float, float]], y0: float, y1: float) -> trimesh.Trimesh:
    """Prism with a convex section given in (x, z), extruded along y from y0 to y1."""
    n = len(section)
    v = [(x, y0, z) for x, z in section] + [(x, y1, z) for x, z in section]
    f = []
    for i in range(1, n - 1):
        f += [(0, i + 1, i), (n, n + i, n + i + 1)]
    for i in range(n):
        j = (i + 1) % n
        f += [(i, j, n + j), (i, n + j, n + i)]
    m = trimesh.Trimesh(vertices=np.array(v, float), faces=np.array(f), process=True)
    m.fix_normals()
    return m


def _stair_prism(section: list[tuple[float, float]], x0: float, x1: float) -> trimesh.Trimesh:
    """Prism with a convex section in (y, z), extruded along x from x0 to x1."""
    m = _prism([(y, z) for y, z in section], x0, x1)          # axes: (y,z) -> (x,z), along y -> x ; remap below
    v = m.vertices.copy()
    v = v[:, [1, 0, 2]]                                       # (x'=along, y'=section x, z) -> (x=along, y=section, z)
    out = trimesh.Trimesh(vertices=v, faces=m.faces, process=True)
    out.fix_normals()
    return out


def _fps(points: np.ndarray, n: int) -> np.ndarray:
    """Farthest-point sampling (deterministic)."""
    if n >= len(points):
        return points
    sel = [int(np.argmin(points[:, 0] + points[:, 1] * 0.001))]
    d = np.linalg.norm(points - points[sel[0]], axis=1)
    for _ in range(n - 1):
        i = int(np.argmax(d))
        sel.append(i)
        d = np.minimum(d, np.linalg.norm(points - points[i], axis=1))
    return points[sel]


def _poly_segments(poly) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    segs = []
    geoms = poly.geoms if isinstance(poly, MultiPolygon) else [poly]
    for g in geoms:
        rings = [g.exterior] + list(g.interiors)
        for r in rings:
            c = list(r.coords)
            for a, b in zip(c[:-1], c[1:]):
                if math.dist(a, b) > 0.05:
                    segs.append((a, b))
    return segs


def _wall_segments(poly) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Footprint segments with consecutive collinear edges merged (one wall run per straight facade)."""
    segs = []
    for g in (poly.geoms if isinstance(poly, MultiPolygon) else [poly]):
        for r in [g.exterior] + list(g.interiors):
            c = [tuple(q) for q in list(r.coords)[:-1]]
            n = len(c)
            keep = [i for i in range(n) if abs((c[i][0] - c[i - 1][0]) * (c[(i + 1) % n][1] - c[i][1]) - (c[i][1] - c[i - 1][1]) * (c[(i + 1) % n][0] - c[i][0])) > 1e-6]
            pts = [c[i] for i in keep]
            for a, b in zip(pts, pts[1:] + pts[:1]):
                if math.dist(a, b) > 0.05:
                    segs.append((a, b))
    return segs


def _convex_plate(pts: list[tuple[float, float]], z0: float, z1: float) -> trimesh.Trimesh:
    """Thin plate with a convex polygon outline (site ground)."""
    n = len(pts)
    v = [(x, y, z0) for x, y in pts] + [(x, y, z1) for x, y in pts]
    f = []
    for i in range(1, n - 1):
        f += [(0, i + 1, i), (n, n + i, n + i + 1)]
    for i in range(n):
        j = (i + 1) % n
        f += [(i, j, n + j), (i, n + j, n + i)]
    m = trimesh.Trimesh(vertices=np.array(v, float), faces=np.array(f), process=True)
    m.fix_normals()
    return m


def _oriented_box(p, q, z0, h, t) -> trimesh.Trimesh:
    ln = math.dist(p, q)
    m = trimesh.creation.box(extents=(ln, t, h))
    ang = math.atan2(q[1] - p[1], q[0] - p[0])
    m.apply_transform(trimesh.transformations.rotation_matrix(ang, [0, 0, 1]))
    m.apply_translation(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, z0 + h / 2))
    return m



T_ROOF = 0.20
EAVES, VERGE = 0.40, 0.20          # roof overhangs drawn in the 3D model (eaves / verge)


def _roof_geometry() -> tuple[float, float, float]:
    """(eaves level, ridge level, vertical panel thickness) of the attic roof."""
    z_e, z_r = LEVELS["attic"] + KNEE, LEVELS["roof"]
    half = (G["attic"][0][2] - G["attic"][0][0]) / 2
    slope = math.hypot(half, z_r - z_e)
    return z_e, z_r, T_ROOF / (half / slope)


def _roof_under(x: float, y: float) -> float:
    """Level of the underside of the pitched roof above the point (x, y) (eaves level outside the attic boxes)."""
    z_e, z_r, tv = _roof_geometry()
    for (x0, y0, x1, y1) in G["attic"]:
        if x0 - 1e-6 <= x <= x1 + 1e-6 and y0 - 1e-6 <= y <= y1 + 1e-6:
            xm, half = (x0 + x1) / 2, (x1 - x0) / 2
            return z_e - tv + (z_r - z_e) * (1 - abs(x - xm) / half)
    return z_e - tv


def build_parts(members: dict, windows: list[dict]) -> tuple[list[dict], dict]:
    """Parts list of the demo building. Names/layers carry the element kind for the classifier."""
    parts: list[dict] = []
    L = LEVELS
    foot = {st: _poly(G[st]) for st in STOREY_ORDER}
    semi = {st: _poly(r) for st, r in SEMI_OPEN.items()}
    balc = {st: _poly(r) for st, r in BALCONY.items()}
    meta: dict[str, Any] = {"terraces": {}, "wall_lengths": {}, "footprints": {st: round(foot[st].area, 2) for st in STOREY_ORDER},
                            "semi_open": {st: round(sum((r[2] - r[0]) * (r[3] - r[1]) for r in rs), 2) for st, rs in SEMI_OPEN.items()},
                            "balconies": {st: round(sum((r[2] - r[0]) * (r[3] - r[1]) for r in rs), 2) for st, rs in BALCONY.items()}}

    def add(name, layer, mesh, **props):
        parts.append({"name": name, "layer": layer, "mesh": mesh, "props": props})

    # --- site: real plot outline, street fence along the A-D side, excavation outline (visible with the section slider)
    add("Site ground", "site", site_plate() if not (DATA / "real3d.npz").exists() else _real_site_plate(), qty_override={"plan_area_m2": PLOT_AREA})
    add("Excavation outline", "excavation", _slab_mesh(Polygon(EXC_OUTLINE), L["basement"] - RAFT_T - BLINDING_T, L["basement"] - RAFT_T - BLINDING_T + 0.03),
        qty_override={"plan_area_m2": EXC_AREA, "perimeter_m": EXC_PERIMETER})

    # --- raft foundation (one element) + foundation beams
    raft = foot["basement"]
    add("Raft foundation", "foundation", _slab_mesh(raft, L["basement"] - RAFT_T, L["basement"]), raft=True,
        qty_override={"perimeter_m": round(raft.length, 3)})
    FR = _frame()
    if FR:
        seen_fb: set[tuple] = set()
        for bm in FR["levels"]["foundation"]["beams"]:
            key = (tuple(round(v, 2) for v in bm["a"]), tuple(round(v, 2) for v in bm["b"]), bm["b_cm"], bm["h_cm"])
            if key in seen_fb:
                continue
            seen_fb.add(key)
            add(f"Foundation beam {bm['id']}", "foundation", _beam_mesh(bm["a"], bm["b"], L["basement"] - bm["h_cm"] / 100, bm["b_cm"] / 100, bm["h_cm"] / 100 - RAFT_T,
                                                                        top=L["basement"] - RAFT_T), source="Σ.01", rebar=",".join(x for x in (bm.get("bars"), bm.get("side")) if x), stirrups=bm.get("stirrups"))
    else:
        cols_b = _column_positions("basement", members)
        for i, bm in enumerate(members["foundation"]["beams"]):
            a, b = _beam_pair(i, cols_b)
            if a is None:
                continue
            add(f"Foundation beam {bm['id']}", "foundation", _beam_mesh(a, b, L["basement"] - bm["h_cm"] / 100, bm["b_cm"] / 100, bm["h_cm"] / 100 - RAFT_T, top=L["basement"] - RAFT_T))

    for si, st in enumerate(STOREY_ORDER):
        z_floor = L[st]
        z_next = L[STOREY_ORDER[si + 1]] if si + 1 < len(STOREY_ORDER) else L["roof"]
        st_poly = foot[st]
        prev = foot[STOREY_ORDER[si - 1]] if si > 0 else None
        # floor slab of the storey: covers the storey below, the storey itself, its semi-open spaces and its balconies (cantilevers)
        if prev is not None:
            prev_st = STOREY_ORDER[si - 1]
            parts_poly = [prev, st_poly] + [semi[k] for k in (prev_st, st) if k in semi] + ([balc[st]] if st in balc else [])
            slab = unary_union(parts_poly)
            holes = [sbox(*r) for r in STAIR_HOLE + [LIFT_SHAFT]] + ([sbox(*r) for r in _private_stair_holes()] if st == "ground" else [])
            slab_cut = slab.difference(unary_union(holes))
            add(f"Floor slab {st}", f"slab_{st}", _slab_mesh(slab_cut, z_floor - SLAB_T, z_floor), qty_override={"perimeter_m": round(slab.length, 3)})
        # columns
        h_col = z_next - z_floor - SLAB_T
        if FR:
            # real skeleton of the formwork drawings: column/wall outlines and beams in their places, with their reinforcement
            lvl = FR["levels"][st]
            for c in lvl["columns"]:
                P = _clean_poly(c["poly"])
                cx, cy = P.centroid.x, P.centroid.y
                h_c = max(_roof_under(cx, cy) - z_floor, 0.6) if st == "attic" else h_col
                qm = _slab_mesh(P, z_floor, z_floor + h_c)                       # measured member: clear height (floor to soffit)
                # drawn member: continuous through the slab below (the column passes the joint) and, in the attic, up into the pitched roof,
                # so the load path column → slab/beam → column → foundation is visible and no member floats
                z_bot = z_floor - SLAB_T if st != "basement" else z_floor
                z_top = z_floor + h_c
                if st == "attic":
                    _, _, tv = _roof_geometry()
                    inside = any(x0 - 1e-6 <= cx <= x1 + 1e-6 and y0 - 1e-6 <= cy <= y1 + 1e-6 for (x0, y0, x1, y1) in G["attic"])
                    z_top = max(_roof_under(x, y) for x, y in P.exterior.coords) + (tv * 0.5 if inside else 0.0)
                add(f"Column {c['id']} {st}", f"column_{st}", _slab_mesh(P, z_bot, z_top), section_area_m2=round(P.area, 4),
                    section=c.get("section"), rebar=c.get("long"), stirrups=f"Φ{c.get('stirrup_d')}/{c.get('stirrup_s_cm')}", source=lvl["sheet"],
                    perimeter_m=round(P.length, 3), qty_override={"volume_m3": round(float(qm.volume), 4), "surface_m2": round(float(qm.area), 3), "height_m": round(h_c, 4)})
                if st == "basement" and not raft.buffer(0.05).contains(Point(cx, cy)):
                    # columns of the cours anglaises (light wells, A.01): they rise to the garden and stand on the raft extension below the well
                    parts[-1]["mesh"] = _slab_mesh(P, z_floor, CA_TOP)
            for bm in lvl["beams"]:
                a, b = bm["a"], bm["b"]
                z_top = min(_roof_under(*a), _roof_under(*b)) if st == "attic" else z_floor + h_col
                add(f"Beam {bm['id']} {st}", f"beam_{st}", _beam_mesh(a, b, z_top, bm["b_cm"] / 100, bm["h_cm"] / 100 - SLAB_T, top=z_top, drop=True),
                    rebar=",".join(x for x in (bm.get("bars"), bm.get("side")) if x), stirrups=bm.get("stirrups"), source=lvl["sheet"])
            cols = []
            mem = {"columns": [], "beams": []}
        else:
            cols = _column_positions(st, members)
            mem = members[MEMBER_SHEET[st]]
        for (x, y), c in zip(cols, mem["columns"]):
            w, d, t = c["w_cm"] / 100, c["d_cm"] / 100, c["t_cm"]
            h_c = max(_roof_under(x, y) - z_floor, 0.6) if st == "attic" else h_col          # attic columns stop under the pitched roof
            add(f"Column {c['id']} {st}", f"column_{st}", _box_mesh(x - w / 2, y - d / 2, z_floor, x + w / 2, y + d / 2, z_floor + h_c),
                section_area_m2=(w * d if not t else (w + d - t / 100) * t / 100))
        # beams under the next slab
        for i, bm in enumerate(mem["beams"]):
            a, b = _beam_pair(i, cols)
            if a is None:
                continue
            z_top = min(_roof_under(*a), _roof_under(*b)) if st == "attic" else z_floor + h_col
            add(f"Beam {bm['id']} {st}", f"beam_{st}", _beam_mesh(a, b, z_top, bm["b_cm"] / 100, bm["h_cm"] / 100 - SLAB_T, top=z_top, drop=True))
        # external walls (masonry + 10 cm insulation) or retaining walls in the basement; the openings of the plans are cut into them
        # basement: reinforced-concrete walls (τοιχεία) 25 cm up to the slab; upper floors: brick infill up to the beams
        wall_h = (KNEE if st == "attic" else (z_next - z_floor - SLAB_T if st == "basement" else z_next - z_floor - SLAB_T - 0.15))
        wall_t = 0.25 if st == "basement" else 0.30
        total_len = 0.0
        ext_ops = [o for o in OPENINGS["ext"] if o["storey"] == st]
        placed: set[int] = set()
        for (a, b) in _wall_segments(st_poly):
            total_len += math.dist(a, b)
            nm = "Retaining wall" if st == "basement" else "External wall"
            gable = st == "attic" and abs(b[0] - a[0]) > abs(b[1] - a[1])          # attic walls along x carry the gable
            asm = _wall_assembly(a, b, st_poly, z_floor, wall_h, wall_t, ext_ops, placed, _gable_top if gable else None)
            add(f"{nm} {st}", f"{'retwall' if st == 'basement' else 'wall'}_{st}", asm["wall"])
            for (m, nme, lay, props) in asm["lintels"] + asm["glazing"]:
                add(nme, lay.replace("@", st), m, **props)
        skipped = [i for i, o in enumerate(OPENINGS["ext"]) if o["storey"] == st and i not in placed and o in ext_ops]
        meta.setdefault("openings_unplaced", []).extend(f"{st}:{OPENINGS['ext'][i]['type']}@{OPENINGS['ext'][i]['c']}" for i in skipped)
        if st == "basement" and FR:
            _cours_anglaises(add, FR, z_floor)
        # interior partitions and doors of the plan
        _interior(add, st, z_floor, z_next, meta)
        meta["wall_lengths"][st] = round(total_len, 2)
        # terraces: slab area outside the walls of the storey; glass balustrade on their free edges (not on the yard slab)
        if prev is not None:
            terrace = slab.difference(st_poly)
            meta["terraces"][st] = round(terrace.area, 2)
            if st != "ground" and terrace.area > 0.5:
                edge = terrace.boundary.intersection(slab.boundary)
                lines = [edge] if edge.geom_type == "LineString" else list(getattr(edge, "geoms", []))
                for ln in lines:
                    if ln.geom_type != "LineString":
                        continue
                    c = list(ln.coords)
                    for a, b in zip(c[:-1], c[1:]):
                        if math.dist(a, b) > 0.3:
                            add(f"Glass balustrade {st}", f"railing_{st}", _wall_mesh(a, b, slab, z_floor, 1.05, 0.04, outward=True))

    # --- attic: gable walls + two-pitch roof over each attic box (ridge +13.50 on the drawings)
    z_e, z_r, _ = _roof_geometry()
    t_roof = T_ROOF
    roof_area = 0.0
    for (x0, y0, x1, y1) in G["attic"]:
        xm = (x0 + x1) / 2
        half = (x1 - x0) / 2
        slope = math.hypot(half, z_r - z_e)
        cosf = half / slope
        tv = t_roof / cosf                                        # vertical thickness of a panel of thickness t_roof
        for sx0, sx1 in ((x0, xm), (xm, x1)):
            xo, xr = (sx0, sx1) if sx0 == x0 else (sx1, sx0)      # eaves side, ridge side
            sec = [(xo, z_e), (xr, z_r), (xr, z_r - tv), (xo, z_e - tv)]
            vol = float(_prism(sec, y0, y1).volume)
            # drawn with a 0.40 m eaves and 0.20 m verge overhang (as built): the roof edge then sits over the walls instead of sharing their faces
            sgn = -1.0 if xo < xr else 1.0
            k = (z_r - z_e) / abs(xr - xo)
            xo2 = xo + sgn * EAVES
            sec2 = [(xo2, z_e - k * EAVES), (xr, z_r), (xr, z_r - tv), (xo2, z_e - k * EAVES - tv)]
            add("Roof slab pitched", "roof", _prism(sec2, y0 - VERGE, y1 + VERGE), qty_override={"plan_area_m2": round(slope * (y1 - y0), 3), "thickness_m": t_roof,
                                                                              "perimeter_m": round(2 * (slope + (y1 - y0)), 3), "volume_m3": round(vol, 4)})
            roof_area += slope * (y1 - y0)
    meta["roof_slope_area_m2"] = round(roof_area, 2)

    # --- common stair of the core: U-shaped, 17 risers per floor (plans A.01/A.02); the lift shaft beside it
    for si, st in enumerate(STOREY_ORDER[:-1]):
        z0, z1 = L[st], L[STOREY_ORDER[si + 1]]
        fa, land, fb = _core_stair(z0, z1)
        add(f"Stair flight {st} A", f"stair_{st}", fa)
        add(f"Stair landing {st}", f"stair_{st}", land)
        add(f"Stair flight {st} B", f"stair_{st}", fb)
    x0, y0, x1, y1 = LIFT_SHAFT
    # the car rests at the main entrance level (ground floor); the shaft runs from the basement pit to the second floor
    add("Elevator car", "furniture_lift", _box_mesh(x0 + 0.10, y0 + 0.12, L["ground"] + 0.02, x1 - 0.10, y1 - 0.10, L["ground"] + 2.30),
        lift=True, color="#8e99a3")
    xm = (x0 + x1) / 2
    for st in STOREY_ORDER:
        z = L[st]
        if st == "attic" or z >= L["roof"]:
            continue
        add(f"Lift landing door {st}", "furniture_liftdoor", _box_mesh(xm - 0.45, y0 - 0.03, z, xm + 0.45, y0 + 0.03, z + 2.05), lift=True, color="#b7bfc6")
    # --- private stairs from the basement storerooms up to the ground-floor maisonettes Δ1 and Δ2 (A.01/A.02)
    for side, nm in ((1, "Δ1"), (-1, "Δ2")):
        add(f"Private stair {nm} basement–ground", "stair_basement", _private_stair(L["basement"], L["ground"], side))
    return parts, meta


# ---------------------------------------------------------------- core, lift, private stairs, cours anglaises (plans A.01/A.02, sheet Σ.02)
CORE_X = (7.30, 9.30)               # common stair: clear width between K14 and the lift wall (DXF, 2.15 m between axes)
CORE_Y = (9.78, 12.83)              # first riser … back wall of the core
FLIGHT_SPLIT = 8.32                 # axis of the 8 cm wall between the up-flight (west) and the return flight (east)
SPLIT_HALF = 0.04
TREAD = 0.28
LIFT_SHAFT = (9.65, 11.14, 11.06, 12.85)      # clear shaft inside the Π-shaped wall K15 (1.40 m wide), door on the stair side
STAIR_HOLE = [(7.30, 10.34, 9.30, 12.83), (7.30, 9.78, 8.32, 10.34)]   # slab opening over the stair (the arrival strip stays)
CA_TOP = 0.10                       # cours anglaises: walls and columns 10–15 cm above the garden (Rhino garden ≈ −0.05)


WAIST = 0.18                        # depth of the stair slab under the nosing line


def _tread_solid(pts, top, z0, h):
    """One step: prism with the tread outline, from its top down to the underside of the stair slab (never below the floor)."""
    return _convex_plate(pts, max(z0, top - h - WAIST), top)


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _core_stair_steps(z0: float, z1: float):
    """Common U-stair of the core (A.01/A.02): 8 steps up to the back wall, 2 at the back (half landing), 6 back towards the
    entrance and the arrival on the floor – 17 risers. Returns [(outline, top)] for flight A, the landing and flight B."""
    n = 17
    h = (z1 - z0) / n
    xa, xm, xb = CORE_X[0], FLIGHT_SPLIT, CORE_X[1]
    ya, yt = CORE_Y[0], CORE_Y[0] + 8 * TREAD
    xl, xr = xm - SPLIT_HALF, xm + SPLIT_HALF                       # faces of the wall between the two flights
    up = [(_rect(xa, ya + k * TREAD, xl, ya + (k + 1) * TREAD), z0 + (k + 1) * h) for k in range(8)]
    land = [(_rect(xa, yt, xm, CORE_Y[1]), z0 + 9 * h), (_rect(xm, yt, xb, CORE_Y[1]), z0 + 10 * h)]
    # return flight: 6 treads from the landing up to the ground-floor slab level (last tread flush with z1, never above it)
    z_land = z0 + 10 * h
    hd = (z1 - z_land) / 6
    down = [(_rect(xr, yt - (k + 1) * TREAD, xb, yt - k * TREAD), z_land + (k + 1) * hd) for k in range(6)]
    return up, land, down, h, hd


def _core_stair(z0: float, z1: float):
    up, land, down, h, hd = _core_stair_steps(z0, z1)
    mk = lambda st, r: trimesh.util.concatenate([_tread_solid(p, t, z0, r) for p, t in st])
    return mk(up, h), mk(land, h), mk(down, hd)


PRIV_UP_Y, PRIV_DN_Y = (15.40, 16.40), (14.39, 15.30)          # rows of the private stair (west copy; the east one is mirrored)
PRIV_PIVOT = (8.04, 15.35)                                      # centre of the winders
PRIV_X = [6.075, 6.35, 6.62, 6.89, 7.16, 7.43, 7.70, 7.97]      # nosings of steps 1–8 (A.01)
PRIV_XE = 9.05                                                  # outer side of the turn (0.20 m wall between Δ1 and Δ2)


def _private_stair_steps(z0: float, z1: float, side: int):
    """Stair Δ1 (side=1) / Δ2 (side=-1, mirrored), as drawn on A.01/A.02: steps 1–8 eastwards along the back of the boiler room,
    winders 9–12 turning round the pivot at the central wall, steps 13–16 westwards above the boiler room and the arrival
    (17) on the ground floor – 17 risers from the basement to the ground floor."""
    h = (z1 - z0) / 17
    (ua, ub), (da, db) = PRIV_UP_Y, PRIV_DN_Y
    px, py = PRIV_PIVOT
    xe = PRIV_XE
    steps = []
    xs = PRIV_X + [8.36]
    for k in range(8):                                             # 1–8 (step 8 widens to the start of the turn)
        x_in = min(xs[k + 1], px) if k == 7 else xs[k + 1]
        steps.append(([(xs[k], ua), (x_in, ua), (xs[k + 1], ub), (xs[k], ub)], k + 1))
    yb = (15.95, py, 14.80)
    steps += [([(px, py), (8.36, ub), (xe, ub), (xe, yb[0])], 9), ([(px, py), (xe, yb[0]), (xe, yb[1])], 10),
              ([(px, py), (xe, yb[1]), (xe, yb[2])], 11), ([(px, py), (xe, yb[2]), (xe, da), (8.44, da)], 12),
              ([(px, py), (8.44, da), (7.97, da), (7.97, db)], 13)]
    for k, (a, b) in enumerate([(7.70, 7.97), (7.43, 7.70), (7.16, 7.43)]):   # 14–16
        steps.append((_rect(a, da, b, db), 14 + k))
    X = (lambda x: x) if side == 1 else (lambda x: W - x)
    out = []
    for pts, k in steps:
        q = [(X(x), y) for x, y in pts]
        if side == -1:
            q = q[::-1]                                            # keep the outline counter-clockwise after mirroring
        out.append((q, z0 + k * h))
    return out, h


def _private_stair(z0, z1, side):
    st, h = _private_stair_steps(z0, z1, side)
    return trimesh.util.concatenate([_tread_solid(p, t, z0, h) for p, t in st])


def _private_stair_holes():
    out = []
    for side in (1, -1):
        # A.02: steps 1–4 run under the ground floor (the slab stays, wall at x = 7.0–7.1 on it); open over 5–8, the winders and 13–16;
        # the 10 cm wall between the two rows stands on the strip of slab left between them
        for (x0, y0, x1, y1) in [(7.10, PRIV_UP_Y[0], PRIV_XE, PRIV_UP_Y[1]), (PRIV_PIVOT[0], PRIV_DN_Y[0], PRIV_XE, PRIV_UP_Y[0]),
                                 (7.16, PRIV_DN_Y[0], PRIV_PIVOT[0], 15.30)]:
            p, q = (x0, x1) if side == 1 else (W - x1, W - x0)
            out.append((p, y0, q, y1))
    return out


def stair_undersides(st: str) -> list[tuple[float, float, float, float, float]]:
    """Plan boxes of the steps that pass over storey `st`, with the level of their underside (walls below stop there)."""
    L = LEVELS
    out = []
    i = STOREY_ORDER.index(st)
    if i + 1 < len(STOREY_ORDER):
        z0, z1 = L[st], L[STOREY_ORDER[i + 1]]
        up, land, down, h, hd = _core_stair_steps(z0, z1)
        sets = [(up + land, h), (down, hd)]
        if st == "basement":
            sets += [(_private_stair_steps(z0, z1, s)[0], h) for s in (1, -1)]
        for steps, r in sets:
            for pts, top in steps:
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                out.append((min(xs), min(ys), max(xs), max(ys), max(z0, top - r - WAIST)))
    return out


def _step_tops_at(st: str, x: float, y: float) -> list[float]:
    """Levels of the step tops near (x, y) (within 0.15 m), for walls that stand on a stair."""
    L = LEVELS
    i = STOREY_ORDER.index(st)
    z0, z1 = L[st], L[STOREY_ORDER[i + 1]]
    out = []
    for side in (1, -1):
        for pts, top in _private_stair_steps(z0, z1, side)[0]:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            if min(xs) - 0.15 <= x <= max(xs) + 0.15 and min(ys) - 1e-3 <= y <= max(ys) + 1e-3:
                out.append(top)
    return out or [z0]


def _wall_boxes_under_stairs(x0, y0, x1, y1, zb, zt, st):
    """A partition (plan rectangle, from zb to zt) split where steps pass over it: there it stops under the stair."""
    over = [u for u in stair_undersides(st) if u[0] < x1 - 1e-3 and u[2] > x0 + 1e-3 and u[1] < y1 - 1e-3 and u[3] > y0 + 1e-3]
    if not over:
        return [(x0, y0, x1, y1, zt)]
    along_x = (x1 - x0) >= (y1 - y0)
    a0, a1 = (x0, x1) if along_x else (y0, y1)
    cuts = sorted({a0, a1, *[min(max(v, a0), a1) for u in over for v in ((u[0], u[2]) if along_x else (u[1], u[3]))]})
    out = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b - a < 1e-3:
            continue
        m = (a + b) / 2
        cx, cy = (m, (y0 + y1) / 2) if along_x else ((x0 + x1) / 2, m)
        top = min([zt] + [u[4] for u in over if u[0] <= cx <= u[2] and u[1] <= cy <= u[3]])
        if top - zb < 0.05:
            continue
        box = (a, y0, b, y1, top) if along_x else (x0, a, x1, b, top)
        if out and abs(out[-1][4] - top) < 1e-6 and abs((out[-1][2] if along_x else out[-1][3]) - a) < 1e-6:
            pv = out[-1]
            out[-1] = (pv[0], pv[1], b, pv[3], top) if along_x else (pv[0], pv[1], pv[2], b, top)
        else:
            out.append(box)
    return out


def _cours_anglaises(add, FR, z_floor: float) -> None:
    """Light wells in front of the basement windows (A.01): their RC walls (Σ.02) up to the garden and the raft extended under them."""
    raft_ext = []
    for w in FR["levels"]["basement"]["walls"]:
        (ax, ay), (bx, by) = w["a"], w["b"]
        if not (min(ay, by) > 20.3 or max(ax, bx) < 0.05):
            continue                                        # walls on the building outline are drawn with the openings above
        t = w["t_m"]
        if abs(ay - by) < 1e-6:
            m = _box_mesh(min(ax, bx), ay - t / 2, z_floor, max(ax, bx), ay + t / 2, CA_TOP)
        else:
            m = _box_mesh(ax - t / 2, min(ay, by), z_floor, ax + t / 2, max(ay, by), CA_TOP)
        add("Cour anglaise wall", "retwall_basement", m, cour_anglaise=True)
    for (x0, y0, x1, y1) in CA_PITS:
        raft_ext.append(_box_mesh(x0, y0, z_floor - RAFT_T, x1, y1, z_floor))
        add("Cour anglaise floor", "foundation", raft_ext[-1], cour_anglaise=True)
        add("Cour anglaise gravel", "land_site_gravel", _box_mesh(x0 + 0.12, y0 + 0.12, z_floor, x1 - 0.12, y1 - 0.12, z_floor + 0.08), color="#b9b3a7")


CA_PITS = [(2.885, 20.35, 5.885, 21.745), (12.335, 20.35, 15.425, 21.745), (-1.385, 6.045, 0.0, 9.045)]


_FRAME_CACHE: dict[str, Any] = {}


def _frame() -> dict[str, Any] | None:
    """Skeleton read from the formwork drawings (app/data/frame_kifisia.json), if present."""
    if "f" not in _FRAME_CACHE:
        p = DATA / "frame_kifisia.json"
        _FRAME_CACHE["f"] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    return _FRAME_CACHE["f"]


def _clean_poly(coords) -> Polygon:
    """Rectilinear outline of a column/wall from the drawing: snapped to 5 mm and simplified."""
    P = Polygon([(round(x / 0.005) * 0.005, round(y / 0.005) * 0.005) for x, y in coords]).buffer(0).simplify(0.004)
    if P.geom_type != "Polygon":
        P = max(P.geoms, key=lambda g: g.area)
    return P


def _column_positions(st: str, members: dict) -> np.ndarray:
    n = len(members[MEMBER_SHEET[st]]["columns"])
    poly = _poly(G[st if st != "basement" else "basement"])
    # candidates on a 0.6 m grid inside the footprint (inset so the columns stay in the building)
    inner = poly.buffer(-0.35)
    minx, miny, maxx, maxy = inner.bounds
    cand = [(x, y) for x in np.arange(minx, maxx + 1e-6, 0.6) for y in np.arange(miny, maxy + 1e-6, 0.6) if inner.contains(sbox(x - 0.01, y - 0.01, x + 0.01, y + 0.01))]
    return _fps(np.array(cand), n)


def _grid_edges(cols: np.ndarray) -> list[tuple[int, int]]:
    edges = []
    for i, p in enumerate(cols):
        for axis in (0, 1):
            other = 1 - axis
            best, bd = None, 1e9
            for j, q in enumerate(cols):
                if i == j or abs(q[other] - p[other]) > 0.45 or q[axis] <= p[axis] + 0.5:
                    continue
                d = q[axis] - p[axis]
                if d < bd:
                    best, bd = j, d
            if best is not None and bd < 8.0:
                edges.append((i, best))
    return sorted(edges, key=lambda e: math.dist(cols[e[0]], cols[e[1]]))


def _beam_pair(i: int, cols: np.ndarray):
    if len(cols) < 2:
        return None, None
    edges = _grid_edges(cols)
    if not edges:
        return None, None
    a, b = edges[i % len(edges)]
    return cols[a], cols[b]


def _beam_mesh(a, b, z_bottom, width, depth, top=None, drop=False):
    """Axis-aligned beam between two column centres. For drop beams the bottom is z_bottom - depth."""
    (x0, y0), (x1, y1) = a, b
    z0 = z_bottom - depth if drop else z_bottom
    z1 = z_bottom if drop else z_bottom + depth
    if abs(x1 - x0) >= abs(y1 - y0):
        return _box_mesh(min(x0, x1), (y0 + y1) / 2 - width / 2, z0, max(x0, x1), (y0 + y1) / 2 + width / 2, z1)
    return _box_mesh((x0 + x1) / 2 - width / 2, min(y0, y1), z0, (x0 + x1) / 2 + width / 2, max(y0, y1), z1)


def _wall_mesh(a, b, poly, z0, h, t, outward=False):
    """Box along segment a-b, offset inward (towards the polygon) by half the thickness unless outward."""
    (x0, y0), (x1, y1) = a, b
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    ln = math.hypot(dx, dy)
    nx, ny = -dy / ln, dx / ln
    probe = poly.contains(sbox(mx + nx * 0.2 - 0.01, my + ny * 0.2 - 0.01, mx + nx * 0.2 + 0.01, my + ny * 0.2 + 0.01))
    s = 1.0 if probe else -1.0                     # inward normal sign
    off = (t / 2) * (s if not outward else s)
    cx, cy = mx + nx * off, my + ny * off
    ext = (ln, t, h) if abs(dx) >= abs(dy) else (t, ln, h)
    m = trimesh.creation.box(extents=ext)
    m.apply_translation((cx, cy, z0 + h / 2))
    return m


def _gable_top(x: float) -> float:
    """Top of the attic wall at the abscissa x: knee wall + gable up to the underside of the ridge."""
    z_e, z_r, tv = _roof_geometry()
    for (x0, y0, x1, y1) in G["attic"]:
        if x0 - 1e-6 <= x <= x1 + 1e-6:
            xm, half = (x0 + x1) / 2, (x1 - x0) / 2
            return z_e + (z_r - tv - z_e) * (1 - abs(x - xm) / half)
    return z_e


def _seg_frame(a, b, poly):
    """Length, unit direction and inward unit normal of the footprint segment a-b."""
    ln = math.dist(a, b)
    d = ((b[0] - a[0]) / ln, (b[1] - a[1]) / ln)
    n = (-d[1], d[0])
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    if not poly.contains(Point(mx + n[0] * 0.2, my + n[1] * 0.2)):
        n = (-n[0], -n[1])
    return ln, d, n


def _uvz_box(a, d, n, u0, u1, v0, v1, z0, z1) -> trimesh.Trimesh:
    """Axis-aligned box given in the wall frame: u along the wall from a, v inward from the footprint line."""
    pts = [(a[0] + d[0] * u + n[0] * v, a[1] + d[1] * u + n[1] * v) for u in (u0, u1) for v in (v0, v1)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return _box_mesh(min(xs), min(ys), z0, max(xs), max(ys), z1)


def _wall_pieces(length, z0, top, holes):
    """Pieces (ua, ub, z_low, top_a, top_b) of a wall elevation after cutting rectangular holes (u0, u1, z_low, z_high)."""
    cuts = sorted({0.0, length, *[min(max(h[0], 0.0), length) for h in holes], *[min(max(h[1], 0.0), length) for h in holes]})
    out = []
    for ua, ub in zip(cuts[:-1], cuts[1:]):
        if ub - ua < 1e-6:
            continue
        um = (ua + ub) / 2
        merged: list[list[float]] = []
        for lo, hi in sorted((h[2], h[3]) for h in holes if h[0] - 1e-9 <= um <= h[1] + 1e-9):
            if merged and lo <= merged[-1][1] + 1e-9:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        cur = z0
        for lo, hi in merged:
            if lo > cur + 1e-6:
                out.append((ua, ub, cur, lo, lo))
            cur = max(cur, hi)
        ta, tb = top(ua), top(ub)
        if min(ta, tb) > cur + 1e-6:
            out.append((ua, ub, cur, ta, tb))
    return out


def _glazing_mesh(a, d, n, u0, u1, zb, zt, typ: str, v_c: float = 0.15) -> trimesh.Trimesh:
    """Frame (4 bars + mullions) and glass pane of a window / balcony door / entrance, in the outer part of the wall."""
    bar, th = 0.06, 0.08
    v0, v1 = v_c - th / 2, v_c + th / 2
    w = u1 - u0
    ms = [_uvz_box(a, d, n, u0, u0 + bar, v0, v1, zb, zt), _uvz_box(a, d, n, u1 - bar, u1, v0, v1, zb, zt),
          _uvz_box(a, d, n, u0 + bar, u1 - bar, v0, v1, zb, zb + bar), _uvz_box(a, d, n, u0 + bar, u1 - bar, v0, v1, zt - bar, zt)]
    nm = 0 if w < 1.9 else (1 if w < 3.0 else 2)                     # sliding sashes of the large balcony doors
    for k in range(1, nm + 1):
        uc = u0 + w * k / (nm + 1)
        ms.append(_uvz_box(a, d, n, uc - bar / 2, uc + bar / 2, v0, v1, zb + bar, zt - bar))
    ms.append(_uvz_box(a, d, n, u0 + bar, u1 - bar, v_c - 0.01, v_c + 0.01, zb + bar, zt - bar))
    return trimesh.util.concatenate(ms)


def _wall_assembly(a, b, poly, z0, wall_h, t, ops, placed, top_fn=None) -> dict[str, Any]:
    """External wall segment a-b with its openings cut out: wall mesh (net), lintels and glazing elements."""
    ln, d, n = _seg_frame(a, b, poly)
    top = top_fn and (lambda u: top_fn(a[0] + d[0] * u)) or (lambda u: z0 + wall_h)
    onx, ony = -n[0], -n[1]
    holes, lintels, glazing = [], [], []
    for oi, o in enumerate(OPENINGS["ext"]):
        if o not in ops or oi in placed or (round(o["n"][0]), round(o["n"][1])) != (round(onx), round(ony)):
            continue
        along_x = abs(d[0]) > 0.5
        line = a[1] if along_x else a[0]
        if abs(o["line"] - line) > 0.06:
            continue
        uc = (o["c"] - a[0]) * d[0] if along_x else (o["c"] - a[1]) * d[1]
        u0, u1 = uc - o["w"] / 2, uc + o["w"] / 2
        if u0 < -0.06 or u1 > ln + 0.06:
            continue
        u0, u1 = max(u0, 0.0), min(u1, ln)
        zb = z0 + o["sill"]
        tmin = min(top(u0), top(u1), top((u0 + u1) / 2))
        zt = min(zb + o["h"], tmin - 0.06)
        lh = min(LINTEL_H, tmin - zt)
        lh = lh if lh >= 0.10 else 0.0
        placed.add(oi)
        holes.append((u0, u1, zb, zt))
        if lh > 0:
            ub0, ub1 = max(u0 - LINTEL_BEARING, 0.0), min(u1 + LINTEL_BEARING, ln)
            holes.append((ub0, ub1, zt, zt + lh))
            L = ub1 - ub0
            lintels.append((_uvz_box(a, d, n, ub0, ub1, 0.0, t, zt, zt + lh), f"Lintel {o['type']} {len(lintels) + 1}", "lintel_@",
                            {"lintel": True, "span_m": round(u1 - u0, 3), "opening": o["type"],
                             "qty_override": {"length_m": round(L, 3), "width_m": LINTEL_B, "depth_m": round(lh, 3), "section_m2": round(LINTEL_B * lh, 4),
                                              "volume_m3": round(LINTEL_B * lh * L, 4)}}))
        typ = o["type"]
        mesh = _glazing_mesh(a, d, n, u0, u1, zb, zt, typ)
        hh = zt - zb
        area = round((u1 - u0) * hh, 3)
        label = {"window": "Window", "balcony_door": "Balcony door", "entrance": "Entrance door / glazing", "garage_door": "Garage door (roller shutter)"}[typ]
        props = {"opening": typ, "w_m": round(u1 - u0, 3), "h_m": round(hh, 3), "sill_m": round(o["sill"], 3), "orientation": [int(onx), int(ony)],
                 "heated": o.get("sched_id") is not None, "qty_override": {"area_m2": area}}
        if o.get("sched_id"):
            props.update(window_id=o["sched_id"], U=o["U"], qty_override={"area_m2": o.get("sched_area") or area})
        nm_ = f"{label} W{o['sched_id']}" if o.get("sched_id") else label
        if typ == "garage_door":
            glazing.append((mesh, nm_, "door_@", props))
        else:
            glazing.append((mesh, nm_, "window_@", props))
    meshes = []
    for (ua, ub, zl, ta, tb) in _wall_pieces(ln, z0, top, holes):
        if abs(ta - tb) < 1e-6:
            meshes.append(_uvz_box(a, d, n, ua, ub, 0.0, t, zl, ta))
        else:                                                           # sloped top (attic gable): convex quad prism along the wall thickness
            xa, xb = a[0] + d[0] * ua, a[0] + d[0] * ub
            ys = sorted([a[1], a[1] + n[1] * t])
            meshes.append(_prism([(xa, zl), (xb, zl), (xb, tb), (xa, ta)], ys[0], ys[1]))
    return {"wall": trimesh.util.concatenate(meshes), "lintels": lintels, "glazing": glazing}


_PLAN_WALLS: dict[str, Any] = {}


def _plan_walls(st: str):
    """Wall rectangles of storey `st` read from the DXF of the plans (tools/import_plan_walls.py), or None."""
    if "d" not in _PLAN_WALLS:
        p = DATA / "plan_walls.json"
        _PLAN_WALLS["d"] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"storeys": {}}
    s = _PLAN_WALLS["d"]["storeys"].get(st)
    return s["walls"] if s else None


def _joined_partitions(st: str, rects: list, reach: float = 0.35) -> list[tuple[float, float, float, float]]:
    """Partitions read from the plan stop a few cm short of the walls, columns and other partitions they meet (drawing joints).
    Each free end is extended along the wall axis, up to `reach`, until it touches the next element, so that all walls join."""
    from shapely.geometry import box as _b
    foot = _poly(G[st])
    t_ext = 0.25 if st == "basement" else 0.30
    obst = [foot.difference(foot.buffer(-t_ext, join_style=2))]                     # inner band of the external walls
    FR = _frame()
    if FR and st in FR["levels"]:
        obst += [_clean_poly(c["poly"]) for c in FR["levels"][st]["columns"]]
    out = [tuple(r) for r in rects]
    for i, (x0, y0, x1, y1) in enumerate(out):
        others = unary_union(obst + [_b(*r) for j, r in enumerate(out) if j != i])
        along_x = (x1 - x0) >= (y1 - y0)
        for end in (0, 1):
            step, d = 0.005, 0.0
            while d < reach:
                probe = (_b(x1 + d, y0 + 0.005, x1 + d + step, y1 - 0.005) if end else _b(x0 - d - step, y0 + 0.005, x0 - d, y1 - 0.005)) if along_x else \
                        (_b(x0 + 0.005, y1 + d, x1 - 0.005, y1 + d + step) if end else _b(x0 + 0.005, y0 - d - step, x1 - 0.005, y0 - d))
                if probe.intersects(others) and probe.intersection(others).area > 1e-7:
                    break
                d += step
            if 0.0 < d < reach:
                if along_x:
                    x0, x1 = (x0, x1 + d) if end else (x0 - d, x1)
                else:
                    y0, y1 = (y0, y1 + d) if end else (y0 - d, y1)
        out[i] = (round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4))
    # close the remaining joints (L and T corners where two walls only touch at a point, slits next to columns/external walls):
    # a morphological closing of all walls fills every gap narrower than 2 × 6 cm; door openings are much wider and stay open
    from shapely.geometry import box as _b2
    walls = unary_union([_b2(*r) for r in out])
    solid = unary_union([walls] + obst)
    closed = solid.buffer(0.06, join_style=2, cap_style=3).buffer(-0.06, join_style=2, cap_style=3)
    fill = closed.difference(solid).intersection(walls.buffer(0.07, join_style=2, cap_style=3))
    # L corners: a wall along x and a wall along y whose ends meet only at a point (or a few cm apart) get the corner square
    hor = [r for r in out if (r[2] - r[0]) >= (r[3] - r[1])]
    ver = [r for r in out if (r[2] - r[0]) < (r[3] - r[1])]
    tol = 0.12
    for A in hor:
        for xe in (A[0], A[2]):
            for B in ver:
                if not (B[0] - tol <= xe <= B[2] + tol):
                    continue
                for ye in (B[1], B[3]):
                    if not (A[1] - tol <= ye <= A[3] + tol):
                        continue
                    q = _b2(min(B[0], xe), min(A[1], ye), max(B[2], xe), max(A[3], ye))
                    if q.area > 0.06:
                        continue
                    fill = fill.union(q.difference(walls))
    for g in (fill.geoms if hasattr(fill, "geoms") else [fill]):
        if g.is_empty or g.area < 1e-4 or g.geom_type != "Polygon":
            continue
        for r in _rects_of(g):
            if (r[2] - r[0]) > 0.005 and (r[3] - r[1]) > 0.005:
                out.append(tuple(round(v, 4) for v in r))
    return out


def _interior(add, st: str, z_floor: float, z_next: float, meta: dict) -> None:
    """Interior partitions of the floor plan (one element per storey) with their doors, lintels and the masonry above the doors."""
    rects = OPENINGS["partitions"].get(st, [])
    pw = _plan_walls(st)
    if pw is not None:
        # walls read from the DXF of the plans: the inner ones are partitions (brick); those on/outside the outline are the RC walls
        inner = _poly(G[st]).buffer(-0.32, join_style=2)
        rects = [tuple(r) for r in pw if inner.contains(Point((r[0] + r[2]) / 2, (r[1] + r[3]) / 2))]
    hanging = []
    if st == "basement":
        hanging = [r for r in rects if abs(r[0] - 9.05) < 0.06 and abs(r[2] - 9.25) < 0.06 and r[1] > 15.2]   # 0.20 wall between Δ1 and Δ2
        rects = [r for r in rects if r not in hanging]
    rects = _joined_partitions(st, rects)
    doors = OPENINGS["doors"].get(st, [])
    if not rects and not doors:
        return
    top_flat = z_next - SLAB_T if st != "attic" else z_floor + 2.7
    boxes, face, length, vol_t = [], 0.0, 0.0, []

    def top_at(x0, x1, y):
        return min(top_flat, min(_roof_under(x0 + 0.05, y), _roof_under(x1 - 0.05, y)) - 0.02) if st == "attic" else top_flat

    for (x0, y0, x1, y1) in rects:
        zt = top_at(x0, x1, (y0 + y1) / 2)
        if zt - z_floor < 0.3:
            continue
        ln_, t_ = max(x1 - x0, y1 - y0), min(x1 - x0, y1 - y0)
        for (a0, b0, a1, b1, top) in _wall_boxes_under_stairs(x0, y0, x1, y1, z_floor, zt, st):
            boxes.append(_box_mesh(a0, b0, z_floor, a1, b1, top))
            face += max(a1 - a0, b1 - b0) * (top - z_floor)
        length += ln_
        vol_t.append(t_)
    extra: list[tuple] = []
    for k, dr in enumerate(doors):
        d, r = dr["dir"], dr["r"]
        ow = round(r + 0.04, 3)
        mx, my = dr["mid"]
        along_x = abs(d[0]) > 0.5
        t_w, c_w = 0.10, (my if along_x else mx)
        for sgn in (1, -1):                                              # thickness / axis of the wall that continues beside the door
            px, py = mx + d[0] * sgn * (ow / 2 + 0.08), my + d[1] * sgn * (ow / 2 + 0.08)
            # the wall that continues beside the door must run in the door's direction (not a wall crossing it)
            hit = next((q for q in rects if ((q[2] - q[0]) >= (q[3] - q[1])) == along_x
                        and q[0] - 0.02 <= px <= q[2] + 0.02 and q[1] - 0.08 <= py <= q[3] + 0.08), None)
            if not hit and _frame() and st in _frame()["levels"]:          # or an RC wall/column of the frame beside the door
                for c in _frame()["levels"][st]["columns"]:
                    P = _clean_poly(c["poly"])
                    for q in _rects_of(P):
                        if min(q[2] - q[0], q[3] - q[1]) >= 0.07 and ((q[2] - q[0]) >= (q[3] - q[1])) == along_x \
                                and q[0] - 0.02 <= px <= q[2] + 0.02 and q[1] - 0.08 <= py <= q[3] + 0.08:
                            hit = q
                            break
                    if hit:
                        break
            if hit:
                t_w = max(min(hit[2] - hit[0], hit[3] - hit[1]), 0.08)
                c_w = (hit[1] + hit[3]) / 2 if along_x else (hit[0] + hit[2]) / 2
                break
        if along_x:
            x0, x1, y0, y1 = mx - ow / 2, mx + ow / 2, c_w - t_w / 2, c_w + t_w / 2
        else:
            x0, x1, y0, y1 = c_w - t_w / 2, c_w + t_w / 2, my - ow / 2, my + ow / 2
        zt = top_at(x0, x1, (y0 + y1) / 2)
        # a door under a stair: its leaf stops at the underside of the stair above (landing or flight), with a 5 cm clearance
        h_door = DOOR_H
        for ax0, ay0, ax1, ay1, und in stair_undersides(st):
            if ax0 < x1 and ax1 > x0 and ay0 < y1 and ay1 > y0:
                h_door = min(h_door, round(und - z_floor - 0.05, 3))
        z_h = z_floor + h_door
        lh = LINTEL_H_INT
        # leaf (closed) and 3-sided frame
        fr = 0.04
        leaf_t = 0.045
        if along_x:
            parts = [_box_mesh(x0, c_w - leaf_t / 2, z_floor, x1, c_w + leaf_t / 2, z_h - fr),
                     _box_mesh(x0 - fr, y0, z_floor, x0, y1, z_h), _box_mesh(x1, y0, z_floor, x1 + fr, y1, z_h), _box_mesh(x0 - fr, y0, z_h - fr, x1 + fr, y1, z_h)]
        else:
            parts = [_box_mesh(c_w - leaf_t / 2, y0, z_floor, c_w + leaf_t / 2, y1, z_h - fr),
                     _box_mesh(x0, y0 - fr, z_floor, x1, y0, z_h), _box_mesh(x0, y1, z_floor, x1, y1 + fr, z_h), _box_mesh(x0, y0 - fr, z_h - fr, x1, y1 + fr, z_h)]
        apt = dr["type"] == "apartment_entrance"
        extra.append((trimesh.util.concatenate(parts), ("Apartment entrance door" if apt else "Interior door") + f" {st} {k + 1}", "door_@",
                      {"opening": "apartment_entrance" if apt else "interior_door", "w_m": round(r, 3), "h_m": h_door, "qty_override": {"area_m2": round(r * h_door, 3)}}))
        if zt - z_h > 0.02:
            lh = min(lh, zt - z_h)
            L = ow + 2 * LINTEL_BEARING
            extra.append((_box_mesh(x0, y0, z_h, x1, y1, z_h + lh), f"Lintel interior door {st} {k + 1}", "lintel_@",
                          {"lintel": True, "span_m": ow, "opening": "interior_door", "qty_override": {"length_m": round(L, 3), "width_m": round(t_w, 3), "depth_m": round(lh, 3),
                                                                                                     "section_m2": round(t_w * lh, 4), "volume_m3": round(t_w * lh * L, 4)}}))
            if zt - (z_h + lh) > 0.02:                                   # masonry above the lintel
                boxes.append(_box_mesh(x0, y0, z_h + lh, x1, y1, zt))
                face += ow * (zt - z_h - lh)
                length += ow
    for (x0, y0, x1, y1) in hanging:
        steps = [b for b in stair_undersides(st) if b[1] < y1 and b[3] > y0 and (abs(b[2] - x0) < 0.05 or abs(b[0] - x1) < 0.05)]
        cuts = sorted({y0, y1, *[min(max(v, y0), y1) for b in steps for v in (b[1], b[3])]})
        for a, b_ in zip(cuts[:-1], cuts[1:]):
            m = (a + b_) / 2
            tops = [b[4] + LEVELS["basement"] * 0 for b in steps if b[1] <= m <= b[3]]
            if not tops:
                continue
            # step top = underside + waist + riser: rebuild it from the step list
            zb = max(t for t in _step_tops_at(st, (x0 + x1) / 2, m))
            boxes.append(_box_mesh(x0, a, zb, x1, b_, top_flat))
    if st == "basement":
        # boiler room: brick wall from the soffit of the private stairs up to the ground-floor slab, so the stairs are closed
        # off from the room below (user, 3D check) – along the inner edge of steps 12–16 (y 14.39) and between Δ1/Δ2 (x 9.05–9.25)
        ye, tw = PRIV_DN_Y[0], 0.10
        for side in (1, -1):
            stp, h = _private_stair_steps(z_floor, z_next, side)
            for pts, top in stp:
                xs, ys = [q[0] for q in pts], [q[1] for q in pts]
                zb = max(z_floor, top - h - WAIST)
                if top_flat - zb < 0.05:
                    continue
                if abs(min(ys) - ye) < 0.02:
                    boxes.append(_box_mesh(min(xs), ye - tw, zb, max(xs), ye, top_flat))
                    face += (max(xs) - min(xs)) * (top_flat - zb)
                if side == 1 and abs(max(xs) - PRIV_XE) < 0.02 and min(ys) < PRIV_UP_Y[0]:
                    y0w, y1w = max(min(ys), ye - tw), min(max(ys), PRIV_UP_Y[0])
                    boxes.append(_box_mesh(PRIV_XE, y0w, zb, W - PRIV_XE, y1w, top_flat))
                    face += (y1w - y0w) * (top_flat - zb)
    if boxes:
        t_avg = float(np.mean(vol_t)) if vol_t else 0.1
        add(f"Internal walls {st}", f"intwall_{st}", trimesh.util.concatenate(boxes), internal=True,
            qty_override={"face_area_m2": round(face, 3), "length_m": round(length, 3), "thickness_m": round(t_avg, 3),
                          "height_m": round(face / max(length, 1e-6), 3), "plan_area_m2": round(length * t_avg, 3)})
    for (m, nme, lay, props) in extra:
        add(nme, lay.replace("@", st), m, **props)


def storeys_def() -> list[dict]:
    names = {"basement": ("Υπόγειο", "Basement"), "ground": ("Ισόγειο", "Ground floor"), "first": ("Α' όροφος", "1st floor"),
             "second": ("Β' όροφος", "2nd floor"), "attic": ("Σοφίτα", "Attic")}
    out = []
    for i, st in enumerate(STOREY_ORDER):
        nxt = LEVELS[STOREY_ORDER[i + 1]] if i + 1 < len(STOREY_ORDER) else LEVELS["roof"]
        out.append({"id": f"S{i:02d}", "key": st, "name_el": names[st][0], "name_en": names[st][1], "elevation_m": LEVELS[st],
                    "height_m": round(nxt - LEVELS[st], 2)})
    return out


# ---------------------------------------------------------------- surroundings, ramp, planting, wood cladding (from the renders / elevations)
# Colours of the render materials (3d.mtl and the photo-realistic renders): white stucco, warm-grey balcony frames, wood (planters,
# louvres, gates), anthracite slat fences, grey concrete boundary walls, lawn, light-grey paving, dark-green pines.
REAL = {"wall": "#efebe4", "column": "#efebe4", "beam": "#efebe4", "slab": "#e3dfd8", "roof": "#6f6a65", "window": "#4d5f6c", "door": "#7a5a3e",
        "railing": "#cfe2ea", "stair": "#d8d3ca", "footing": "#9a9a96", "fence": "#3a3d40", "site": "#86a364", "pergola": "#8a6242", "vegetation": "#4f7a34"}
C = {"wood": "#8a6242", "wood_dark": "#6e4b30", "frame": "#8f8378", "white": "#f3f1ec", "anthracite": "#33373b", "concrete": "#8e8c87",
     "paving": "#c9c7c1", "ramp": "#5d5f61", "lawn": "#86a364", "hedge": "#3f6b2c", "plants": "#5c8f3a", "pine": "#355a2a", "trunk": "#5a4433", "marble": "#202224"}
RAMP_X = (18.70, 22.30)                       # ramp along the east side, from the street gate down to the garage door (east wall, x = 18.30)
RAMP_Y = (-5.40, 3.90)                        # sloping part; flat at the gate (y < -5.40) and on the landing (y > 3.90)
LANDING_Y = (3.90, 10.60)


def _hexa(pts) -> trimesh.Trimesh:
    return trimesh.convex.convex_hull(np.array(pts, float))


def _ramp_mesh(x0, x1, ya, yb, za, zb, t=0.25) -> trimesh.Trimesh:
    return _hexa([(x0, ya, za), (x1, ya, za), (x0, yb, zb), (x1, yb, zb), (x0, ya, za - t), (x1, ya, za - t), (x0, yb, zb - t), (x1, yb, zb - t)])


def _clip_convex(pts, x0=None, x1=None, y0=None, y1=None):
    from shapely.geometry import box as _b
    P = Polygon(pts).intersection(_b(-1e3 if x0 is None else x0, -1e3 if y0 is None else y0, 1e3 if x1 is None else x1, 1e3 if y1 is None else y1))
    return [tuple(c) for c in list(P.exterior.coords)[:-1]] if not P.is_empty and P.area > 0.01 else None


REAL_RAMP = (18.25, 22.85, 15.60)
PLOT_X = (-3.2, 23.3)            # ramp + landing of the real (Rhino) model: x from, x to, y end of the landing


def _real_site_plate() -> trimesh.Trimesh:
    """Base plate under the real (Rhino) surroundings, open over the basement ramp (street level → garage door) and over the
    cours anglaises, so that both are visible instead of being covered. Built from convex pieces (no triangulation engine)."""
    x0, x1, y1 = REAL_RAMP
    holes = [(x0, -1e3, x1, y1)] + [(a, b, c, d) for (a, b, c, d) in CA_PITS]
    xs = sorted({PLOT_X[0], PLOT_X[1], *[h[0] for h in holes], *[h[2] for h in holes]})
    pieces = []
    for xa, xb in zip(xs[:-1], xs[1:]):
        if xb - xa < 1e-3:
            continue
        xm = (xa + xb) / 2
        cut = sorted((h[1], h[3]) for h in holes if h[0] < xm < h[2])
        ylo = -1e3
        for (ha, hb) in cut + [(1e3, 1e3)]:
            pc = _clip_convex(PLOT, x0=xa, x1=xb, y0=ylo, y1=ha)
            if pc:
                pieces.append(pc)
            ylo = hb
    return trimesh.util.concatenate([_convex_plate(pc, -1.60, -1.30) for pc in pieces])


def site_plate() -> trimesh.Trimesh:
    """Site ground over the plot with an opening for the basement ramp (convex pieces, no triangulation engine needed)."""
    x0, x1 = RAMP_X[0] - 0.2, RAMP_X[1] + 0.2
    pieces = [_clip_convex(PLOT, x1=x0), _clip_convex(PLOT, x0=x1), _clip_convex(PLOT, x0=x0, x1=x1, y0=LANDING_Y[1] + 0.2)]
    return trimesh.util.concatenate([_convex_plate(pc, -0.30, -0.02) for pc in pieces if pc])


def _pine(x, y, h=9.0, r=2.4) -> tuple[trimesh.Trimesh, trimesh.Trimesh]:
    trunk = trimesh.creation.cylinder(radius=0.18, height=h * 0.55, sections=8)
    trunk.apply_translation((x, y, h * 0.275))
    crown = trimesh.creation.icosphere(subdivisions=1, radius=1.0)
    crown.apply_scale((r, r, h * 0.22))
    crown.apply_translation((x, y, h * 0.72))
    return trunk, crown


def landscape_parts() -> list[dict]:
    """Parts of the surroundings. Layer 'land_<kind>_...' fixes the element kind; props carry the colour and the cost key."""
    out: list[dict] = []

    def add(name, kind, mesh, color, key=None, measure=None, **props):
        pr = {"color": color, **props}
        if key:
            pr["landscape"] = key
            pr["measure"] = measure
        out.append({"name": name, "layer": f"land_{kind}_{name}", "mesh": mesh, "props": pr})

    ys = PLOT[0][1]                                                   # street line (y = -6.99)
    zb = LEVELS["basement"]
    # ---- ramp to the basement: gate apron, slope, landing in front of the garage door, side retaining walls
    add("Ramp apron", "site", _box_mesh(RAMP_X[0], ys, -0.27, RAMP_X[1], RAMP_Y[0], -0.02), C["ramp"], "ramp_m2", "plan")
    add("Basement ramp", "site", _ramp_mesh(RAMP_X[0], RAMP_X[1], RAMP_Y[0], RAMP_Y[1], -0.02, zb), C["ramp"], "ramp_m2", "slope")
    add("Ramp landing", "site", _box_mesh(18.30, LANDING_Y[0], zb - 0.25, RAMP_X[1], LANDING_Y[1], zb), C["ramp"], "ramp_m2", "plan")
    xw0, xw1 = RAMP_X[1], RAMP_X[1] + 0.25
    add("Ramp retaining wall east", "wall", _box_mesh(xw0, RAMP_Y[0], zb - 0.25, xw1, LANDING_Y[1] + 0.25, 0.9), C["concrete"], "ramp_wall_m2", "face")
    add("Ramp retaining wall end", "wall", _box_mesh(18.30, LANDING_Y[1], zb - 0.25, xw1, LANDING_Y[1] + 0.25, 0.0), C["concrete"], "ramp_wall_m2", "face")
    add("Ramp curb west", "wall", _box_mesh(RAMP_X[0] - 0.20, RAMP_Y[0], -0.30, RAMP_X[0], LANDING_Y[0], 0.45), C["concrete"], "ramp_wall_m2", "face")
    # ---- street front: white low wall + anthracite vertical slats, entrance canopy with wooden door and black marble, wooden garage gate
    gate_x = (RAMP_X[0] - 0.1, RAMP_X[1] + 0.1)
    ent_x = (7.55, 10.95)
    for xa, xb in ((PLOT[0][0], ent_x[0]), (ent_x[1], gate_x[0] - 0.45)):
        add(f"Street wall {xa:.0f}", "wall", _box_mesh(xa, ys, -0.02, xb, ys + 0.25, 0.60), C["white"], "fence_wall_m", "length")
        add(f"Street fence slats {xa:.0f}", "fence", _box_mesh(xa, ys + 0.08, 0.60, xb, ys + 0.13, 1.80), C["anthracite"])
    for xp in (gate_x[0] - 0.45, gate_x[1]):
        add(f"Gate pillar {xp:.1f}", "wall", _box_mesh(xp, ys - 0.05, -0.02, xp + 0.45, ys + 0.40, 2.10), C["concrete"], "fence_wall_m", "length")
    add("Garage sliding gate", "door", _box_mesh(gate_x[0], ys + 0.10, 0.0, gate_x[1], ys + 0.16, 1.95), C["wood"], "gate_garage", "count")
    add("Entrance canopy", "pergola", trimesh.util.concatenate([_box_mesh(ent_x[0], ys, -0.02, ent_x[0] + 0.30, ys + 2.2, 2.80), _box_mesh(ent_x[1] - 0.30, ys, -0.02, ent_x[1], ys + 2.2, 2.80),
                                                               _box_mesh(ent_x[0], ys, 2.50, ent_x[1], ys + 2.2, 2.80)]), C["white"], "entrance_canopy", "count")
    add("Pedestrian gate", "door", _box_mesh(ent_x[0] + 0.35, ys + 0.10, 0.0, ent_x[0] + 1.85, ys + 0.16, 2.10), C["wood"], "gate_pedestrian", "count")
    add("Marble panel letterboxes", "wall", _box_mesh(ent_x[0] + 1.95, ys + 0.05, 0.0, ent_x[1] - 0.35, ys + 0.30, 2.10), C["marble"], "marble_m2", "face_x")
    # ---- side and back boundary walls (grey concrete)
    ring = PLOT + [PLOT[0]]
    for i, (a, b) in enumerate(zip(ring[:-1], ring[1:])):
        if i == 3:                                                    # D → A is the street side
            continue
        add(f"Boundary wall {i}", "fence", _oriented_box(a, b, -0.02, 1.50, 0.20), C["concrete"])
    # ---- front gardens: paved path and patios, lawn, hedges along the fence, slat screens between the gardens and the path
    add("Entrance path", "site", _box_mesh(ent_x[0] + 0.3, ys + 0.3, -0.02, ent_x[1] - 0.3, 5.25, 0.03), C["paving"])
    for xa, xb in ((0.0, 7.25), (11.05, 18.30)):
        add(f"Patio {xa:.0f}", "site", _box_mesh(xa, 1.25, -0.02, xb, 5.25, 0.03), C["paving"])
        add(f"Lawn front {xa:.0f}", "site", _box_mesh(xa if xa > 1 else PLOT[0][0] + 0.25, ys + 1.0, -0.02, xb if xb < 18 else RAMP_X[0] - 0.25, 1.25, 0.02), C["lawn"])
        add(f"Hedge front {xa:.0f}", "vegetation", _box_mesh(xa if xa > 1 else PLOT[0][0] + 0.3, ys + 0.35, 0.0, xb if xb < 18 else RAMP_X[0] - 0.3, ys + 1.0, 1.10), C["hedge"], "hedge_m", "length")
    for xs in (ent_x[0] - 0.05, ent_x[1]):
        add(f"Garden screen {xs:.1f}", "fence", _box_mesh(xs, ys + 1.0, 0.0, xs + 0.05, 5.25, 1.60), C["anthracite"])
    add("Lawn back", "site", _box_mesh(-2.8, 20.6, -0.02, 22.4, 29.5, 0.02), C["lawn"])
    add("Hedge back", "vegetation", _box_mesh(-2.6, 29.6, 0.0, 22.2, 30.3, 1.40), C["hedge"], "hedge_m", "length")
    add("Lawn west", "site", _box_mesh(-2.9, -5.0, -0.02, -0.2, 20.6, 0.02), C["lawn"])
    # ---- pine trees around the building (as in the renders)
    for i, (x, y, hh) in enumerate([(-1.8, -3.5, 9.0), (-1.9, 17.5, 10.0), (2.0, 25.5, 11.0), (9.0, 27.0, 9.5), (16.5, 25.0, 10.5), (21.0, 24.0, 9.0), (0.5, 2.0, 7.5), (15.5, 0.8, 7.0)]):
        tr, cr = _pine(x, y, hh)
        add(f"Pine trunk {i + 1}", "vegetation", tr, C["trunk"], "trees", "count")
        add(f"Pine crown {i + 1}", "vegetation", cr, C["pine"])
    # ---- balconies: wooden planters with plants on the front edges, balcony frames, wood louvres and the wooden strip of the stairwell
    for st, (xa, xb), y_front in (("first", (-1.1, 7.25), 3.903), ("second", (11.05, 19.40), 3.281)):
        z = LEVELS[st]
        add(f"Planter {st}", "pergola", _box_mesh(xa + 0.15, y_front, z, xb - 0.15, y_front + 0.45, z + 0.60), C["wood"], "planter_m", "length")
        add(f"Planter plants {st}", "vegetation", _box_mesh(xa + 0.25, y_front + 0.05, z + 0.60, xb - 0.25, y_front + 0.40, z + 1.00), C["plants"])
    zf, zs, zt = LEVELS["first"], LEVELS["second"], LEVELS["attic"]
    for name, (xa, xb), (ya, yb), (z0, z1), col in (("Balcony frame east", (11.05, 19.40), (3.281, 5.25), (zf - 0.45, zt - 0.10), C["frame"]),
                                                     ("Balcony frame west", (-1.10, 7.25), (3.903, 5.25), (zs - 0.30, zt - 0.10), C["white"])):
        tt = 0.35
        frame = trimesh.util.concatenate([_box_mesh(xa, ya, z0, xa + tt, yb, z1), _box_mesh(xb - tt, ya, z0, xb, yb, z1), _box_mesh(xa, ya, z1 - tt, xb, yb, z1)])
        add(name, "wall", frame, col, "frame_m3", "volume")
    for name, (xa, xb), y, (z0, z1) in (("Wood louvres west 1", (-1.10, -1.06), (5.25, 6.75), (zs, zs + 2.6)), ("Wood louvres east 1", (19.36, 19.40), (5.25, 6.75), (zf, zf + 2.6))):
        add(name, "pergola", _box_mesh(xa, y[0], z0, xb, y[1], z1), C["wood"], "wood_cladding_m2", "face")
    add("Wood cladding stairwell ground-first", "pergola", _box_mesh(8.25, 6.80, 0.0, 10.05, 6.84, LEVELS["second"]), C["wood_dark"], "wood_cladding_m2", "face_x")
    add("Wood cladding stairwell second", "pergola", _box_mesh(8.25, 5.20, LEVELS["second"], 10.05, 5.24, LEVELS["attic"]), C["wood_dark"], "wood_cladding_m2", "face_x")
    return out


def real_parts() -> list[dict]:
    """Surroundings, planting, timber cladding, planters and timber doors from the real Rhino model (app/data/real3d.npz, made by
    tools/import_real3d.py from the light export of 3d.3dm), in the local frame. Empty when the file is missing."""
    path = DATA / "real3d.npz"
    if not path.exists():
        return []
    d = np.load(path)
    V, F = d["V"].astype(np.float64), d["F"].astype(np.int64)
    out = []
    for i, it in enumerate(json.loads(str(d["index"]))):
        f = F[it["f0"]:it["f0"] + it["nf"]] - it["v0"]
        Vi = V[it["v0"]:it["v0"] + it["nv"]]
        if it["kind"] == "site":                                   # the garden surface is open over the cours anglaises
            c = Vi[f].mean(axis=1)
            inside = np.zeros(len(f), bool)
            for (x0, y0, x1, y1) in CA_PITS:
                inside |= (c[:, 0] > x0) & (c[:, 0] < x1) & (c[:, 1] > y0) & (c[:, 1] < y1) & (c[:, 2] > LEVELS["basement"] + 0.5)
            f = f[~inside]
        m = trimesh.Trimesh(Vi, f, process=False)
        pr = {"color": it["color"], "source": "Rhino 3d.3dm", "rhino_layer": it["layer"], "rhino_material": it["material"], "landscape": "visual", "measure": "count"}
        if it["kind"] == "pergola" and it["layer"] != "khpos":
            pr.update(landscape="wood_cladding_m2", measure="half_area")        # timber planks of the facades: both faces of each plank in the mesh
        nm = re.sub(r"[^\w.-]+", "_", it["material"]).strip("_")[:40]
        out.append({"name": f"real {it['kind']} {it['layer']} {nm} {i}", "layer": f"land_{it['kind']}_real_{i}", "mesh": m, "props": pr})
    return out


def _aabb_gap(a, b) -> tuple[float, int, float]:
    """Separation of two axis-aligned boxes: (largest gap, axis, signed shift that closes it). Negative gap = they overlap."""
    best = (-1e9, 0, 0.0)
    for ax in range(3):
        g1 = b[0][ax] - a[1][ax]                     # b beyond a
        g2 = a[0][ax] - b[1][ax]                     # a beyond b
        g, sh = (g1, g1) if g1 >= g2 else (g2, -g2)
        if g > best[0]:
            best = (g, ax, sh)
    return best


def connect_real_parts(parts: list[dict], tol: float = 0.02, snap: float = 0.40) -> list[dict]:
    """Pieces of the Rhino model that do not touch the building (exported without their fixings) are connected to it:
    a gap up to `snap` is closed by moving the piece onto the nearest element; the timber pergola of the roof terrace,
    whose posts and bearers are not in the export, gets steel bearers on posts standing on the balcony frames.
    Returns the added support members; the moved pieces carry the property `snapped_m`."""
    solid = [p for p in parts if not p["layer"].startswith("land_vegetation") and p["layer"] not in ("site", "excavation")]
    boxes = [(p, p["mesh"].bounds) for p in solid]
    added: list[dict] = []
    for p in parts:
        if not p["layer"].startswith("land_") or "_real_" not in p["layer"] or p["layer"].startswith(("land_vegetation", "land_site")):
            continue
        bb = p["mesh"].bounds
        cand = [(_aabb_gap(bb, ob), q) for q, ob in boxes if q is not p]
        (gap, ax, shift), q = min(cand, key=lambda c: c[0][0])
        if gap <= tol:
            # boxes touch, but the piece may still hover over a slab or the ground: measure the clear drop under its base
            drop = _drop_clearance(p["mesh"], [(qq, ob) for qq, ob in boxes if qq is not p])
            if drop is None or drop < 0.08 or drop > snap:          # a few cm under cladding fixed to a wall is normal; only hovering pieces move
                continue
            gap, ax, shift = drop, 2, -drop
        if gap <= snap:
            t = [0.0, 0.0, 0.0]
            t[ax] = shift - math.copysign(0.002, shift) if abs(shift) > 0.004 else shift
            p["mesh"] = p["mesh"].copy(); p["mesh"].apply_translation(t)
            p["props"]["snapped_m"] = round(abs(t[ax]), 3)
            continue
        if p["props"].get("rhino_layer") == "doma" and "pergola" in p["layer"]:
            added += _terrace_pergola_supports(p["mesh"], boxes)
    return added


def _drop_clearance(mesh: trimesh.Trimesh, boxes) -> float | None:
    """Smallest vertical clearance between the base of `mesh` and the surfaces right under it (None: nothing under it)."""
    V = mesh.vertices
    zmin = V[:, 2].min()
    pts = V[V[:, 2] <= zmin + 0.01][:, :2]
    if not len(pts):
        return None
    pts = np.unique(np.round(pts, 3), axis=0)
    best = None
    for q, ob in boxes:
        if ob[1][2] > zmin + 0.01 or ob[1][0] < pts[:, 0].min() or ob[0][0] > pts[:, 0].max() or ob[1][1] < pts[:, 1].min() or ob[0][1] > pts[:, 1].max():
            if not (ob[0][2] <= zmin + 0.01 and ob[1][0] >= pts[:, 0].min() and ob[0][0] <= pts[:, 0].max() and ob[1][1] >= pts[:, 1].min() and ob[0][1] <= pts[:, 1].max()):
                continue
        T = q["mesh"].triangles
        a, b, c = T[:, 0], T[:, 1], T[:, 2]
        v0, v1 = b[:, :2] - a[:, :2], c[:, :2] - a[:, :2]
        den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
        ok = np.abs(den) > 1e-9
        a, v0, v1, den, b, c = a[ok], v0[ok], v1[ok], den[ok], b[ok], c[ok]
        for x, y in pts:
            wx, wy = x - a[:, 0], y - a[:, 1]
            u = (wx * v1[:, 1] - v1[:, 0] * wy) / den
            v = (v0[:, 0] * wy - wx * v0[:, 1]) / den
            inside = (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6)
            if not inside.any():
                continue
            z = a[inside, 2] + u[inside] * (b[inside, 2] - a[inside, 2]) + v[inside] * (c[inside, 2] - a[inside, 2])
            z = z[z <= zmin + 0.005]
            if len(z):
                d = float(zmin - z.max())
                best = d if best is None else min(best, d)
    return best


def _terrace_pergola_supports(mesh: trimesh.Trimesh, boxes) -> list[dict]:
    """Two steel bearers (100x200) along the pergola under its slats and steel posts (120x120) down to whatever is below
    (balcony frame or slab), at most ~3.6 m apart; posts only where there is something to stand on."""
    (x0, y0, z0), (x1, y1, z1) = mesh.bounds
    bw, bh, pw = 0.10, 0.20, 0.12
    lines = [y0 + 0.30, y1 - 0.12]                                  # bearer axes (slats overhang the front bearer)
    out = []
    for yl in lines:
        out.append({"name": "Pergola steel bearer (support)", "layer": "land_pergola_support", "mesh": _box_mesh(x0 + 0.05, yl - bw / 2, z0 - bh, x1 - 0.05, yl + bw / 2, z0),
                    "props": {"color": "#3d4043", "landscape": "visual", "measure": "count", "added_support": True}})
    n = max(2, math.ceil((x1 - x0) / 3.6) + 1)
    xs = [x0 + 0.15 + i * ((x1 - x0) - 0.30) / (n - 1) for i in range(n)]
    for yl in lines:
        for x in xs:
            top = z0 - bh
            below = [ob[1][2] for q, ob in boxes if ob[0][0] <= x <= ob[1][0] and ob[0][1] <= yl <= ob[1][1] and ob[1][2] <= top - 0.3]
            if not below:
                continue
            zb = max(below)
            if top - zb > 4.0:
                continue
            out.append({"name": "Pergola steel post (support)", "layer": "land_pergola_support",
                        "mesh": _box_mesh(x - pw / 2, yl - pw / 2, zb, x + pw / 2, yl + pw / 2, top),
                        "props": {"color": "#3d4043", "landscape": "visual", "measure": "count", "added_support": True}})
    return out


def landscape_quantities(parts: list[dict]) -> dict[str, float]:
    """Cost quantities of the surroundings (ramp, gates, hedges, trees, planters, frames…) from the parts of landscape_parts()."""
    q: dict[str, float] = {}
    for p in parts:
        k, m = p["props"].get("landscape"), p["props"].get("measure")
        if not k:
            continue
        (x0, y0, z0), (x1, y1, z1) = p["mesh"].bounds
        dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
        v = {"plan": dx * dy, "slope": dx * (dy ** 2 + dz ** 2) ** 0.5, "face": max(dx, dy) * dz, "face_x": dx * dz, "length": max(dx, dy), "count": 1.0,
             "volume": float(abs(p["mesh"].volume))}.get(m, 0.0)
        q[k] = q.get(k, 0.0) + v
    return {k: round(v, 3) for k, v in q.items()}


def build_project(project_id: str = "demo-kifisia") -> tuple[dict[str, Any], dict[str, trimesh.Trimesh]]:
    members = json.loads((DATA / "members.json").read_text(encoding="utf-8"))
    windows = json.loads((DATA / "windows.json").read_text(encoding="utf-8"))
    gantt = json.loads((DATA / "gantt.json").read_text(encoding="utf-8"))
    parts, meta3d = build_parts(members, windows)
    land = landscape_parts()
    rp = real_parts()
    land_q = landscape_quantities(land)
    if rp:                                                     # the real model replaces the drawn surroundings; their cost quantities stay
        land_q.pop("wood_cladding_m2", None)                   # (timber cladding is measured on the real planks)
        land_q.pop("frame_m3", None)                           # the balcony frames stay as elements and are measured there
        parts += [p for p in land if p["props"].get("measure") == "volume"] + rp      # balcony frames stay (structure)
        parts += connect_real_parts(parts)                     # fixings missing from the Rhino export (nothing hangs in the air)
    else:
        land_q = {}
        parts += land
    layer_map = {"foundation": "footing", "retwall_basement": "wall", "excavation": "site"}
    for pt in parts:
        for pre, kd in (("lintel_", "beam"), ("window_", "window"), ("door_", "door"), ("intwall_", "wall"), ("furniture_", "furniture")):
            if pt["layer"].startswith(pre):
                layer_map[pt["layer"]] = kd
    for pt in parts:
        if pt["layer"].startswith("land_"):
            layer_map[pt["layer"]] = pt["layer"].split("_")[1]
    elements = ingest.build_elements(parts, layer_map=layer_map)
    storeys = storeys_def()
    ingest.assign_storeys(elements, [{"id": s["id"], "elevation_m": s["elevation_m"]} for s in storeys])
    for e, p in zip(elements, parts):
        if p["props"].get("rhino_layer") == "khpos" or p["layer"].startswith("land_site"):
            e["storey"] = None                               # garden, fences and gates of the Rhino model belong to the plot, not to the basement
        if p["layer"].startswith("retwall"):
            e["material"] = "concrete"
            e["props"]["retaining"] = True                   # retaining walls are concrete
        if p["layer"].startswith("door_") and p["props"].get("opening") == "garage_door":
            e["material"] = "steel"
        if p["props"].get("raft"):
            e["props"]["raft"] = True
        if p["props"].get("qty_override"):
            e["qty"].update(p["props"]["qty_override"])      # exact plan area / perimeter of non-rectangular slabs and pitched roofs
        for k_ in ("color", "landscape", "measure"):
            if p["props"].get(k_) is not None:
                e["props"][k_] = p["props"][k_]
        if "color" not in e["props"]:                        # colour of the render material
            e["props"]["color"] = "#a3a19c" if e.get("material") == "concrete" and e["kind"] == "wall" else REAL.get(e["kind"], "#c8c8c8")
    meshes = {e["id"]: p["mesh"] for e, p in zip(elements, parts)}
    enclosed = {st: sum(r[2] * 0 + (r[2] - r[0]) * (r[3] - r[1]) for r in _rects_of(_poly(G[st]))) for st in STOREY_ORDER}
    gfa = round(sum(PERMIT["declared"]["areas_m2"].values()), 2)           # all levels incl. basement and attic, as listed on sheet Δ.01
    ground_cov = round(enclosed["ground"] + meta3d["semi_open"]["ground"], 2)
    meta3d["enclosed_m2"] = {k: round(v, 2) for k, v in enclosed.items()}
    meta3d["coverage_model_m2"] = ground_cov
    project = {
        "id": project_id, "version": 1,
        "name": "Πολυκατοικία Ποταμού 4, Νέα Κηφισιά (demo)", "name_en": "Residential building, Potamou 4, Nea Kifisia (demo)",
        "meta": {
            "landscape_qty": land_q,
            "location": {"municipality": "Κηφισιά", "address": "Ποταμού 4, Ο.Τ. 426, Νέα Κηφισιά", "lat": 38.0746, "lon": 23.8130,
                         "climate_zone": "B", "altitude_m": 190},
            "permit": {"number": "833237", "date": "2023-10-18", "authority": "ΥΔΟΜ Κηφισιάς", **PERMIT},
            "use": "residential", "apartments": 5, "plot_area_m2": PLOT_AREA, "gfa_m2": gfa, "far_area_m2": PERMIT["declared"]["far_area_m2"], "height_m": PERMIT["declared"]["height_m"],
            "conditioned_area_m2": round(sum(a["area_m2"] for a in APARTMENTS), 2), "population": AREAS["population"],
            # coverage (κάλυψη) of the permit = ground floor 241.79 + semi-open 5.76; it drives the uncovered site area
            "coverage_m2": PERMIT["declared"]["coverage_m2"],
            "planting_m2": PERMIT["declared"]["planting_m2"],
            "common_area_m2": round(sum(PERMIT["declared"]["stairwell_m2"].values()), 2),
            "basement_finished_m2": AREAS["basement_flat_m2"],
            "excavation": {"area_m2": EXC_AREA, "perimeter_m": EXC_PERIMETER, "depth_m": round(-LEVELS["basement"] + RAFT_T + BLINDING_T, 2),
                           "source": "A.14 Διάγραμμα εκσκαφών / excavation diagram"},
            "structure": {"system": "RC frame with walls", "concrete": "C25/30", "steel": "B500C", "code": "EAK 2000/2003", "seismic_zone": "II",
                          "a_g": 0.24, "soil": "B", "T1": 0.15, "T2": 0.60, "gamma_I": 1.0, "q": 3.0, "theta": 1.0, "Tx": 0.40, "Ty": 0.40,
                          "beta0": 2.5, "Rd": 1.962},
            "structural": structural.load_demo(),
            "synthetic_geometry": True, "demo_rev": DEMO_REV, "walls_net_of_openings": True,
            "openings_source": "Κατόψεις Αρχιτεκτονικα.dxf / floor plans of the permit drawings (app/data/openings.json)",
        },
        "storeys": storeys,
        "apartments": APARTMENTS,
        "areas": AREAS,
        "elements": elements,
        "geometry3d": meta3d,
        "schedule": {"tasks": gantt, "start_date": "2023-04-03"},
        "layer_map": {},
    }
    project["meta"]["location"]["address"] = "Ποταμού 4, Ο.Τ. 426, Νέα Κηφισιά"
    project["properties"] = fm.demo_properties()
    return project, meshes
