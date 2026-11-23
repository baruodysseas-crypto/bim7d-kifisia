"""Make a light copy of the big Rhino OBJ export (e.g. 3d.obj, 2 GB) that the tool can read: every object/layer group with its
material and real colour, simplified by merging vertices closer than a few centimetres. Interior furniture and fittings are dropped.

Run (Windows, from the bim7d-tool folder):  .venv\\Scripts\\python tools\\extract_3d.py "..\\3d.obj"
or double-click tools\\extract_3d.bat.  Writes next to the OBJ:
  3d_light.glb      – the light model (metres, Z up as in Rhino), one node per group+material, coloured like the render materials
  3d_summary.json   – every group: material, colour, triangles, bounding box, area – also the dropped ones, for checking
Two passes over the file (vertices, then faces), so memory stays moderate; a 2 GB OBJ takes roughly 10–20 minutes.
"""
from __future__ import annotations

import array
import json
import sys
import time
from pathlib import Path

import numpy as np

GRID_M = 0.03                     # vertices closer than this are merged (simplification)
MAX_TRIS = 1_500_000              # total triangles kept in the light GLB
# materials / names of interior furniture and fittings that are not needed for the building model
DROP = ("leather", "tissus", "fabric", "curtain", "knoll", "tulip", "cooctop", "cooktop", "chrome", "sofa", "chair", "bed ", "pillow", "lamp", "furniture", "έπιπλ",
        "καναπ", "καρεκλ", "κρεβατ", "τραπεζ", "κουζιν")


