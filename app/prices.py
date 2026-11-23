"""Price indices, live providers and price dynamics (5D cost engine support).

Design
------
Every price-book item has *components*: weights over index groups (concrete, steel_rebar,
labour, ...). The current unit price is

    price_now = price_base * sum_g( weight_g * ratio_g )        with ratio_g = value_g / base_g

`value_g` is updated either manually (UI), from official indices (ELSTAT, entered/seeded),
or from live providers (Yahoo Finance futures, TradingEconomics, ENTSO-E). Every provider
fails softly: on any error the last known value is kept and the error is recorded.

Network note: live providers need internet access on the machine that runs the tool and were
written against public documentation; they are covered by offline unit tests with mocked
responses only.
"""
from __future__ import annotations

import json
import math
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

# --------------------------------------------------------------------------------------
# Seed state: index groups. `base`/`value` are in the group's own unit; ratio = value/base.
# ELSTAT-based groups are expressed as an index (base 100 = price-book base period, Sep 2025). Values are the
# year-on-year changes of the ELSTAT monthly release for new residential construction materials, September 2026
# (published Oct 2026). They are the *Greek* part of the price model; update them monthly from the release.
# --------------------------------------------------------------------------------------
SEED_GROUPS: dict[str, dict[str, Any]] = {
    "general":    {"el": "Γενικός δείκτης κόστους κατασκευής", "en": "General construction cost index", "unit": "index", "base": 130.31, "value": 137.61,
                   "source": "ELSTAT (Sep 2026: 137.61, +5.6% y/y, base 2021=100); live: Eurostat sts_copi_q – κόστος κατασκευής νέων κατοικιών, Ελλάδα (2021=100)", "mode": "manual",
                   "provider": {"type": "eurostat", "base_period": "2025-Q3"}},
    "concrete":   {"el": "Έτοιμο σκυρόδεμα", "en": "Ready-mix concrete", "unit": "index", "base": 100.0, "value": 106.6,
                   "source": "ΕΛΣΤΑΤ έτοιμο σκυρόδεμα +6,6% y/y (Σεπ 2026)", "mode": "manual", "provider": None},
    "steel_rebar": {"el": "Χάλυβας οπλισμού (ράβδοι)", "en": "Rebar steel", "unit": "index", "base": 100.0, "value": 104.0,
                   "source": "ΕΛΣΤΑΤ σίδηρος οπλισμού +4,0% y/y (Σεπ 2026); live: συμβόλαιο χάλυβα HRC (Yahoo HRC=F, USD/t)", "mode": "manual",
                   "provider": {"type": "yahoo", "symbol": "HRC=F", "use": "ratio_only"}},
    "masonry":    {"el": "Τούβλα / κονιάματα / πλακίδια", "en": "Bricks, mortar, tiles", "unit": "index", "base": 100.0, "value": 107.1,
                   "source": "ΕΛΣΤΑΤ Σεπ 2026: τούβλα +12,4%, πλακίδια +4,7%, τσιμέντο +4,3% (μέσος όρος, ίσα βάρη = παραδοχή)", "mode": "manual", "provider": None},
    "insulation": {"el": "Θερμομονωτικά", "en": "Insulation materials", "unit": "index", "base": 100.0, "value": 105.8,
                   "source": "παραδοχή: ακολουθεί τα πλαστικά (ΕΛΣΤΑΤ δεν δίνει θερμομονωτικά στην ανακοίνωση)", "mode": "manual", "provider": None},
    "plastics":   {"el": "Πλαστικά / σωλήνες / χρώματα", "en": "Plastics, pipes, paints", "unit": "index", "base": 100.0, "value": 105.8,
                   "source": "ΕΛΣΤΑΤ πλαστικοί σωλήνες +5,8% y/y (Σεπ 2026)", "mode": "manual", "provider": None},
    "aluminium":  {"el": "Αλουμίνιο (κουφώματα)", "en": "Aluminium (window frames)", "unit": "index", "base": 100.0, "value": 104.9,
                   "source": "ΕΛΣΤΑΤ κουφώματα αλουμινίου +4,9% y/y (Σεπ 2026); προαιρετικά LME μέσω Yahoo ALI=F", "mode": "manual",
                   "provider": {"type": "yahoo", "symbol": "ALI=F", "use": "ratio_only"}},
    "copper":     {"el": "Χαλκός (αγωγοί / σωλήνες)", "en": "Copper (cables, pipes)", "unit": "index", "base": 100.0, "value": 111.3,
                   "source": "ΕΛΣΤΑΤ χάλκινοι σωλήνες +11,3% y/y (Σεπ 2026· δεν δίνεται ξεχωριστά για καλώδια); προαιρετικά COMEX μέσω Yahoo HG=F", "mode": "manual",
                   "provider": {"type": "yahoo", "symbol": "HG=F", "use": "ratio_only"}},
    "electricity": {"el": "Ηλεκτρική ενέργεια (€/MWh)", "en": "Electricity (EUR/MWh)", "unit": "EUR/MWh", "base": 100.0, "value": 114.9,
                   "source": "ELSTAT electricity +14.9% y/y (Sep 2026); Greek day-ahead ~60-145 EUR/MWh in Jun-Jul 2026", "mode": "manual",
                   "provider": {"type": "entsoe", "domain": "10YGR-HTSO-----Y"}},
    "fuel":       {"el": "Καύσιμα (diesel)", "en": "Fuel (diesel)", "unit": "index", "base": 100.0, "value": 131.2,
                   "source": "ELSTAT diesel +31.2% y/y (Sep 2026); Brent via Yahoo BZ=F optional", "mode": "manual",
                   "provider": {"type": "yahoo", "symbol": "BZ=F", "use": "ratio_only"}},
    "labour":     {"el": "Εργατικά", "en": "Labour", "unit": "index", "base": 100.0, "value": 104.0,
                   "source": "προσέγγιση: δείκτης κόστους κατασκευής νέων κατοικιών (ΕΛΣΤΑΤ +4,0% y/y, Β΄ τρίμ. 2026)· live: Eurostat sts_copi_q (ο ίδιος δείκτης)", "mode": "manual",
                   "provider": {"type": "eurostat", "base_period": "2025-Q3"}},
}
ALIASES = {"steel": "steel_rebar"}   # generic steel components follow rebar

