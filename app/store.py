"""Project storage on disk: projects/<id>/project.json (+ uploads, model.glb, plan thumbnails) and a global price-state file."""
from __future__ import annotations

import json
import os
import pickle
import re
import shutil
from pathlib import Path
from typing import Any

from . import prices

ROOT = Path(os.environ.get("BIM7D_DATA", Path(__file__).resolve().parent.parent / "projects"))
PRICE_FILE = ROOT / "_prices.json"


def slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip()).strip("-").lower()
    return s or "project"


def project_dir(pid: str) -> Path:
    d = ROOT / pid
    if ".." in pid or "/" in pid or "\\" in pid:
        raise ValueError("bad project id")
    return d


def list_projects() -> list[dict[str, Any]]:
    out = []
    if not ROOT.exists():
        return out
    for d in sorted(ROOT.iterdir()):
        if d.name.startswith("_"):                       # _backup, _deleted
            continue
        f = d / "project.json"
        if d.is_dir() and f.exists():
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
                out.append({"id": p["id"], "name": p.get("name"), "name_en": p.get("name_en"), "elements": len(p.get("elements", [])),
                            "gfa_m2": p["meta"].get("gfa_m2"), "demo": bool(p["meta"].get("synthetic_geometry"))})
            except Exception:
                continue
    return out


def exists(pid: str) -> bool:
    return (project_dir(pid) / "project.json").exists()


def load(pid: str) -> dict[str, Any]:
    return json.loads((project_dir(pid) / "project.json").read_text(encoding="utf-8"))


def save(project: dict[str, Any]) -> None:
    d = project_dir(project["id"])
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "project.json.tmp"
    tmp.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    tmp.replace(d / "project.json")


def delete(pid: str, permanent: bool = False) -> str | None:
    """Delete a project. By default it is moved to projects/_deleted/<id>-<time> (recoverable by moving the folder back)."""
    d = project_dir(pid)
    if not d.exists():
        return None
    if permanent:
        shutil.rmtree(d, ignore_errors=True)
        return None
    import time as _t
    base = ROOT / "_deleted" / f"{pid}-{_t.strftime('%Y%m%d-%H%M%S')}"
    dest, n = base, 1
    while dest.exists():
        n += 1
        dest = base.with_name(f"{base.name}-{n}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(d), str(dest))
    return str(dest)


def glb_path(pid: str) -> Path:
    return project_dir(pid) / "model.glb"


def parts_path(pid: str) -> Path:
    return project_dir(pid) / "parts.pkl"


def save_parts(pid: str, parts: list[dict[str, Any]]) -> None:
    with open(parts_path(pid), "wb") as f:
        pickle.dump(parts, f, protocol=4)


def load_parts(pid: str) -> list[dict[str, Any]] | None:
    p = parts_path(pid)
    if not p.exists():
        return None
    with open(p, "rb") as f:
        return pickle.load(f)


def upload_dir(pid: str) -> Path:
    d = project_dir(pid) / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def plans_dir(pid: str) -> Path:
    d = project_dir(pid) / "plans"
    d.mkdir(parents=True, exist_ok=True)
    return d


def price_state() -> dict[str, Any]:
    return prices.load_state(PRICE_FILE)


def save_price_state(state: dict[str, Any]) -> None:
    prices.save_state(PRICE_FILE, state)


def ensure_demo() -> None:
    """Create the demo project if missing; rebuild it when the bundled demo geometry is newer than the stored one
    (the old copy, with any edits, is moved to projects/_backup/ instead of being deleted)."""
    from . import demo, ingest
    pid = "demo-kifisia"
    keep_live = None
    if exists(pid):
        try:
            rev = int(load(pid).get("meta", {}).get("demo_rev", 1))
        except Exception:
            rev = 1
        if rev >= demo.DEMO_REV:
            return
        try:
            keep_live = load(pid).get("live")          # fetched site data (cadastre, earthquakes, climate) survive a model rebuild
        except Exception:
            keep_live = None
        bak = ROOT / "_backup"
        bak.mkdir(parents=True, exist_ok=True)
        dest = bak / f"{pid}-rev{rev}"
        n = 1
        while dest.exists():
            n += 1
            dest = bak / f"{pid}-rev{rev}-{n}"
        shutil.move(str(project_dir(pid)), str(dest))
    project, meshes = demo.build_project(pid)
    if keep_live:
        project["live"] = keep_live
    save(project)
    ingest.export_glb(project["elements"], meshes, glb_path(pid))
