"""Import the garden, planting, timber, planters and doors of the real Rhino model (3d_ktirio_light.glb from tools/extract_3d.py)
into app/data/real3d.npz, in the local frame of the demo (x along the street, y into the plot, z = 0 at the ground floor).

    python tools/import_real3d.py path/3d_ktirio_light.glb
The synthetic building stays (its elements carry the quantities); from the real model come the surroundings and the facade extras."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import trimesh

OFFSET = np.array([1.325, 11.785, -2.55])            # Rhino model → demo local frame (street line, building outline, ridge +13.50)
CLIP = (-6.0, -11.0, 26.5, 36.5)                      # plot and a small margin around it (half the street)
BUILDING_SKIN = re.compile(r"wood|veneer|green_|leaf|flower|branch|onyx|stone|avenue", re.I)
SKIP = re.compile(r"curtain|fabric|wool|white_fabric|titanium|chrome|glass_li|plaster_\(|tv|cooc|leather|tissus|knoll|body$", re.I)


def kind_of(layer: str, name: str, mat: str) -> tuple[str, str]:
    m = (mat + " " + name).lower()
    if re.search(r"leaf|flower|green_|branch|onyx|άχάφι|bark|body", m):
        return "vegetation", ""
    if "grass" in m:
        return "site", "#7f9f57"
    if "asphalt" in m:
        return "site", "#3d3f42"
    if "soil" in m:
        return "site", "#6e5b45"
    if re.search(r"concrete|granite|aran|ceppo|stone|avenue|alpine", m):
        return "site", ""
    if "waves" in m:
        return "site", "#6fa6c8"
    if re.search(r"wood|veneer", m):
        return ("door" if "veneer" in m else "pergola"), ""
    if re.search(r"iron|metal|plastic|sku", m):
        return "fence", "#3a3d40"
    if "wallpaint" in m:
        return "wall", "#f1efea"
    if "rooftile" in m:
        return "roof", "#6f6a65"
    if m.startswith("layer_"):
        return "site", "#a9a6a0"
    return "site", ""


def main(glb: str, summary: str | None = None) -> None:
    sc = trimesh.load(glb)
    colours = {}
    if summary:
        for g in json.loads(Path(summary).read_text(encoding="utf-8"))["groups"]:
            colours[g.get("node", "")] = g["colour"]
    items, V_all, F_all = [], [], []
    nv = 0
    for node in sc.graph.nodes_geometry:
        T, gname = sc.graph[node]
        parts = node.split("|")
        if len(parts) < 4:
            continue
        layer, name, mat = parts[1], parts[2], parts[3]
        if SKIP.search(mat) or SKIP.search(name):
            continue
        if layer != "khpos" and not BUILDING_SKIN.search(mat):
            continue
        g = sc.geometry[gname]
        V = trimesh.transform_points(g.vertices, T) + OFFSET
        m = trimesh.Trimesh(V, g.faces, process=False)
        for o, n in (((CLIP[0], 0, 0), (1, 0, 0)), ((CLIP[2], 0, 0), (-1, 0, 0)), ((0, CLIP[1], 0), (0, 1, 0)), ((0, CLIP[3], 0), (0, -1, 0))):
            if len(m.faces) == 0:
                break
            m = trimesh.intersections.slice_mesh_plane(m, plane_normal=n, plane_origin=o, cap=False)
        if len(m.faces) == 0:
            continue
        kind, col = kind_of(layer, name, mat)
        grid = 0.10 if kind == "vegetation" else 0.02
        q = np.round(m.vertices / grid).astype(np.int64)
        _, idx, inv = np.unique(q, axis=0, return_index=True, return_inverse=True)
        F = inv.reshape(-1)[m.faces]
        F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])]
        if not len(F):
            continue
        Vs = m.vertices[idx]
        if not col:
            col = colours.get(node) or "#9a9a9a"
            if col.lower() in ("#999999", "#ffffff", "#fafafa"):
                col = {"vegetation": "#4f7a34", "site": "#c9c7c1", "pergola": "#8a6242", "door": "#7a5a3e"}.get(kind, "#b5b2ac")
        if kind == "vegetation" and int(col[1:3], 16) > 150:
            col = "#5d8a3c"
        mm = trimesh.Trimesh(Vs, F, process=False)
        items.append({"name": f"{layer}|{name}|{mat}", "layer": layer, "material": mat, "kind": kind, "color": col, "v0": nv, "nv": len(Vs),
                      "f0": sum(len(x) for x in F_all), "nf": len(F), "area_m2": round(float(mm.area), 2),
                      "plan_m2": round(float(mm.area_faces[np.abs(mm.face_normals[:, 2]) > 0.7].sum()), 2)})
        V_all.append(Vs.astype(np.float32))
        F_all.append((F + nv).astype(np.uint32))
        nv += len(Vs)
    out = Path(__file__).resolve().parents[1] / "app" / "data" / "real3d.npz"
    np.savez_compressed(out, V=np.vstack(V_all), F=np.vstack(F_all), index=np.array(json.dumps(items, ensure_ascii=False)))
    print(f"{len(items)} groups, {nv:,} vertices, {sum(len(f) for f in F_all):,} triangles -> {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
