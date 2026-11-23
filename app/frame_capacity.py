"""Seismic resistance from the real reinforced-concrete skeleton (formwork drawings S.01–S.06 of the structural design).

For every column / wall of every storey the drawings give the real cross-section (L, T, U shapes, walls), the longitudinal bars
(e.g. 12Φ20), the stirrups (Φ10/10) and – for walls – the web reinforcement; for every beam the section, the top (π) and bottom (κ)
bars and the stirrups.  From them:

  1. Flexural resistance M_R of each vertical element in X and in Y (fibre section analysis of the real polygon, mean material
     strengths fcm = fck + 8 MPa, fym = 1.15·fyk, parabola–rectangle concrete εcu = 3.5 ‰), with the axial load of the seismic
     combination (storey weights of the static report shared by tributary area).
  2. Shear resistance V_R from the stirrups / horizontal web bars (EC2 6.2.3, cot θ = 1 as for critical regions in EC8, V_Rd,max
     check) – ductile (flexure) or brittle (shear) failure of each element.
  3. Joint check: Σ M_Rc ≥ 1.3 Σ M_Rb (EC8 §4.4.2.3, capacity design: strong columns – weak beams); where the beams are weaker the
     column top moment is limited by them in the storey mechanism.
  4. Storey resistance in X and Y = Σ of the element shears at the mechanism; the elastic storey shear for a ground acceleration a
     is V_el = V_d · q · a / A (design shears V_d of the static report at A = 0.24 g, q = 3).  The storey "yields" at
     a_y = A · V_R / (q · V_d); it reaches near-collapse at a_c = a_y · R(μ), with available ductility μ = 3.5 for flexure-governed
     elements and 1.5 for shear-governed elements (weighted by their share), R(μ) = √(2μ−1) for T < T_C.
  5. Detailing checks of EC8 DCM / ΕΚΩΣ (reinforcement ratios, stirrup spacing in critical regions, continuity between floors).

Screening level – not a ΚΑΝ.ΕΠΕ. non-linear assessment."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import voronoi_diagram
from shapely.geometry import MultiPoint

DATA = Path(__file__).parent / "data"
FRAME_FILE = DATA / "frame_kifisia.json"
STOREYS = ["basement", "ground", "first", "second", "attic"]
STATIC_IDX = {"basement": 2, "ground": 3, "first": 4, "second": 5, "attic": 6}
HEIGHT = {"basement": 3.00, "ground": 3.05, "first": 3.05, "second": 3.20, "attic": 3.20}
NAMES = {"basement": ("Υπόγειο", "Basement"), "ground": ("Ισόγειο", "Ground floor"), "first": ("Α΄ όροφος", "1st floor"),
         "second": ("Β΄ όροφος", "2nd floor"), "attic": ("Σοφίτα", "Attic")}
FCK, FYK = 25.0, 500.0
FCM, FYM = FCK + 8.0, 1.15 * FYK          # mean strengths (MPa)
ES = 200000.0
COVER = 0.05                               # to the bar axis (drawings: 6 cm nominal to the stirrup face side)
MU_FLEX, MU_SHEAR = 3.5, 1.5


def load_frame() -> dict[str, Any] | None:
    if not FRAME_FILE.exists():
        return None
    return json.loads(FRAME_FILE.read_text(encoding="utf-8"))


def bar_area(n: int, d: int) -> float:
    return n * math.pi * (d / 1000) ** 2 / 4          # m2


def parse_bars(s: str | None) -> list[tuple[int, int]]:
    return [(int(n), int(d)) for n, d in re.findall(r"(\d+)Φ(\d+)", s or "")]


# ------------------------------------------------------------------------------------------------ sections
def _bars_layout(poly: Polygon, bars: list[tuple[int, int]], web: list[dict] | None) -> list[tuple[float, float, float]]:
    """Bar positions: the listed bars evenly along the perimeter of the polygon inset by the cover (corners first), plus the
    vertical web bars of walls (two faces) along the long legs."""
    inner = poly.buffer(-COVER, join_style=2)
    if inner.is_empty:
        inner = poly.buffer(-0.02, join_style=2)
    if inner.geom_type != "Polygon":
        inner = max(inner.geoms, key=lambda g: g.area)
    ring = LineString(inner.exterior.coords)
    L = ring.length
    out = []
    corners = list(inner.exterior.coords)[:-1]
    n_tot = sum(n for n, _ in bars)
    sizes = [d for n, d in bars for _ in range(n)]
    sizes.sort(reverse=True)                                   # biggest bars at the corners
    k = 0
    for c in corners:
        if k >= n_tot:
            break
        out.append((c[0], c[1], bar_area(1, sizes[k])))
        k += 1
    rest = n_tot - k
    if rest > 0:
        # remaining bars evenly along the perimeter, skipping the corner positions
        cpos = sorted(ring.project(Point(c)) for c in corners)
        for i in range(rest):
            s = (i + 0.5) / rest * L
            for cp in cpos:                                    # nudge away from a corner
                if abs(s - cp) < 0.04:
                    s += 0.05
            p = ring.interpolate(s % L)
            out.append((p.x, p.y, bar_area(1, sizes[k + i])))
    for w in web or []:
        v = w.get("vert")
        if not v:
            continue
        d, s = v
        # web bars on both faces of the parts longer than 1 m: along the inner ring where the boundary bars are sparse
        n = int(L / (s / 100.0) * 0.5)
        for i in range(n):
            p = ring.interpolate((i + 0.25) / max(n, 1) * L)
            out.append((p.x, p.y, bar_area(1, d)))
    return out


def _fibres(poly: Polygon, h: float = 0.025) -> np.ndarray:
    x0, y0, x1, y1 = poly.bounds
    xs = np.arange(x0 + h / 2, x1, h)
    ys = np.arange(y0 + h / 2, y1, h)
    X, Y = np.meshgrid(xs, ys)
    pts = np.c_[X.ravel(), Y.ravel()]
    from shapely import contains_xy
    m = contains_xy(poly, pts[:, 0], pts[:, 1])
    pts = pts[m]
    return np.c_[pts, np.full(len(pts), h * h)]


def _sigma_c(eps: np.ndarray) -> np.ndarray:
    e2, n = 0.002, 2.0
    s = np.where(eps <= 0, 0.0, np.where(eps < e2, FCM * (1 - (1 - eps / e2) ** n), FCM))
    return s


def moment_capacity(poly: Polygon, bars: list[tuple[float, float, float]], N_kN: float, axis: str) -> float:
    """M_R [kNm] for bending that makes the section rotate about an axis perpendicular to `axis` ('x' = lateral load in X:
    strains vary with x).  Mean of the two senses. Compression positive. N in kN (compression > 0)."""
    fib = _fibres(poly)
    if len(fib) == 0:
        return 0.0
    j = 0 if axis == "x" else 1
    t_c = fib[:, j]
    Ac = fib[:, 2]
    tb = np.array([b[j] for b in bars]) if bars else np.zeros(0)
    Ab = np.array([b[2] for b in bars]) if bars else np.zeros(0)
    cen = float((t_c * Ac).sum() / Ac.sum())
    N = N_kN / 1000.0                                           # MN
    res = []
    for sense in (1, -1):
        tc, tb_ = sense * (t_c - cen), sense * (tb - cen)
        top = tc.max() + 0.0
        lo, hi = 1e-4, (tc.max() - tc.min()) * 3
        def force(c: float):
            eps_c = 0.0035 * (tc - (top - c)) / c               # strain at each fibre, εcu at the extreme fibre
            eps_s = 0.0035 * (tb_ - (top - c)) / c
            Fc = (_sigma_c(eps_c) * Ac).sum()
            sig_s = np.clip(eps_s * ES, -FYM, FYM) - np.where(eps_s > 0, _sigma_c(eps_s), 0.0)   # displaced concrete
            Fs = (sig_s * Ab).sum()
            M = (_sigma_c(eps_c) * Ac * tc).sum() + (sig_s * Ab * tb_).sum()
            return Fc + Fs - N, M
        flo, _ = force(lo)
        fhi, _ = force(hi)
        if flo * fhi > 0:
            res.append(0.0)
            continue
        for _ in range(60):
            mid = (lo + hi) / 2
            fm, _ = force(mid)
            if (fm > 0) == (fhi > 0):
                hi, fhi = mid, fm
            else:
                lo, flo = mid, fm
        _, M = force((lo + hi) / 2)
        res.append(abs(M) * 1000.0)                              # kNm
    return float(np.mean(res))


def web_geometry(poly: Polygon, axis: str) -> tuple[float, float, int]:
    """For shear in direction `axis`: total web width b_w (sum of the parts cut by a line across the direction near mid-length),
    the length d along the direction and the number of webs."""
    x0, y0, x1, y1 = poly.bounds
    if axis == "x":
        ext = x1 - x0
        cuts = [LineString([(x0 + f * ext, y0 - 1), (x0 + f * ext, y1 + 1)]) for f in (0.3, 0.5, 0.7)]
    else:
        ext = y1 - y0
        cuts = [LineString([(x0 - 1, y0 + f * ext), (x1 + 1, y0 + f * ext)]) for f in (0.3, 0.5, 0.7)]
    widths, webs = [], []
    for c in cuts:
        g = poly.intersection(c)
        parts = [g] if g.geom_type == "LineString" else list(getattr(g, "geoms", []))
        widths.append(sum(p.length for p in parts))
        webs.append(len(parts))
    return float(np.median(widths)), ext, int(np.median(webs))


def shear_capacity(poly: Polygon, axis: str, stirrup_d: int, stirrup_s_cm: float, web: list[dict] | None) -> float:
    bw, ext, nweb = web_geometry(poly, axis)
    d = max(ext - COVER, 0.1)
    z = 0.9 * d
    s = stirrup_s_cm / 100.0
    asw_s = 2 * nweb * bar_area(1, stirrup_d) / s                # two legs per web
    for w in web or []:
        hz = w.get("horiz")
        if hz:
            asw_s = max(asw_s, 2 * nweb * bar_area(1, hz[0]) / (hz[1] / 100.0))
    VRs = asw_s * z * FYM * 1.0 * 1000.0                        # kN, cot θ = 1
    nu1 = 0.6 * (1 - FCK / 250)
    VRmax = bw * z * nu1 * FCM / 2.0 * 1000.0                   # cot θ = 1
    return float(min(VRs, VRmax))


def beam_moments(b: dict, end: str | None = None) -> tuple[float, float]:
    """(M_R top-in-tension, M_R bottom-in-tension) of a beam [kNm] from its π (top) and κ (bottom) bars; at a support (end 'a' or
    'b') the extra top bars drawn over that support are added."""
    s = b.get("bars") or ""
    top = parse_bars(re.search(r"π([^,]*)", s).group(1)) if re.search(r"π([^,]*)", s) else []
    if end and (b.get("extra_top") or {}).get(end):
        for t in sorted(set(b["extra_top"][end])):                 # the same note written twice is one set of bars
            top += parse_bars(t)
    bot = parse_bars(re.search(r"κ([^,]*)", s).group(1)) if re.search(r"κ([^,]*)", s) else []
    d = b["h_cm"] / 100 - COVER
    At, Ab = sum(bar_area(n, dd) for n, dd in top), sum(bar_area(n, dd) for n, dd in bot)
    bw = b["b_cm"] / 100
    def m(As):
        x = As * FYM / (0.8 * bw * FCM) if bw > 0 else 0
        return As * FYM * (d - 0.4 * x) * 1000.0
    return m(At), m(Ab)


# ------------------------------------------------------------------------------------------------ the building
def _tributary(polys: list[Polygon], floor: Polygon) -> list[float]:
    pts = [p.centroid for p in polys]
    if len(pts) < 2:
        return [floor.area]
    vd = voronoi_diagram(MultiPoint(pts), envelope=floor.buffer(5).envelope)
    areas = [0.0] * len(pts)
    for cell in vd.geoms:
        a = cell.intersection(floor).area
        for i, p in enumerate(pts):
            if cell.contains(p):
                areas[i] += a
                break
    tot = sum(areas) or 1.0
    return [a / tot for a in areas]


def analyse(frame: dict[str, Any], struct: dict[str, Any] | None, floors: dict[str, Polygon], params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    d = (struct or {}).get("design", {})
    A = float(params.get("a_g") or d.get("a_g") or 0.24)
    q = float(d.get("q") or 3.0)
    T = max(d.get("Tx") or 0.4, d.get("Ty") or 0.4)
    T2 = d.get("T2") or 0.6
    rep = {s["idx"]: s for s in (struct or {}).get("storeys", [])}
    lv = frame["levels"]
    elements, storeys, joints, checks = [], [], [], []
    polys = {st: [Polygon(c["poly"]).buffer(0) for c in lv[st]["columns"]] for st in STOREYS if st in lv}
    # wall top elevation for the shear span of walls
    z0 = {"basement": 0.0, "ground": 3.0, "first": 6.05, "second": 9.10, "attic": 12.30}
    def wall_top(st: str, P: Polygon) -> float:
        top = z0[st] + HEIGHT[st]
        for s2 in STOREYS[STOREYS.index(st) + 1:]:
            if any(P.intersection(Q).area > 0.5 * P.area for Q in polys.get(s2, [])):
                top = z0[s2] + HEIGHT[s2]
            else:
                break
        return top
    # moment capacities first (needed by the joint check of the storey below)
    MR: dict[tuple[str, str], dict[str, float]] = {}
    for st in STOREYS:
        if st not in lv:
            continue
        R = rep.get(STATIC_IDX[st], {})
        W = float(R.get("W_kN") or 0.0)
        floor = floors.get(st) or Polygon()
        share = _tributary(polys[st], floor) if floor.area > 0 else [1 / len(polys[st])] * len(polys[st])
        for c, P, sh in zip(lv[st]["columns"], polys[st], share):
            bars = c.get("long_bars") or []
            lay = _bars_layout(P, bars, c.get("web"))
            N = W * sh
            mx = moment_capacity(P, lay, N, "x")
            my = moment_capacity(P, lay, N, "y")
            MR[(st, c["id"])] = {"x": mx, "y": my, "N": N}
    for st in STOREYS:
        if st not in lv:
            continue
        L = lv[st]
        H = HEIGHT[st]
        h_beam = 0.50
        R = rep.get(STATIC_IDX[st], {})
        Vd = {"x": float(R.get("Vx_kN") or 0.0), "y": float(R.get("Vy_kN") or 0.0)}
        tot = {"x": 0.0, "y": 0.0}
        shear_share = {"x": 0.0, "y": 0.0}
        nxt = STOREYS[STOREYS.index(st) + 1] if STOREYS.index(st) + 1 < len(STOREYS) else None
        for c, P in zip(L["columns"], polys[st]):
            x0, y0, x1, y1 = P.bounds
            ex, ey = x1 - x0, y1 - y0
            wall = max(ex, ey) >= 1.5 or P.area >= 0.40
            row = {"storey": st, "id": c["id"], "section": c.get("section"), "long": c.get("long"), "stirrups": f"Φ{c.get('stirrup_d')}/{c.get('stirrup_s_cm')}",
                   "type": "wall" if wall else "column", "area_m2": round(P.area, 3), "N_kN": round(MR[(st, c['id'])]["N"]), "centroid": [round(P.centroid.x, 2), round(P.centroid.y, 2)]}
            for ax in ("x", "y"):
                M = MR[(st, c["id"])][ax]
                VR = shear_capacity(P, ax, c.get("stirrup_d") or 8, c.get("stirrup_s_cm") or 15, c.get("web"))
                if wall:
                    Ls = max(H, 0.45 * (wall_top(st, P) - z0[st]))
                    Vf = M / Ls
                else:
                    # top end: limited by the beams of the joint when they are weaker (capacity design)
                    jr = _joint_ratio(st, c, P, ax, L["beams"], MR, polys, lv, nxt)
                    m_top = M * min(1.0, jr["ratio"]) if jr else M
                    Vf = (M + m_top) / max(H - h_beam, 1.0)
                    if jr:
                        joints.append({"storey": st, "id": c["id"], "dir": ax, **jr})
                V = min(Vf, VR)
                mode = "shear" if VR < Vf else "flexure"
                row[f"M_R_{ax}"] = round(M)
                row[f"V_flex_{ax}"] = round(Vf)
                row[f"V_R_{ax}"] = round(VR)
                row[f"V_{ax}"] = round(V)
                row[f"mode_{ax}"] = mode
                tot[ax] += V
                if mode == "shear":
                    shear_share[ax] += V
            elements.append(row)
        # RC retaining walls of the basement (25 cm, 2#Φ12/20) – shear walls along their length
        if st == "basement":
            for w in L.get("walls", []):
                (ax_, ay_), (bx_, by_) = w["a"], w["b"]
                ln = math.dist(w["a"], w["b"])
                if ln < 0.6:
                    continue
                ax = "x" if abs(bx_ - ax_) > abs(by_ - ay_) else "y"
                t = w.get("t_m") or 0.25
                VRs = 2 * bar_area(1, 12) / 0.20 * 0.9 * (ln - COVER) * FYM * 1000.0
                VRmax = t * 0.9 * ln * 0.6 * (1 - FCK / 250) * FCM / 2 * 1000.0
                tot[ax] += min(VRs, VRmax)
        row_s = {"key": st, "name_el": NAMES[st][0], "name_en": NAMES[st][1], "H_m": H, "W_kN": R.get("W_kN"), "Vd_x_kN": Vd["x"], "Vd_y_kN": Vd["y"],
                 "elements": sum(1 for e in elements if e["storey"] == st)}
        for ax in ("x", "y"):
            VR = tot[ax]
            f_sh = shear_share[ax] / VR if VR > 0 else 0.0
            mu = MU_FLEX * (1 - f_sh) + MU_SHEAR * f_sh
            Rm = mu if T >= T2 else math.sqrt(2 * mu - 1)
            a_y = A * VR / (q * Vd[ax]) if Vd[ax] > 0 else None
            row_s.update({f"V_R_{ax}_kN": round(VR), f"ratio_{ax}": round(VR / Vd[ax], 2) if Vd[ax] else None, f"shear_share_{ax}": round(f_sh, 2),
                          f"mu_{ax}": round(mu, 2), f"a_y_{ax}": round(a_y, 3) if a_y else None, f"a_c_{ax}": round(a_y * Rm, 3) if a_y else None})
        storeys.append(row_s)
    # governing storey and direction
    gov = min(((s, ax) for s in storeys for ax in ("x", "y") if s.get(f"a_y_{ax}")), key=lambda t: t[0][f"a_c_{t[1]}"])
    a_y = min(s[f"a_y_{ax}"] for s in storeys for ax in ("x", "y") if s.get(f"a_y_{ax}"))
    a_c = gov[0][f"a_c_{gov[1]}"]
    checks = detailing_checks(frame, elements, polys)
    jc = [j for j in joints if not j["exempt"]]
    weak = [j for j in jc if j["ratio"] < 1.3]
    return {"method": "rebar_model", "source": frame.get("source"), "source_en": frame.get("source_en"),
            "design": {"a_g": A, "q": q, "T": T, "T2": T2, "fcm": FCM, "fym": FYM, "concrete": frame["materials"]["concrete"], "steel": frame["materials"]["steel"]},
            "storeys": storeys, "elements": elements, "joints": {"checked": len(jc), "below_1_3": len(weak), "below_1_0": sum(1 for j in jc if j["ratio"] < 1.0),
                                                                  "worst": sorted(jc, key=lambda j: j["ratio"])[:12]},
            "checks": checks, "corrections": frame.get("corrections", []),
            "pga_g": {"design": A, "yield": round(a_y, 3), "collapse": round(a_c, 3)},
            "governing": {"storey": gov[0]["key"], "name_el": gov[0]["name_el"], "name_en": gov[0]["name_en"], "dir": gov[1]},
            "assumptions_el": [
                "Θέσεις, διατομές, οπλισμοί και συνδετήρες από τους ξυλότυπους Σ.01–Σ.06 (ανάγνωση των PDF)· τα σίδερα κάθε διατομής κατανέμονται ομοιόμορφα στην περίμετρο (γωνίες πρώτα), όπως στα σκαριφήματα.",
                f"Μέσες αντοχές υλικών: fcm = {FCM:.0f} MPa, fym = {FYM:.0f} MPa· αξονικά φορτία του σεισμικού συνδυασμού από τα βάρη ορόφων του τεύχους, με επιφάνειες επιρροής.",
                "Στον έλεγχο των κόμβων οι δοκοί έχουν τα συνεχή σίδερα (π, κ) και τα πρόσθετα σίδερα στήριξης που είναι σχεδιασμένα πάνω από κάθε στήριξη (π.χ. «2Φ16»).",
                "Η διαρροή ορόφου ορίζεται όταν η ελαστική τέμνουσα του ορόφου (από τις τέμνουσες σχεδιασμού του τεύχους) φτάσει την αντοχή του μηχανισμού· η οιονεί κατάρρευση με πλαστιμότητα μ = 3,5 (καμπτική αστοχία) ή 1,5 (διατμητική).",
                "Επίπεδο προμελέτης· δεν αντικαθιστά αποτίμηση ΚΑΝ.ΕΠΕ. με μη γραμμική ανάλυση."],
            "assumptions_en": [
                "Positions, sections, bars and stirrups from the formwork drawings S.01–S.06 (read from the PDFs); the bars of each section are spread evenly along its perimeter (corners first), as in the sketches.",
                f"Mean material strengths: fcm = {FCM:.0f} MPa, fym = {FYM:.0f} MPa; axial loads of the seismic combination from the storey weights of the report, by tributary area.",
                "In the joint check the beams have their continuous bars (π, κ) and the extra support bars drawn over each support (e.g. “2Φ16”).",
                "A storey yields when the elastic storey shear (from the design shears of the report) reaches the mechanism resistance; near-collapse with ductility μ = 3.5 (flexure) or 1.5 (shear).",
                "Screening level; it does not replace a ΚΑΝ.ΕΠΕ. non-linear assessment."]}


def _joint_ratio(st, c, P, ax, beams, MR, polys, lv, nxt) -> dict[str, Any] | None:
    """ΣM_Rc / ΣM_Rb at the top joint of column c (direction ax). Beams of the slab above the storey are those of the same sheet."""
    near = []
    for b in beams:
        dx, dy = b["b"][0] - b["a"][0], b["b"][1] - b["a"][1]
        bax = "x" if abs(dx) > abs(dy) else "y"
        if bax != ax:
            continue
        da, db = P.distance(Point(b["a"])), P.distance(Point(b["b"]))
        if min(da, db) < 0.15:
            mt, mb = beam_moments(b, "a" if da <= db else "b")
            near.append((b["id"], (mt + mb) / 2))
    if not near:
        return None
    Mb = sum(m for _, m in near)
    Mc = MR[(st, c["id"])][ax]
    above = None
    if nxt:
        for c2, P2 in zip(lv[nxt]["columns"], polys[nxt]):
            if P.intersection(P2).area > 0.5 * min(P.area, P2.area):
                above = c2
                Mc += MR[(nxt, c2["id"])][ax]
                break
    return {"beams": [i for i, _ in near], "sum_MRc": round(Mc), "sum_MRb": round(Mb), "ratio": round(Mc / Mb, 2) if Mb else 9.9,
            "column_above": above["id"] if above else None, "exempt": above is None}      # EC8 §4.4.2.3(6): top-storey joints are exempt


def detailing_checks(frame: dict[str, Any], elements: list[dict], polys) -> list[dict[str, Any]]:
    out = []
    lv = frame["levels"]
    for st in STOREYS:
        for c, P in zip(lv[st]["columns"], polys[st]):
            x0, y0, x1, y1 = P.bounds
            wall = max(x1 - x0, y1 - y0) >= 1.5 or P.area >= 0.40
            As = sum(bar_area(n, d) for n, d in c.get("long_bars") or [])
            rho = As / P.area * 100
            dmin = min((d for _, d in c.get("long_bars") or [(0, 20)]), default=20)
            s = (c.get("stirrup_s_cm") or 0) * 10
            b0 = min(x1 - x0, y1 - y0) * 1000 - 2 * 40
            if not wall and (rho < 1.0 or rho > 4.0):
                out.append({"storey": st, "id": c["id"], "kind": "rho_column", "value": round(rho, 2), "limit": "1–4 %",
                            "el": f"Ποσοστό οπλισμού {rho:.2f} % εκτός ορίων 1–4 % (EC8 §5.4.3.2.2)", "en": f"Reinforcement ratio {rho:.2f} % outside 1–4 % (EC8 §5.4.3.2.2)"})
            lim = min(b0 / 2, 175, 8 * dmin)
            if False and not wall and s > lim + 1:                  # EC8 stirrup spacing: not shown (the design follows EAK/EKOS 2000)
                out.append({"storey": st, "id": c["id"], "kind": "stirrup_spacing", "value": s, "limit": round(lim),
                            "el": f"Απόσταση συνδετήρων {s:.0f} mm > {lim:.0f} mm στην κρίσιμη περιοχή (EC8 §5.4.3.2.2)", "en": f"Stirrup spacing {s:.0f} mm > {lim:.0f} mm in the critical region (EC8 §5.4.3.2.2)"})
        for b in lv[st]["beams"]:
            mt, mb = beam_moments(b)
            s_ = b.get("stirrups") or ""
            m = re.search(r"Φ(\d+)/(\d+)", s_)
            if m:
                sd, ss = int(m.group(1)), int(m.group(2)) * 10
                lim = min(b["h_cm"] * 10 / 4, 24 * sd, 225)
                if ss > lim + 1:
                    out.append({"storey": st, "id": b["id"], "kind": "beam_stirrups", "value": ss, "limit": round(lim),
                                "el": f"Δοκός {b['id']}: συνδετήρες ανά {ss} mm > {lim:.0f} mm (EC8 §5.4.3.1.2)", "en": f"Beam {b['id']}: stirrups at {ss} mm > {lim:.0f} mm (EC8 §5.4.3.1.2)"})
    return out


def floors_from_demo() -> dict[str, Polygon]:
    from . import demo
    return {st: demo._poly(demo.G[st]) for st in STOREYS}
