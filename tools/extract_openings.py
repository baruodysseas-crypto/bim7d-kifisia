"""Extract openings (windows, balcony doors, doors), interior partitions and registration from the architectural DXF (Αρχιτεκτονικα.dxf)
of the demo building and write app/data/openings.json.

Run once (needs ezdxf + shapely):   python tools/extract_openings.py "path/Αρχιτεκτονικα.dxf"
How it works (all coordinates in the local frame of app/demo.py: x along the street front, y toward the plot back, z = 0 at the ground-floor top):
  * every floor plan is registered to the local frame with the outer masonry faces of the plan (OFFSETS below);
  * walls = pairs of parallel wall lines (layers 0.5/0.50) closer than 0.30 m; a gap in a wall line pair is an opening;
  * door swings are the ARC entities of layer 0.18: hinge = arc centre, leaf width = radius, the closed leaf is found from the wall behind it;
  * window width/position come from the wall gaps (confirmed with the dimension chains of the plans); heights and sills come from the window
    schedule of the energy study (windows.json) and from the glass panes (layer GYALI) of the elevations: head = +2.50 m above the floor.
"""
from __future__ import annotations

import collections
import json
import math
import sys
from pathlib import Path

import ezdxf
from shapely.geometry import Point, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
BANDS = {"basement": (1773.7, 1796.7), "ground": (1751.1, 1770.7), "first": (1727.1, 1747.0), "second": (1702.9, 1722.8), "attic": (1679.0, 1699.2)}
OFFSETS = {"basement": (2270.69, 1774.62), "ground": (2270.05, 1748.598), "first": (2270.05, 1725.25), "second": (2270.05, 1701.03), "attic": (2270.05, 1677.40)}
KINDS = {"window": ("Παράθυρο", "Window"), "balcony_door": ("Μπαλκονόπορτα", "Balcony door"), "entrance": ("Είσοδος κτιρίου", "Building entrance"),
         "garage_door": ("Πόρτα γκαράζ", "Garage door")}

