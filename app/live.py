"""Live data of the site, fetched on the user's PC from public services.

  * Cadastre (Κτηματολόγιο): parcel geometry and attributes for a ΚΑΕΚ, and the municipality (ΟΤΑ), from the public
    ArcGIS services that the Cadastre's own web map uses (maps.ktimatologio.gr).
    «Πηγή δεδομένων: Ν.Π.Δ.Δ. ΕΛΛΗΝΙΚΟ ΚΤΗΜΑΤΟΛΟΓΙΟ».
  * Earthquakes: USGS ComCat (FDSN event web service), all events around the site since 1900.
    From the catalogue: Gutenberg–Richter recurrence (Aki maximum likelihood), the shaking each historical event caused at the
    site (Ambraseys et al. 1996, as in the 7D risk model) and a simple probabilistic seismic hazard curve for the site.
  * Climate: Open-Meteo historical weather archive (ERA5 reanalysis), daily values for the last 30 full years.
    From it: monthly climate of the site (feeds the 6D energy balance), heating/cooling degree days (Eurostat definition),
    hot days, rainfall extremes and the trends per decade.

Every call is made by the backend of the tool; the network layer is `_get_json`, replaced by a mock in the tests.
Results are stored in the project (project["live"]) with the time they were fetched, so the tool keeps working offline."""
from __future__ import annotations

import json
import math
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Any, Callable

import numpy as np

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) 7D-BIM-thesis-tool/1.0"
CAD = "https://services-eu1.arcgis.com/40tFGWzosjaLJpmn/arcgis/rest/services"
PARCEL_LAYERS = [("ΛΕΙΤΟΥΡΓΟΥΝ ΚΤΗΜΑΤΟΛΟΓΙΟ", "GEOTEMAXIA_LEITOURGOUN_ON_gdb"), ("ΑΝΑΡΤΗΣΗ ΚΤΗΜΑΤΟΓΡΑΦΗΣΗΣ", "GEOTEMAXIA_ANARTHSH_ON_gdb"),
                 ("ΠΡΟΚΑΤΑΡΚΤΙΚΑ", "GEOTEMAXIA_PROKATARKTIKA_ON_gdb")]
OTA_LAYER = f"{CAD}/OTA_P_gdb/FeatureServer/0"
USGS = "https://earthquake.usgs.gov/fdsnws/event/1/query"
METEO = "https://archive-api.open-meteo.com/v1/archive"
SOURCE_CAD = "Πηγή δεδομένων: Ν.Π.Δ.Δ. ΕΛΛΗΝΙΚΟ ΚΤΗΜΑΤΟΛΟΓΙΟ"
SOURCE_USGS = "USGS ComCat (earthquake.usgs.gov)"
SOURCE_METEO = "Open-Meteo historical weather API (ERA5 / ERA5-Land, Copernicus ECMWF)"
DEMO_KAEK = "050693510008"            # Ποταμού 4, Νέα Κηφισιά
DEMO_LATLON = (38.10093, 23.81182)


class LiveError(Exception):
    pass


def offline() -> bool:
    return os.environ.get("BIM7D_OFFLINE", "") == "1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get_json(url: str, params: dict[str, Any] | None = None, timeout: float = 40.0) -> Any:
    if offline():
        raise LiveError("offline mode (BIM7D_OFFLINE=1)")
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 (fixed https endpoints)
            out = json.loads(r.read().decode("utf-8"))
    except Exception as ex:
        raise LiveError(f"Δεν ήταν δυνατή η σύνδεση με {urllib.parse.urlparse(url).netloc}: {ex}") from ex
    if isinstance(out, dict) and out.get("error") and not out.get("features"):
        e = out["error"]
        raise LiveError(f"Η υπηρεσία επέστρεψε σφάλμα: {e.get('message', e) if isinstance(e, dict) else e}")
    return out


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ================================================================================================
# CADASTRE
# ================================================================================================
def normalize_kaek(text: str) -> str:
    k = "".join(ch for ch in str(text) if ch.isdigit())
    if len(k) < 12:
        raise LiveError("Το ΚΑΕΚ πρέπει να έχει 12 ψηφία (π.χ. 05 069 35 10 008).")
    return k[:12]


