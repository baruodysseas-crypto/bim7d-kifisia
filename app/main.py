"""FastAPI backend of the 7D-BIM tool. Run: uvicorn app.main:app  (see start.bat / README)."""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import access, analysis, cost, demo, energy, fm, hazards, ingest, lifecycle, live, plans, prices, quantities, schedule, store, structural

BASE = Path(__file__).resolve().parent.parent
WEB = BASE / "web"
@asynccontextmanager
async def _lifespan(_app: FastAPI):
    store.ROOT.mkdir(parents=True, exist_ok=True)
    store.ensure_demo()
    if not live.offline() and os.environ.get("BIM7D_NO_AUTOREFRESH", "") != "1":
        threading.Thread(target=_auto_refresh, daemon=True).start()
    yield


LOCK = threading.RLock()
AUTO: dict[str, Any] = {"running": False, "started": None, "finished": None, "status": {}}


def _live_inputs(p: dict[str, Any]) -> dict[str, Any]:
    hz = hazards.load()
    return {"scenarios": hz["seismic"]["scenarios"], "design_climate": {"T_ext": energy.T_EXT, "G_h": energy.G_H, "G_45": energy.G_45}}


def _refresh_live(pid: str, what: list[str] | None = None, kaek: str | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    with LOCK:
        p = store.load(pid)
    # the network part runs outside the lock; the result is merged into a fresh copy of the project
    tmp = {"id": p["id"], "meta": p.get("meta", {}), "live": json.loads(json.dumps(p.get("live") or {}))}
    st = live.refresh(tmp, what, kaek=kaek, params=params, **_live_inputs(p))
    with LOCK:
        p = store.load(pid)
        p["live"] = tmp["live"]
        store.save(p)
    return st


def _auto_refresh() -> None:
    """At start-up: market prices (if older than 12 h) and the live site data of the Kifisia project (if older than 7 days)."""
    AUTO.update(running=True, started=live.now_iso())
    try:
        ps = store.price_state()
        last = max((g.get("updated") or "" for g in ps["groups"].values() if g.get("provider")), default="")
        if live.age_hours(last or None) > 12 or not ps.get("series"):
            st = prices.refresh_all(ps)
            st_h = prices.refresh_history(ps)
            with LOCK:
                store.save_price_state(ps)
            AUTO["status"]["prices"] = {"current": st, "history": st_h}
        if store.exists(THESIS_PROJECT):
            lv = store.load(THESIS_PROJECT).get("live") or {}
            what = [k for k in ("cadastre", "seismic", "climate") if live.age_hours((lv.get(k) or {}).get("fetched")) > 24 * 7]
            if what:
                AUTO["status"]["live"] = _refresh_live(THESIS_PROJECT, what)
    except Exception as ex:  # noqa: BLE001 - never break the start of the app
        AUTO["status"]["error"] = f"{type(ex).__name__}: {ex}"
    finally:
        AUTO.update(running=False, finished=live.now_iso())


app = FastAPI(title="7D-BIM Lifecycle Tool", version="1.0", lifespan=_lifespan)
access.install(app)  # password gate, active only when BIM7D_PASSWORD is set (online copy)
MODEL_EXT = {".glb", ".gltf", ".obj", ".stl", ".ply", ".3dm", ".ifc", ".off", ".dae"}
PLAN_EXT = {".pdf", ".dxf"}


def get_project(pid: str) -> dict[str, Any]:
    if not store.exists(pid):
        raise HTTPException(404, "project not found")
    return store.load(pid)


def _slim(p: dict[str, Any]) -> dict[str, Any]:
    q = {k: v for k, v in p.items() if k not in ("elements", "geometry3d")}
    q["model"] = ingest.model_summary(p["elements"])
    q["element_count"] = len(p["elements"])
    q.setdefault("settings", {})
    return q


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "time": time.time()}


# ---------------------------------------------------------------- projects
THESIS_PROJECT = "demo-kifisia"


def _only_kifisia() -> bool:
    """The thesis edition works only on the Kifisia project; creating or deleting projects is closed.
    (The automatic tests open it with BIM7D_ALLOW_NEW=1.)"""
    return os.environ.get("BIM7D_ALLOW_NEW", "") != "1"


