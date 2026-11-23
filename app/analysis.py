"""Glue between the stored project and the engines: one place that turns (project, price state, settings) into results."""
from __future__ import annotations

import copy
from typing import Any

from . import cost, energy, fm, hazards, lifecycle, prices, quantities, schedule


def settings(project: dict[str, Any]) -> dict[str, Any]:
    s = project.setdefault("settings", {})
    s.setdefault("assumptions", {})
    s.setdefault("quantity_overrides", {})
    s.setdefault("energy", {"preset": "as_certified", "selected": {}})
    s.setdefault("lifecycle", {})
    s.setdefault("hazards", {})
    s.setdefault("exposure", {})
    s.setdefault("monte_carlo", {"start_in_months": 6, "n": 2000})
    return s


def quantities_of(project: dict[str, Any]) -> dict[str, Any]:
    st = settings(project)
    res = quantities.compute(project, st["assumptions"])
    q = dict(res["quantities"])
    ov = st["quantity_overrides"]
    for k, v in ov.items():
        if k in q and v is not None:
            q[k] = float(v)
    res["calculated"] = res["quantities"]
    res["quantities"] = q
    res["overridden"] = [k for k, v in ov.items() if v is not None and k in q]
    return res


def cost_of(project: dict[str, Any], pstate: dict[str, Any], q: dict[str, float] | None = None, shocks: dict[str, float] | None = None) -> dict[str, Any]:
    q = q or quantities_of(project)["quantities"]
    return cost.compute(project, q, pstate, shocks)


def schedule_of(project: dict[str, Any], cost_res: dict[str, Any]) -> dict[str, Any]:
    tasks = schedule.tasks_from_project(project)
    return {"tasks": tasks, "weeks": schedule.project_weeks(tasks), "critical_path": schedule.critical_path(tasks),
            "curve": schedule.cost_curve(tasks, {int(k): v for k, v in cost_res["by_task"].items()}), "midpoints": schedule.task_midpoints(tasks),
            "cost_by_task": {int(k): v for k, v in cost_res["by_task"].items()}}


def energy_of(project: dict[str, Any], q: dict[str, float], pstate: dict[str, Any], sel: dict[str, Any] | None = None, preset: str | None = None) -> dict[str, Any]:
    es = settings(project)["energy"]
    sel = es["selected"] if sel is None else sel
    preset = preset or es.get("preset", "as_certified")
    ratio = prices.ratio(pstate, "general")
    return energy.study(project, sel, index_ratio=ratio, preset=preset, quantities=q)


def lifecycle_of(project: dict[str, Any], cost_res: dict[str, Any], q: dict[str, float], en: dict[str, Any], assumptions: dict[str, Any] | None = None) -> dict[str, Any]:
    a = dict(settings(project).get("lifecycle", {}))
    a.update(assumptions or {})
    return lifecycle.compare(project, cost_res, q, en, a)


def hazards_summary(project: dict[str, Any], cost_res: dict[str, Any], q: dict[str, float]) -> dict[str, Any]:
    st = settings(project)
    return hazards.risk_summary(project, cost_res, q, base_params=st["hazards"], exposure=st["exposure"])


def fm_of(project: dict[str, Any], cost_res: dict[str, Any], lc: dict[str, Any], risk: dict[str, Any] | None = None) -> dict[str, Any]:
    """7D facility management on the life-cycle case in use (with the energy upgrades when a package is chosen)."""
    return fm.compute(project, cost_res, lc["upgrade"] or lc["base"], risk)


def everything(project: dict[str, Any], pstate: dict[str, Any]) -> dict[str, Any]:
    """All results needed by the report (and the dashboard)."""
    qres = quantities_of(project)
    q = qres["quantities"]
    c = cost_of(project, pstate, q)
    sch = schedule_of(project, c)
    mc_cfg = settings(project)["monte_carlo"]
    mc = cost.monte_carlo(project, q, pstate, sch["midpoints"], start_in_months=mc_cfg["start_in_months"], n=int(mc_cfg["n"]))
    en = energy_of(project, q, pstate)
    lc = lifecycle_of(project, c, q, en)
    seis = hazards.seismic_all(project, c, settings(project)["hazards"].get("seismic", {}))
    hz_params = settings(project)["hazards"]
    fire_i = hazards.fire_internal(project, c, hz_params.get("fire_internal", {"storey": _default_fire_storey(project)}))
    wild = hazards.wildfire(project, c, hz_params.get("wildfire", {}))
    fl = hazards.flood_all(project, c, hz_params.get("flood", {}))
    risk = hazards_summary(project, c, q)
    sens = cost.group_sensitivity(project, q, pstate)
    fmr = fm_of(project, c, lc, risk)
    return {"fm": fmr, "quantities": qres, "cost": c, "schedule": sch, "monte_carlo": mc, "energy": en, "lifecycle": lc, "seismic": seis, "fire_internal": fire_i, "wildfire": wild,
            "flood": fl, "risk": risk, "sensitivity": sens, "behaviour": prices.describe_behaviour(pstate)}


def _default_fire_storey(project: dict[str, Any]) -> str:
    st = [s for s in project.get("storeys") or [] if s["elevation_m"] >= 0]
    if st:
        return (st[1] if len(st) > 1 else st[0])["id"]
    return project["storeys"][0]["id"] if project.get("storeys") else "S01"