def _poly_metrics(ring: list[list[float]]) -> dict[str, float]:
    """Area / perimeter of a WGS84 ring in metres (local equirectangular projection, < 0.1 % error at plot scale)."""
    lat0 = sum(p[1] for p in ring) / len(ring)
    kx, ky = 111320.0 * math.cos(math.radians(lat0)), 110574.0
    xy = [((p[0]) * kx, (p[1]) * ky) for p in ring]
    a = 0.0
    per = 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]):
        a += x1 * y2 - x2 * y1
        per += math.hypot(x2 - x1, y2 - y1)
    cx = sum(p[0] for p in ring[:-1] or ring) / max(1, len(ring[:-1] or ring))
    cy = sum(p[1] for p in ring[:-1] or ring) / max(1, len(ring[:-1] or ring))
    return {"area_m2": abs(a) / 2, "perimeter_m": per, "lat": cy, "lon": cx}


def fetch_cadastre(kaek_text: str, get: Callable[..., Any] | None = None) -> dict[str, Any]:
    get = get or _get_json
    kaek = normalize_kaek(kaek_text)
    last: Exception | None = None
    for label, svc in PARCEL_LAYERS:
        try:
            j = get(f"{CAD}/{svc}/FeatureServer/0/query", {"where": f"KAEK='{kaek}'", "outFields": "*", "returnGeometry": "true", "outSR": "4326", "f": "json"})
        except LiveError as ex:
            last = ex
            continue
        feats = j.get("features") or []
        if not feats:
            continue
        f = feats[0]
        rings = (f.get("geometry") or {}).get("rings") or []
        if not rings:
            raise LiveError("Το ΚΑΕΚ βρέθηκε αλλά χωρίς γεωμετρία.")
        ring = max(rings, key=len)
        att = {k: v for k, v in (f.get("attributes") or {}).items() if not k.startswith("Shape__") and k != "OBJECTID"}
        m = _poly_metrics(ring)
        ota = {}
        try:
            o = get(f"{OTA_LAYER}/query", {"geometry": json.dumps({"x": m["lon"], "y": m["lat"], "spatialReference": {"wkid": 4326}}),
                                           "geometryType": "esriGeometryPoint", "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
                                           "outFields": "*", "returnGeometry": "false", "f": "json"})
            of = o.get("features") or []
            ota = (of[0].get("attributes") or {}) if of else {}
        except LiveError:
            pass
        return {"kaek": kaek, "kaek_fmt": f"{kaek[:2]} {kaek[2:5]} {kaek[5:7]} {kaek[7:9]} {kaek[9:]}", "layer": label, "attributes": att,
                "ring_wgs84": ring, "area_m2": round(float(att.get("AREA") or m["area_m2"]), 2), "perimeter_m": round(float(att.get("PERIMETER") or m["perimeter_m"]), 2),
                "lat": round(m["lat"], 6), "lon": round(m["lon"], 6), "ota": {k: ota.get(k) for k in ("OTA_NAME", "NOMOS_NAME", "CODE_OKXE", "STATUS") if k in ota},
                "fetched": now_iso(), "source": SOURCE_CAD}
    if last is not None:
        raise last
    raise LiveError(f"Το ΚΑΕΚ {kaek} δεν βρέθηκε στο Κτηματολόγιο.")


# ================================================================================================
# EARTHQUAKES
# ================================================================================================
def pga_ambraseys(Ms: float, d_km: float, soil: str = "B") -> float:
    """Median PGA [g], Ambraseys et al. (1996) – same relation as the 7D seismic scenarios."""
    sa = 1.0 if soil == "B" else 0.0
    ss = 1.0 if soil in ("C", "D", "E") else 0.0
    return 10 ** (-1.48 + 0.266 * Ms - 0.922 * math.log10(math.sqrt(d_km ** 2 + 3.5 ** 2)) + 0.117 * sa + 0.124 * ss)


