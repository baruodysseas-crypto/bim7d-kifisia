"""3D ingestion: mesh files (GLB/GLTF/OBJ/PLY/STL/IFC/3DM) -> classified BIM elements + viewer GLB.

Internal convention: metres, Z up. Each element is a dict (see `make_element`)."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import trimesh

KINDS = ["footing", "slab", "column", "beam", "wall", "window", "door", "roof", "stair", "railing",
         "pergola", "fence", "vegetation", "furniture", "site", "other"]

IFC_CLASS = {"footing": "IfcFooting", "slab": "IfcSlab", "column": "IfcColumn", "beam": "IfcBeam", "wall": "IfcWall",
             "window": "IfcWindow", "door": "IfcDoor", "roof": "IfcRoof", "stair": "IfcStair", "railing": "IfcRailing",
             "pergola": "IfcMember", "fence": "IfcRailing", "vegetation": "IfcGeographicElement",
             "furniture": "IfcFurniture", "site": "IfcSite", "other": "IfcBuildingElementProxy"}

DEFAULT_MATERIAL = {"footing": "concrete", "slab": "concrete", "column": "concrete", "beam": "concrete", "wall": "masonry",
                    "window": "glazing_alu", "door": "timber", "roof": "concrete", "stair": "concrete", "railing": "glass_steel",
                    "pergola": "timber", "fence": "steel", "vegetation": "organic", "furniture": "timber", "site": "soil", "other": "other"}

# keyword rules (first match wins) - English + Greek + the layer names found in the user's drawings
_RULES: list[tuple[str, str]] = [
    ("footing", r"footing|foundation|raft|θεμελ|θεμελι"),
    ("column", r"column|colum|pillar|κολων|υποστυλ|\bk\d+\b|ifccolumn"),
    ("beam", r"beam|girder|lintel|δοκ|\bd\d+\b|ifcbeam"),
    ("roof", r"roof|στεγ|δωμα|δώμα|ifcroof"),
    ("slab", r"slab|floor|deck|πλακ|δαπεδ|ifcslab"),
    ("railing", r"railing|balust|guard|κιγκλ|στηθα|ifcrailing"),
    ("window", r"window|glaz|glass|gyali|κουφ|παραθυρ|υαλ|γυαλ|ifcwindow|curtain"),
    ("door", r"door|πορτ|ifcdoor"),
    ("stair", r"stair|σκαλ|κλιμακ|ifcstair"),
    ("pergola", r"pergola|louver|louvre|περγκ|περσιδ|shading"),
    ("fence", r"fence|gate|φραχ|περιφραξ|μάντρα|mantra"),
    ("vegetation", r"tree|plant|veget|shrub|bush|grass|prasino|δεντρ|δέντρ|φυτ|χλοο|ifcgeographic"),
    ("furniture", r"furn|chair|table|sofa|epipla|έπιπλ|ifcfurn"),
    ("wall", r"wall|brick|masonry|τοιχ|τοίχ|ifcwall"),
    ("site", r"terrain|topo|site|road|street|ground|έδαφ|δρομ|οδός|ifcsite"),
]


def classify(*names: str) -> str:
    text = " ".join(n for n in names if n).lower()
    for kind, pat in _RULES:
        if re.search(pat, text):
            return kind
    return "other"


def make_element(eid: str, name: str, kind: str, mesh: trimesh.Trimesh | None, layer: str = "", props: dict | None = None,
                 storey: str | None = None) -> dict[str, Any]:
    qty: dict[str, float] = {"count": 1}
    bbox = [0.0] * 6
    if mesh is not None and len(mesh.vertices):
        b = mesh.bounds
        bbox = [float(x) for x in (*b[0], *b[1])]
        dx, dy, dz = (b[1] - b[0]).tolist()
        vol = _volume(mesh, dx, dy, dz)
        qty["volume_m3"] = round(vol, 4)
        qty["surface_m2"] = round(float(mesh.area), 3)
        horiz = sorted([dx, dy])
        if kind in ("column",):
            qty.update(height_m=dz, section_m2=vol / max(dz, 1e-6), width_m=horiz[0], depth_m=horiz[1])
        elif kind == "beam":
            qty.update(length_m=horiz[1], section_m2=vol / max(horiz[1], 1e-6), width_m=horiz[0], depth_m=dz)
        elif kind in ("slab", "footing", "roof"):
            t = max(min(dz, 1.0), 1e-3) if dz > 1e-3 else 0.2
            qty.update(thickness_m=dz, plan_area_m2=vol / max(dz, 1e-3), perimeter_m=2 * (dx + dy))
        elif kind in ("wall", "fence", "railing", "pergola"):
            qty.update(length_m=horiz[1], height_m=dz, thickness_m=horiz[0], face_area_m2=vol / max(horiz[0], 1e-3) if horiz[0] > 1e-3 else horiz[1] * dz,
                       plan_area_m2=dx * dy)
        elif kind in ("window", "door"):
            qty.update(width_m=horiz[1], height_m=dz, thickness_m=horiz[0], area_m2=horiz[1] * dz)
        else:
            qty.update(plan_area_m2=dx * dy, height_m=dz)
        qty = {k: round(float(v), 4) for k, v in qty.items()}
    return {"id": eid, "name": name, "kind": kind, "ifc_class": IFC_CLASS.get(kind, "IfcBuildingElementProxy"),
            "layer": layer, "storey": storey, "material": DEFAULT_MATERIAL.get(kind, "other"),
            "qty": qty, "bbox": [round(x, 4) for x in bbox], "props": props or {}}


def _volume(mesh: trimesh.Trimesh, dx: float, dy: float, dz: float) -> float:
    try:
        if mesh.is_watertight:
            return abs(float(mesh.volume))
    except Exception:
        pass
    return float(dx * dy * dz) * 0.9   # open mesh -> bounding-box estimate


# --------------------------------------------------------------------------------------
# Storeys
# --------------------------------------------------------------------------------------
_ORD_EL = ["Ισόγειο", "Α' όροφος", "Β' όροφος", "Γ' όροφος", "Δ' όροφος", "Ε' όροφος", "ΣΤ' όροφος"]
_ORD_EN = ["Ground floor", "1st floor", "2nd floor", "3rd floor", "4th floor", "5th floor", "6th floor"]


def detect_storeys(elements: list[dict], tol: float = 0.6) -> list[dict]:
    """Storey levels from the top Z of horizontal elements (slabs/footings/roofs)."""
    tops = sorted(e["bbox"][5] for e in elements if e["kind"] in ("slab", "footing", "roof") and e["bbox"][5] > e["bbox"][2])
    if not tops:
        zs = sorted(e["bbox"][2] for e in elements if e["kind"] in ("column", "wall"))
        tops = zs[:1]
    clusters: list[list[float]] = []
    for z in tops:
        if clusters and z - clusters[-1][-1] <= tol:
            clusters[-1].append(z)
        else:
            clusters.append([z])
    levels = [float(np.median(c)) for c in clusters]
    if not levels:
        levels = [0.0]
    zmax = max((e["bbox"][5] for e in elements if e["kind"] not in ("vegetation", "site")), default=levels[-1] + 3.0)
    storeys = []
    # the lowest cluster is the foundation raft: storey 'basement/foundation' starts at ground; keep levels as floor tops
    ground_idx = min(range(len(levels)), key=lambda i: abs(levels[i]))
    for i, z in enumerate(levels):
        nxt = levels[i + 1] if i + 1 < len(levels) else zmax
        rel = i - ground_idx
        if rel < 0:
            name_el = "Θεμελίωση" if i == 0 and len(levels) > 1 and rel == -ground_idx and ground_idx > 1 else ("Υπόγειο" if rel == -1 else f"Υπόγειο {-rel}")
            name_en = "Foundation" if name_el == "Θεμελίωση" else ("Basement" if rel == -1 else f"Basement {-rel}")
        else:
            name_el = _ORD_EL[rel] if rel < len(_ORD_EL) else f"Όροφος {rel}"
            name_en = _ORD_EN[rel] if rel < len(_ORD_EN) else f"Floor {rel}"
        storeys.append({"id": f"S{i:02d}", "name_el": name_el, "name_en": name_en, "elevation_m": round(z, 3),
                        "height_m": round(max(nxt - z, 0.0), 3)})
    return storeys


def assign_storeys(elements: list[dict], storeys: list[dict]) -> None:
    if not storeys:
        return
    levels = [s["elevation_m"] for s in storeys]
    for e in elements:
        b = e["bbox"]
        if e["kind"] in ("vegetation", "site"):
            e["storey"] = None
            continue
        z = b[5] if e["kind"] in ("slab", "footing") else 0.5 * (b[2] + b[5])
        if e["kind"] in ("slab", "footing"):
            idx = min(range(len(levels)), key=lambda i: abs(levels[i] - z))
        else:
            idx = 0
            for i, lv in enumerate(levels):
                if z >= lv - 0.05:
                    idx = i
        e["storey"] = storeys[idx]["id"]


# --------------------------------------------------------------------------------------
# Loading files
# --------------------------------------------------------------------------------------
def _auto_scale(parts: list[dict]) -> float:
    mx = 0.0
    for p in parts:
        ext = p["mesh"].extents
        mx = max(mx, float(np.max(ext)))
    if mx > 8000:
        return 0.001
    if mx > 800:
        return 0.01
    return 1.0


def load_parts(path: str | Path, up: str | None = None, scale: float | None = None) -> tuple[list[dict], dict]:
    """Return ([{name, layer, mesh, props}], info). Meshes are in metres, Z up."""
    path = Path(path)
    ext = path.suffix.lower()
    info: dict[str, Any] = {"file": path.name, "format": ext.lstrip(".")}
    if ext == ".ifc":
        parts = _load_ifc(path, info)
    elif ext == ".3dm":
        parts = _load_3dm(path, info)
    else:
        parts = _load_trimesh(path, info)
        if up is None:
            up = "y" if ext in (".glb", ".gltf") else "z"
    if scale is None and ext not in (".ifc", ".3dm"):
        scale = _auto_scale(parts)
    if scale and scale != 1.0:
        for p in parts:
            p["mesh"].apply_scale(scale)
    if up == "y":   # glTF Y-up -> Z-up : (x, y, z) -> (x, -z, y)
        R = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], float)
        for p in parts:
            p["mesh"].apply_transform(R)
    info.update(scale=scale or 1.0, up=up or "z", parts=len(parts))
    return parts, info


def _load_obj(path: Path, info: dict) -> list[dict]:
    """Wavefront OBJ split per `o` object / `g` group (trimesh merges them). Rhino writes one `g`/`o` per object or layer."""
    verts: list[tuple[float, float, float]] = []
    parts: dict[tuple[str, str], dict] = {}
    obj = grp = ""
    cur: dict | None = None
    order: list[tuple[str, str]] = []

    def part() -> dict:
        key = (obj, grp)
        if key not in parts:
            parts[key] = {"faces": []}
            order.append(key)
        return parts[key]

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line or line[0] == "#":
                continue
            if line.startswith("v "):
                x = line.split()
                verts.append((float(x[1]), float(x[2]), float(x[3])))
            elif line.startswith("o "):
                obj, cur = line[2:].strip(), None
            elif line.startswith("g "):
                grp, cur = line[2:].strip(), None
            elif line.startswith("f "):
                idx = []
                for tok in line.split()[1:]:
                    i = int(tok.split("/")[0])
                    idx.append(i - 1 if i > 0 else len(verts) + i)
                if cur is None:
                    cur = part()
                for k in range(1, len(idx) - 1):                    # fan triangulation
                    cur["faces"].append((idx[0], idx[k], idx[k + 1]))
    V = np.asarray(verts, dtype=float)
    out = []
    for n, key in enumerate(order):
        f = np.asarray(parts[key]["faces"], dtype=np.int64)
        if len(f) == 0:
            continue
        used, inv = np.unique(f, return_inverse=True)
        m = trimesh.Trimesh(vertices=V[used], faces=inv.reshape(-1, 3), process=False)
        o, g = key
        out.append({"name": o or g or f"obj{n}", "layer": g or o or f"obj{n}", "mesh": m, "props": {}})
    return out


def _load_trimesh(path: Path, info: dict) -> list[dict]:
    if path.suffix.lower() == ".obj":
        return _load_obj(path, info)
    scene = trimesh.load(str(path), force="scene", process=False)
    parts = []
    if isinstance(scene, trimesh.Trimesh):
        scene = trimesh.Scene(scene)
    for node in scene.graph.nodes_geometry:
        T, gname = scene.graph[node]
        g = scene.geometry[gname]
        if not isinstance(g, trimesh.Trimesh) or len(g.faces) == 0:
            continue
        m = g.copy()
        m.apply_transform(T)
        parts.append({"name": str(node), "layer": str(gname), "mesh": m, "props": {}})
    return parts


_UNIT_TO_M = {"Meters": 1.0, "Millimeters": 0.001, "Centimeters": 0.01, "Decimeters": 0.1, "Feet": 0.3048, "Inches": 0.0254, "Kilometers": 1000.0}


def _load_3dm(path: Path, info: dict) -> list[dict]:
    try:
        import rhino3dm
    except ImportError as ex:
        raise RuntimeError("ανάγνωση .3dm: δεν είναι εγκατεστημένη η βιβλιοθήκη rhino3dm (δεν υπάρχει έτοιμο πακέτο για αυτή την έκδοση Python)· "
                           "εξάγετε από το Rhino σε OBJ ή GLB ή εγκαταστήστε Python 3.12/3.13 / reading .3dm needs rhino3dm; export OBJ/GLB instead") from ex
    f = rhino3dm.File3dm.Read(str(path))
    if f is None:
        raise ValueError("rhino3dm could not read the file")
    unit = str(f.Settings.ModelUnitSystem).split(".")[-1]
    k = _UNIT_TO_M.get(unit, 1.0)
    layers = {i: f.Layers[i].FullPath for i in range(len(f.Layers))}
    mp = rhino3dm.MeshingParameters.Default if hasattr(rhino3dm.MeshingParameters, "Default") else None
    parts = []
    for obj in f.Objects:
        geom, attr = obj.Geometry, obj.Attributes
        meshes: list[Any] = []
        if isinstance(geom, rhino3dm.Mesh):
            meshes = [geom]
        elif isinstance(geom, rhino3dm.Brep):
            try:
                res = rhino3dm.Mesh.CreateFromBrep(geom, mp) if mp is not None else rhino3dm.Mesh.CreateFromBrep(geom)
                meshes = list(res) if res is not None else []
            except Exception:
                meshes = []
        elif isinstance(geom, rhino3dm.Extrusion):
            try:
                m = geom.GetMesh(rhino3dm.MeshType.Default)
                meshes = [m] if m is not None else []
            except Exception:
                meshes = []
        for m in meshes:
            V = np.array([[v.X, v.Y, v.Z] for v in m.Vertices], float) * k
            F = []
            for i in range(m.Faces.Count):
                fc = m.Faces[i]
                if fc[2] == fc[3]:
                    F.append([fc[0], fc[1], fc[2]])
                else:
                    F.append([fc[0], fc[1], fc[2]])
                    F.append([fc[0], fc[2], fc[3]])
            if len(V) and F:
                tm = trimesh.Trimesh(V, np.array(F), process=False)
                parts.append({"name": attr.Name or str(attr.Id), "layer": layers.get(attr.LayerIndex, ""), "mesh": tm, "props": {}})
    info["rhino_units"] = unit
    return parts


def _load_ifc(path: Path, info: dict) -> list[dict]:
    try:
        import ifcopenshell
    except ImportError as ex:
        raise RuntimeError("ανάγνωση .ifc: δεν είναι εγκατεστημένη η βιβλιοθήκη ifcopenshell· εξάγετε σε OBJ ή GLB ή εγκαταστήστε Python 3.12/3.13 / reading .ifc needs ifcopenshell; export OBJ/GLB instead") from ex
    import ifcopenshell.geom
    import ifcopenshell.util.element as ue
    import ifcopenshell.util.unit as uu
    model = ifcopenshell.open(str(path))
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    try:
        k = uu.calculate_unit_scale(model)
    except Exception:
        k = 1.0
    parts = []
    it = ifcopenshell.geom.iterator(settings, model)
    if it.initialize():
        while True:
            sh = it.get()
            prod = model.by_id(sh.id)
            g = sh.geometry
            V = np.array(g.verts, float).reshape(-1, 3) * k
            F = np.array(g.faces, int).reshape(-1, 3)
            if len(V) and len(F):
                storey = None
                try:
                    c = ue.get_container(prod)
                    storey = c.Name if c is not None else None
                except Exception:
                    pass
                mats = []
                try:
                    m = ue.get_material(prod)
                    if m is not None:
                        mats = [m.Name] if hasattr(m, "Name") and m.Name else []
                except Exception:
                    pass
                parts.append({"name": prod.Name or prod.is_a(), "layer": prod.is_a(), "mesh": trimesh.Trimesh(V, F, process=False),
                              "props": {"ifc_guid": prod.GlobalId, "ifc_class": prod.is_a(), "ifc_storey": storey, "ifc_material": mats}})
            if not it.next():
                break
    info["ifc_schema"] = model.schema
    return parts


# --------------------------------------------------------------------------------------
# Parts -> model
# --------------------------------------------------------------------------------------
def build_elements(parts: Iterable[dict], layer_map: dict[str, str] | None = None, max_elements: int = 20000) -> list[dict]:
    """Classify parts into elements. `layer_map` maps a layer (or exact name) -> kind and overrides the rules."""
    layer_map = layer_map or {}
    elements: list[dict] = []
    for i, p in enumerate(parts):
        if i >= max_elements:
            break
        kind = layer_map.get(p["layer"]) or layer_map.get(p["name"])
        if not kind:
            ifc = p.get("props", {}).get("ifc_class", "")
            kind = classify(ifc, p["layer"], p["name"])
        el = make_element(f"E{i + 1:05d}", p["name"], kind, p["mesh"], p["layer"], p.get("props"))
        elements.append(el)
    return elements


def layer_summary(parts: list[dict], layer_map: dict[str, str] | None = None) -> list[dict]:
    """Per-layer summary for the mapping UI: suggested kind, element count, total volume."""
    layer_map = layer_map or {}
    agg: dict[str, dict] = {}
    for p in parts:
        key = p["layer"] or p["name"]
        a = agg.setdefault(key, {"layer": key, "count": 0, "volume_m3": 0.0, "suggested": classify(p["layer"], p["name"])})
        a["count"] += 1
        m = p["mesh"]
        a["volume_m3"] += abs(float(m.volume)) if m.is_watertight else float(np.prod(m.extents)) * 0.9
    for a in agg.values():
        a["kind"] = layer_map.get(a["layer"], a["suggested"])
        a["volume_m3"] = round(a["volume_m3"], 3)
    return sorted(agg.values(), key=lambda x: -x["count"])


KIND_COLORS = {"footing": "#8d8d8d", "slab": "#b9b9b9", "column": "#9a9a9a", "beam": "#a8a8a8", "wall": "#e6dccb", "window": "#7fb5d6",
               "door": "#8a5a3c", "roof": "#c8c0b4", "stair": "#bdb3a2", "railing": "#9fd0e6", "pergola": "#8b5e3c", "fence": "#3b3b3b",
               "vegetation": "#4f8f3a", "furniture": "#a47c55", "site": "#c9d6b0", "other": "#c0c0c0"}


def export_glb(elements: list[dict], meshes: dict[str, trimesh.Trimesh], out: Path) -> None:
    """Write the viewer GLB (Y-up) with one node per element, named by element id."""
    scene = trimesh.Scene()
    R = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], float)   # Z-up -> Y-up
    for e in elements:
        m = meshes.get(e["id"])
        if m is None:
            continue
        mm = m.copy()
        rgba = _hex_rgba((e.get("props") or {}).get("color") or KIND_COLORS.get(e["kind"], "#c0c0c0"), 110 if e["kind"] == "window" else 255)
        mm.visual = trimesh.visual.ColorVisuals(mesh=mm, face_colors=np.tile(rgba, (len(mm.faces), 1)))
        mm.apply_transform(R)
        scene.add_geometry(mm, node_name=e["id"], geom_name=e["id"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(scene.export(file_type="glb"))


def _hex_rgba(h: str, a: int = 255) -> list[int]:
    h = h.lstrip("#")
    return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a]


def model_summary(elements: list[dict]) -> dict[str, Any]:
    by_kind: dict[str, dict] = {}
    for e in elements:
        s = by_kind.setdefault(e["kind"], {"count": 0, "volume_m3": 0.0})
        s["count"] += 1
        s["volume_m3"] += e["qty"].get("volume_m3", 0.0)
    for s in by_kind.values():
        s["volume_m3"] = round(s["volume_m3"], 2)
    return by_kind
