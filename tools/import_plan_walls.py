"""Walls of the architectural floor plans (DXF of the permit drawings) → app/data/plan_walls.json.

Each wall in the DXF is drawn as two parallel lines (layers 0.50 / 0.5, magenta); columns and RC walls are closed outlines on
layer «ΠΡΟΤΕΙΝΟΜΕΝΟΣ ΦΟ» (cyan, hatched). Every pair of parallel lines 4–45 cm apart with nothing between them becomes a wall
rectangle, in the local frame of the model (x along the front, y towards the back, metres). The plans are stacked in the DXF:
each storey is located by its Π-shaped lift wall (K15, 1.90 × 1.95 m), whose corner is at (9.40, 11.15) in the model.

usage:  python tools/import_plan_walls.py Drawing1.dxf
"""
import json
import sys
from pathlib import Path

import ezdxf

LIFT_CORNER = (9.40, 11.15)
# DXF position of the lift wall (lower-left corner) of each storey's plan (from top to bottom of the drawing)
ANCHORS = {"basement": (2687.244, 1928.19), "ground": (2687.69, 1898.747)}


def load(path):
    d = ezdxf.readfile(path)
    segs, cols = [], []
    for e in d.modelspace():
        L = e.dxf.layer
        if L in ("0.50", "0.5"):
            if e.dxftype() == "LINE":
                segs.append((e.dxf.start.x, e.dxf.start.y, e.dxf.end.x, e.dxf.end.y))
            elif e.dxftype() == "LWPOLYLINE":
                p = [v[:2] for v in e.get_points()]
                if e.closed:
                    p = p + [p[0]]
                segs += [(a[0], a[1], b[0], b[1]) for a, b in zip(p[:-1], p[1:])]
        elif L == "ΠΡΟΤΕΙΝΟΜΕΝΟΣ ΦΟ" and e.dxftype() == "LWPOLYLINE":
            cols.append([v[:2] for v in e.get_points()])
    return segs, cols


def wall_rects(segs, X0, Y0, region=(-2.0, -0.5, 20.5, 22.5), tmin=0.04, tmax=0.45):
    H, V = [], []
    for x1, y1, x2, y2 in segs:
        x1, x2, y1, y2 = x1 - X0, x2 - X0, y1 - Y0, y2 - Y0
        if not (region[0] < min(x1, x2) and max(x1, x2) < region[2] and region[1] < min(y1, y2) and max(y1, y2) < region[3]):
            continue
        if abs(y1 - y2) < 2e-3 and abs(x1 - x2) > 1e-3:
            H.append((min(x1, x2), max(x1, x2), (y1 + y2) / 2))
        elif abs(x1 - x2) < 2e-3 and abs(y1 - y2) > 1e-3:
            V.append((min(y1, y2), max(y1, y2), (x1 + x2) / 2))
    rects = []
    for S, horiz in ((H, True), (V, False)):
        S = sorted(S, key=lambda s: s[2])
        for i, a in enumerate(S):
            for b in S[i + 1:]:
                g = b[2] - a[2]
                if g < tmin:
                    continue
                if g > tmax:
                    break
                lo, hi = max(a[0], b[0]), min(a[1], b[1])
                if hi - lo < 0.03:
                    continue
                if any(a[2] + 1e-3 < c[2] < b[2] - 1e-3 and min(c[1], hi) - max(c[0], lo) > 0.02 for c in S):
                    continue
                r = (lo, a[2], hi, b[2]) if horiz else (a[2], lo, b[2], hi)
                rects.append([round(v, 4) for v in r])
    return rects


def main(path):
    segs, cols = load(path)
    out = {"source": f"{Path(path).name} – κατόψεις της άδειας (τοίχοι: layers 0.50/0.5, υποστυλώματα/τοιχεία: ΠΡΟΤΕΙΝΟΜΕΝΟΣ ΦΟ)", "storeys": {}}
    for st, (ax, ay) in ANCHORS.items():
        X0, Y0 = ax - LIFT_CORNER[0], ay - LIFT_CORNER[1]
        out["storeys"][st] = {"offset": [round(X0, 4), round(Y0, 4)], "walls": wall_rects(segs, X0, Y0)}
    dst = Path(__file__).resolve().parents[1] / "app" / "data" / "plan_walls.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print({k: len(v["walls"]) for k, v in out["storeys"].items()}, "→", dst)


if __name__ == "__main__":
    main(sys.argv[1])