def mmi_wald(pga_g: float) -> float:
    pga = max(pga_g * 981.0, 1e-3)
    lg = math.log10(pga)
    low, high = 2.20 * lg + 1.00, 3.66 * lg - 1.66
    v = low if low <= 5.0 else (high if high >= 7.0 else low + (high - low) * (low - 5.0) / 2.0)
    return max(1.0, min(10.0, v))


def fetch_quakes_raw(lat: float, lon: float, radius_km: float = 150.0, minmag: float = 4.0, start: str = "1900-01-01",
                     get: Callable[..., Any] | None = None) -> dict[str, Any]:
    get = get or _get_json
    return get(USGS, {"format": "geojson", "latitude": f"{lat:.5f}", "longitude": f"{lon:.5f}", "maxradiuskm": radius_km,
                      "minmagnitude": minmag, "starttime": start, "orderby": "time-asc", "limit": 20000})


def analyse_quakes(raw: dict[str, Any], lat: float, lon: float, soil: str = "B", radius_km: float = 150.0,
                   scenarios: dict[str, dict[str, Any]] | None = None, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    ev = []
    for f in raw.get("features") or []:
        p = f.get("properties") or {}
        g = (f.get("geometry") or {}).get("coordinates") or [None, None, None]
        if p.get("mag") is None or g[0] is None or p.get("type", "earthquake") != "earthquake":
            continue
        t = datetime.fromtimestamp((p.get("time") or 0) / 1000, tz=timezone.utc)
        d = haversine_km(lat, lon, g[1], g[0])
        dep = float(g[2] or 0)
        d_eff = math.hypot(d, dep) if dep > 30.0 else d                 # intermediate-depth events: hypocentral distance
        m = float(p["mag"])
        pga = pga_ambraseys(m, d_eff, soil)
        ev.append({"id": f.get("id"), "time": t.strftime("%Y-%m-%d"), "year": t.year + (t.timetuple().tm_yday - 1) / 365.25, "mag": round(m, 1),
                   "mag_type": p.get("magType"), "depth_km": round(float(g[2] or 0), 1), "lat": round(g[1], 4), "lon": round(g[0], 4),
                   "dist_km": round(d, 1), "d_eff_km": round(d_eff, 1), "place": p.get("place") or "", "pga_g": round(pga, 4), "mmi_site": round(mmi_wald(pga), 1), "url": p.get("url")})
    ev.sort(key=lambda e: e["year"])
    if not ev:
        return {"n": 0, "events": [], "note": "Δεν βρέθηκαν σεισμοί στην ακτίνα αναζήτησης."}
    t_now = today.year + (today.timetuple().tm_yday - 1) / 365.25
    # --- recurrence on the complete part of the catalogue (USGS global coverage M>=4.5 from 1973)
    Mc, y0 = 4.5, 1973.0
    comp = np.array([e["mag"] for e in ev if e["mag"] >= Mc and e["year"] >= y0])
    years = max(1.0, t_now - y0)
    gr: dict[str, Any] = {"Mc": Mc, "from_year": int(y0), "years": round(years, 1), "n": int(comp.size)}
    if comp.size >= 10:
        dm = 0.1
        b = math.log10(math.e) / (float(comp.mean()) - (Mc - dm / 2))
        b = min(max(b, 0.5), 1.6)
        nu = comp.size / years                                         # annual rate of M >= Mc
        a = math.log10(nu) + b * Mc
        mmax = round(max(e["mag"] for e in ev) + 0.3, 1)
        gr.update({"b": round(b, 3), "b_se": round(b / math.sqrt(comp.size), 3), "a": round(a, 3), "rate_Mc": round(nu, 3), "Mmax": mmax})
        rates = []
        for m in (4.5, 5.0, 5.5, 6.0, 6.5, 7.0):
            r = 10 ** (a - b * m) if m <= mmax else 0.0
            obs = sum(1 for e in ev if e["mag"] >= m and e["year"] >= y0) / years
            rates.append({"M": m, "rate_gr": round(r, 4), "rate_obs": round(obs, 4), "return_period_y": round(1 / r, 1) if r > 0 else None,
                          "p50y": round(1 - math.exp(-r * 50), 3)})
        gr["rates"] = rates
        hz = hazard_curve(ev, b, nu, Mc, mmax, soil, y0)
        gr["hazard"] = hz
    # --- observed shaking at the site
    big = [e for e in ev if e["mag"] >= 5.0] or ev                        # damaging events; small near-by shocks give short, harmless peaks
    strongest = max(big, key=lambda e: e["pga_g"])
    largest = max(ev, key=lambda e: e["mag"])
    nearest_big = min((e for e in ev if e["mag"] >= 5.0), key=lambda e: e["dist_km"], default=None)
    by_decade: dict[int, int] = {}
    for e in ev:
        if e["mag"] >= Mc:
            by_decade[int(e["year"] // 10 * 10)] = by_decade.get(int(e["year"] // 10 * 10), 0) + 1
    out = {"n": len(ev), "radius_km": radius_km, "soil": soil, "period": [ev[0]["time"], ev[-1]["time"]],
           "largest": largest, "strongest_at_site": strongest, "nearest_M5": nearest_big,
           "top_site": sorted(ev, key=lambda e: -e["pga_g"])[:15],
           "events": [{k: e[k] for k in ("time", "year", "mag", "dist_km", "depth_km", "lat", "lon", "pga_g", "place")} for e in ev],
           "by_decade": [{"decade": k, "n": v} for k, v in sorted(by_decade.items())], "gr": gr,
           "model": "Gutenberg–Richter (Aki 1965, Mc 4.5 από 1973) · PGA: Ambraseys et al. (1996), σ=0.25 · PSHA με τις θέσεις των ιστορικών επικέντρων"}
    if scenarios and gr.get("hazard"):
        out["scenario_rates"] = scenario_rates(scenarios, gr["hazard"], soil)
    return out


def hazard_curve(ev: list[dict[str, Any]], b: float, nu: float, Mc: float, mmax: float, soil: str, y0: float,
                 sigma: float = 0.25) -> dict[str, Any]:
    """λ(PGA > x) = ν(Mc) · Σ_m Σ_d  f_M(m) · w_d · P(PGA > x | m, d)
    with f_M the doubly-truncated Gutenberg–Richter density, and the source-to-site distances taken from the epicentres
    of the complete catalogue (each historical epicentre equally likely to host the next event)."""
    d = np.array([e["d_eff_km"] for e in ev if e["mag"] >= Mc and e["year"] >= y0], dtype=float)
    if d.size == 0:
        d = np.array([e["d_eff_km"] for e in ev], dtype=float)
    beta = b * math.log(10)
    ms = np.arange(Mc + 0.05, mmax, 0.1)
    if ms.size == 0:
        ms = np.array([Mc + 0.05])
    pdf = beta * np.exp(-beta * (ms - Mc)) / (1 - math.exp(-beta * (mmax - Mc)))
    w_m = pdf * 0.1
    w_m = w_m / w_m.sum()
    sa = 1.0 if soil == "B" else 0.0
    ss = 1.0 if soil in ("C", "D", "E") else 0.0
    log_med = (-1.48 + 0.266 * ms[:, None] - 0.922 * np.log10(np.sqrt(d[None, :] ** 2 + 3.5 ** 2)) + 0.117 * sa + 0.124 * ss)   # (m, d)
    xs = np.round(np.geomspace(0.01, 1.0, 41), 4)
    from math import erf, sqrt
    lam = []
    for x in xs:
        z = (math.log10(x) - log_med) / sigma
        p = 0.5 * (1 - np.vectorize(erf)(z / sqrt(2)))
        lam.append(float(nu * (w_m[:, None] * p).sum() / d.size))
    lam = np.array(lam)

    def pga_for(rate: float) -> float | None:
        if rate > lam[0] or rate < lam[-1]:
            return None
        return float(np.exp(np.interp(math.log(rate), np.log(lam[::-1]), np.log(xs[::-1]))))

    rp = {str(T): (round(pga_for(1 / T), 3) if pga_for(1 / T) else None) for T in (50, 100, 475, 975, 2475)}
    return {"pga_g": xs.tolist(), "annual_rate": [round(float(v), 7) for v in lam], "pga_for_return_period": rp, "sigma": sigma,
            "note": "Περίοδος επαναφοράς 475 ετών = 10 % πιθανότητα υπέρβασης σε 50 χρόνια (βάση του ΕΑΚ / EC8)."}


def rate_of_pga(hz: dict[str, Any], x: float) -> float:
    xs, lam = np.array(hz["pga_g"]), np.array(hz["annual_rate"])
    if x <= xs[0]:
        return float(lam[0])
    if x >= xs[-1]:
        return float(lam[-1])
    return float(np.exp(np.interp(math.log(x), np.log(xs), np.log(np.maximum(lam, 1e-12)))))


def scenario_rates(scenarios: dict[str, dict[str, Any]], hz: dict[str, Any], soil: str) -> dict[str, Any]:
    """Annual probability that the shaking (median PGA) of each 7D scenario is reached or exceeded at the site, read from the
    hazard curve. These are exceedance probabilities, the same meaning as `annual_probability` in hazards.json, which the EAL
    integrates as a loss–exceedance curve (hazards.expected_annual)."""
    out = {}
    for k, s in scenarios.items():
        x = pga_ambraseys(float(s["Ms"]), float(s["distance_km"]), soil)
        lam = rate_of_pga(hz, x)
        out[k] = {"key": k, "Ms": s["Ms"], "distance_km": s["distance_km"], "pga_g": round(x, 3), "exceed_rate": round(lam, 6),
                  "annual_probability": round(1 - math.exp(-lam), 6), "return_period_y": round(1 / lam, 0) if lam > 0 else None,
                  "assumed": s.get("annual_probability")}
    return out


# ================================================================================================
# CLIMATE
# ================================================================================================
DAILY = "temperature_2m_mean,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,shortwave_radiation_sum"
DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def fetch_climate_raw(lat: float, lon: float, y1: int, y2: int, get: Callable[..., Any] | None = None) -> dict[str, Any]:
    get = get or _get_json
    return get(METEO, {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "start_date": f"{y1}-01-01", "end_date": f"{y2}-12-31",
                       "daily": DAILY, "timezone": "Europe/Athens"}, 90.0)


def _trend(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3:
        return 0.0
    return float(np.polyfit(np.array(xs, float), np.array(ys, float), 1)[0])


def analyse_climate(raw: dict[str, Any], design_T: list[float] | None = None, design_G: list[float] | None = None) -> dict[str, Any]:
    d = raw.get("daily") or {}
    t = d.get("time") or []
    if not t:
        raise LiveError("Η υπηρεσία καιρού δεν επέστρεψε δεδομένα.")

    def arr(k: str) -> np.ndarray:
        return np.array([np.nan if v is None else v for v in d.get(k, [None] * len(t))], dtype=float)

    tm, tx, tn, pr, wx, sw = (arr(k) for k in DAILY.split(","))
    yrs = np.array([int(s[:4]) for s in t])
    mon = np.array([int(s[5:7]) for s in t])
    years = []
    for y in sorted(set(yrs.tolist())):
        s = yrs == y
        if s.sum() < 360:
            continue
        T = tm[s]
        hdd = float(np.nansum(np.where(T <= 15.0, 18.0 - T, 0.0)))     # Eurostat: HDD = Σ(18 − Tm) for Tm ≤ 15 °C
        cdd = float(np.nansum(np.where(T >= 24.0, T - 21.0, 0.0)))     # Eurostat: CDD = Σ(Tm − 21) for Tm ≥ 24 °C
        years.append({"year": y, "t_mean": round(float(np.nanmean(T)), 2), "t_max": round(float(np.nanmax(tx[s])), 1), "t_min": round(float(np.nanmin(tn[s])), 1),
                      "hdd": round(hdd), "cdd": round(cdd), "hot_days_35": int(np.nansum(tx[s] >= 35.0)), "tropical_nights": int(np.nansum(tn[s] >= 20.0)),
                      "frost_days": int(np.nansum(tn[s] < 0.0)), "rain_mm": round(float(np.nansum(pr[s]))), "rain_max_day_mm": round(float(np.nanmax(pr[s])), 1),
                      "wind_max_kmh": round(float(np.nanmax(wx[s])), 1)})
    monthly = []
    for m in range(1, 13):
        s = mon == m
        monthly.append({"month": m, "t_mean": round(float(np.nanmean(tm[s])), 2), "t_max_mean": round(float(np.nanmean(tx[s])), 2),
                        "t_min_mean": round(float(np.nanmean(tn[s])), 2), "rain_mm": round(float(np.nansum(pr[s])) / max(1, len(set(yrs[s].tolist()))), 1),
                        "G_h_kwh_m2": round(float(np.nanmean(sw[s])) * DAYS[m - 1] / 3.6, 1)})
    ys = [r["year"] for r in years]
    trends = {k: round(_trend(ys, [r[k] for r in years]) * 10, 3) for k in ("t_mean", "hdd", "cdd", "hot_days_35", "tropical_nights", "rain_mm", "rain_max_day_mm")}
    n = len(years)
    first, last = years[: min(10, n)], years[-min(10, n):]

    def avg(rows: list[dict[str, Any]], k: str) -> float:
        return round(float(np.mean([r[k] for r in rows])), 2) if rows else 0.0

    out = {"lat": raw.get("latitude"), "lon": raw.get("longitude"), "elevation_m": raw.get("elevation"), "period": [ys[0], ys[-1]] if ys else None,
           "years": years, "monthly": monthly, "trend_per_decade": trends,
           "mean": {k: avg(years, k) for k in ("t_mean", "hdd", "cdd", "hot_days_35", "tropical_nights", "frost_days", "rain_mm", "rain_max_day_mm")},
           "first_decade": {k: avg(first, k) for k in ("t_mean", "hdd", "cdd", "hot_days_35")},
           "last_decade": {k: avg(last, k) for k in ("t_mean", "hdd", "cdd", "hot_days_35")},
           "extremes": {"t_max": max(years, key=lambda r: r["t_max"]) if years else None, "rain_max_day": max(years, key=lambda r: r["rain_max_day_mm"]) if years else None},
           "definitions": "HDD = Σ(18 − Tm) όταν Tm ≤ 15 °C · CDD = Σ(Tm − 21) όταν Tm ≥ 24 °C (ορισμοί Eurostat) · καύσωνας: Tmax ≥ 35 °C · τροπική νύχτα: Tmin ≥ 20 °C"}
    if design_T:
        out["design_T_ext"] = design_T
        out["delta_T_vs_design"] = [round(monthly[i]["t_mean"] - design_T[i], 2) for i in range(12)]
    if design_G:
        out["design_G_h"] = design_G
    return out


def climate_for_energy(cl: dict[str, Any], design: dict[str, list[float]]) -> dict[str, list[float]]:
    """Monthly climate of the site in the form the 6D balance uses (T_ext, G_h, G_45 scaled with G_h)."""
    T = [m["t_mean"] for m in cl["monthly"]]
    G = [m["G_h_kwh_m2"] for m in cl["monthly"]]
    G45 = [round(design["G_45"][i] * (G[i] / design["G_h"][i] if design["G_h"][i] else 1.0), 1) for i in range(12)]
    return {"T_ext": T, "G_h": G, "G_45": G45}


# ================================================================================================
# all together
# ================================================================================================
def site_point(project: dict[str, Any]) -> tuple[float, float]:
    lv = project.get("live") or {}
    c = lv.get("cadastre") or {}
    if c.get("lat"):
        return float(c["lat"]), float(c["lon"])
    loc = (project.get("meta") or {}).get("location") or {}
    if project.get("id") == "demo-kifisia" or not loc.get("lat"):
        return DEMO_LATLON
    return float(loc["lat"]), float(loc["lon"])


def refresh(project: dict[str, Any], what: list[str] | None = None, kaek: str | None = None, get: Callable[..., Any] | None = None,
            scenarios: dict[str, dict[str, Any]] | None = None, design_climate: dict[str, list[float]] | None = None,
            params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Refresh the requested parts in project["live"]; a failing part keeps its last good result and records the error."""
    what = what or ["cadastre", "seismic", "climate"]
    params = params or {}
    lv = project.setdefault("live", {})
    lv.setdefault("use", {"seismic_rates": False, "climate": False})
    status: dict[str, Any] = {}
    if "cadastre" in what:
        k = kaek or (lv.get("cadastre") or {}).get("kaek") or (project.get("meta") or {}).get("kaek") or (DEMO_KAEK if project.get("id") == "demo-kifisia" else None)
        if k:
            try:
                lv["cadastre"] = fetch_cadastre(k, get)
                status["cadastre"] = {"ok": True}
            except LiveError as ex:
                status["cadastre"] = {"ok": False, "error": str(ex)}
                lv.setdefault("errors", {})["cadastre"] = str(ex)
        else:
            status["cadastre"] = {"ok": False, "error": "Δεν έχει δοθεί ΚΑΕΚ."}
    lat, lon = site_point(project)
    soil = ((project.get("meta") or {}).get("structure") or {}).get("soil", "B")
    if "seismic" in what:
        try:
            r = float(params.get("radius_km", (lv.get("seismic") or {}).get("radius_km", 150)))
            raw = fetch_quakes_raw(lat, lon, r, float(params.get("minmag", 4.0)), get=get)
            res = analyse_quakes(raw, lat, lon, soil, r, scenarios)
            res.update({"fetched": now_iso(), "source": SOURCE_USGS, "lat": lat, "lon": lon})
            lv["seismic"] = res
            status["seismic"] = {"ok": True, "n": res.get("n")}
        except LiveError as ex:
            status["seismic"] = {"ok": False, "error": str(ex)}
            lv.setdefault("errors", {})["seismic"] = str(ex)
    if "climate" in what:
        try:
            y2 = date.today().year - 1
            y1 = y2 - 29
            raw = fetch_climate_raw(lat, lon, y1, y2, get=get)
            res = analyse_climate(raw, (design_climate or {}).get("T_ext"), (design_climate or {}).get("G_h"))
            res.update({"fetched": now_iso(), "source": SOURCE_METEO})
            if design_climate:
                res["energy_climate"] = climate_for_energy(res, design_climate)
            lv["climate"] = res
            status["climate"] = {"ok": True}
        except LiveError as ex:
            status["climate"] = {"ok": False, "error": str(ex)}
            lv.setdefault("errors", {})["climate"] = str(ex)
    for k, s in status.items():
        if s.get("ok"):
            (lv.get("errors") or {}).pop(k, None)
    lv["updated"] = now_iso()
    return status


def age_hours(iso: str | None) -> float:
    if not iso:
        return 1e9
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600
    except Exception:
        return 1e9
