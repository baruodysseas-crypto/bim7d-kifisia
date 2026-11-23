"""7D facility management: table of shares of the deed, allocation of the 5D running costs, asset register, calendar, PDF section."""
import os
import tempfile

import pytest

os.environ.setdefault("BIM7D_DATA", tempfile.mkdtemp(prefix="bim7d_test_fm_"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PID = "demo-kifisia"


@pytest.fixture(scope="module", autouse=True)
def _startup():
    with TestClient(app) as c:
        yield c


def test_demo_properties_follow_the_deed():
    f = client.get(f"/api/projects/{PID}/fm").json()
    ids = [p["id"] for p in f["properties"]]
    assert len(ids) == 18 and {"Α1", "Α5", "ΘΣ1", "ΘΣ6", "ΑΠ-Δ1", "ΑΠ-Δ2", "Δ1", "Δ5"} <= set(ids)
    assert all(c["ok"] for c in f["checks"])                                   # every column adds up to 1000
    d3 = next(p for p in f["properties"] if p["id"] == "Δ3")
    assert d3["keys"] == {"votes": 197, "lighting": 176, "lift": 253, "cleaning": 176, "maintenance": 176, "plot": 197, "garden": 176}
    d4 = next(p for p in f["properties"] if p["id"] == "Δ4")
    assert abs(d4["total_m2"] - 124.75) < 1e-6                                  # 84.13 + attic annex 40.62
    assert abs(sum(c["area_m2"] for c in f["common_areas"]) - (115.35 + 22.23 + 17.86 + 17.86)) < 0.01
    assert not any("owner" in p for p in f["properties"])                       # owners are not stored


def test_allocation_reconciles_with_the_5d_running_cost():
    f = client.get(f"/api/projects/{PID}/fm").json()
    rc = f["reconciliation"]
    assert abs(rc["allocated_total"] - rc["building_running_total"]) <= 0.001 * rc["building_running_total"] + 10
    p = {x["id"]: x for x in f["properties"]}
    assert p["Δ1"]["avg_annual"]["replacement"] >= 0 and p["Δ1"]["avg_annual_total"] > p["Α1"]["avg_annual_total"] > 0
    # ground-floor apartments pay nothing for the lift; the 1st floor pays its lift share
    assert f["by_target_avg"]["lift"] > 0
    assert p["Δ1"]["keys"]["lift"] == 0 and p["Δ3"]["keys"]["lift"] == 253
    assert sum(x["risk_eal"] for x in f["properties"]) == pytest.approx(f["risk_total_eal"], rel=0.01)


def test_asset_register_and_calendar():
    f = client.get(f"/api/projects/{PID}/fm").json()
    lift = next(a for a in f["assets"] if a["id"] == "lift")
    assert lift["allocation"] == {"lift": 1.0} and any(t["every_months"] == 24 for t in lift["tasks"])
    assert f["calendar"] and all(1 <= e["year"] <= f["horizon"] for e in f["calendar"])
    assert any(e["action"] == "replacement" for e in f["calendar"])
    assert any(s["replace_every"] is None for s in f["service_life"])           # the structure is not replaced


def test_edit_table_of_shares():
    r = client.post("/api/projects", json={"name": "FM test", "gfa_m2": 300, "apartments": 2}).json()
    pid = r["id"]
    rows = [{"id": "Δ1", "name_el": "Διαμέρισμα Δ1", "type": "apartment", "storey": "ground", "area_m2": 100, "total_m2": 100, "owner": "X",
             "keys": {k: 600 for k in ("votes", "lighting", "lift", "cleaning", "maintenance", "plot", "garden")}},
            {"id": "Δ2", "name_el": "Διαμέρισμα Δ2", "type": "apartment", "storey": "first", "area_m2": 80, "total_m2": 80,
             "keys": {k: 300 for k in ("votes", "lighting", "lift", "cleaning", "maintenance", "plot", "garden")}}]
    res = client.put(f"/api/projects/{pid}/fm/properties", json={"properties": rows}).json()
    assert not any(c["ok"] for c in res["checks"])                              # 900 ‰: reported, not refused
    from app import store
    assert "owner" not in store.load(pid)["properties"]["properties"][0]
    client.delete(f"/api/projects/{pid}")


def test_report_has_the_7d_section_and_no_building_terms():
    r = client.post(f"/api/projects/{PID}/report", json={"lang": "el", "sections": ["summary", "fm"]})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    import pymupdf
    doc = pymupdf.open(stream=r.content, filetype="pdf")
    text = "".join(pg.get_text() for pg in doc)
    assert "Διαχείριση εγκαταστάσεων" in text and "Επιμερισμός" in text
    assert "όρων δόμησης" not in text and "ΚΑΕΚ" not in text


def test_thesis_edition_is_only_kifisia(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv("BIM7D_ALLOW_NEW", "0")
    c = TestClient(app)
    assert c.post("/api/projects", json={"name": "x"}).status_code == 403
    assert c.delete("/api/projects/whatever").status_code == 403
    assert {p["id"] for p in c.get("/api/projects").json()} <= {"demo-kifisia"}
