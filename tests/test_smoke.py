"""End-to-end smoke tests (run: python -m pytest -q tests)."""
import io
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest
import trimesh

os.environ["BIM7D_DATA"] = tempfile.mkdtemp(prefix="bim7d_test_")

from fastapi.testclient import TestClient  # noqa: E402

from app import cost, energy, hazards, ingest, prices  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
PID = "demo-kifisia"


@pytest.fixture(scope="module", autouse=True)
def _startup():
    with TestClient(app) as c:     # runs the startup hook that creates the demo project
        yield c


# ------------------------------------------------------------------ demo project, 4D-7D
def test_demo_project_and_quantities():
    p = client.get(f"/api/projects/{PID}").json()
    assert p["element_count"] > 200 and len(p["storeys"]) >= 4
    q = client.get(f"/api/projects/{PID}/quantities").json()
    assert q["quantities"]["concrete_structure_m3"] > 100
    assert 60 < q["totals"]["rebar_kg_per_m3"] < 200


def test_cost_sanity_and_overrides():
    c = client.get(f"/api/projects/{PID}/cost").json()["cost"]
    per_m2_incl_vat = c["total_with_vat"] / client.get(f"/api/projects/{PID}").json()["meta"]["gfa_m2"]
    assert 1000 < per_m2_incl_vat < 2200
    assert abs(c["direct"] + c["general_expenses"] + c["profit"] + c["contingency"] - c["net"]) < 1
    assert abs(c["net"] * (1 + c["overheads"]["vat_pct"] / 100) - c["total_with_vat"]) < 1
    # disable a line and override a price -> total must change
    key = c["lines"][3]["key"]
    s = client.get(f"/api/projects/{PID}/settings").json()["settings"]
    client.patch(f"/api/projects/{PID}/settings", json={"price_overrides": {"items": {key: {"disabled": True}}}})
    c2 = client.get(f"/api/projects/{PID}/cost").json()["cost"]
    assert c2["net"] < c["net"]
    client.patch(f"/api/projects/{PID}/settings", json={"price_overrides": {"items": {}}})
    assert abs(client.get(f"/api/projects/{PID}/cost").json()["cost"]["net"] - c["net"]) < 1


def test_monte_carlo_ordering():
    m = client.get(f"/api/projects/{PID}/cost/montecarlo?start_months=6&n=500").json()
    assert m["p10"] <= m["p50"] <= m["p90"] <= m["p95"]


def test_schedule_and_4d_state():
    s = client.get(f"/api/projects/{PID}/schedule").json()
    assert s["weeks"] > 30 and s["critical_path"]
    st0 = client.get(f"/api/projects/{PID}/schedule/state?week=0").json()["state"]
    st1 = client.get(f"/api/projects/{PID}/schedule/state?week={s['weeks']}").json()["state"]
    assert set(st0.values()) <= {"todo", "active", "done"}
    assert sum(v == "done" for v in st1.values()) > sum(v == "done" for v in st0.values())
    # cumulative cost is monotone and ends at the net cost
    cum = [c["cumulative"] for c in s["curve"]]
    assert all(b >= a - 1e-6 for a, b in zip(cum, cum[1:]))


def test_energy_upgrades_reduce_demand():
    base = client.post(f"/api/projects/{PID}/energy", json={"preset": "pre_2010", "selected": {}}).json()["study"]
    sel = {"roof_insulation_panel": {"enabled": True}, "pv_roof_panels": {"enabled": True}}
    ids = [m["id"] for m in base["measures"]]
    sel = {k: v for k, v in sel.items() if k in ids} or {ids[0]: {"enabled": True}}
    pk = client.post(f"/api/projects/{PID}/energy", json={"preset": "pre_2010", "selected": sel}).json()["study"]
    assert pk["package"]["primary_kwh_m2"] < base["baseline"]["primary_kwh_m2"]
    assert pk["package_cost_eur"] > 0


def test_lifecycle_and_lca():
    r = client.post(f"/api/projects/{PID}/lifecycle", json={"assumptions": {"horizon_years": 50}}).json()
    assert r["base"]["npv_total"] > 1e6 and r["base"]["lca"]["total_kg"] > 1e5
    r2 = client.post(f"/api/projects/{PID}/lifecycle", json={"assumptions": {"horizon_years": 30}}).json()
    assert r2["base"]["npv_total"] < r["base"]["npv_total"]


