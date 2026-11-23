"""Live site data (cadastre, earthquakes, climate) and price history – with recorded real responses, no network."""
import gzip
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import energy, hazards, live, prices, store
from app.main import app

FX = Path(__file__).parent / "fixtures"
USGS = json.loads((FX / "usgs_kifisia.json").read_text())
METEO = json.loads(gzip.open(FX / "meteo_kifisia_1996_2025.json.gz", "rt").read())
PARCEL = {"features": [{"attributes": {"KAEK": "050693510008", "DESCR": "Αστικός αδόμητος χώρος", "AREA": 1060.11, "PERIMETER": 132.73, "PROP_HOR": 18},
                        "geometry": {"rings": [[[23.8118104, 38.1011260], [23.8120607, 38.1009725], [23.8118402, 38.1006849], [23.8115778, 38.1008049], [23.8118104, 38.1011260]]]}}]}
OTA = {"features": [{"attributes": {"OTA_NAME": "ΚΗΦΙΣΙΑΣ", "NOMOS_NAME": "ΑΤΤΙΚΗΣ", "CODE_OKXE": "05069"}}]}


def fake_get(url, params=None, timeout=None):
    if "GEOTEMAXIA_LEITOURGOUN" in url:
        return PARCEL
    if "GEOTEMAXIA" in url:
        return {"features": []}
    if "OTA_P" in url:
        return OTA
    if "earthquake.usgs.gov" in url:
        return USGS
    if "open-meteo" in url:
        return METEO
    raise live.LiveError("unexpected url " + url)


def test_cadastre_parcel():
    c = live.fetch_cadastre("05 069 35 10 008", fake_get)
    assert c["kaek"] == "050693510008" and c["area_m2"] == pytest.approx(1060.11)
    assert c["ota"]["OTA_NAME"] == "ΚΗΦΙΣΙΑΣ" and 38.10 < c["lat"] < 38.102
    with pytest.raises(live.LiveError):
        live.normalize_kaek("12345")


def test_earthquake_history_and_hazard_curve():
    sc = hazards.load()["seismic"]["scenarios"]
    r = live.analyse_quakes(USGS, 38.10093, 23.81182, "B", 150, sc)
    assert r["n"] > 800 and r["largest"]["mag"] >= 6.5
    gr = r["gr"]
    assert 0.7 < gr["b"] < 1.6 and gr["rate_Mc"] > 1
    pga475 = gr["hazard"]["pga_for_return_period"]["475"]
    assert 0.15 < pga475 < 0.32                    # EAK zone II: a_g = 0.24 g
    lam = gr["hazard"]["annual_rate"]
    assert all(a >= b for a, b in zip(lam, lam[1:]))
    # the 1999 Athens (Parnitha) earthquake is in the catalogue and among the strongest shaking at Kifisia
    assert any(e["time"] == "1999-09-07" and e["mag"] >= 5.9 for e in r["top_site"])
    s = r["scenario_rates"]
    assert s["small"]["annual_probability"] > s["moderate"]["annual_probability"] > s["large"]["annual_probability"]


def test_climate_history():
    cl = live.analyse_climate(METEO, energy.T_EXT, energy.G_H)
    assert cl["period"] == [1996, 2025] and len(cl["years"]) == 30
    assert 14 < cl["mean"]["t_mean"] < 19 and cl["mean"]["hdd"] > 800 and cl["mean"]["cdd"] > 200
    assert cl["trend_per_decade"]["t_mean"] > 0                 # warming over the 30 years
    ec = live.climate_for_energy(cl, energy.CLIMATE)
    assert len(ec["T_ext"]) == 12 and ec["T_ext"][6] > ec["T_ext"][0]


def test_live_feeds_6d_and_7d(monkeypatch):
    c = TestClient(app)
    monkeypatch.setattr(live, "_get_json", fake_get)
    r = c.post("/api/projects/demo-kifisia/live/refresh", json={}).json()
    assert all(v["ok"] for v in r["status"].values()), r["status"]
    assert r["live"]["cadastre"]["kaek"] == "050693510008"
    e = r["energy_compare"]
    assert e["design"]["primary_kwh_m2"] != e["site"]["primary_kwh_m2"]
    assert r["historical_scenario"]["loss_eur"] >= 0
    # 7D: switching to the historical probabilities changes the expected annual loss
    eal0 = c.post("/api/projects/demo-kifisia/hazards/run", json={"kind": "seismic", "all": True, "params": {}}).json()["eal_eur"]
    c.patch("/api/projects/demo-kifisia/live/use", json={"seismic_rates": True, "climate": True})
    run = c.post("/api/projects/demo-kifisia/hazards/run", json={"kind": "seismic", "all": True, "params": {}}).json()
    assert run["eal_eur"] != eal0 and run["runs"]["moderate"]["probability_source"] == "history"
    c.patch("/api/projects/demo-kifisia/live/use", json={"seismic_rates": False, "climate": False})


YH = {"chart": {"result": [{"meta": {"regularMarketPrice": 5.4}, "timestamp": [1700000000 + i * 2629800 for i in range(36)],
                            "indicators": {"quote": [{"close": [4.0 * (1.01 ** i) for i in range(36)]}]}}]}}
FXH = {"chart": {"result": [{"meta": {"regularMarketPrice": 1.1}, "timestamp": [1700000000 + i * 2629800 for i in range(36)],
                             "indicators": {"quote": [{"close": [1.1] * 36}]}}]}}
ES = {"dimension": {"time": {"category": {"index": {f"{y}-Q{q}": i for i, (y, q) in enumerate((y, q) for y in range(2015, 2027) for q in range(1, 5))}}}},
      "value": {str(i): 90 + i * 0.8 for i in range(47)}}


def test_price_history_and_calibration():
    def http(url, timeout, headers=None):
        if "eurostat" in url:
            return json.dumps(ES).encode()
        if "EURUSD" in url:
            return json.dumps(FXH).encode()
        if "yahoo" in url:
            return json.dumps(YH).encode()
        raise ConnectionError(url)
    st = prices.default_state()
    out = prices.refresh_all(st, http=http)
    assert out["general"]["ok"] and st["groups"]["general"]["base"] == pytest.approx(ES["value"][str(42)])   # 2025-Q3
    h = prices.refresh_history(st, http=http)
    assert h["copper"]["ok"] and h["steel_rebar"]["ok"] and h["general"]["ok"]
    assert st["series"]["copper"]["unit"] == "EUR" and len(st["series"]["copper"]["t"]) >= 30
    c = st["calibration"]["copper"]
    assert c["mu"] == pytest.approx(12 * 0.00995, rel=0.05) and c["sigma"] < 0.01
    assert st["dynamics"]["copper"]["calibrated"]
    prices.use_assumed_dynamics(st)
    assert st["dynamics"]["copper"]["sigma"] == prices.DYNAMICS["copper"]["sigma"]