# Exterior openings read from the plans (centre along the wall, width of the frame, head height of the frame above the floor).
# n = outward normal, line = coordinate of the wall plane, c = centre along the wall, w x h = frame size (window schedule), sill above floor finish.
# (st, n, line, c, w, h, sill, type)
EXT = [
    # ---- basement (retaining walls): light-well windows and the garage door
    ("basement", (-1, 0), 0.0, 7.48, 2.3, 2.4, 0.2, "window"),
    ("basement", (0, 1), 20.35, 4.39, 2.0, 1.2, 1.3, "window"), ("basement", (0, 1), 20.35, 13.91, 2.0, 1.2, 1.3, "window"),
    ("basement", (1, 0), 18.30, 7.38, 3.1, 2.4, 0.0, "garage_door"),
    # ---- ground floor
    ("ground", (-1, 0), 0.0, 10.65, 1.6, 1.5, 1.0, "window"), ("ground", (-1, 0), 0.0, 14.00, 1.6, 1.5, 1.0, "window"),
    ("ground", (1, 0), 18.30, 10.65, 1.6, 1.5, 1.0, "window"), ("ground", (1, 0), 18.30, 14.00, 1.6, 1.5, 1.0, "window"),
    ("ground", (-1, 0), 1.5, 16.45, 0.6, 1.3, 1.2, "window"), ("ground", (-1, 0), 1.5, 18.55, 1.6, 1.5, 1.0, "window"),
    ("ground", (1, 0), 16.8, 16.45, 0.6, 1.3, 1.2, "window"), ("ground", (1, 0), 16.8, 18.55, 1.6, 1.5, 1.0, "window"),
    ("ground", (-1, 0), 11.05, 17.15, 0.6, 1.5, 1.0, "window"), ("ground", (1, 0), 7.25, 17.15, 0.6, 1.5, 1.0, "window"),
    ("ground", (0, 1), 16.65, 8.30, 0.6, 1.5, 1.0, "window"), ("ground", (0, 1), 16.65, 10.00, 0.6, 1.5, 1.0, "window"),
    ("ground", (0, -1), 5.25, 3.625, 5.25, 2.5, 0.0, "balcony_door"), ("ground", (0, -1), 5.25, 14.675, 5.25, 2.5, 0.0, "balcony_door"),
    ("ground", (0, -1), 6.85, 7.80, 0.8, 2.5, 0.0, "entrance"), ("ground", (0, -1), 6.85, 9.15, 1.2, 2.5, 0.0, "entrance"), ("ground", (0, -1), 6.85, 10.50, 0.8, 2.5, 0.0, "entrance"),
    # ---- first floor
    ("first", (-1, 0), 1.5, 13.77, 0.6, 1.3, 1.2, "window"), ("first", (1, 0), 16.8, 13.75, 0.6, 1.3, 1.2, "window"),
    ("first", (1, 0), 16.8, 16.25, 1.2, 2.5, 0.0, "balcony_door"),
    ("first", (0, 1), 13.10, 0.85, 0.6, 1.5, 1.0, "window"), ("first", (0, 1), 13.10, 17.50, 0.6, 1.3, 1.2, "window"),
    ("first", (-1, 0), 11.05, 15.18, 0.6, 1.5, 1.0, "window"), ("first", (-1, 0), 11.05, 17.07, 0.6, 1.5, 1.0, "window"),
    ("first", (0, 1), 17.70, 3.65, 1.8, 2.5, 0.0, "balcony_door"), ("first", (0, 1), 17.70, 14.65, 1.8, 0.6, 1.9, "window"),
    ("first", (0, -1), 6.90, 2.185, 2.43, 2.5, 0.0, "balcony_door"), ("first", (0, -1), 6.90, 5.01, 2.43, 2.5, 0.0, "balcony_door"),
    ("first", (0, -1), 6.90, 14.65, 5.25, 2.5, 0.0, "balcony_door"),
    ("first", (1, 0), 18.30, 10.65, 1.6, 1.5, 1.0, "window"),
    # ---- second floor
    ("second", (-1, 0), 0.0, 7.15, 2.5, 2.5, 0.0, "balcony_door"), ("second", (1, 0), 18.30, 7.15, 2.5, 2.5, 0.0, "balcony_door"),
    ("second", (-1, 0), 0.0, 10.65, 1.6, 2.5, 0.0, "balcony_door"), ("second", (1, 0), 18.30, 10.65, 1.6, 2.5, 0.0, "balcony_door"),
    ("second", (-1, 0), 1.5, 13.75, 0.6, 1.3, 1.2, "window"), ("second", (1, 0), 16.8, 13.75, 0.6, 1.5, 1.0, "window"),
    ("second", (1, 0), 7.25, 13.78, 0.8, 2.5, 0.0, "balcony_door"), ("second", (-1, 0), 11.05, 13.80, 0.8, 2.5, 0.0, "balcony_door"),
    ("second", (0, -1), 5.25, 3.625, 5.25, 2.5, 0.0, "balcony_door"), ("second", (0, -1), 5.25, 14.675, 5.25, 2.5, 0.0, "balcony_door"),
    ("second", (0, 1), 17.70, 3.65, 1.8, 2.5, 0.0, "balcony_door"), ("second", (0, 1), 17.70, 14.65, 1.8, 2.5, 0.0, "balcony_door"),
    # ---- attic (gable walls)
    ("attic", (0, -1), 5.25, 2.185, 2.43, 1.7, 0.0, "window"), ("attic", (0, -1), 5.25, 5.015, 2.43, 1.7, 0.0, "window"),
    ("attic", (0, -1), 5.25, 13.235, 2.43, 1.7, 0.0, "window"), ("attic", (0, -1), 5.25, 16.065, 2.43, 1.7, 0.0, "window"),
    ("attic", (0, 1), 13.10, 2.15, 0.6, 1.15, 0.8, "window"), ("attic", (0, 1), 13.10, 3.65, 1.8, 2.05, 0.0, "window"),
    ("attic", (0, 1), 13.10, 14.66, 1.8, 2.05, 0.0, "window"), ("attic", (0, 1), 13.10, 16.18, 0.6, 1.15, 0.8, "window"),
]
# window schedule rows that are heated openings of the thermal study (all but the common areas): matched by size, in order
HEATED_EXCLUDE = {("ground", "entrance"), ("basement", "garage_door")}