def test_three_seismic_scenarios_monotonic():
    runs = client.post(f"/api/projects/{PID}/hazards/run", json={"kind": "seismic", "all": True, "params": {}}).json()["runs"]
    assert list(runs) == ["small", "moderate", "large"] or set(runs) >= {"small", "moderate", "large"}
    l = [runs[k]["loss_eur"] for k in ("small", "moderate", "large")]
    assert l[0] < l[1] < l[2]
    assert runs["small"]["pga_g"] < runs["moderate"]["pga_g"] < runs["large"]["pga_g"]
    assert abs(sum(runs["large"]["distribution"]) - 1) < 1e-6
    # strengthening reduces loss
    ids = list(hazards.load()["seismic"]["mitigations"].keys())
    strong = client.post(f"/api/projects/{PID}/hazards/run", json={"kind": "seismic", "all": False, "params": {"Ms": 6.8, "distance_km": 5, "mitigations": ids}}).json()
    assert strong["loss_eur"] < runs["large"]["loss_eur"]


@pytest.mark.parametrize("kind,params", [("fire_internal", {}), ("wildfire", {"distance_m": 5}), ("flood", {"depth_m": 1.5})])
def test_other_hazards(kind, params):
    r = client.post(f"/api/projects/{PID}/hazards/run", json={"kind": kind, "params": params}).json()
    assert r["loss_eur"] >= 0 and 0 <= r["loss_ratio"] <= 1 and isinstance(r["element_damage"], dict)


def test_wildfire_closer_is_worse():
    a = client.post(f"/api/projects/{PID}/hazards/run", json={"kind": "wildfire", "params": {"distance_m": 5}}).json()
    b = client.post(f"/api/projects/{PID}/hazards/run", json={"kind": "wildfire", "params": {"distance_m": 60}}).json()
    assert a["flux_kW_m2"] > b["flux_kW_m2"] and a["loss_eur"] >= b["loss_eur"]


def test_risk_summary():
    r = client.post(f"/api/projects/{PID}/hazards/risk", json={}).json()
    assert r["total_eal_eur"] > 0 and r["mitigations"]
    r0 = client.post(f"/api/projects/{PID}/hazards/risk", json={"exposure": {"flood": 0.0, "wildfire": 0.0}}).json()
    assert r0["hazards"]["flood"] == 0


# ------------------------------------------------------------------ PDF
@pytest.mark.parametrize("lang", ["el", "en"])
def test_report_pdf(lang):
    r = client.post(f"/api/projects/{PID}/report", json={"lang": lang, "author": "Test", "notes": "n"})
    assert r.status_code == 200 and r.content[:5] == b"%PDF-" and len(r.content) > 200_000
    import pymupdf
    d = pymupdf.open(stream=r.content, filetype="pdf")
    assert len(d) >= 12
    txt = "".join(pg.get_text() for pg in d)
    assert ("Σεισμός" if lang == "el" else "Earthquake") in txt


# ------------------------------------------------------------------ prices (mocked network)
def test_price_parsers():
    y = json.dumps({"chart": {"result": [{"meta": {"regularMarketPrice": 4.55}, "indicators": {"quote": [{"close": [4.4, 4.5]}]}}]}})
    assert prices.parse_yahoo_chart(y) == 4.55
    y2 = json.dumps({"chart": {"result": [{"meta": {}, "indicators": {"quote": [{"close": [4.4, None, 4.5]}]}}]}})
    assert prices.parse_yahoo_chart(y2) == 4.5
    te = json.dumps([{"Name": "Aluminum", "Last": 2600}, {"Name": "Steel", "Symbol": "JBP", "Last": 3133.5}])
    assert prices.parse_tradingeconomics(te, "steel") == 3133.5
    with pytest.raises(LookupError):
        prices.parse_tradingeconomics(te, "gold")
    xml = '<Publication_MarketDocument xmlns="urn:x"><TimeSeries><Period><Point><position>1</position><price.amount>100</price.amount></Point><Point><position>2</position><price.amount>140</price.amount></Point></Period></TimeSeries></Publication_MarketDocument>'
    assert prices.parse_entsoe_day_ahead(xml) == 120.0


def test_refresh_all_soft_failure_and_success():
    st = prices.default_state()
    def boom(url, timeout, headers=None):
        raise TimeoutError("offline")
    out = prices.refresh_all(st, http=boom)
    assert out and all(not v["ok"] for v in out.values()) and st["groups"]["copper"]["error"]
    v0 = prices.ratio(st, "copper")
    assert v0 == pytest.approx(1.113, abs=0.01)           # last value (ELSTAT seed, Sep 2026) kept after failure
    rnd = {"px": 5.0}
    def fake(url, timeout, headers=None):
        px = rnd["px"]
        return json.dumps({"chart": {"result": [{"meta": {"regularMarketPrice": px}, "indicators": {"quote": [{"close": [px]}]}}]}}).encode()
    st = prices.default_state()
    prices.refresh_all(st, http=fake)
    r1 = prices.ratio(st, "copper")
    rnd["px"] = 5.5
    prices.refresh_all(st, http=fake)                       # +10% commodity move on second fetch
    assert prices.ratio(st, "copper") == pytest.approx(r1 * 1.1, rel=1e-6)


