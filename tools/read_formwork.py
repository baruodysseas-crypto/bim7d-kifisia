"""Read the structural formwork plans (ξυλότυποι, vector PDF, 1:50) of the Kifisia project:
columns (position, outline, section, reinforcement) and beams (axis, section, reinforcement), one sheet per level.
Output: app/data/frame_kifisia.json (coordinates in metres, in the frame of each sheet: x right, y up)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pymupdf
from shapely.geometry import box as sbox
from shapely.ops import unary_union

PT_M = 0.0254 / 72 * 50          # 1 pt on paper at 1:50 -> metres
GREEK_K = "ΚK"


def norm(t: str) -> str:
    return t.replace("Κ", "K").replace("Δ", "Δ").strip()


def page_items(path: Path):
    p = pymupdf.open(str(path))[0]
    M = p.rotation_matrix
    texts = []
    for b in p.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            t = "".join(s["text"] for s in l["spans"]).strip()
            if not t:
                continue
            r = pymupdf.Rect(l["bbox"]) * M
            dx, dy = l["dir"]
            # direction in the displayed (rotated) page: unrot (1,0) -> (0,-1); (0,1) -> (1,0)
            ddir = (dy, -dx)
            texts.append({"t": norm(t), "r": r, "dir": ddir, "size": l["spans"][0]["size"]})
    fills, segs = [], []
    for d in p.get_drawings():
        if d.get("fill") is not None and sum(d["fill"]) < 0.05 and len(d["items"]) <= 12:
            fills.append(d["rect"] * M)
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1] * M, it[2] * M
                segs.append((a.x, a.y, b.x, b.y, d.get("width") or 0.0))
            elif it[0] == "re":
                r = it[1] * M
                segs += [(r.x0, r.y0, r.x1, r.y0, 0), (r.x1, r.y0, r.x1, r.y1, 0), (r.x1, r.y1, r.x0, r.y1, 0), (r.x0, r.y1, r.x0, r.y0, 0)]
    return p, texts, fills, segs


COL_LABEL = re.compile(r"^K(\d+)$")
COL_SCHED = re.compile(r"^K(\d+)\s*(\d+)/(\d+)(?:/(\d+))?$")
BAR = re.compile(r"^(\d+)Φ(\d+)(?:\s*\+\s*(\d+)Φ(\d+))?$")
STIR = re.compile(r"^Σ\s*Φ(\d+)/(\d+)")
BEAM = re.compile(r"^Δ(\d+)\s+(\d+)/(\d+)")
BEAM_RF = re.compile(r"π(\d+)Φ(\d+)(?:\+(\d+)Φ(\d+))?,\s*κ(\d+)Φ(\d+)(?:\+(\d+)Φ(\d+))?")


def read_sheet(path: Path) -> dict:
    p, texts, fills, segs = page_items(path)
    W = p.rect.width
    # --- plan region: the plan labels K<n> (big, plain) – the schedule labels carry the dimensions
    plan_k = [t for t in texts if COL_LABEL.match(t["t"]) and t["size"] > 14]
    sched = [t for t in texts if COL_SCHED.match(t["t"].replace(" ", " ")) or (COL_LABEL.match(t["t"]) is None and re.match(r"^K\d+\s", t["t"]))]
    # column schedule (left of the plan): "K5 55/70/25" or "K10" + "55/70/25" on the same line; bars and stirrups on the lines below
    def is_sched(t):
        return any(abs(u["r"].x0 - t["r"].x0) < 3 and 0 <= u["r"].y0 - t["r"].y1 < 6 and re.match(r"^\d+Φ\d+", u["t"]) for u in texts)
    cols = {}
    sched_ids = set()
    for t in texts:
        if t["size"] < 14 or not t["t"].startswith("K") or not is_sched(t):
            continue
        sched_ids.add(id(t))
        m = COL_SCHED.match(t["t"])
        if m:
            lab, dims = m.group(1), [m.group(2), m.group(3)] + ([m.group(4)] if m.group(4) else [])
        else:
            m2 = re.match(r"^K(\d+)$", t["t"])
            if not m2:
                continue
            right = [u for u in texts if re.match(r"^\d+/\d+(/\d+)?$", u["t"]) and 0 <= u["r"].x0 - t["r"].x1 < 20 and abs(u["r"].y1 - t["r"].y1) < 6]
            if not right:
                continue
            lab, dims = m2.group(1), right[0]["t"].split("/")
        below = sorted([u for u in texts if abs(u["r"].x0 - t["r"].x0) < 3 and 0 <= u["r"].y0 - t["r"].y1 < 30], key=lambda u: u["r"].y0)
        bars = next((u["t"] for u in below if re.match(r"^\d+Φ\d+", u["t"])), None)
        stir = next((u["t"] for u in below if STIR.match(u["t"])), None)
        cols["K" + lab] = {"dims_cm": [int(x) for x in dims], "bars": bars, "stirrups": stir}
    plan_k = [t for t in plan_k if id(t) not in sched_ids]
    px0 = min(t["r"].x0 for t in plan_k) - 60
    px1 = max(t["r"].x1 for t in plan_k) + 60
    py0 = min(t["r"].y0 for t in plan_k) - 60
    py1 = max(t["r"].y1 for t in plan_k) + 60
    fills = [r for r in fills if r.x0 > px0 and r.x1 < px1 and r.y0 > py0 and r.y1 < py1]
    # --- plan columns: union of black filled rectangles, labelled by the nearest plan label
    polys = unary_union([sbox(r.x0, r.y0, r.x1, r.y1).buffer(0.6) for r in fills if r.width < 200 and r.height < 200])
    geoms = list(getattr(polys, "geoms", [polys]))
    labels = [t for t in plan_k]
    out_cols = []
    used = set()
    for g in geoms:
        g = g.buffer(-0.6)
        if g.is_empty or g.area < 30:
            continue
        c = g.centroid
        best = min(labels, key=lambda t: (t["r"].x0 + t["r"].x1) / 2 * 0 + g.distance(sbox(t["r"].x0, t["r"].y0, t["r"].x1, t["r"].y1)), default=None)
        if best is None:
            continue
        d = g.distance(sbox(best["r"].x0, best["r"].y0, best["r"].x1, best["r"].y1))
        if d > 40:
            continue
        name = best["t"]
        ring = [(round(x * PT_M, 3), round(-y * PT_M, 3)) for x, y in g.simplify(0.3).exterior.coords]
        out_cols.append({"id": name, "x": round(c.x * PT_M, 3), "y": round(-c.y * PT_M, 3), "outline": ring, "area_m2": round(g.area * PT_M ** 2, 4),
                         "bbox_m": [round((g.bounds[2] - g.bounds[0]) * PT_M, 3), round((g.bounds[3] - g.bounds[1]) * PT_M, 3)]})
        used.add(name)
    # --- beams: label "Δn b/h,..." with the reinforcement line next to it; the axis is the closest pair of parallel lines ~b apart
    beams = []
    for t in texts:
        m = BEAM.match(t["t"])
        if not m:
            continue
        num, b, h = m.group(1), int(m.group(2)), int(m.group(3))
        horiz = abs(t["dir"][0]) > 0.5
        cx, cy = (t["r"].x0 + t["r"].x1) / 2, (t["r"].y0 + t["r"].y1) / 2
        rf = None
        for u in texts:
            if BEAM_RF.search(u["t"]) and abs(((u["r"].x0 + u["r"].x1) / 2) - cx) < (60 if horiz else 30) and abs(((u["r"].y0 + u["r"].y1) / 2) - cy) < (30 if horiz else 60):
                if rf is None or abs((u["r"].y0 if horiz else u["r"].x0) - (t["r"].y0 if horiz else t["r"].x0)) < abs((rf["r"].y0 if horiz else rf["r"].x0) - (t["r"].y0 if horiz else t["r"].x0)):
                    rf = u
        stir = None
        for u in texts:
            if STIR.match(u["t"]) and abs(((u["r"].x0 + u["r"].x1) / 2) - cx) < (60 if horiz else 30) and abs(((u["r"].y0 + u["r"].y1) / 2) - cy) < (30 if horiz else 60):
                stir = u["t"]
                break
        wpt = b / 100 / PT_M
        # candidate lines parallel to the label
        cand = []
        for (x0, y0, x1, y1, lw) in segs:
            if horiz and abs(y1 - y0) < 0.3 and abs(x1 - x0) > 20 and min(x0, x1) - 5 <= cx <= max(x0, x1) + 5 and abs(y0 - cy) < 45:
                cand.append((y0, min(x0, x1), max(x0, x1)))
            if not horiz and abs(x1 - x0) < 0.3 and abs(y1 - y0) > 20 and min(y0, y1) - 5 <= cy <= max(y0, y1) + 5 and abs(x0 - cx) < 45:
                cand.append((x0, min(y0, y1), max(y0, y1)))
        best = None
        for i, (o1, s1, e1) in enumerate(cand):
            for (o2, s2, e2) in cand[i + 1:]:
                if abs(abs(o2 - o1) - wpt) < 1.2:
                    mid = (o1 + o2) / 2
                    score = abs(mid - (cy if horiz else cx))
                    span = (max(s1, s2), min(e1, e2))
                    if span[1] - span[0] < 10:
                        continue
                    if best is None or score < best[0]:
                        best = (score, mid, span)
        rec = {"id": "Δ" + num, "b_cm": b, "h_cm": h, "dir": "x" if horiz else "y", "label": t["t"], "rebar": rf["t"] if rf else None, "stirrups": stir}
        if best:
            _, mid, (s0, s1) = best
            if horiz:
                rec["a"], rec["b"] = [round(s0 * PT_M, 3), round(-mid * PT_M, 3)], [round(s1 * PT_M, 3), round(-mid * PT_M, 3)]
            else:
                rec["a"], rec["b"] = [round(mid * PT_M, 3), round(-s0 * PT_M, 3)], [round(mid * PT_M, 3), round(-s1 * PT_M, 3)]
        else:
            rec["label_at"] = [round(cx * PT_M, 3), round(-cy * PT_M, 3)]
        beams.append(rec)
    title = " ".join(t["t"] for t in texts if "ΞΥΛΟΤΥΠΟΣ" in t["t"])
    return {"sheet": path.name, "title": title, "schedule": cols, "columns": sorted(out_cols, key=lambda c: int(c["id"][1:])), "beams": beams,
            "missing_in_plan": sorted(set(cols) - used, key=lambda k: int(k[1:]))}


if __name__ == "__main__":
    out = {}
    for arg in sys.argv[1:]:
        key, path = arg.split("=", 1)
        out[key] = read_sheet(Path(path))
        s = out[key]
        print(key, s["title"], "| schedule", len(s["schedule"]), "| plan columns", len(s["columns"]), "| beams", len(s["beams"]), "located", sum(1 for b in s["beams"] if "a" in b), "| missing", s["missing_in_plan"])
    Path("/tmp/frame_raw.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
