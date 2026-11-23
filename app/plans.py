"""Inspection of 2D drawings (DXF / PDF): layers, closed-polyline areas, text labels, sheet titles, scales, thumbnails.

Used to document the inputs of a project and to cross-check the 3D model against the drawings
(areas per storey, scale, title blocks) - "ταύτιση σχεδίων με 3D"."""
from __future__ import annotations

import collections
import math
import re
from pathlib import Path
from typing import Any

_SCALE_RE = re.compile(r"(?:ΚΛΙΜΑΚΑ|SCALE|Κλίμακα)\s*[:=]?\s*(1\s*[:/]\s*\d{1,4})", re.I)
_LEVEL_RE = re.compile(r"(ΚΑΤΟΨΗ|ΚΑΤΟΨΕΙΣ|ΤΟΜΗ|ΤΟΜΕΣ|ΟΨΗ|ΟΨΕΙΣ|ΥΠΟΓΕΙΟ|ΙΣΟΓΕΙΟ|ΟΡΟΦΟΣ|ΣΟΦΙΤΑ|ΔΩΜΑ|ΘΕΜΕΛΙΩΣΗ|PLAN|SECTION|ELEVATION|BASEMENT|GROUND|FLOOR|ROOF)[^\n]{0,40}", re.I)


def polygon_area(pts: list[tuple[float, float]]) -> float:
    a = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


def inspect_dxf(path: Path) -> dict[str, Any]:
    import ezdxf
    from ezdxf import bbox

    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    cnt = collections.Counter(e.dxftype() for e in msp)
    layers = collections.Counter(e.dxf.layer for e in msp)
    try:
        ext = bbox.extents(msp, fast=True)
        size = [float(ext.size.x), float(ext.size.y)]
    except Exception:
        size = [0.0, 0.0]
    insunits = doc.header.get("$INSUNITS", 0)
    unit_to_m = {0: None, 1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}.get(insunits)
    if unit_to_m is None:                                    # guess from the drawing size (a building is 5..200 m)
        m = max(size) or 1.0
        unit_to_m = 0.001 if m > 5000 else 0.01 if m > 500 else 1.0
    closed = []
    texts: list[str] = []
    for e in msp:
        t = e.dxftype()
        try:
            if t == "LWPOLYLINE" and e.closed and len(e) >= 3:
                pts = [(p[0], p[1]) for p in e.get_points("xy")]
                closed.append((e.dxf.layer, polygon_area(pts) * unit_to_m ** 2))
            elif t in ("TEXT", "MTEXT"):
                s = e.dxf.text if t == "TEXT" else e.plain_text()
                if s and len(s) < 200:
                    texts.append(s.strip())
        except Exception:
            continue
    big = sorted(closed, key=lambda x: -x[1])[:12]
    by_layer = collections.defaultdict(float)
    for l, a in closed:
        by_layer[l] += a
    scales = sorted({m.group(1).replace(" ", "") for s in texts for m in [_SCALE_RE.search(s)] if m})
    titles = sorted({m.group(0).strip() for s in texts for m in [_LEVEL_RE.search(s.upper())] if m})[:20]
    return {"kind": "dxf", "name": path.name, "dxf_version": doc.dxfversion, "units_to_m": unit_to_m, "entities": sum(cnt.values()),
            "entity_types": dict(cnt.most_common(8)), "layers": [{"layer": l, "entities": n, "closed_area_m2": round(by_layer.get(l, 0.0), 1)} for l, n in layers.most_common(40)],
            "size_m": [round(size[0] * unit_to_m, 1), round(size[1] * unit_to_m, 1)], "largest_closed_polylines": [{"layer": l, "area_m2": round(a, 1)} for l, a in big],
            "scales": scales, "titles": titles, "texts": len(texts)}