def test_price_api_edit_changes_cost():
    c0 = client.get(f"/api/projects/{PID}/cost").json()["cost"]["net"]
    g = client.get("/api/prices").json()["state"]["groups"]["labour"]
    client.patch("/api/prices/group/labour", json={"value": g["value"] * 1.3})
    c1 = client.get(f"/api/projects/{PID}/cost").json()["cost"]["net"]
    assert c1 > c0
    client.patch("/api/prices/group/labour", json={"value": g["value"]})
    assert abs(client.get(f"/api/projects/{PID}/cost").json()["cost"]["net"] - c0) < 1


# ------------------------------------------------------------------ input loaders
def _boxes():
    """A tiny 2-storey frame made of boxes on named layers."""
    parts = []
    def add(name, layer, ext, pos):
        m = trimesh.creation.box(extents=ext); m.apply_translation(pos); parts.append((name, layer, m))
    for i, (x, y) in enumerate([(0, 0), (6, 0), (0, 5), (6, 5)]):
        add(f"c{i}", "column_ground", (0.3, 0.3, 3.0), (x, y, 1.5))
        add(f"d{i}", "column_first", (0.3, 0.3, 3.0), (x, y, 4.5))
    add("s0", "slab_ground", (6.6, 5.6, 0.2), (3, 2.5, 3.0)); add("s1", "slab_first", (6.6, 5.6, 0.2), (3, 2.5, 6.0))
    add("f0", "foundation", (7, 6, 0.5), (3, 2.5, -0.25))
    return parts


@pytest.mark.parametrize("fmt", ["glb", "obj"])
def test_model_upload_glb_obj(fmt, tmp_path):
    scene = trimesh.Scene()
    for name, layer, m in _boxes():
        scene.add_geometry(m, node_name=layer + "_" + name, geom_name=layer + "_" + name)
    f = tmp_path / f"m.{fmt}"
    scene.export(f)
    pid = client.post("/api/projects", json={"name": f"Test {fmt}", "gfa_m2": 80}).json()["id"]
    with open(f, "rb") as fh:
        r = client.post(f"/api/projects/{pid}/upload", files={"file": (f.name, fh, "application/octet-stream")})
    assert r.status_code == 200, r.text
    p = client.get(f"/api/projects/{pid}").json()
    assert p["element_count"] >= 5
    assert client.get(f"/api/projects/{pid}/model.glb").status_code == 200
    q = client.get(f"/api/projects/{pid}/quantities").json()["quantities"]
    assert q["concrete_structure_m3"] > 0
    assert client.get(f"/api/projects/{pid}/cost").status_code == 200
    assert client.post(f"/api/projects/{pid}/energy", json={}).status_code == 200
    assert client.post(f"/api/projects/{pid}/hazards/run", json={"kind": "seismic", "all": True, "params": {}}).status_code == 200
    rep = client.post(f"/api/projects/{pid}/report", json={"lang": "en"})
    assert rep.status_code == 200 and rep.content[:4] == b"%PDF"
    client.delete(f"/api/projects/{pid}")


def test_model_upload_3dm(tmp_path):
    rhino3dm = pytest.importorskip("rhino3dm")
    f = rhino3dm.File3dm()
    f.Settings.ModelUnitSystem = rhino3dm.UnitSystem.Meters
    keep = []                                              # rhino3dm wraps native objects: keep every Python wrapper alive until Write()
    for lay in ("column_ground", "slab_ground"):
        l = rhino3dm.Layer(); l.Name = lay; f.Layers.Add(l); keep.append(l)
    li = {l.Name: i for i, l in enumerate(f.Layers)}
    def brep_box(x0, y0, z0, x1, y1, z1):
        bb = rhino3dm.BoundingBox(rhino3dm.Point3d(x0, y0, z0), rhino3dm.Point3d(x1, y1, z1))
        return rhino3dm.Brep.CreateFromBox(rhino3dm.Box(bb))
    def mesh_box(x0, y0, z0, x1, y1, z1):                  # a light mesh export (what the README recommends)
        m = rhino3dm.Mesh()
        for z in (z0, z1):
            for (x, y) in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                m.Vertices.Add(x, y, z)
        for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            m.Faces.AddFace(*q)
        return m
    items = (("column_ground", brep_box(0, 0, 0, 0.3, 0.3, 3)), ("column_ground", mesh_box(6, 0, 0, 6.3, 0.3, 3)), ("slab_ground", mesh_box(0, 0, 3, 6.3, 5, 3.2)))
    for lay, g in items:
        a = rhino3dm.ObjectAttributes(); a.LayerIndex = li[lay]; keep.append(a)
        (f.Objects.AddBrep if isinstance(g, rhino3dm.Brep) else f.Objects.AddMesh)(g, a)
    path = tmp_path / "t.3dm"; f.Write(str(path), 7); del keep
    parts, info = ingest.load_parts(path)
    assert len(parts) >= 2
    els = ingest.build_elements(parts)
    assert any(e["kind"] == "column" for e in els) and any(e["kind"] == "slab" for e in els)
    assert max(e["bbox"][5] for e in els) == pytest.approx(3.2, abs=0.05)