@app.get("/api/projects")
def projects() -> list[dict[str, Any]]:
    lst = store.list_projects()
    if _only_kifisia():
        lst = [p for p in lst if p.get("id") == THESIS_PROJECT]
    return lst


@app.post("/api/projects")
def create_project(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if _only_kifisia():
        raise HTTPException(403, "Η έκδοση της διπλωματικής αφορά μόνο το έργο της Κηφισιάς – δεν δημιουργούνται νέα έργα.")
    name = (body.get("name") or "Νέο έργο").strip()
    pid = store.slug(body.get("id") or name)
    base, n = pid, 1
    while store.exists(pid):
        n += 1
        pid = f"{base}-{n}"
    if body.get("demo"):
        project, meshes = demo.build_project(pid)
        project["name"], project["name_en"] = name, name
        store.save(project)
        ingest.export_glb(project["elements"], meshes, store.glb_path(pid))
        return _slim(project)
    project = {"id": pid, "version": 1, "name": name, "name_en": body.get("name_en") or name,
               "meta": {"location": {"municipality": "", "address": "", "lat": 38.0, "lon": 23.8, "climate_zone": "B", "altitude_m": 100}, "permit": {}, "use": "residential",
                        "apartments": 0, "plot_area_m2": 0, "gfa_m2": 0, "height_m": 0, "conditioned_area_m2": 0, "population": 0,
                        "structure": {"system": "RC frame", "concrete": "C25/30", "steel": "B500C", "code": "EAK 2000/2003", "seismic_zone": "II", "a_g": 0.24, "soil": "B",
                                      "T1": 0.15, "T2": 0.60, "gamma_I": 1.0, "q": 3.0, "theta": 1.0, "Tx": 0.3, "Ty": 0.3, "beta0": 2.5, "Rd": 1.0}},
               "storeys": [], "apartments": [], "areas": {}, "elements": [], "geometry3d": {},
               "schedule": {"tasks": json.loads((Path(demo.DATA) / "gantt.json").read_text(encoding="utf-8")), "start_date": None, "template": True}, "layer_map": {}}
    m = project["meta"]
    m["location"]["address"] = body.get("address", "") or ""
    for k in ("gfa_m2", "apartments", "plot_area_m2", "height_m", "far_area_m2", "coverage_m2"):
        if body.get(k) not in (None, ""):
            m[k] = float(body[k]) if k != "apartments" else int(float(body[k]))
    if isinstance(body.get("permit"), dict):
        m["permit"].update({k: v for k, v in body["permit"].items() if v not in (None, "")})
    if m["gfa_m2"]:
        m["conditioned_area_m2"] = round(m["gfa_m2"] * 0.9, 1)
    if body.get("year_built") not in (None, ""):
        m["year_built"] = int(float(body["year_built"]))
    store.save(project)
    return _slim(project)


@app.get("/api/projects/{pid}")
def project_info(pid: str) -> dict[str, Any]:
    return _slim(get_project(pid))


@app.delete("/api/projects/{pid}")
def delete_project(pid: str) -> dict[str, Any]:
    if _only_kifisia():
        raise HTTPException(403, "Η έκδοση της διπλωματικής αφορά μόνο το έργο της Κηφισιάς – δεν διαγράφονται έργα.")
    if pid == "demo-kifisia":
        raise HTTPException(400, "Το έργο demo δεν διαγράφεται (ξαναδημιουργείται αυτόματα).")
    if not store.exists(pid):
        raise HTTPException(404, "project not found")
    moved = store.delete(pid)
    return {"ok": True, "moved_to": moved}


@app.patch("/api/projects/{pid}/meta")
def patch_meta(pid: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    p = get_project(pid)

    def merge(a: dict, b: dict) -> None:
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                merge(a[k], v)
            else:
                a[k] = v
    for key in ("name", "name_en"):
        if key in body:
            p[key] = body[key]
    merge(p["meta"], body.get("meta", {}))
    if "storeys" in body:
        p["storeys"] = body["storeys"]
    if "apartments" in body:
        p["apartments"] = body["apartments"]
    if "areas" in body:
        p["areas"].update(body["areas"])
    store.save(p)
    return _slim(p)


@app.patch("/api/projects/{pid}/settings")
def patch_settings(pid: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    p = get_project(pid)
    st = analysis.settings(p)
    for k, v in body.items():
        if isinstance(v, dict) and isinstance(st.get(k), dict) and k not in ("energy",):
            st[k].update(v)
        else:
            st[k] = v
    for k in ("price_overrides", "custom_cost_lines", "maintenance_overrides", "energy_overrides"):
        if k in body:
            p[k] = body[k]
            st.pop(k, None)
    store.save(p)
    return {"ok": True, "settings": st}


@app.get("/api/projects/{pid}/settings")
def get_settings(pid: str) -> dict[str, Any]:
    p = get_project(pid)
    return {"settings": analysis.settings(p), "price_overrides": p.get("price_overrides", {}), "custom_cost_lines": p.get("custom_cost_lines", []),
            "maintenance_overrides": p.get("maintenance_overrides", [])}


# ---------------------------------------------------------------- model & elements
@app.get("/api/projects/{pid}/model.glb")
def model_glb(pid: str) -> Response:
    get_project(pid)
    f = store.glb_path(pid)
    if not f.exists():
        raise HTTPException(404, "no 3D model yet")
    return FileResponse(f, media_type="model/gltf-binary", headers={"Cache-Control": "no-cache"})


@app.get("/api/projects/{pid}/elements")
def elements(pid: str, kind: str | None = None, storey: str | None = None, limit: int = 2000) -> dict[str, Any]:
    p = get_project(pid)
    els = [e for e in p["elements"] if (not kind or e["kind"] == kind) and (not storey or e.get("storey") == storey)]
    out = [{"id": e["id"], "name": e["name"], "kind": e["kind"], "ifc_class": e["ifc_class"], "storey": e.get("storey"), "layer": e.get("layer"), "material": e.get("material"),
            "volume_m3": e["qty"].get("volume_m3"), "area_m2": e["qty"].get("face_area_m2") or e["qty"].get("area_m2") or e["qty"].get("plan_area_m2"),
            "length_m": e["qty"].get("length_m"), "height_m": e["qty"].get("height_m"), "color": (e.get("props") or {}).get("color")} for e in els[:limit]]
    return {"count": len(els), "elements": out, "kinds": ingest.KINDS}


@app.patch("/api/projects/{pid}/elements/{eid}")
def patch_element(pid: str, eid: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    p = get_project(pid)
    for e in p["elements"]:
        if e["id"] == eid:
            for k in ("kind", "storey", "material", "name"):
                if k in body:
                    e[k] = body[k]
            if "kind" in body:
                e["ifc_class"] = ingest.IFC_CLASS.get(body["kind"], e["ifc_class"])
            store.save(p)
            return {"ok": True}
    raise HTTPException(404, "element not found")


@app.get("/api/projects/{pid}/layers")
def layers(pid: str) -> dict[str, Any]:
    p = get_project(pid)
    parts = store.load_parts(pid)
    if parts is None:
        agg: dict[str, dict] = {}
        for e in p["elements"]:
            a = agg.setdefault(e.get("layer") or e["name"], {"layer": e.get("layer") or e["name"], "count": 0, "volume_m3": 0.0, "kind": e["kind"], "suggested": e["kind"]})
            a["count"] += 1
            a["volume_m3"] = round(a["volume_m3"] + e["qty"].get("volume_m3", 0.0), 3)
        return {"layers": sorted(agg.values(), key=lambda x: -x["count"]), "kinds": ingest.KINDS, "remappable": False}
    return {"layers": ingest.layer_summary(parts, p.get("layer_map")), "kinds": ingest.KINDS, "remappable": True}


def _rebuild(p: dict[str, Any], parts: list[dict[str, Any]], layer_map: dict[str, str]) -> dict[str, Any]:
    elements = ingest.build_elements(parts, layer_map)
    storeys = p["storeys"] if p.get("storeys") and p["meta"].get("storeys_locked") else ingest.detect_storeys(elements)
    ingest.assign_storeys(elements, [{"id": s["id"], "elevation_m": s["elevation_m"]} for s in storeys])
    meshes = {e["id"]: part["mesh"] for e, part in zip(elements, parts)}
    p["elements"], p["storeys"], p["layer_map"] = elements, storeys, layer_map
    slab_area = sum(e["qty"].get("plan_area_m2", 0.0) for e in elements if e["kind"] == "slab")
    zs = [e["bbox"][5] for e in elements if e["kind"] not in ("site", "vegetation")]
    p["meta"]["synthetic_geometry"] = False
    if not p["meta"].get("gfa_m2"):
        p["meta"]["gfa_m2"] = round(slab_area, 1)
    if not p["meta"].get("conditioned_area_m2"):
        p["meta"]["conditioned_area_m2"] = round(0.6 * p["meta"]["gfa_m2"], 1)
    p["meta"]["height_m"] = round(max(zs) - min(e["bbox"][2] for e in elements), 2) if zs else 0
    store.save(p)
    ingest.export_glb(elements, meshes, store.glb_path(p["id"]))
    return p


@app.post("/api/projects/{pid}/layers/map")
def map_layers(pid: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    p = get_project(pid)
    parts = store.load_parts(pid)
    if parts is None:
        raise HTTPException(400, "this project has no source parts to re-map (upload a 3D file first)")
    lm = dict(p.get("layer_map") or {})
    lm.update({k: v for k, v in (body.get("map") or {}).items() if v in ingest.KINDS})
    p = _rebuild(p, parts, lm)
    return _slim(p)


# ---------------------------------------------------------------- uploads
UPLOAD_LIMITS = {"file_mb": 100, "model_mb": 300, "files_per_project": 60, "project_mb": 1500}   # drawings/PDF, 3D model, count, total per project


@app.get("/api/limits")
def limits() -> dict[str, Any]:
    return UPLOAD_LIMITS


@app.get("/api/projects/{pid}/files")
def list_files(pid: str) -> dict[str, Any]:
    get_project(pid)
    fs = [{"name": x.name, "mb": round(x.stat().st_size / 1048576, 2)} for x in sorted(store.upload_dir(pid).iterdir()) if x.is_file()]
    return {"files": fs, "count": len(fs), "total_mb": round(sum(f["mb"] for f in fs), 2), "limits": UPLOAD_LIMITS}


@app.delete("/api/projects/{pid}/files/{name}")
def delete_file(pid: str, name: str) -> dict[str, Any]:
    p = get_project(pid)
    f = store.upload_dir(pid) / Path(name).name
    if not f.is_file():
        raise HTTPException(404, "file not found")
    f.unlink()
    if p.get("plans"):
        p["plans"] = [x for x in p["plans"] if x.get("name") != f.name]
        store.save(p)
    return {"ok": True}


@app.post("/api/projects/{pid}/upload")
async def upload(pid: str, file: UploadFile = File(...), up: str | None = Query(None), scale: float | None = Query(None)) -> dict[str, Any]:
    p = get_project(pid)
    name = Path(file.filename or "upload").name
    ext = Path(name).suffix.lower()
    lim = UPLOAD_LIMITS["model_mb" if ext in MODEL_EXT else "file_mb"]
    have = [x for x in store.upload_dir(pid).iterdir() if x.is_file() and x.name != name]
    if len(have) >= UPLOAD_LIMITS["files_per_project"]:
        raise HTTPException(413, f"Το έργο έχει ήδη {len(have)} αρχεία (όριο {UPLOAD_LIMITS['files_per_project']}). Διαγράψτε κάποια ή φτιάξτε νέο έργο.")
    dest = store.upload_dir(pid) / name
    size = 0
    with open(dest, "wb") as f:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > lim * 1024 * 1024:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"Το αρχείο {name} ξεπερνά το όριο {lim} MB για αυτόν τον τύπο. Μειώστε το (π.χ. εξαγωγή GLB με λιγότερα τρίγωνα, PDF χωρίς σκαναρισμένες εικόνες).")
            f.write(chunk)
    if sum(x.stat().st_size for x in store.upload_dir(pid).iterdir() if x.is_file()) > UPLOAD_LIMITS["project_mb"] * 1024 * 1024:
        dest.unlink(missing_ok=True)
        raise HTTPException(413, f"Ξεπεράστηκε το συνολικό όριο {UPLOAD_LIMITS['project_mb']} MB αρχείων ανά έργο.")
    if ext == ".pdf" and await run_in_threadpool(structural.looks_like_statics, dest):
        return await _attach_statics(p, dest, name)
    if ext in PLAN_EXT:
        info = plans.inspect(dest, store.plans_dir(pid))
        p.setdefault("plans", [])
        p["plans"] = [x for x in p["plans"] if x["name"] != name] + [info]
        store.save(p)
        return {"kind": "plan", "info": info}
    if ext in MODEL_EXT:
        try:
            parts, info = ingest.load_parts(dest, up=up, scale=scale)
        except Exception as ex:
            raise HTTPException(422, f"cannot read the 3D file: {ex}")
        if not parts:
            raise HTTPException(422, "the 3D file contains no geometry")
        store.save_parts(pid, parts)
        p = _rebuild(p, parts, p.get("layer_map") or {})
        p["model_source"] = info
        store.save(p)
        return {"kind": "model", "info": info, "project": _slim(p), "layers": ingest.layer_summary(parts, p.get("layer_map"))}
    raise HTTPException(415, f"unsupported file type {ext}")


async def _attach_statics(p: dict[str, Any], dest: Path, name: str) -> dict[str, Any]:
    try:
        st = await run_in_threadpool(structural.parse_statics_pdf, dest)
        cap = structural.capacity(st, p, {})
    except (ValueError, KeyError) as ex:
        raise HTTPException(422, str(ex))
    st["file"] = name
    p["meta"]["structural"] = st
    d = st["design"]
    s_ = p["meta"].setdefault("structure", {})
    for k_src, k_dst in (("zone", "seismic_zone"), ("a_g", "a_g"), ("gamma_I", "gamma_I"), ("q", "q"), ("soil", "soil"), ("T1", "T1"), ("T2", "T2"), ("Tx", "Tx"), ("Ty", "Ty"), ("concrete", "concrete"), ("steel", "steel")):
        if d.get(k_src) not in (None, ""):
            s_[k_dst] = d[k_src]
    store.save(p)
    return {"kind": "structural", "capacity": cap, "members": len(st["members"]), "storeys": len(st["storeys"])}


@app.get("/api/projects/{pid}/structural")
def structural_get(pid: str, material_factor: float | None = Query(None, ge=0.8, le=2.0), ductility_capacity: float | None = Query(None, ge=1.0, le=6.0)) -> dict[str, Any]:
    p = get_project(pid)
    params = {k: v for k, v in (("material_factor", material_factor), ("ductility_capacity", ductility_capacity)) if v is not None}
    try:
        cap = structural.for_project(p, params)
    except (ValueError, KeyError) as ex:
        raise HTTPException(422, str(ex))
    return {"has_report": bool(p["meta"].get("structural")), "capacity": cap, "file": (p["meta"].get("structural") or {}).get("file")}


@app.post("/api/projects/{pid}/structural/upload")
async def structural_upload(pid: str, file: UploadFile = File(...)) -> dict[str, Any]:
    p = get_project(pid)
    name = Path(file.filename or "statics.pdf").name
    dest = store.upload_dir(pid) / name
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f, 1024 * 1024)
    return await _attach_statics(p, dest, name)


@app.delete("/api/projects/{pid}/structural")
def structural_clear(pid: str) -> dict[str, Any]:
    p = get_project(pid)
    p["meta"].pop("structural", None)
    store.save(p)
    return {"ok": True}


@app.get("/api/projects/{pid}/plans")
def plan_list(pid: str) -> dict[str, Any]:
    p = get_project(pid)
    return {"plans": p.get("plans", []), "checks": plans.reconcile(p, p.get("plans", []))}


@app.get("/api/projects/{pid}/plans/thumb/{name}")
def plan_thumb(pid: str, name: str) -> Response:
    f = store.plans_dir(pid) / Path(name).name
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/png")


# ---------------------------------------------------------------- 4D-7D
@app.get("/api/projects/{pid}/quantities")
def get_quantities(pid: str) -> dict[str, Any]:
    p = get_project(pid)
    return analysis.quantities_of(p)


@app.get("/api/projects/{pid}/cost")
def get_cost(pid: str) -> dict[str, Any]:
    p = get_project(pid)
    ps = store.price_state()
    q = analysis.quantities_of(p)["quantities"]
    c = analysis.cost_of(p, ps, q)
    pb = cost.load_price_book(p)
    return {"cost": c, "price_book_base": pb["base_period"], "sensitivity": cost.group_sensitivity(p, q, ps), "groups": {k: {"el": v["el"], "en": v["en"]} for k, v in ps["groups"].items()}}


@app.get("/api/projects/{pid}/cost/montecarlo")
def get_mc(pid: str, start_months: float = 6.0, n: int = 2000) -> dict[str, Any]:
    p = get_project(pid)
    ps = store.price_state()
    q = analysis.quantities_of(p)["quantities"]
    c = analysis.cost_of(p, ps, q)
    sch = analysis.schedule_of(p, c)
    return cost.monte_carlo(p, q, ps, sch["midpoints"], start_in_months=start_months, n=min(n, 6000))


@app.get("/api/projects/{pid}/schedule")
def get_schedule(pid: str) -> dict[str, Any]:
    p = get_project(pid)
    c = analysis.cost_of(p, store.price_state())
    return analysis.schedule_of(p, c)


@app.get("/api/projects/{pid}/schedule/state")
def get_4d_state(pid: str, week: float = 0) -> dict[str, Any]:
    p = get_project(pid)
    tasks = schedule.tasks_from_project(p)
    return {"week": week, "state": schedule.state_at(p, tasks, week)}


@app.post("/api/projects/{pid}/energy")
def post_energy(pid: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    p = get_project(pid)
    ps = store.price_state()
    q = analysis.quantities_of(p)["quantities"]
    st = analysis.settings(p)
    if "selected" in body or "preset" in body:
        st["energy"] = {"preset": body.get("preset", st["energy"].get("preset", "as_certified")), "selected": body.get("selected", st["energy"].get("selected", {}))}
        store.save(p)
    res = analysis.energy_of(p, q, ps)
    res.pop("baseline_state", None)
    return {"study": res, "state": st["energy"]}


@app.get("/api/projects/{pid}/energy/baseline")
def get_baseline(pid: str) -> dict[str, Any]:
    p = get_project(pid)
    q = analysis.quantities_of(p)["quantities"]
    return energy.baseline_for(p, q)


@app.put("/api/projects/{pid}/energy/baseline")
def put_baseline(pid: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    p = get_project(pid)
    p["energy_baseline"] = body
    store.save(p)
    return {"ok": True}


@app.post("/api/projects/{pid}/lifecycle")
def post_lifecycle(pid: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    p = get_project(pid)
    ps = store.price_state()
    q = analysis.quantities_of(p)["quantities"]
    c = analysis.cost_of(p, ps, q)
    en = analysis.energy_of(p, q, ps)
    if body.get("assumptions"):
        analysis.settings(p)["lifecycle"].update(body["assumptions"])
        store.save(p)
    return analysis.lifecycle_of(p, c, q, en, body.get("assumptions"))


# ---------------------------------------------------------------- 7D facility management
@app.get("/api/projects/{pid}/fm")
def get_fm(pid: str) -> dict[str, Any]:
    p = get_project(pid)
    ps = store.price_state()
    q = analysis.quantities_of(p)["quantities"]
    c = analysis.cost_of(p, ps, q)
    en = analysis.energy_of(p, q, ps)
    lc = analysis.lifecycle_of(p, c, q, en)
    risk = analysis.hazards_summary(p, c, q)
    return analysis.fm_of(p, c, lc, risk)


@app.put("/api/projects/{pid}/fm/properties")
def put_properties(pid: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Replace the table of shares (σύσταση): {properties: [{id, name_el, type, storey, area_m2, total_m2, keys: {votes, lighting, ...}}], common_areas: [...]}."""
    p = get_project(pid)
    rows = body.get("properties")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(422, "properties: λίστα ιδιοκτησιών")
    for r in rows:
        if not r.get("id") or not isinstance(r.get("keys"), dict):
            raise HTTPException(422, "Κάθε ιδιοκτησία χρειάζεται id και keys (χιλιοστά).")
        r.pop("owner", None)                                           # owners are not kept
    cur = fm.properties_of(p)
    p["properties"] = {"_source": body.get("_source") or cur.get("_source") or "Πίνακας ποσοστών (χρήστης)", "_source_en": body.get("_source_en") or cur.get("_source_en") or "Table of shares (user)",
                       "keys": cur["keys"], "properties": rows, "common_areas": body.get("common_areas", cur.get("common_areas", []))}
    store.save(p)
    return {"ok": True, "checks": fm.check_table(p["properties"])}


@app.patch("/api/projects/{pid}/fm/allocation")
def patch_allocation(pid: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """How a component's cost is split, e.g. {"hvac": {"private": 1.0}}; the shares of each component must add up to 1."""
    p = get_project(pid)
    for k, v in body.items():
        if not isinstance(v, dict) or abs(sum(float(x) for x in v.values()) - 1.0) > 1e-6:
            raise HTTPException(422, f"{k}: τα μερίδια πρέπει να αθροίζουν 1")
    analysis.settings(p).setdefault("fm_allocation", {}).update(body)
    store.save(p)
    return {"ok": True}


@app.get("/api/hazards/defaults")
def hazard_defaults() -> dict[str, Any]:
    return hazards.defaults({"meta": {"gfa_m2": 1000.0}})


@app.post("/api/projects/{pid}/hazards/run")
def run_hazard(pid: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    p = get_project(pid)
    c = analysis.cost_of(p, store.price_state())
    kind = body.get("kind", "seismic")
    params = body.get("params", {})
    try:
        if kind == "seismic" and body.get("all"):
            res = hazards.seismic_all(p, c, params)
        elif kind == "flood" and body.get("all"):
            res = hazards.flood_all(p, c, params)
        else:
            res = hazards.run(p, c, kind, params)
    except (ValueError, KeyError, StopIteration) as ex:
        raise HTTPException(422, str(ex))
    st = analysis.settings(p)
    st["hazards"][kind] = params
    store.save(p)
    return res


@app.post("/api/projects/{pid}/hazards/risk")
def hazards_risk(pid: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    p = get_project(pid)
    c = analysis.cost_of(p, store.price_state())
    q = analysis.quantities_of(p)["quantities"]
    st = analysis.settings(p)
    if "exposure" in body:
        st["exposure"].update(body["exposure"])
        store.save(p)
    return hazards.risk_summary(p, c, q, base_params=st["hazards"], exposure=st["exposure"])


# ---------------------------------------------------------------- prices
@app.get("/api/prices")
def get_prices() -> dict[str, Any]:
    ps = store.price_state()
    safe = json.loads(json.dumps(ps))
    safe["settings"] = {k: ("•••" if v and "key" in k or v and "token" in k else v) for k, v in safe["settings"].items()}
    return {"state": safe, "behaviour": prices.describe_behaviour(ps)}


@app.post("/api/prices/refresh")
def refresh_prices(history: bool = True) -> dict[str, Any]:
    ps = store.price_state()
    out = prices.refresh_all(ps)
    hist = prices.refresh_history(ps) if history else {}
    with LOCK:
        store.save_price_state(ps)
    return {"result": out, "history": hist, "behaviour": prices.describe_behaviour(ps)}


@app.post("/api/prices/dynamics")
def price_dynamics(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    ps = store.price_state()
    if body.get("use") == "calibrated":
        prices.use_calibrated_dynamics(ps)
    else:
        prices.use_assumed_dynamics(ps)
    store.save_price_state(ps)
    return {"ok": True, "behaviour": prices.describe_behaviour(ps)}


# ---------------------------------------------------------------- live site data (cadastre, earthquakes, climate)
@app.get("/api/status/auto")
def auto_status() -> dict[str, Any]:
    return AUTO


@app.get("/api/projects/{pid}/live")
def get_live(pid: str, light: bool = False) -> dict[str, Any]:
    p = get_project(pid)
    lv = p.get("live") or {}
    if light:
        return {"use": lv.get("use") or {}, "climate_period": (lv.get("climate") or {}).get("period"), "seismic_fetched": (lv.get("seismic") or {}).get("fetched"),
                "climate_fetched": (lv.get("climate") or {}).get("fetched")}
    out = {"live": lv, "site": live.site_point(p), "auto": {k: AUTO[k] for k in ("running", "started", "finished")},
           "design_climate": {"T_ext": energy.T_EXT, "G_h": energy.G_H}, "scenarios": hazards.load()["seismic"]["scenarios"],
           "offline": live.offline()}
    if lv.get("climate"):
        # 6D effect of the site's climate: the same building on the design climate vs on the measured one
        q = analysis.quantities_of(p)["quantities"]
        ps = store.price_state()
        use = dict((lv.get("use") or {}))
        res = {}
        for flag in (False, True):
            pp = dict(p)
            pp["live"] = {**lv, "use": {**use, "climate": flag}}
            e = analysis.energy_of(pp, q, ps)["baseline"]
            res["site" if flag else "design"] = {"primary_kwh_m2": e["primary_kwh_m2"], "class": e["class"], "energy_cost_eur_year": e["energy_cost_eur_year"],
                                                 "heating_kwh_m2": e["needs"]["heating_kwh_m2"], "cooling_kwh_m2": e["needs"]["cooling_kwh_m2"], "co2_kg_m2": e["co2_kg_m2"]}
        out["energy_compare"] = res
    if (lv.get("seismic") or {}).get("strongest_at_site"):
        ev = lv["seismic"]["strongest_at_site"]
        c = analysis.cost_of(p, store.price_state())
        r = hazards.seismic(p, c, {"Ms": ev["mag"], "distance_km": ev.get("d_eff_km", ev["dist_km"])})
        out["historical_scenario"] = {"event": ev, "pga_g": r.get("pga_g"), "mmi": r.get("intensity_mmi"), "loss_eur": r.get("loss_eur"),
                                      "mean_grade": r.get("mean_grade"), "loss_ratio": r.get("loss_ratio"), "downtime_days": r.get("downtime_days"), "p_d3plus": r.get("p_d3plus")}
    return out


@app.post("/api/projects/{pid}/live/refresh")
def refresh_live(pid: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    get_project(pid)
    what = body.get("what") or ["cadastre", "seismic", "climate"]
    st = _refresh_live(pid, what, kaek=body.get("kaek"), params=body.get("params"))
    return {"status": st, **get_live(pid)}


@app.patch("/api/projects/{pid}/live/use")
def live_use(pid: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    with LOCK:
        p = get_project(pid)
        u = p.setdefault("live", {}).setdefault("use", {"seismic_rates": False, "climate": False})
        for k in ("seismic_rates", "climate"):
            if k in body:
                u[k] = bool(body[k])
        store.save(p)
    return {"ok": True, "use": u}


@app.patch("/api/prices/group/{group}")
def set_price(group: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    ps = store.price_state()
    if group not in ps["groups"]:
        raise HTTPException(404, "unknown group")
    g = ps["groups"][group]
    if "value" in body:
        prices.set_value(ps, group, float(body["value"]), "manual")
    if "base" in body and float(body["base"]) > 0:
        g["base"] = float(body["base"])
    if "mode" in body:
        g["mode"] = body["mode"]
    if "dynamics" in body:
        ps["dynamics"].setdefault(group, {}).update({k: float(v) for k, v in body["dynamics"].items() if k in ("mu", "sigma")})
    store.save_price_state(ps)
    return {"ok": True, "ratio": prices.ratio(ps, group)}


@app.patch("/api/prices/settings")
def price_settings(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    ps = store.price_state()
    for k in ("tradingeconomics_key", "entsoe_token", "timeout_s"):
        if k in body:
            ps["settings"][k] = body[k]
    store.save_price_state(ps)
    return {"ok": True}


@app.get("/api/prices/paths")
def price_paths(years: float = 3.0, n: int = 400) -> dict[str, Any]:
    ps = store.price_state()
    import numpy as np
    paths = prices.simulate_ratio_paths(ps, list(ps["groups"].keys()), years, n=min(n, 2000))
    out = {}
    for g, a in paths.items():
        out[g] = {"p10": np.percentile(a, 10, axis=0).round(4).tolist(), "p50": np.percentile(a, 50, axis=0).round(4).tolist(), "p90": np.percentile(a, 90, axis=0).round(4).tolist()}
    return {"months": len(next(iter(out.values()))["p50"]) - 1, "paths": out}


# ---------------------------------------------------------------- report
@app.post("/api/projects/{pid}/report")
def make_report(pid: str, body: dict[str, Any] = Body(default={})) -> Response:
    from . import report
    p = get_project(pid)
    ps = store.price_state()
    lang = body.get("lang", "el")
    data = analysis.everything(p, ps)
    pdf = report.build(p, ps, data, lang=lang, sections=body.get("sections"), notes=body.get("notes", ""), author=body.get("author", ""))
    fname = f"{pid}_{lang}.pdf"
    (store.project_dir(pid) / fname).write_bytes(pdf)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---------------------------------------------------------------- static
if (WEB / "vendor").exists():
    app.mount("/vendor", StaticFiles(directory=WEB / "vendor"), name="vendor")
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
def index() -> Response:
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})
