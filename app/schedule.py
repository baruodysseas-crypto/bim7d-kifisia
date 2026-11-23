"""4D engine: tasks (weeks) linked to BIM elements, 4D state at any week, cost S-curve and critical path."""
from __future__ import annotations

from typing import Any

# which element kinds/storeys each task builds (by task id of the Gantt chart). storeys are ordered bottom-up.
TASK_LINKS: dict[int, dict[str, Any]] = {
    1: {"kinds": [], "note": "excavation"},
    2: {"kinds": ["footing"], "sequence": "storey"},
    3: {"kinds": ["column", "beam", "slab", "roof", "stair"], "sequence": "storey"},
    4: {"kinds": ["wall"], "sequence": "storey"},
    9: {"kinds": ["railing"], "sequence": "storey"},
    17: {"kinds": ["window"], "sequence": "storey"},
    18: {"kinds": ["door"], "sequence": "storey"},
    22: {"kinds": ["pergola", "fence"], "sequence": "none"},
    24: {"kinds": ["vegetation"], "sequence": "none"},
}


def tasks_from_project(project: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for t in project["schedule"]["tasks"]:
        segs = t["segments"]
        start = min(s[0] for s in segs)
        end = max(s[1] for s in segs)
        out.append({"id": t["id"], "name": t["name"], "segments": segs, "start_week": start, "end_week": end, "weeks": sum(s[1] - s[0] + 1 for s in segs)})
    return out


def task_midpoints(tasks: list[dict[str, Any]]) -> dict[int, float]:
    mids = {}
    for t in tasks:
        tot = sum(s[1] - s[0] + 1 for s in t["segments"])
        mids[t["id"]] = sum((s[0] - 1 + (s[1] - s[0] + 1) / 2) * (s[1] - s[0] + 1) for s in t["segments"]) / max(tot, 1)
    return mids


def project_weeks(tasks: list[dict[str, Any]]) -> int:
    return max((t["end_week"] for t in tasks), default=0)


def cost_curve(tasks: list[dict[str, Any]], cost_by_task: dict[int, float]) -> list[dict[str, float]]:
    """Cumulative cost per week, spreading each task's cost uniformly over its active weeks."""
    n = project_weeks(tasks)
    weekly = [0.0] * (n + 1)
    for t in tasks:
        weeks = [w for s in t["segments"] for w in range(s[0], s[1] + 1)]
        c = cost_by_task.get(t["id"], 0.0)
        for w in weeks:
            weekly[w] += c / max(len(weeks), 1)
    cum, run = [], 0.0
    for w in range(1, n + 1):
        run += weekly[w]
        cum.append({"week": w, "weekly": round(weekly[w], 0), "cumulative": round(run, 0)})
    return cum


def critical_path(tasks: list[dict[str, Any]]) -> list[int]:
    """Simple finish-to-start logic derived from the Gantt: a task depends on every task that ends the week before it
    starts or overlaps its start (the typical building sequence). The returned chain is the longest one."""
    order = sorted(tasks, key=lambda t: (t["start_week"], t["end_week"]))
    best: dict[int, tuple[int, list[int]]] = {}
    for t in order:
        pred = [p for p in order if p["end_week"] < t["start_week"] + 1 and p["id"] != t["id"] and p["end_week"] <= t["start_week"]]
        if pred:
            b = max(pred, key=lambda p: best.get(p["id"], (0, []))[0])
            d, chain = best.get(b["id"], (0, []))
            best[t["id"]] = (d + t["weeks"], chain + [t["id"]])
        else:
            best[t["id"]] = (t["weeks"], [t["id"]])
    if not best:
        return []
    return best[max(best, key=lambda k: best[k][0])][1]


def state_at(project: dict[str, Any], tasks: list[dict[str, Any]], week: float) -> dict[str, str]:
    """Return {element_id: 'todo'|'active'|'done'} at a given week (4D)."""
    els = project["elements"]
    storey_order = {s["id"]: i for i, s in enumerate(sorted(project["storeys"], key=lambda s: s["elevation_m"]))}
    kind_task: dict[str, dict[str, Any]] = {}
    for t in tasks:
        link = TASK_LINKS.get(t["id"])
        if not link:
            continue
        for k in link["kinds"]:
            kind_task.setdefault(k, {"task": t, "seq": link.get("sequence", "none")})
    res: dict[str, str] = {}
    n_st = max(len(storey_order), 1)
    for e in els:
        info = kind_task.get(e["kind"])
        if not info:
            res[e["id"]] = "done" if e["kind"] in ("site",) else "todo"
            continue
        t = info["task"]
        s0, s1 = t["start_week"] - 1, t["end_week"]
        if info["seq"] == "storey" and e.get("storey") in storey_order:
            i = storey_order[e["storey"]]
            span = (s1 - s0) / n_st
            a, b = s0 + i * span, s0 + (i + 1) * span
        else:
            a, b = s0, s1
        res[e["id"]] = "done" if week >= b else ("active" if week > a else "todo")
    return res