def load_lines(doc):
    msp = doc.modelspace()
    segs: dict = collections.defaultdict(list)
    arcs: dict = collections.defaultdict(list)

    def band_of(y):
        for k, (a, b) in BANDS.items():
            if a - 0.5 <= y <= b + 0.5:
                return k
        return None

    for e in msp:
        t, l = e.dxftype(), e.dxf.layer
        try:
            if l in ("0.5", "0.50"):
                if t == "LINE":
                    a, b = e.dxf.start, e.dxf.end
                    k = band_of((a.y + b.y) / 2)
                    if k:
                        segs[k].append(((a.x, a.y), (b.x, b.y)))
                elif t == "LWPOLYLINE":
                    pts = [(p[0], p[1]) for p in e.get_points("xy")]
                    if e.closed:
                        pts.append(pts[0])
                    for i in range(len(pts) - 1):
                        k = band_of((pts[i][1] + pts[i + 1][1]) / 2)
                        if k:
                            segs[k].append((pts[i], pts[i + 1]))
            elif l == "0.18" and t == "ARC":
                c = e.dxf.center
                k = band_of(c.y)
                if k:
                    arcs[k].append((c.x, c.y, e.dxf.radius, e.dxf.start_angle, e.dxf.end_angle))
        except Exception:
            pass
    return segs, arcs


def wall_union(segs, off):
    ox, oy = off
    H, V = [], []
    for p, q in segs:
        p = (p[0] - ox, p[1] - oy)
        q = (q[0] - ox, q[1] - oy)
        if abs(p[1] - q[1]) < 2e-3 and abs(p[0] - q[0]) > 0.05:
            H.append(((p[1] + q[1]) / 2, min(p[0], q[0]), max(p[0], q[0])))
        elif abs(p[0] - q[0]) < 2e-3 and abs(p[1] - q[1]) > 0.05:
            V.append(((p[0] + q[0]) / 2, min(p[1], q[1]), max(p[1], q[1])))

    def pairs(L, lo=0.07, hi=0.30):
        out, L = [], sorted(L)
        for i, a in enumerate(L):
            for b in L[i + 1:]:
                if b[0] - a[0] > hi:
                    break
                if b[0] - a[0] < lo:
                    continue
                s, e = max(a[1], b[1]), min(a[2], b[2])
                if e - s > 0.05:
                    out.append((a[0], b[0], s, e))
        return out

    R = [box(x0, y0, x1, y1) for (y0, y1, x0, x1) in pairs(H)] + [box(x0, y0, x1, y1) for (x0, x1, y0, y1) in pairs(V)]
    return unary_union(R)


def rects_of(poly):
    """Axis-aligned rectangles of a rectilinear polygon (strip decomposition, merged along y)."""
    out = []
    for g in (poly.geoms if hasattr(poly, "geoms") else [poly]):
        if g.is_empty or g.geom_type != "Polygon":
            continue
        xs = sorted({round(c[0], 3) for r in [g.exterior, *g.interiors] for c in r.coords})
        ys = sorted({round(c[1], 3) for r in [g.exterior, *g.interiors] for c in r.coords})
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
                    strips.append((run[0], ys[j], run[1], ys[j + 1]))
                    run = None
            if run is not None:
                strips.append((run[0], ys[j], run[1], ys[j + 1]))
        strips.sort(key=lambda r: (r[0], r[2], r[1]))
        merged = []
        for r in strips:
            if merged and merged[-1][0] == r[0] and merged[-1][2] == r[2] and abs(merged[-1][3] - r[1]) < 1e-6:
                merged[-1] = (r[0], merged[-1][1], r[2], r[3])
            else:
                merged.append(r)
        out += merged
    return out