def inspect_pdf(path: Path, thumb_dir: Path | None = None, max_pages: int = 40) -> dict[str, Any]:
    import fitz

    doc = fitz.open(str(path))
    pages = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        text = page.get_text("text") or ""
        scales = sorted({m.group(1).replace(" ", "") for m in _SCALE_RE.finditer(text)})
        titles = [m.group(0).strip() for m in _LEVEL_RE.finditer(text.upper())][:3]
        thumb = None
        if thumb_dir is not None:
            thumb_dir.mkdir(parents=True, exist_ok=True)
            name = f"{path.stem}_p{i + 1}.png"
            pix = page.get_pixmap(dpi=40)
            pix.save(str(thumb_dir / name))
            thumb = name
        pages.append({"page": i + 1, "width_mm": round(page.rect.width * 25.4 / 72), "height_mm": round(page.rect.height * 25.4 / 72), "chars": len(text),
                      "scales": scales, "titles": titles, "text_head": " ".join(text.split())[:140], "thumb": thumb, "has_text": len(text.strip()) > 20})
    n = len(doc)
    doc.close()
    return {"kind": "pdf", "name": path.name, "pages_total": n, "pages": pages, "scanned": all(not p["has_text"] for p in pages) if pages else False}


def inspect(path: Path, thumb_dir: Path | None = None) -> dict[str, Any]:
    ext = path.suffix.lower()
    if ext == ".dxf":
        return inspect_dxf(path)
    if ext == ".pdf":
        return inspect_pdf(path, thumb_dir)
    return {"kind": ext.lstrip("."), "name": path.name}


def reconcile(project: dict[str, Any], plan_infos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Consistency checks between the 3D model, the declared data and the drawings. Each check: id, status ok|warn|info, text (el/en)."""
    checks = []
    els = project["elements"]
    slabs = [e for e in els if e["kind"] == "slab"]
    model_gfa = sum(e["qty"].get("plan_area_m2", 0.0) for e in slabs if e.get("storey") not in (None,)) if slabs else 0.0
    declared = float(project["meta"].get("gfa_m2") or 0.0)
    if declared and model_gfa:
        rel = (model_gfa - declared) / declared
        checks.append({"id": "gfa", "status": "ok" if abs(rel) < 0.15 else "warn", "value": round(model_gfa, 1), "ref": declared,
                       "el": f"Επιφάνεια πλακών μοντέλου {model_gfa:,.0f} m² (με υπόγειο, εξώστες και δώματα) έναντι συνολικής επιφάνειας ορόφων {declared:,.0f} m² με υπόγειο ({rel:+.0%}). Η δόμηση Σ.Δ. δεν περιλαμβάνει υπόγειο και σοφίτα.",
                       "en": f"Model slab area {model_gfa:,.0f} m² (incl. basement, balconies and terraces) vs total floor area {declared:,.0f} m² incl. basement ({rel:+.0%}). The building-factor area excludes basement and attic."})
    nost = [e for e in els if e["kind"] not in ("site", "vegetation") and not e.get("storey")]
    checks.append({"id": "storeys", "status": "ok" if not nost else "warn", "value": len(nost), "el": f"{len(nost)} στοιχεία χωρίς όροφο.", "en": f"{len(nost)} elements without a storey."})
    other = [e for e in els if e["kind"] == "other"]
    checks.append({"id": "other", "status": "ok" if len(other) < 0.05 * max(len(els), 1) else "warn", "value": len(other), "el": f"{len(other)} στοιχεία ταξινομημένα ως «άλλο».", "en": f"{len(other)} elements classified as 'other'."})
    dxfs = [p for p in plan_infos if p["kind"] == "dxf"]
    for p in dxfs:
        if p["largest_closed_polylines"]:
            a = p["largest_closed_polylines"][0]["area_m2"]
            checks.append({"id": f"dxf:{p['name']}", "status": "info", "value": a, "el": f"{p['name']}: μεγαλύτερο κλειστό περίγραμμα {a:,.0f} m² (έλεγχος με επιφάνεια ορόφου).",
                           "en": f"{p['name']}: largest closed outline {a:,.0f} m² (compare with storey area)."})
    pdfs = [p for p in plan_infos if p["kind"] == "pdf"]
    if pdfs:
        scales = sorted({s for p in pdfs for pg in p["pages"] for s in pg["scales"]})
        checks.append({"id": "pdf_scales", "status": "info", "value": scales, "el": f"{len(pdfs)} αρχεία PDF με κλίμακες: {', '.join(scales) or 'δεν βρέθηκαν'}.",
                       "en": f"{len(pdfs)} PDF files with scales: {', '.join(scales) or 'none found'}."})
    if not plan_infos:
        checks.append({"id": "no_plans", "status": "info", "value": 0, "el": "Δεν έχουν ανέβει σχέδια PDF/DXF για διασταύρωση.", "en": "No PDF/DXF drawings uploaded for cross-checking."})
    return checks
