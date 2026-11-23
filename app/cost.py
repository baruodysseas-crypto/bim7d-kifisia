"""5D cost engine: price book x quantities x live index ratios, overheads, VAT and forward risk (Monte-Carlo)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from . import prices as P

DATA = Path(__file__).parent / "data"


def _quality_multipliers(project: dict[str, Any] | None) -> dict[str, float]:
    """Trade multipliers of the quality level chosen in a new-build estimate (empty for projects without one)."""
    nb = (((project or {}).get("meta") or {}).get("newbuild") or {}).get("params") or {}
    q = nb.get("quality")
    if not q or q == "standard":
        return {}
    try:
        return json.loads((DATA / "newbuild_calibration.json").read_text(encoding="utf-8"))["quality"].get(q, {})
    except (OSError, KeyError, ValueError):
        return {}


def load_price_book(project: dict[str, Any] | None = None) -> dict[str, Any]:
    pb = json.loads((DATA / "price_book.json").read_text(encoding="utf-8"))
    qm = _quality_multipliers(project)
    if qm:
        for it in pb["items"].values():
            it["price"] = round(it["price"] * qm.get(it.get("trade", "other"), 1.0), 4)
    ov = (project or {}).get("price_overrides", {}) or {}
    for k, v in (ov.get("items") or {}).items():
        if k in pb["items"]:
            pb["items"][k].update(v)
        else:
            pb["items"][k] = v
    pb["overheads"].update(ov.get("overheads") or {})
    return pb


def item_factor(item: dict[str, Any], state: dict[str, Any], shocks: dict[str, float] | None = None) -> float:
    shocks = shocks or {}
    f = 0.0
    for g, w in item["components"].items():
        gg = P.ALIASES.get(g, g)
        f += w * P.ratio(state, gg) * shocks.get(gg, 1.0)
    s = sum(item["components"].values()) or 1.0
    return f / s


def compute(project: dict[str, Any], quantities: dict[str, float], state: dict[str, Any], shocks: dict[str, float] | None = None) -> dict[str, Any]:
    pb = load_price_book(project)
    lines = []
    for key, it in pb["items"].items():
        qkey = it.get("qty")
        qty = float(quantities.get(qkey, it.get("fixed_qty", 0.0))) if qkey else float(it.get("fixed_qty", 0.0))
        if it.get("qty_override") is not None:
            qty = float(it["qty_override"])
        if it.get("disabled"):
            qty = 0.0
        factor = item_factor(it, state, shocks)
        unit_now = it["price"] * factor
        lines.append({"key": key, "el": it["el"], "en": it["en"], "unit": it["unit"], "qty": round(qty, 2), "price_base": it["price"],
                      "index_factor": round(factor, 4), "price_now": round(unit_now, 2), "total_base": round(qty * it["price"], 2),
                      "total": round(qty * unit_now, 2), "task": it.get("task"), "trade": it.get("trade", "other"),
                      "overridden": it.get("qty_override") is not None or "price" in ((project or {}).get("price_overrides", {}).get("items", {}).get(key, {})), "disabled": bool(it.get("disabled"))})
    for i, c in enumerate(project.get("custom_cost_lines", []) or []):
        fac = item_factor({"components": c.get("components", {"general": 1.0})}, state, shocks)
        qty, pr = float(c.get("qty", 0)), float(c.get("price", 0))
        lines.append({"key": f"custom{i}", "el": c.get("name", "Custom"), "en": c.get("name", "Custom"), "unit": c.get("unit", "pcs"), "qty": qty,
                      "price_base": pr, "index_factor": round(fac, 4), "price_now": round(pr * fac, 2), "total_base": round(qty * pr, 2),
                      "total": round(qty * pr * fac, 2), "task": c.get("task"), "trade": c.get("trade", "other")})
    direct = sum(l["total"] for l in lines)
    direct_base = sum(l["total_base"] for l in lines)
    oh = pb["overheads"]
    ge = direct * oh["general_expenses_pct"] / 100
    pr = (direct + ge) * oh["profit_pct"] / 100
    cont = (direct + ge + pr) * oh.get("contingency_pct", 0) / 100
    net = direct + ge + pr + cont
    vat = net * oh["vat_pct"] / 100
    gfa = float(quantities.get("gfa_m2") or 1.0)
    by_trade: dict[str, float] = {}
    by_task: dict[int, float] = {}
    mult = (net / direct) if direct else 1.0
    for l in lines:
        by_trade[l["trade"]] = by_trade.get(l["trade"], 0.0) + l["total"] * mult
        if l["task"] is not None:
            by_task[int(l["task"])] = by_task.get(int(l["task"]), 0.0) + l["total"] * mult
    return {
        "lines": lines, "direct": round(direct, 2), "direct_base": round(direct_base, 2), "general_expenses": round(ge, 2), "profit": round(pr, 2),
        "contingency": round(cont, 2), "net": round(net, 2), "vat": round(vat, 2), "total_with_vat": round(net + vat, 2),
        "net_per_m2_gfa": round(net / gfa, 1), "total_per_m2_gfa": round((net + vat) / gfa, 1), "index_effect_pct": round(100 * (direct / direct_base - 1), 2) if direct_base else 0.0,
        "by_trade": {k: round(v, 2) for k, v in sorted(by_trade.items(), key=lambda kv: -kv[1])},
        "by_task": {k: round(v, 2) for k, v in sorted(by_task.items())}, "overheads": oh, "base_period": pb["base_period"],
    }


def group_sensitivity(project: dict[str, Any], quantities: dict[str, float], state: dict[str, Any], pct: float = 10.0) -> list[dict[str, Any]]:
    """Cost change (EUR, net of VAT) if each index group moves by +pct %. Ranks the price drivers of the project."""
    base = compute(project, quantities, state)["net"]
    out = []
    for g in state["groups"]:
        if g == "steel_rebar":
            sh = {"steel_rebar": 1 + pct / 100}
        else:
            sh = {g: 1 + pct / 100}
        c = compute(project, quantities, state, sh)["net"]
        out.append({"group": g, "label_el": state["groups"][g]["el"], "label_en": state["groups"][g]["en"], "delta_eur": round(c - base, 0),
                    "delta_pct": round(100 * (c / base - 1), 2)})
    return sorted(out, key=lambda r: -r["delta_eur"])


def monte_carlo(project: dict[str, Any], quantities: dict[str, float], state: dict[str, Any], task_weeks: dict[int, float],
                start_in_months: float = 0.0, n: int = 3000, seed: int = 11) -> dict[str, Any]:
    """Distribution of the net construction cost when prices follow the group dynamics until each task is executed.
    `task_weeks` gives the mid-point (in weeks from construction start) of every task."""
    pb = load_price_book(project)
    base = compute(project, quantities, state)
    horizon_months = start_in_months + (max(task_weeks.values()) if task_weeks else 52) / 4.345 + 1
    groups = list(state["groups"].keys())
    paths = P.simulate_ratio_paths(state, groups, years=horizon_months / 12 + 0.1, n=n, seed=seed)
    nsteps = next(iter(paths.values())).shape[1]
    mult = base["net"] / base["direct"] if base["direct"] else 1.0
    total = np.zeros(n)
    for l in base["lines"]:
        it = pb["items"].get(l["key"])
        if it is None:
            comps = {"general": 1.0}
        else:
            comps = it["components"]
        t_weeks = task_weeks.get(int(l["task"]), 0.0) if l["task"] is not None else 0.0
        idx = int(round(min(nsteps - 1, max(0.0, start_in_months + t_weeks / 4.345))))
        tw = sum(comps.values()) or 1.0
        shares = {}
        for g, w in comps.items():
            gg = P.ALIASES.get(g, g)
            shares[gg] = shares.get(gg, 0.0) + w * P.ratio(state, gg) / tw
        s = sum(shares.values()) or 1.0
        fut = np.zeros(n)
        for g, sh in shares.items():
            fut += (sh / s) * paths[g][:, idx]
        total += l["total"] * fut * mult
    pcts = np.percentile(total, [5, 10, 50, 90, 95])
    hist, edges = np.histogram(total, bins=30)
    return {"n": n, "start_in_months": start_in_months, "mean": round(float(total.mean()), 0), "std": round(float(total.std()), 0),
            "p05": round(float(pcts[0]), 0), "p10": round(float(pcts[1]), 0), "p50": round(float(pcts[2]), 0), "p90": round(float(pcts[3]), 0), "p95": round(float(pcts[4]), 0),
            "today": base["net"], "hist": [int(x) for x in hist], "edges": [round(float(x), 0) for x in edges]}