def main(dxf_path: str) -> None:
    sys.path.insert(0, str(ROOT))
    from app import demo
    doc = ezdxf.readfile(dxf_path)
    segs, arcs = load_lines(doc)
    result: dict = {"source": "Αρχιτεκτονικα.dxf (plans of the permit drawings)", "offsets": OFFSETS, "ext": [], "doors": {}, "partitions": {}}
    pool = json.loads((ROOT / "app/data/windows.json").read_text(encoding="utf-8"))
    used: set[int] = set()
    for (st, n, line, c, w, h, sill, typ) in EXT:
        sched = None
        if (st, typ) not in HEATED_EXCLUDE:
            for row in pool:
                if row["id"] not in used and abs(row["w"] - w) < 0.011 and abs(row["h"] - h) < 0.011:
                    sched = row
                    used.add(row["id"])
                    break
        result["ext"].append({"storey": st, "type": typ, "n": list(n), "line": line, "c": c, "w": w, "h": h, "sill": sill,
                              "sched_id": sched["id"] if sched else None, "U": sched["U"] if sched else None, "sched_area": sched["area"] if sched else None})
    result["unmatched_schedule_ids"] = [r["id"] for r in pool if r["id"] not in used]
    for st in ("basement", "ground", "first", "second", "attic"):
        off = OFFSETS[st]
        U = wall_union(segs[st], off)
        foot = demo._poly(demo.G[st])
        inner = foot.buffer(-0.28)
        part = U.intersection(inner)
        rects = [r for r in rects_of(part)]
        keep = []
        for (x0, y0, x1, y1) in rects:
            t, L = min(x1 - x0, y1 - y0), max(x1 - x0, y1 - y0)
            if L < 0.35 or (t > 0.34 and L < 0.9):          # columns / stubs
                continue
            keep.append([round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)])
        result["partitions"][st] = keep
        # doors from the swing arcs
        seen = set()
        doors = []
        ox, oy = off
        for (cx, cy, r, a0, a1) in arcs[st]:
            hx, hy = round(cx - ox, 3), round(cy - oy, 3)
            key = (round(hx, 1), round(hy, 1), round(r, 2))
            if key in seen:
                continue
            seen.add(key)
            best = None
            for ang in (a0, a1):
                d = (round(math.cos(math.radians(ang))), round(math.sin(math.radians(ang))))
                cov = sum(U.contains(Point(hx + d[0] * (r + o), hy + d[1] * (r + o))) for o in (0.05, 0.1, 0.15, 0.2, 0.3))
                cov_h = sum(U.contains(Point(hx - d[0] * o, hy - d[1] * o)) for o in (0.05, 0.1, 0.15))
                sc = cov + 0.5 * cov_h
                if best is None or sc > best[0]:
                    best = (sc, d, ang)
            d = best[1]
            mid = (hx + d[0] * r / 2, hy + d[1] * r / 2)
            if st == "ground" and math.hypot(hx - 8.54, hy - 6.85) < 0.3:        # the main entrance (listed with the exterior openings)
                continue
            kind = "apartment_entrance" if abs(r - 0.87) < 0.02 and st in ("ground", "first", "second") else "interior"
            doors.append({"hinge": [hx, hy], "r": round(r, 3), "dir": list(d), "mid": [round(mid[0], 3), round(mid[1], 3)], "type": kind})
        result["doors"][st] = doors
    out = ROOT / "app/data/openings.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=0), encoding="utf-8")
    cnt = collections.Counter((o["storey"], o["type"]) for o in result["ext"])
    print("ext openings:", len(result["ext"]), dict(cnt))
    print("unmatched schedule ids:", result["unmatched_schedule_ids"])
    for st in result["partitions"]:
        pr = result["partitions"][st]
        print(st, "partition rects", len(pr), "total length m", round(sum(max(r[2] - r[0], r[3] - r[1]) for r in pr), 1),
              "doors", collections.Counter(d["type"] for d in result["doors"][st]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT.parent / "Αρχιτεκτονικα.dxf"))