def test_model_upload_ifc(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.api
    f = ifcopenshell.api.run("project.create_file")
    proj = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject", name="t")
    ifcopenshell.api.run("unit.assign_unit", f)
    ctx = ifcopenshell.api.run("context.add_context", f, context_type="Model")
    body = ifcopenshell.api.run("context.add_context", f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=ctx)
    site = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcSite", name="s")
    bld = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuilding", name="b")
    st = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="L0")
    ifcopenshell.api.run("aggregate.assign_object", f, products=[site], relating_object=proj)
    ifcopenshell.api.run("aggregate.assign_object", f, products=[bld], relating_object=site)
    ifcopenshell.api.run("aggregate.assign_object", f, products=[st], relating_object=bld)
    for cls, name, dims, pos in (("IfcColumn", "C1", (0.3, 0.3, 3.0), (0, 0, 0)), ("IfcSlab", "S1", (6.0, 5.0, 0.2), (0, 0, 3.0))):
        e = ifcopenshell.api.run("root.create_entity", f, ifc_class=cls, name=name)
        rep = ifcopenshell.api.run("geometry.add_wall_representation", f, context=body, length=dims[0], height=dims[2], thickness=dims[1]) if cls == "IfcColumn" else ifcopenshell.api.run("geometry.add_slab_representation", f, context=body, depth=dims[2], polyline=[(0, 0), (dims[0], 0), (dims[0], dims[1]), (0, dims[1])])
        ifcopenshell.api.run("geometry.assign_representation", f, product=e, representation=rep)
        ifcopenshell.api.run("spatial.assign_container", f, products=[e], relating_structure=st)
    path = tmp_path / "t.ifc"; f.write(str(path))
    parts, info = ingest.load_parts(path)
    assert len(parts) == 2
    kinds = {e["kind"] for e in ingest.build_elements(parts)}
    assert {"column", "slab"} <= kinds


def test_plan_upload_dxf_and_pdf(tmp_path):
    import ezdxf
    doc = ezdxf.new("R2010"); doc.layers.add("WALLS")
    msp = doc.modelspace()
    for a, b in (((0, 0), (10, 0)), ((10, 0), (10, 8)), ((10, 8), (0, 8)), ((0, 8), (0, 0))):
        msp.add_line(a, b, dxfattribs={"layer": "WALLS"})
    msp.add_text("ΚΑΤΟΨΗ ΙΣΟΓΕΙΟΥ", dxfattribs={"layer": "WALLS", "height": 0.3})
    d = tmp_path / "plan.dxf"; doc.saveas(d)
    from reportlab.pdfgen import canvas
    pdf = tmp_path / "plan.pdf"; c = canvas.Canvas(str(pdf)); c.drawString(100, 700, "SECTION A-A 1:100"); c.rect(100, 400, 200, 200); c.save()
    pid = client.post("/api/projects", json={"name": "Plans test"}).json()["id"]
    for f in (d, pdf):
        with open(f, "rb") as fh:
            r = client.post(f"/api/projects/{pid}/upload", files={"file": (f.name, fh, "application/octet-stream")})
        assert r.status_code == 200, r.text
        assert r.json()["kind"] == "plan"
    pl = client.get(f"/api/projects/{pid}/plans").json()
    assert len(pl["plans"]) == 2 and pl["checks"]
    client.delete(f"/api/projects/{pid}")


