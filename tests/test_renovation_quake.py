"""Custom earthquake label, project deletion / upload limits, and the thesis edition's tabs (no building terms, no renovation)."""
import os
import tempfile

import pytest

os.environ.setdefault("BIM7D_DATA", tempfile.mkdtemp(prefix="bim7d_test_quake_"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _startup():
    with TestClient(app) as c:
        yield c


def test_custom_earthquake_is_labelled_with_its_magnitude():
    r = client.post("/api/projects/demo-kifisia/hazards/run", json={"kind": "seismic", "params": {"Ms": 7.2, "distance_km": 5}, "all": False}).json()
    assert r["Ms"] == 7.2 and r["scenario"] == "custom" and "7,2" in r["label_el"] and r["p_collapse_d5"] > 0.5
    small = client.post("/api/projects/demo-kifisia/hazards/run", json={"kind": "seismic", "params": {"Ms": 5.0, "distance_km": 15}, "all": False}).json()
    assert small["p_collapse_d5"] < 0.2                                                                     # no collapse in the video


def test_frontend_is_the_7d_edition():
    a = client.get("/static/js/anim.js").text
    assert "_setupCollapse" in a and "ΚΑΤΑΡΡΕΥΣΗ" in a
    m = client.get("/static/js/main.js").text
    assert "fmView" in m and "7D Διαχείριση εγκαταστάσεων" in m and "4D Χρόνος" in m and "6D Βιωσιμότητα" in m and "7D Κίνδυνοι & ανθεκτικότητα" in m
    assert "renovationView" not in m and "ΚΑΕΚ" not in m and "όροι" not in m.lower()
    v5 = client.get("/static/js/views5.js").text                    # live site data: cadastre, earthquakes, climate – no building terms
    assert "Κτηματολόγιο" in v5 and "όροι δόμησης" not in v5.lower() and "συντελεστ" not in v5.lower()
    for path in ("/api/projects/demo-kifisia/site", "/api/renovation/catalogue"):
        assert client.get(path).status_code in (404, 405)


def test_delete_project_is_recoverable_and_upload_limits():
    from app import store
    from app import main as M
    r = client.post("/api/projects", json={"name": "Προς διαγραφή", "gfa_m2": 200}).json()
    pid = r["id"]
    up = client.post(f"/api/projects/{pid}/upload", files={"file": ("x.txt", b"hello")})
    assert up.status_code == 415                                             # unsupported type, file stays listed
    fl = client.get(f"/api/projects/{pid}/files").json()
    assert fl["count"] == 1 and fl["limits"]["files_per_project"] == M.UPLOAD_LIMITS["files_per_project"]
    old = dict(M.UPLOAD_LIMITS)
    M.UPLOAD_LIMITS["file_mb"] = 0                                            # anything is too big now
    try:
        big = client.post(f"/api/projects/{pid}/upload", files={"file": ("plan.dxf", b"0\nEOF\n")})
        assert big.status_code == 413 and "MB" in big.json()["detail"]
    finally:
        M.UPLOAD_LIMITS.update(old)
    assert client.delete(f"/api/projects/{pid}/files/x.txt").json()["ok"]
    d = client.delete(f"/api/projects/{pid}").json()
    assert d["ok"] and "_deleted" in d["moved_to"] and not store.exists(pid)