def _mtl(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    cur = None
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("newmtl "):
            cur = line[7:].strip()
            out[cur] = {"Kd": [0.8, 0.8, 0.8], "d": 1.0, "map": None}
        elif cur and line.startswith("Kd "):
            out[cur]["Kd"] = [float(x) for x in line.split()[1:4]]
        elif cur and line.startswith("d "):
            out[cur]["d"] = float(line.split()[1])
        elif cur and line.startswith("map_Kd "):
            out[cur]["map"] = line[7:].strip()
    return out


def _texture_colour(name: str, folders: list[Path]) -> list[float] | None:
    try:
        from PIL import Image
    except Exception:                                                     # noqa: BLE001
        return None
    for f in folders:
        for cand in (f / name, f / Path(name).name):
            if cand.exists() and cand.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"):
                try:
                    im = Image.open(cand).convert("RGB").resize((1, 1), Image.Resampling.BOX)
                    return [c / 255.0 for c in im.getpixel((0, 0))]
                except Exception:                                         # noqa: BLE001
                    return None
    return None


def colour_of(mat: str, m: dict | None, folders: list[Path]) -> tuple[list[float], float]:
    low = mat.lower()
    alpha = (m or {}).get("d", 1.0)
    if "glass" in low or alpha < 0.5:
        return [0.55, 0.72, 0.85], 0.45
    if m and m.get("map"):
        c = _texture_colour(m["map"], folders)
        if c:
            return c, 1.0
    if "wood" in low or "veneer" in low or "ξυλ" in low:
        return [0.55, 0.38, 0.22], 1.0
    if "leaf" in low or "flower" in low or "grass" in low or "φυτ" in low:
        return [0.30, 0.52, 0.22], 1.0
    if m and sum(m["Kd"]) > 0.05:
        return m["Kd"], 1.0
    if "concrete" in low or "stucco" in low:
        return [0.75, 0.74, 0.72], 1.0
    return [0.6, 0.6, 0.6], 1.0


def main(obj_path: str) -> None:
    src = Path(obj_path).resolve()
    t0 = time.time()
    mtllib = None
    # ---- pass 1: vertices
    xs = array.array("f")
    with open(src, "r", encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh):
            if line.startswith("v "):
                p = line.split()
                xs.extend((float(p[1]), float(p[2]), float(p[3])))
            elif line.startswith("mtllib "):
                mtllib = line[7:].strip()
            if n % 5_000_000 == 0 and n:
                print(f"  vertices: {n:,} lines, {len(xs) // 3:,} vertices, {time.time() - t0:.0f}s", flush=True)
    V = np.frombuffer(xs, dtype=np.float32).reshape(-1, 3).astype(np.float64)
    del xs
    ext = float(np.max(V.max(0) - V.min(0))) if len(V) else 0.0
    unit = 0.001 if ext > 2000 else (0.01 if ext > 300 else 1.0)          # mm / cm / m from the model size
    V *= unit
    print(f"{len(V):,} vertices, size {ext:.1f} (unit {unit} m) – {time.time() - t0:.0f}s", flush=True)
    key = np.floor(V / GRID_M).astype(np.int64)
    uniq, cid = np.unique(key, axis=0, return_inverse=True)
    cid = cid.reshape(-1).astype(np.uint32)
    sums = np.zeros((len(uniq), 3))
    np.add.at(sums, cid, V)
    cnt = np.bincount(cid, minlength=len(uniq)).astype(float)
    CV = sums / cnt[:, None]                                              # merged vertex positions
    del key, sums
    print(f"merged to {len(CV):,} vertices (grid {GRID_M * 100:.0f} cm) – {time.time() - t0:.0f}s", flush=True)
    # ---- pass 2: faces per (object/group, material)
    groups: dict[tuple[str, str], array.array] = {}
    raw_tris: dict[tuple[str, str], int] = {}
    obj, grp, mat = "", "", ""
    nv = len(V)
    vcount = 0
    with open(src, "r", encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh):
            c = line[:2]
            if c == "v ":
                vcount += 1
                continue
            if c == "f ":
                idx = []
                for tok in line.split()[1:]:
                    i = int(tok.split("/", 1)[0])
                    idx.append(i - 1 if i > 0 else vcount + i)
                k = (grp or obj or "default", mat)
                a = groups.get(k)
                if a is None:
                    a = groups[k] = array.array("I")
                    raw_tris[k] = 0
                c0 = int(cid[idx[0]])
                for j in range(1, len(idx) - 1):
                    raw_tris[k] += 1
                    c1, c2 = int(cid[idx[j]]), int(cid[idx[j + 1]])
                    if c0 != c1 and c1 != c2 and c0 != c2:
                        a.extend((c0, c1, c2))
            elif line.startswith("usemtl "):
                mat = line[7:].strip()
            elif line.startswith("g "):
                grp = line[2:].strip()
            elif line.startswith("o "):
                obj = line[2:].strip()
                grp = ""
            if n % 5_000_000 == 0 and n:
                print(f"  faces: {n:,} lines – {time.time() - t0:.0f}s", flush=True)
    del cid, V
    folders = [src.parent, src.parent / f"{src.stem}_embedded_files", src.parent / "3d_embedded_files"]
    mname = mtllib or (src.stem + ".mtl")
    mats = _mtl(src.parent / mname) or _mtl(src.parent.parent / mname)
    folders.append(src.parent.parent)
    import trimesh
    summary = []
    meshes = []
    for (g, m), a in groups.items():
        F = np.frombuffer(a, dtype=np.uint32).reshape(-1, 3)
        F = np.unique(np.sort(F, axis=1), axis=0) if len(F) else F         # drop duplicate triangles
        low = (g + " " + m).lower()
        drop = any(w in low for w in DROP)
        col, alpha = colour_of(m, mats.get(m), folders)
        rec = {"group": g, "material": m, "colour": "#%02x%02x%02x" % tuple(int(max(0, min(1, x)) * 255) for x in col), "alpha": alpha,
               "triangles_raw": raw_tris[(g, m)], "triangles": int(len(F)), "dropped": drop}
        if len(F):
            used = np.unique(F)
            P = CV[used]
            rec["bbox"] = [round(float(x), 3) for x in (*P.min(0), *P.max(0))]
            remap = np.zeros(len(CV), dtype=np.int64)
            remap[used] = np.arange(len(used))
            tm = trimesh.Trimesh(P, remap[F], process=False)
            rec["area_m2"] = round(float(tm.area), 2)
            if not drop:
                meshes.append((rec, tm))
        summary.append(rec)
    meshes.sort(key=lambda x: -x[0]["area_m2"])
    scene = trimesh.Scene()
    total = 0
    for i, (rec, tm) in enumerate(meshes):
        if total + len(tm.faces) > MAX_TRIS:
            rec["dropped"] = "size"
            continue
        total += len(tm.faces)
        rgba = [int(rec["colour"][k:k + 2], 16) for k in (1, 3, 5)] + [int(rec["alpha"] * 255)]
        tm.visual = trimesh.visual.ColorVisuals(mesh=tm, face_colors=np.tile(rgba, (len(tm.faces), 1)))
        name = f"{i:04d}|{rec['group']}|{rec['material']}"[:200]
        rec["node"] = name
        scene.add_geometry(tm, node_name=name, geom_name=name)
    out_glb = src.parent / f"{src.stem}_light.glb"
    out_js = src.parent / f"{src.stem}_summary.json"
    out_glb.write_bytes(scene.export(file_type="glb"))
    out_js.write_text(json.dumps({"source": src.name, "unit_m": unit, "grid_m": GRID_M, "triangles_kept": total, "groups": summary,
                                  "materials": {k: {**v} for k, v in mats.items()}}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nOK: {out_glb.name} ({out_glb.stat().st_size / 1e6:.1f} MB, {total:,} triangles) and {out_js.name} – {time.time() - t0:.0f}s")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