def test_bad_uploads_rejected():
    pid = client.post("/api/projects", json={"name": "Bad uploads"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 415
    r = client.post(f"/api/projects/{pid}/upload", files={"file": ("x.glb", b"not a glb", "application/octet-stream")})
    assert r.status_code == 422
    client.delete(f"/api/projects/{pid}")


# ------------------------------------------------------------------ demo geometry: footprints/levels/excavation of the permit
def test_demo_geometry_matches_permit_data():
    from app import demo, plans, quantities
    p = store_load()
    g3 = p["geometry3d"]
    # floor areas of the area calculation sheet (Δ.01): basement 330.27 + 13.68, ground 241.79, 1st 167.31, 2nd 186.11
    for key, target in (("basement", 343.95), ("ground", 241.79), ("first", 167.31), ("second", 186.11)):
        assert abs(g3["footprints"][key] - target) < 0.05, (key, g3["footprints"][key], target)
        assert demo._poly(demo.G[key]).geom_type == "Polygon", f"{key} footprint should be one connected shape"
    assert abs(g3["coverage_model_m2"] - 247.55) < 0.02                       # coverage = ground floor 241.79 + semi-open 5.76
    assert abs(g3["balconies"]["first"] - 58.92) < 0.01 and abs(g3["balconies"]["second"] - 96.06) < 0.01
    assert abs(sum(g3["semi_open"].values()) - 32.90) < 0.02
    levels = {s["key"]: s["elevation_m"] for s in p["storeys"]}
    assert levels == {"basement": -3.0, "ground": 0.0, "first": 3.05, "second": 6.1, "attic": 9.3}          # sections A-A' / B-B'
    # right wing of the 1st floor exists (it was missing in the first synthetic massing)
    first = demo._poly(demo.G["first"])
    assert first.bounds[0] < 0.5 and first.bounds[2] > 17.5
    # quantities driven by the permit: coverage, planting, excavation diagram
    q = quantities.compute(p)["quantities"]
    assert abs(q["site_area_m2"] - (1023.47 - 247.55)) < 0.01
    assert abs(q["planting_m2"] - 530.61) < 0.01 and abs(q["paving_m2"] - (775.92 - 530.61)) < 0.01
    assert abs(q["excavation_m3"] - 432.58 * 3.35) < 0.5
    assert 0 < q["backfill_m3"] < 0.3 * q["excavation_m3"] and q["excavation_haul_m3"] > 1000
    sched = [e for e in p["elements"] if e["kind"] == "window" and e["props"].get("window_id")]
    assert len(sched) == 49 and abs(sum(e["qty"]["area_m2"] for e in sched) - 181.77) < 0.01        # all 49 windows of the energy study
    assert q["window_area_m2"] > 181.77                                         # + entrance glazing and basement light-well windows
    assert 1300 < cost.compute(p, q, store_prices())["total_per_m2_gfa"] < 2100
    assert abs(p["meta"]["gfa_m2"] - 1020.39) < 0.01                          # total floor area incl. basement (area tables of the drawings)
    assert [s["name_el"] for s in sorted(p["storeys"], key=lambda s: s["elevation_m"])] == ["Υπόγειο", "Ισόγειο", "Α' όροφος", "Β' όροφος", "Σοφίτα"]
    plan = {e["name"]: e["qty"]["plan_area_m2"] for e in p["elements"] if e["name"] in ("Site ground", "Excavation outline")}
    assert abs(plan["Site ground"] - 1023.47) < 0.01 and abs(plan["Excavation outline"] - 432.58) < 0.01       # the excavation never exceeds the plot
    # the thesis edition has no building-terms checks: only the drawings ↔ 3D consistency checks
    chk = client.get(f"/api/projects/{PID}/plans").json()["checks"]
    assert chk and not any(c["id"].startswith("permit:") for c in chk)

def test_openings_cut_into_walls_and_priced():
    """Openings read from the floor plans: cut out of the walls (net areas), lintels, windows/balcony doors/doors as elements, cost lines."""
    import collections
    from app import demo, quantities
    p = store_load()
    els = p["elements"]
    by = collections.Counter((e["kind"], (e.get("props") or {}).get("opening")) for e in els)
    assert by[("window", "window")] == 33 and by[("window", "balcony_door")] == 17 and by[("window", "entrance")] == 3
    assert by[("door", "garage_door")] == 1 and by[("door", "apartment_entrance")] == 5 and by[("door", "interior_door")] == 35
    lint = [e for e in els if (e.get("props") or {}).get("lintel")]
    assert len(lint) > 80 and all(e["kind"] == "beam" and e["qty"]["length_m"] > e["props"]["span_m"] for e in lint)      # bearing on both sides
    # every element lies on a real storey; walls are watertight bodies with the openings cut out
    assert all(e["storey"] for e in els if e["kind"] in ("window", "door", "wall") and not (e.get("props") or {}).get("landscape"))   # garden items belong to the plot
    walls = [e for e in els if e["kind"] == "wall" and not (e.get("props") or {}).get("internal") and not (e.get("props") or {}).get("retaining")
             and not (e.get("props") or {}).get("landscape")]                  # surroundings have their own cost lines
    gross = sum(e["qty"]["length_m"] * e["qty"]["height_m"] for e in walls)
    net = sum(e["qty"]["face_area_m2"] for e in walls)
    assert net < gross - 100                                                    # > 100 m2 of openings + lintel zones removed from the masonry
    q = quantities.compute(p)["quantities"]
    assert abs(q["masonry_external_m2"] - net) < 0.01                           # walls are already net: no second subtraction
    assert q["lintel_count"] == len(lint) and 140 < q["lintel_length_m"] < 200 and q["lintel_concrete_m3"] > 4
    assert q["interior_doors"] == 35 and q["security_doors"] == 5 and q["garage_door_area_m2"] > 7 and q["masonry_internal_m2"] > 600
    c = cost.compute(p, q, store_prices())
    lines = {l["key"]: l for l in c["lines"]}
    assert lines["lintels"]["qty"] == round(q["lintel_length_m"], 2) and lines["lintels"]["total"] > 0
    assert lines["interior_doors"]["qty"] == 35 and lines["door_frames"]["qty"] == 5 and lines["garage_door"]["total"] > 0
    # lintels are not counted twice in the structural concrete
    struct = sum(e["qty"].get("volume_m3", 0) for e in els if (e["kind"] in ("slab", "column", "beam", "roof", "stair") or (e["kind"] == "wall" and e["material"] == "concrete"))
                 and not (e.get("props") or {}).get("lintel"))
    assert abs(q["concrete_structure_m3"] - struct) < 0.5
    # a model whose walls are not cut still gets the glazing subtracted
    p2 = store_load(); p2["meta"].pop("walls_net_of_openings")
    q2 = quantities.compute(p2)["quantities"]
    assert q2["masonry_external_m2"] < q["masonry_external_m2"]
    assert not demo.build_parts(json.loads((demo.DATA / "members.json").read_text(encoding="utf-8")), [])[1].get("openings_unplaced")


def test_excavation_estimate_without_diagram():
    from app import quantities
    p = store_load()
    p["meta"].pop("excavation"); p["meta"].pop("coverage_m2"); p["meta"].pop("planting_m2")
    q = quantities.compute(p)["quantities"]
    assert q["excavation_m3"] > 0 and q["planting_m2"] > 0 and q["site_area_m2"] > 0


def test_demo_upgrade_keeps_a_backup(tmp_path, monkeypatch):
    from app import demo, store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(store, "PRICE_FILE", tmp_path / "_prices.json")
    store.ensure_demo()
    p = store.load("demo-kifisia")
    assert p["meta"]["demo_rev"] == demo.DEMO_REV
    del p["meta"]["demo_rev"]                         # looks like an older demo
    p["name"] = "edited"
    store.save(p)
    store.ensure_demo()
    assert store.load("demo-kifisia")["name"] != "edited"
    assert any((tmp_path / "_backup").iterdir())
    assert [x["id"] for x in store.list_projects()] == ["demo-kifisia"]


def store_load():
    from app import store
    return store.load(PID)


def store_prices():
    from app import store
    return store.price_state()


def test_untouched_price_seeds_follow_new_elstat_values(tmp_path):
    """A saved price state whose groups were never edited/refreshed takes the current seed; edited groups are kept."""
    st = prices.default_state()
    st["groups"]["concrete"].update({"value": 101.0, "source": "old seed"})           # old, never edited
    st["groups"]["labour"].update({"value": 120.0, "updated": "2026-01-01T00:00:00+00:00", "history": [{"v": 120.0}]})   # user edit
    f = tmp_path / "prices.json"
    prices.save_state(f, st)
    new = prices.load_state(f)
    assert new["groups"]["concrete"]["value"] == pytest.approx(prices.SEED_GROUPS["concrete"]["value"])
    assert new["groups"]["labour"]["value"] == 120.0


def test_frontend_serves_damage_video_module():
    js = client.get("/static/js/anim.js")
    assert js.status_code == 200 and "VideoRecorder" in js.text and "DamageAnim" in js.text
    views = client.get("/static/js/views1.js").text
    assert "MediaRecorder" in js.text and "DamageAnim" in views
    # every hazard view passes its result to the 3D view so the scenario can be animated
    h2 = client.get("/static/js/views2.js").text
    assert h2.count("showIn3D(") == 4 and "S.damageMeta = meta" in h2


# ------------------------------------------------------------------ static study → seismic resistance → Richter
FIXTURE = Path(__file__).parent / "fixtures" / "statics_excerpt.json"


def test_static_report_parser_reads_the_excerpt():
    from app import structural
    pages = json.loads(FIXTURE.read_text(encoding="utf-8"))["pages"]
    st = structural.parse_statics_pages(pages)
    d = st["design"]
    assert d["a_g"] == 0.24 and d["q"] == 3.0 and d["soil"] == "B" and d["zone"] == "II" and d["concrete"] == "C25/30" and d["steel"] == "B500C"
    assert d["Tx"] == 0.4 and d["Rd_x"] == 1.96
    assert [s["idx"] for s in st["storeys"]] == [2, 3, 4, 5, 6]
    s2 = st["storeys"][0]
    assert (s2["Vx_kN"], s2["W_kN"], s2["dh_m"]) == (3270.0, 16349.0, 3.0)
    assert len(st["walls"]) == 4 and abs(st["walls"][0]["nv_x"] - 0.727) < 1e-6
    assert len(st["quantities"]) == 6 and st["quantities"][0]["area_m2"] == 293.0
    assert len(st["members"]) == 2 and st["members"][0]["u_flex_seismic"] == 0.42 and st["members"][0]["rects"] == ["25/50", "50/25"]
    with pytest.raises(ValueError):
        structural.parse_statics_pages(["τίποτα σχετικό"])


def test_richter_is_the_inverse_of_the_attenuation_law():
    from app import structural
    for Ms, d, site in [(5.0, 15, "B"), (6.0, 10, "B"), (6.8, 5, "C"), (7.2, 30, "A")]:
        a = hazards.pga_ambraseys(Ms, d, site)
        assert abs(structural.ms_for_pga(a, d, site) - Ms) < 1e-9
        a84 = hazards.pga_ambraseys(Ms, d, site, 84)
        assert abs(structural.ms_for_pga(a84, d, site, 1.0) - Ms) < 1e-9
    rows = structural.magnitude_limits({"yield": 0.1, "collapse": 0.28})
    assert all(r["yield"] < r["collapse"] for r in rows)
    assert all(rows[i]["collapse"] < rows[i + 1]["collapse"] for i in range(len(rows) - 1))          # farther away → stronger quake needed
    assert all(r["collapse_lo"] < r["collapse"] < r["collapse_hi"] for r in rows)


def test_demo_capacity_from_the_permit_static_study():
    from app import structural
    st = structural.load_demo()
    assert st and len(st["storeys"]) == 5 and len(st["members"]) == 62 and st["design"]["Tx"] == 0.4
    c = structural.capacity(st)
    # the building is designed for A=0.24 g with q=3 and is checked at ~100 % → first yield near A·Ω/q, collapse above the design earthquake
    assert 0.08 < c["pga_g"]["yield"] < 0.13 and c["pga_g"]["collapse"] > c["pga_g"]["design"]
    assert c["pga_g"]["yield"] < c["median_pga_g"][1] < c["median_pga_g"][2] < c["pga_g"]["collapse"] <= c["median_pga_g"][3] + 1e-9 < c["median_pga_g"][4]
    # strength of the mechanism is not below the design base shear of the report (3270 kN)
    assert c["base"]["Vu_kN"] >= c["base"]["Vd_kN"] == 3270.0 and c["base"]["Vy_kN"] >= 0.95 * c["base"]["Vd_kN"]
    assert c["weakest_storey"] == "second" and 0.95 < c["utilisation"]["flex_max"] < 1.05 and not c["utilisation"]["shear_governs"]
    # a more ductile / stronger material assumption can only raise the capacity
    c2 = structural.capacity(st, None, {"material_factor": 1.5, "ductility_capacity": 4.0})
    assert c2["pga_g"]["yield"] > c["pga_g"]["yield"] and c2["pga_g"]["collapse"] > c["pga_g"]["collapse"]
    assert 5.0 < c["limits"][0]["collapse"] < 7.0 and c["limits"][0]["distance_km"] == 5            # Ms for near-collapse at 5 km


def test_seismic_run_uses_the_static_capacity_and_api():
    r = client.get(f"/api/projects/{PID}/structural").json()
    assert r["has_report"] and r["capacity"]["method"] == "rebar_model"        # the Kifisia project: from the real reinforcement
    res = client.post(f"/api/projects/{PID}/hazards/run", json={"kind": "seismic", "all": False, "params": {"scenario": "large"}}).json()
    assert res["code_level"] == "static" and res["capacity"]["method"] == "rebar_model"
    assert res["median_pga_g"] == r["capacity"]["median_pga_g"]
    # the scenario stronger than the yield capacity damages the building more than the generic EAK-2000 curves would say at the first level
    gen = client.post(f"/api/projects/{PID}/hazards/run", json={"kind": "seismic", "all": False, "params": {"scenario": "large", "code_level": "high"}}).json()
    assert gen["code_level"] == "high" and gen["capacity"] is None
    assert res["mean_grade"] > gen["mean_grade"]
    # the code level chosen last is stored with the project (the PDF follows it) → restore the static-study choice
    client.post(f"/api/projects/{PID}/hazards/run", json={"kind": "seismic", "all": False, "params": {"scenario": "large", "code_level": "static"}})
    # editable factors reach the API
    r2 = client.get(f"/api/projects/{PID}/structural", params={"material_factor": 1.5}).json()
    assert r2["capacity"]["report_based"]["pga_g"]["collapse"] > r["capacity"]["report_based"]["pga_g"]["collapse"]
    assert client.get(f"/api/projects/{PID}/structural", params={"material_factor": 9}).status_code == 422


def test_project_without_report_uses_section_estimate_and_rejects_bad_report(tmp_path):
    new = client.post("/api/projects", json={"name": "Χωρίς στατικό", "demo": True}).json()
    pid = new["id"]
    client.delete(f"/api/projects/{pid}/structural")
    r = client.get(f"/api/projects/{pid}/structural").json()
    assert not r["has_report"] and r["capacity"]["method"] == "sections"
    c = r["capacity"]
    assert 0.02 <= c["pga_g"]["yield"] < c["pga_g"]["collapse"] < 1.5 and len(c["limits"]) == 6
    # an unrelated PDF is not accepted as a static report
    import pymupdf
    doc = pymupdf.open(); page = doc.new_page(); page.insert_text((72, 72), "hello world"); pdf = tmp_path / "x.pdf"; doc.save(str(pdf))
    bad = client.post(f"/api/projects/{pid}/structural/upload", files={"file": ("x.pdf", pdf.read_bytes(), "application/pdf")})
    assert bad.status_code == 422
    client.delete(f"/api/projects/{pid}")


def test_pdf_contains_the_richter_section():
    r = client.post(f"/api/projects/{PID}/report", json={"lang": "el", "sections": ["hazards"]})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    import pymupdf
    txt = " ".join(" ".join(pg.get_text() for pg in pymupdf.open(stream=r.content, filetype="pdf")).split()).lower()
    assert "αντοχή σε σεισμό και μέγεθος σε ρίχτερ" in txt and "οιονεί κατάρρευση" in txt and "ms οιονεί κατάρρευσης" in txt


def test_frontend_has_the_richter_tab():
    h2 = client.get("/static/js/views2.js").text
    assert "async function capacity(b)" in h2 and "/structural/upload" in h2 and "Ρίχτερ" in h2


def test_demo_surroundings_ramp_planting_cladding_and_colours():
    """Surroundings, planting, timber cladding and doors of the real Rhino model (or the drawn ones without it), in their material colours and priced."""
    from app import demo, quantities
    p = store_load()
    els = p["elements"]
    assert all((e.get("props") or {}).get("color", "").startswith("#") for e in els)
    if (demo.DATA / "real3d.npz").exists():
        real = [e for e in els if (e.get("props") or {}).get("source") == "Rhino 3d.3dm"]
        kinds = {e["kind"] for e in real}
        assert len(real) > 30 and {"vegetation", "site", "pergola", "door", "fence"} <= kinds
        assert {e["props"]["rhino_layer"] for e in real} >= {"khpos", "1os", "2os"}
        lawn = [e for e in real if "Grass" in e["props"]["rhino_material"]]
        assert lawn and lawn[0]["props"]["color"] == "#7f9f57"
        street = [e for e in real if "Asphalt" in e["props"]["rhino_material"]]
        assert street and street[0]["bbox"][4] < -6.0                        # the street lies outside the street line (y = -6.99)
    else:
        names = {e["name"] for e in els}
        assert {"Basement ramp", "Ramp landing", "Garage sliding gate", "Planter first"} <= names
    q = quantities.compute(p)["quantities"]
    assert q["ramp_m2"] > 50 and q["wood_cladding_m2"] > 10 and q["planter_m"] > 10 and q["trees"] == 8 and q["gate_garage"] == 1
    c = cost.compute(p, q, store_prices())
    keys = {l["key"] for l in c["lines"] if l["total"] > 0}
    assert {"ramp", "ramp_walls", "wood_cladding", "planters", "trees", "hedges", "gate_garage", "balcony_frames"} <= keys
    els_api = client.get(f"/api/projects/{PID}/elements").json()["elements"]
    assert all(e["color"] for e in els_api)