# Annual drift / volatility per group used for forward scenarios (Monte-Carlo life-cycle cost).
# Calibrated to observed behaviour: ELSTAT index +2.3..5.6% y/y in 2026; SHFE rebar ranged
# 1,580..6,198 CNY/t over 2009-2026 and moved 3,130 in Apr-2026 (vol ~20-25%); Greek day-ahead power
# moves tens of percent day-to-day (mean-reverting, vol ~30%). Editable in the UI.
DYNAMICS: dict[str, dict[str, float]] = {
    "general": {"mu": 0.030, "sigma": 0.025}, "concrete": {"mu": 0.035, "sigma": 0.040},
    "steel_rebar": {"mu": 0.020, "sigma": 0.220}, "masonry": {"mu": 0.035, "sigma": 0.040},
    "insulation": {"mu": 0.030, "sigma": 0.060}, "plastics": {"mu": 0.030, "sigma": 0.070},
    "aluminium": {"mu": 0.030, "sigma": 0.180}, "copper": {"mu": 0.040, "sigma": 0.200},
    "electricity": {"mu": 0.025, "sigma": 0.300}, "fuel": {"mu": 0.025, "sigma": 0.280},
    "labour": {"mu": 0.035, "sigma": 0.025},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_state() -> dict[str, Any]:
    groups = {}
    for k, g in SEED_GROUPS.items():
        gg = dict(g)
        gg["updated"] = None
        gg["history"] = []
        gg["error"] = None
        groups[k] = gg
    return {"version": 1, "groups": groups, "dynamics": json.loads(json.dumps(DYNAMICS)), "dynamics_assumed": json.loads(json.dumps(DYNAMICS)),
            "series": {}, "calibration": {}, "settings": {"tradingeconomics_key": "", "entsoe_token": "", "timeout_s": 12, "use_calibrated": True}}


def load_state(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            st = json.loads(path.read_text(encoding="utf-8"))
            base = default_state()
            for k, v in base["groups"].items():
                cur = st["groups"].setdefault(k, v)
                if cur is not v and not cur.get("updated") and not cur.get("history"):
                    st["groups"][k] = v            # never edited/refreshed by the user -> take the current ELSTAT seed
                else:
                    if cur.get("provider") != v.get("provider"):          # a changed live source restarts its tracking
                        for x in ("seed_ratio", "ref_commodity", "live_commodity", "live_ratio"):
                            cur.pop(x, None)
                    cur["provider"], cur["source"], cur["el"], cur["en"] = v["provider"], v["source"], v["el"], v["en"]
            st.setdefault("dynamics", base["dynamics"])
            st.setdefault("series", {})
            st.setdefault("calibration", {})
            st.setdefault("dynamics_assumed", json.loads(json.dumps(DYNAMICS)))
            st.setdefault("settings", base["settings"])
            return st
        except Exception:
            pass
    return default_state()


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def ratio(state: dict[str, Any], group: str) -> float:
    group = ALIASES.get(group, group)
    g = state["groups"].get(group)
    if not g or not g.get("base"):
        return 1.0
    return float(g["value"]) / float(g["base"])


def set_value(state: dict[str, Any], group: str, value: float, source: str = "manual") -> None:
    g = state["groups"][group]
    g["value"] = float(value)
    if source == "manual":                       # a manual entry restarts commodity tracking from this level
        g.pop("seed_ratio", None)
        g.pop("ref_commodity", None)
    g["updated"] = _now()
    g["history"] = (g.get("history") or [])[-199:] + [{"t": g["updated"], "v": float(value), "src": source}]


# --------------------------------------------------------------------------------------
# Providers (all return a float and raise on failure)
# --------------------------------------------------------------------------------------
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def _http_get(url: str, timeout: float, headers: dict[str, str] | None = None) -> bytes:
    import os
    import urllib.request
    if os.environ.get("BIM7D_OFFLINE", "") == "1":
        raise ConnectionError("offline mode (BIM7D_OFFLINE=1)")
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA, "Accept": "application/json,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https endpoints)
        return r.read()


def parse_yahoo_chart(payload: bytes | str) -> float:
    data = json.loads(payload)
    res = data["chart"]["result"][0]
    price = res["meta"].get("regularMarketPrice")
    if price is None:
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        price = closes[-1]
    return float(price)


def fetch_yahoo(symbol: str, timeout: float = 8, http=_http_get) -> float:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
    return parse_yahoo_chart(http(url, timeout))


def parse_tradingeconomics(payload: bytes | str, match: str) -> float:
    rows = json.loads(payload)
    for r in rows:
        name = f"{r.get('Name', '')} {r.get('Symbol', '')} {r.get('Ticker', '')}".lower()
        if match.lower() in name:
            return float(r.get("Last") or r.get("Close"))
    raise LookupError(f"no TradingEconomics commodity matching '{match}'")


def fetch_tradingeconomics(key: str, match: str, timeout: float = 8, http=_http_get) -> float:
    if not key:
        raise PermissionError("TradingEconomics API key not set")
    url = f"https://api.tradingeconomics.com/markets/commodities?c={key}&f=json"
    return parse_tradingeconomics(http(url, timeout), match)


def parse_entsoe_day_ahead(xml_bytes: bytes | str) -> float:
    """Average of all <price.amount> points (EUR/MWh) in an ENTSO-E A44 document."""
    root = ET.fromstring(xml_bytes)
    vals = [float(e.text) for e in root.iter() if e.tag.endswith("price.amount") and e.text]
    if not vals:
        raise LookupError("no price points in ENTSO-E response")
    return float(sum(vals) / len(vals))


def fetch_entsoe(token: str, domain: str, timeout: float = 8, http=_http_get, today: datetime | None = None) -> float:
    if not token:
        raise PermissionError("ENTSO-E token not set")
    d = today or datetime.now(timezone.utc)
    start = d.strftime("%Y%m%d0000")
    end = d.strftime("%Y%m%d2300")
    url = ("https://web-api.tp.entsoe.eu/api?documentType=A44&processType=A01"
           f"&in_Domain={domain}&out_Domain={domain}&periodStart={start}&periodEnd={end}&securityToken={token}")
    return parse_entsoe_day_ahead(http(url, timeout))


EUROSTAT = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/sts_copi_q"
            "?geo=EL&indic_bt=COST&unit=I21&s_adj=NSA&cpa2_1=CPA_F41001_X_410014&sinceTimePeriod=2005-Q1&lang=en")


def parse_eurostat_series(payload: bytes | str) -> list[tuple[str, float]]:
    """JSON-stat 2.0 (Eurostat API) with all dimensions but time fixed -> [(period, value)] in time order."""
    j = json.loads(payload)
    idx = j["dimension"]["time"]["category"]["index"]
    vals = j.get("value") or {}
    out = []
    for per, i in sorted(idx.items(), key=lambda kv: kv[1]):
        v = vals.get(str(i)) if isinstance(vals, dict) else (vals[i] if i < len(vals) else None)
        if v is not None:
            out.append((per, float(v)))
    if not out:
        raise LookupError("empty Eurostat series")
    return out


def fetch_eurostat_cost(timeout: float = 12, http=_http_get) -> list[tuple[str, float]]:
    return parse_eurostat_series(http(EUROSTAT, timeout))


def parse_yahoo_history(payload: bytes | str) -> list[tuple[str, float]]:
    """Monthly closes from a Yahoo v8 chart response -> [("YYYY-MM", close)], one value per month (last one wins)."""
    res = json.loads(payload)["chart"]["result"][0]
    ts = res.get("timestamp") or []
    cl = res["indicators"]["quote"][0].get("close") or []
    by: dict[str, float] = {}
    for t, c in zip(ts, cl):
        if c is not None:
            by[datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m")] = float(c)
    if not by:
        raise LookupError("empty Yahoo history")
    return sorted(by.items())


def fetch_yahoo_history(symbol: str, timeout: float = 12, http=_http_get, rng: str = "10y") -> list[tuple[str, float]]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval=1mo"
    return parse_yahoo_history(http(url, timeout))


def calibrate(series: list[tuple[str, float]], periods_per_year: int) -> dict[str, Any]:
    """Annual drift and volatility of a price series (log returns): sigma = sd·sqrt(k), mu = mean·k + sigma²/2 (GBM)."""
    v = np.array([x for _, x in series], dtype=float)
    v = v[v > 0]
    if v.size < 8:
        raise ValueError("too few points to calibrate")
    r = np.diff(np.log(v))
    sg = float(r.std(ddof=1) * math.sqrt(periods_per_year))
    mu = float(r.mean() * periods_per_year + 0.5 * sg * sg)
    yrs = (v.size - 1) / periods_per_year
    return {"mu": round(mu, 4), "sigma": round(sg, 4), "n": int(v.size), "from": series[0][0], "to": series[-1][0], "years": round(yrs, 1),
            "cagr": round(float((v[-1] / v[0]) ** (1 / yrs) - 1), 4) if yrs > 0 else None,
            "min": round(float(v.min()), 3), "max": round(float(v.max()), 3)}


MU_CLAMP = (-0.05, 0.10)          # a decade of history is not a forecast: drift used forward is limited to this band


def refresh_history(state: dict[str, Any], http=_http_get) -> dict[str, Any]:
    """Download the history of every live group (Yahoo monthly 10 years in EUR, Eurostat quarterly), keep it in
    state["series"], calibrate drift/volatility and – if settings.use_calibrated – use them for the forward scenarios."""
    status: dict[str, Any] = {}
    to = float(state.get("settings", {}).get("timeout_s", 12))
    series = state.setdefault("series", {})
    calib = state.setdefault("calibration", {})
    state.setdefault("dynamics_assumed", json.loads(json.dumps(DYNAMICS)))
    fx: dict[str, float] = {}
    try:
        fx = dict(fetch_yahoo_history("EURUSD=X", to, http))
        series["_eurusd"] = {"t": list(fx.keys()), "v": [round(x, 5) for x in fx.values()], "unit": "USD per EUR", "src": "Yahoo EURUSD=X", "updated": _now()}
    except Exception as ex:  # noqa: BLE001
        status["_eurusd"] = {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
    for k, g in state["groups"].items():
        p = g.get("provider") or {}
        try:
            if p.get("type") == "yahoo":
                h = fetch_yahoo_history(p["symbol"], to, http)
                if fx:
                    h = [(t, v / fx[t]) for t, v in h if t in fx and fx[t]]
                    unit = "EUR"
                else:
                    unit = "USD"
                series[k] = {"t": [t for t, _ in h], "v": [round(v, 4) for _, v in h], "unit": unit, "src": f"Yahoo {p['symbol']}", "freq": "M", "updated": _now()}
                c = calibrate(h, 12)
            elif p.get("type") == "eurostat":
                h = fetch_eurostat_cost(to, http)
                series[k] = {"t": [t for t, _ in h], "v": [v for _, v in h], "unit": "index 2021=100", "src": "Eurostat sts_copi_q (EL)", "freq": "Q", "updated": _now()}
                c = calibrate(h[-41:], 4)                                    # last 10 years
            else:
                continue
            calib[k] = c
            if state.get("settings", {}).get("use_calibrated", True):
                state["dynamics"][k] = {"mu": round(min(max(c["mu"], MU_CLAMP[0]), MU_CLAMP[1]), 4), "sigma": c["sigma"], "calibrated": True}
            status[k] = {"ok": True, "n": c["n"]}
        except Exception as ex:  # noqa: BLE001 - soft failure by design
            status[k] = {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
    return status


def use_assumed_dynamics(state: dict[str, Any]) -> None:
    state["dynamics"] = json.loads(json.dumps(state.get("dynamics_assumed") or DYNAMICS))
    state.setdefault("settings", {})["use_calibrated"] = False


def use_calibrated_dynamics(state: dict[str, Any]) -> None:
    state.setdefault("settings", {})["use_calibrated"] = True
    for k, c in (state.get("calibration") or {}).items():
        if k in state["dynamics"]:
            state["dynamics"][k] = {"mu": round(min(max(c["mu"], MU_CLAMP[0]), MU_CLAMP[1]), 4), "sigma": c["sigma"], "calibrated": True}


def refresh_all(state: dict[str, Any], http=_http_get) -> dict[str, Any]:
    """Update every group that has a provider. Never raises; returns per-group status."""
    status: dict[str, Any] = {}
    cfg = state.get("settings", {})
    to = float(cfg.get("timeout_s", 8))
    for k, g in state["groups"].items():
        p = g.get("provider")
        if not p:
            continue
        try:
            if p["type"] in ("yahoo", "tradingeconomics"):
                if p["type"] == "yahoo":
                    v = fetch_yahoo(p["symbol"], to, http)
                    src = "yahoo:" + p["symbol"]
                else:
                    v = fetch_tradingeconomics(cfg.get("tradingeconomics_key", ""), p["match"], to, http)
                    src = "tradingeconomics:" + p["match"]
                if p.get("use") == "ratio_only":
                    # The first successful fetch fixes the commodity reference level. Afterwards the group value follows
                    #   value = base * seed_ratio * (live / reference)
                    # where seed_ratio is the ELSTAT-seeded (or manually entered) ratio at the time of the first fetch.
                    seed = g.setdefault("seed_ratio", g["value"] / g["base"])
                    ref = g.setdefault("ref_commodity", v)
                    if not (0.33 <= v / ref <= 3.0):          # contract roll / unit change at the source: restart tracking from today
                        g["seed_ratio"] = seed = g["value"] / g["base"]
                        g["ref_commodity"] = ref = v
                    g["value"] = g["base"] * seed * (v / ref)
                    g["live_commodity"] = v
                    g["live_ratio"] = v / ref
                    g["updated"] = _now()
                    g["history"] = (g.get("history") or [])[-199:] + [{"t": g["updated"], "v": g["value"], "src": src}]
                    g["error"] = None
                    status[k] = {"ok": True, "value": v, "note": "commodity tracked; ratio vs first fetch"}
                    continue
                set_value(state, k, v, p["type"])
            elif p["type"] == "eurostat":
                h = fetch_eurostat_cost(to, http)
                bp = dict(h).get(p.get("base_period", ""))
                if bp:
                    g["base"] = bp
                v = h[-1][1]
                set_value(state, k, v, "eurostat")
                g["live_period"] = h[-1][0]
            elif p["type"] == "entsoe":
                v = fetch_entsoe(cfg.get("entsoe_token", ""), p["domain"], to, http)
                set_value(state, k, v, "entsoe")
            else:
                continue
            g["error"] = None
            status[k] = {"ok": True, "value": v}
        except Exception as ex:  # soft failure by design
            g["error"] = f"{type(ex).__name__}: {ex}"
            status[k] = {"ok": False, "error": g["error"]}
    return status


# --------------------------------------------------------------------------------------
# Dynamics: simulated price-ratio paths for forward cost scenarios
# --------------------------------------------------------------------------------------
def simulate_ratio_paths(state: dict[str, Any], groups: list[str], years: float, steps_per_year: int = 12,
                         n: int = 2000, seed: int = 7) -> dict[str, np.ndarray]:
    """Geometric Brownian motion per group (log-normal), correlated through a common 'market' factor.
    Returns arrays shape (n, steps+1) of ratio *relative to today* (1.0 at t=0)."""
    rng = np.random.default_rng(seed)
    steps = max(1, int(round(years * steps_per_year)))
    dt = 1.0 / steps_per_year
    common = rng.standard_normal((n, steps))
    out: dict[str, np.ndarray] = {}
    for g in groups:
        g = ALIASES.get(g, g)
        d = state["dynamics"].get(g, {"mu": 0.03, "sigma": 0.05})
        mu, sg = float(d["mu"]), float(d["sigma"])
        rho = 0.35
        z = rho * common + math.sqrt(1 - rho ** 2) * rng.standard_normal((n, steps))
        incr = (mu - 0.5 * sg ** 2) * dt + sg * math.sqrt(dt) * z
        path = np.concatenate([np.zeros((n, 1)), np.cumsum(incr, axis=1)], axis=1)
        out[g] = np.exp(path)
    return out


def describe_behaviour(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the behaviour table (drift, vol, 1-year P10/P90 price multiplier) for the UI/report."""
    rows = []
    for g, d in state["dynamics"].items():
        mu, sg = d["mu"], d["sigma"]
        m = lambda z: math.exp((mu - 0.5 * sg * sg) + sg * z)
        rows.append({"group": g, "label_el": state["groups"][g]["el"], "label_en": state["groups"][g]["en"],
                     "mu": mu, "sigma": sg, "p10_1y": m(-1.2816), "p50_1y": m(0.0), "p90_1y": m(1.2816),
                     "ratio_now": ratio(state, g), "source": state["groups"][g]["source"], "updated": state["groups"][g].get("updated"),
                     "error": state["groups"][g].get("error"), "calibrated": bool(d.get("calibrated")),
                     "assumed": (state.get("dynamics_assumed") or {}).get(g), "calibration": (state.get("calibration") or {}).get(g)})
    return rows
