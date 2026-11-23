"""Structural capacity from the static study  →  seismic resistance  →  magnitude (Richter) limits.

Pipeline
  1. ``parse_statics_pages``  reads the output of the *Statics 2023* program (the structural report of the permit): design parameters
     (zone, a_g, q, soil, materials), seismic weight and design shear per storey, the checks of every column/wall (flexure, shear),
     and the material take-off.  Greek text in that PDF is mis-encoded by the program (the glyphs are right, the Unicode is not), so
     only Latin letters, numbers and layout are relied upon.
  2. ``capacity``  turns the checks into capacity factors  λ = (resistance / design demand)  per storey and for the building:
        λ_y  first member yield          = 1 / max utilisation of the seismic combinations
        λ_u  plastic mechanism (collapse)= 1 / highest storey-mean utilisation   (redistribution between members)
        λ_v  shear (brittle) margin      = 1 / max shear utilisation (shear is designed with capacity-design forces)
     and then into peak ground accelerations (elastic-equivalent):
        A_y = a_g · λ_y · Ω / q          (yield)      A_c = a_g · λ_u · Ω · min(1, 1/u_v)   (collapse, ductility q is used up)
     where Ω is the ratio of expected to design strength (editable, 1.25).
  3. ``magnitude_limits``  inverts the attenuation law (Ambraseys et al. 1996) to the magnitude (surface-wave magnitude Ms, quoted
     as "Richter") that produces those accelerations at a given epicentral distance.
  4. ``estimate_from_model``  rough fall-back from the member sections of the 3D model (Hassan–Sozen type shear-stress index) for
     projects without a static study.

Everything is pre-design level (screening), not a ΚΑΝ.ΕΠΕ. assessment."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

DATA = Path(__file__).parent / "data"
G = 9.81

STATIC_NAMES = {2: ("Υπόγειο", "Basement"), 3: ("Ισόγειο", "Ground floor"), 4: ("Α΄ όροφος", "1st floor"), 5: ("Β΄ όροφος", "2nd floor"), 6: ("Σοφίτα", "Attic")}
STOREY_KEYS = {2: "basement", 3: "ground", 4: "first", 5: "second", 6: "attic"}


# ------------------------------------------------------------------------------------------------
# parsing of the Statics 2023 report
# ------------------------------------------------------------------------------------------------
def _f(x: str) -> float:
    return float(x.replace(",", "."))


def _first(pat: str, txt: str, cast=float, flags: int = 0):
    m = re.search(pat, txt, flags)
    if not m:
        return None
    try:
        return cast(m.group(1))
    except (ValueError, TypeError):
        return None


def parse_statics_pages(pages: list[str]) -> dict[str, Any]:
    """Parse the text pages of a Statics-2023 structural report. Returns a dict (see structural.json)."""
    txt = "\n".join(pages)
    if "Statics" not in txt or "dh=" not in txt:
        raise ValueError("Το αρχείο δεν φαίνεται τεύχος στατικών του προγράμματος Statics (δεν βρέθηκαν οι πίνακες ορόφων).")
    head = "\n".join(pages[:6])
    design = {
        "program": "Statics 2023" if re.search(r"Statics\s*(\d{4})", txt) is None else "Statics " + re.search(r"Statics\s*(\d{4})", txt).group(1),
        "zone": _first(r"Δπηθηλδπλόηεηαο\s*\.+\s*([IV]+)", head, str) or _first(r"Επηθηλδπλόηεηαο\s*\.+\s*([IV]+)", head, str),
        "a_g": _first(r"A\s*=\s*a\*g\s*\.+\s*([\d.]+)\*g", head),
        "gamma_I": _first(r"γI\s*\.+\s*([\d.]+)", head),
        "q": _first(r"\bq\s*\.{3,}\s*([\d.]+)", head),
        "soil": _first(r"Καηεγνξία εδάθνπο\s*\.+\s*([A-Z])", head, str),
        "T1": _first(r"\S1=([\d.]+),\s*\S2=", head), "T2": _first(r"\S1=[\d.]+,\s*\S2=([\d.]+)", head),
        "theta": _first(r"ζεκειίσζεο ζ\s*\.+\s*([\d.]+)", head),
        "Tx": _first(r"Tx\s*=\s*([\d.]+)\s*sec", head), "Ty": _first(r"Ty\s*=\s*([\d.]+)\s*sec", head),
        "Rd_x": _first(r"Rdx\(Tx\)\s*=\s*([\d.]+)", head), "Rd_y": _first(r"Rdy\(Ty\)\s*=\s*([\d.]+)", head),
        "concrete": _first(r"\b(C\d{2}/\d{2})\b", head, str), "steel": _first(r"\b(B500[A-C])\b", head, str),
        "E_concrete_GPa": _first(r"([\d.]+)\s*GPa", head),
        "psi2_residential": _first(r"ς2\s*=\s*([\d.]+)", head),
    }
    design["a_g"] = design["a_g"] if design["a_g"] else None
    # storeys (design shear and seismic weight above each level)
    storeys = []
    for m in re.finditer(r"\S+\s+(\d+)\s+dh=([\d.]+)m\s+q=([\d.]+)\s+\S{1,2}x=([\d.]+)mm\s+\S{1,2}y=([\d.]+)mm\s+Vx=(\d+)\s+Vy=(\d+)\s+W=(\d+)", txt):
        idx = int(m.group(1))
        th = re.search(r"\S{1,2}x=([\d.]+)\s*<\s*0\.10\s+\S{1,2}y=([\d.]+)", txt[m.end(): m.end() + 200])
        storeys.append({"idx": idx, "dh_m": _f(m.group(2)), "q": _f(m.group(3)), "drift_x_mm": _f(m.group(4)), "drift_y_mm": _f(m.group(5)),
                        "Vx_kN": float(m.group(6)), "Vy_kN": float(m.group(7)), "W_kN": float(m.group(8)),
                        "theta_x": _f(th.group(1)) if th else None, "theta_y": _f(th.group(2)) if th else None})
    if not storeys:
        raise ValueError("Δεν βρέθηκε ο πίνακας ελέγχου θ (σεισμικές τέμνουσες ανά όροφο).")
    # share of the storey shear carried by walls (ΕΑΚ 4.1.4.2)
    walls = []
    for m in re.finditer(r"^\s*(\d)\s+x-x\s+(-?\d+)\s+(-?\d+)\s+(-?[\d.]+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s*\n\s+y-y\s+(-?\d+)\s+(-?\d+)\s+(-?[\d.]+)", txt, re.M):
        walls.append({"idx": int(m.group(1)), "Vt_x": float(m.group(2)), "Vo_x": float(m.group(3)), "nv_x": float(m.group(4)),
                      "Vt_y": float(m.group(5)), "Vo_y": float(m.group(6)), "nv_y": float(m.group(7))})
    # material take-off per storey
    quant = []
    qi = txt.find("Fe   Beton   Fe  Beton")
    if qi > 0:
        for m in re.finditer(r"^\s*(\d)\s+((?:-?[\d.]+\s+){12}-?[\d.]+)\s*$", txt[qi: qi + 2500], re.M):
            v = [float(x) for x in m.group(2).split()]
            quant.append({"idx": int(m.group(1)), "beams_fe_t": v[0], "beams_concrete_m3": v[1], "slabs_fe_t": v[2], "slabs_concrete_m3": v[3], "columns_fe_t": v[5], "columns_concrete_m3": v[6],
                          "footings_fe_t": v[7], "footings_concrete_m3": v[8], "area_m2": v[9], "formwork_m2": v[10], "fe_t": v[11], "concrete_m3": v[12]})
    steel_ratio = _first(r"\S+\s+\S+\s+=\s*([\d.]+)\s+\S+/\S+", txt[qi: qi + 4000] if qi > 0 else "")
    # vertical members (columns/walls): one block per member and storey
    blocks = []
    pat = re.compile(r"(?:ΤΠΟ.ΣΤΛΩΜΑ|ΥΠΟΣΤΥΛΩΜΑ)\s+(\d+)")
    marks = [(m.start(), int(m.group(1))) for m in pat.finditer(txt)] + [(len(txt), 0)]
    seen: dict[int, int] = {}
    for (a, k), (b, _) in zip(marks, marks[1:]):
        blk = txt[a:b]
        Hs = [float(x) for x in re.findall(r"H=([\d.]+)m", blk)]
        flex = []
        for line in blk.split("\n"):
            m = re.match(r"\s*(?:Pmin|Pmax|Mxmin|Mxmax|Mymin|Mymax)?\s*(-?\d+):\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+([\d.]+)\s*$", line)
            if m:
                flex.append((int(m.group(1)), float(m.group(7))))
        shear = [(int(v), abs(int(s))) for v, s in re.findall(r"Vrd3=(\d+)\s+Vsd=\s*(-?\d+)", blk)]
        secs = re.findall(r"Τ\d+\s+Ο\d+\s+(\d+)/(\d+)\s+H=", blk)
        gcase = re.search(r"^\s*G\s+(-?\d+)\s+(-?\d+)", blk, re.M)
        qcase = re.search(r"^\s*Q\s+(-?\d+)\s+(-?\d+)", blk, re.M)
        ng = (abs(float(gcase.group(1))) + abs(float(gcase.group(2)))) / 2 if gcase else None
        nq = (abs(float(qcase.group(1))) + abs(float(qcase.group(2)))) / 2 if qcase else None
        seen[k] = seen.get(k, 0) + 1
        u_seis = max([r for c, r in flex if abs(c) != 1] or [0.0])
        u_grav = max([r for c, r in flex if abs(c) == 1] or [0.0])
        u_sh = max([s / v for v, s in shear if v > 0] or [0.0])
        As = re.findall(r"As_tot=([\d.]+)", blk)
        blocks.append({"member": k, "order": seen[k], "H_m": Hs[0] if Hs else None, "rects": [f"{w}/{d}" for w, d in secs], "u_flex_seismic": round(u_seis, 3), "u_flex_gravity": round(u_grav, 3),
                       "u_shear": round(u_sh, 3), "As_tot_cm2": float(As[0]) if As else None, "N_G_kN": ng, "N_Q_kN": nq})
    if not blocks:
        raise ValueError("Δεν βρέθηκαν έλεγχοι υποστυλωμάτων/τοιχωμάτων στο τεύχος.")
    return {"design": design, "storeys": storeys, "walls": walls, "quantities": quant, "members": blocks, "steel_kg_per_m3": steel_ratio,
            "report_pages": len(pages)}


def parse_statics_pdf(path: str | Path) -> dict[str, Any]:
    import fitz  # PyMuPDF
    doc = fitz.open(str(path))
    try:
        return parse_statics_pages([doc[i].get_text() for i in range(doc.page_count)])
    finally:
        doc.close()


def looks_like_statics(path: str | Path) -> bool:
    """True when the PDF is a Statics-program structural report (checks the first pages for the program name and the storey table)."""
    import fitz
    try:
        doc = fitz.open(str(path))
    except Exception:
        return False
    try:
        n = min(doc.page_count, 12)
        head = "\n".join(doc[i].get_text() for i in range(n))
        return bool(re.search(r"Statics\s*\d{4}", head)) or ("dh=" in head and "Vx=" in head)
    finally:
        doc.close()


def load_demo() -> dict[str, Any] | None:
    import json
    p = DATA / "structural.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ------------------------------------------------------------------------------------------------
# spectrum and attenuation
# ------------------------------------------------------------------------------------------------
def phi(T: float, T1: float = 0.15, T2: float = 0.60, b0: float = 2.5) -> float:
    if T <= T1:
        return 1.0 + (b0 - 1.0) * T / T1
    if T <= T2:
        return b0
    return b0 * (T2 / T) ** (2.0 / 3.0)


def ms_for_pga(pga_g: float, d_km: float, soil: str = "B", z: float = 0.0) -> float:
    """Inverse of Ambraseys et al. (1996): surface-wave magnitude giving the median (z=0) or z-sigma PGA at distance d."""
    sa = 1.0 if soil == "B" else 0.0
    ss = 1.0 if soil in ("C", "D", "E") else 0.0
    r = math.sqrt(d_km ** 2 + 3.5 ** 2)
    return (math.log10(max(pga_g, 1e-6)) - 0.25 * z + 1.48 + 0.922 * math.log10(r) - 0.117 * sa - 0.124 * ss) / 0.266


def magnitude_limits(pga_states: dict[str, float], soil: str = "B", distances: tuple[float, ...] = (5, 10, 20, 30, 50, 100)) -> list[dict[str, Any]]:
    """Ms (Richter-type) that brings the building to each state, per epicentral distance. ±1σ gives the band."""
    rows = []
    for d in distances:
        row = {"distance_km": d}
        for name, a in pga_states.items():
            row[name] = round(ms_for_pga(a, d, soil), 2)
            row[name + "_lo"] = round(ms_for_pga(a, d, soil, 1.0), 2)       # PGA 1σ above the median: smaller quake suffices
            row[name + "_hi"] = round(ms_for_pga(a, d, soil, -1.0), 2)
        row["in_range"] = all(4.0 <= row[n] <= 7.5 for n in pga_states)
        rows.append(row)
    return rows


# ------------------------------------------------------------------------------------------------
# capacity from the static study
# ------------------------------------------------------------------------------------------------
def _storey_groups(struct: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    """Assign every member block to the storeys with the same height (3.05 m is shared by ground and first floor)."""
    out: dict[int, list[dict[str, Any]]] = {s["idx"]: [] for s in struct["storeys"]}
    for b in struct["members"]:
        H = b.get("H_m")
        if H is None:
            continue
        cand = [s["idx"] for s in struct["storeys"] if abs(s["dh_m"] - H) < 0.011]
        for i in cand:
            out[i].append(b)
    return out


def capacity(struct: dict[str, Any], project: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    d = struct["design"]
    omega = float(params.get("material_factor", 1.25))
    A = float(params.get("a_g") or d.get("a_g") or 0.24)
    q = float(d.get("q") or 3.0)
    soil = str(params.get("soil") or d.get("soil") or "B")
    T1, T2 = d.get("T1") or 0.15, d.get("T2") or 0.60
    Tx, Ty = d.get("Tx") or 0.4, d.get("Ty") or 0.4
    groups = _storey_groups(struct)
    walls = {w["idx"]: w for w in struct.get("walls", [])}
    rows = []
    u_flex_all, u_shear_all, u_mean_by_storey = [], [], {}
    for s in struct["storeys"]:
        bl = groups.get(s["idx"], [])
        uf = [b["u_flex_seismic"] for b in bl]
        us = [b["u_shear"] for b in bl]
        if not bl:
            continue
        mean_u = float(np.mean(uf))
        u_mean_by_storey[s["idx"]] = mean_u
        u_flex_all += uf
        u_shear_all += us
        w = walls.get(s["idx"], {})
        rows.append({"idx": s["idx"], "key": STOREY_KEYS.get(s["idx"]), "name_el": STATIC_NAMES.get(s["idx"], (f"Στάθμη {s['idx']}",) * 2)[0], "name_en": STATIC_NAMES.get(s["idx"], (f"Level {s['idx']}",) * 2)[1],
                     "dh_m": s["dh_m"], "W_kN": s["W_kN"], "Vx_kN": s["Vx_kN"], "Vy_kN": s["Vy_kN"], "members": len(bl), "u_flex_max": round(max(uf), 2), "u_flex_mean": round(mean_u, 2),
                     "u_shear_max": round(max(us), 2), "lambda_u": round(1 / mean_u, 2) if mean_u > 0 else None, "wall_share_x": w.get("nv_x"), "wall_share_y": w.get("nv_y"),
                     "drift_x_mm": s.get("drift_x_mm"), "drift_y_mm": s.get("drift_y_mm"), "theta_x": s.get("theta_x"), "theta_y": s.get("theta_y")})
    if not rows:
        raise ValueError("Δεν υπάρχουν έλεγχοι μελών για υπολογισμό αντοχής.")
    u_max = max(u_flex_all)
    lam_y = 1.0 / max(u_max, 1e-3)
    u_eff = max(u_mean_by_storey.values())
    lam_u = 1.0 / max(u_eff, 1e-3)
    u_v = max(u_shear_all) if u_shear_all else 0.0
    shear_gov = u_v > 1.0
    mu_cap = float(params.get("ductility_capacity", q))            # available displacement ductility = the behaviour factor used in design
    # elastic-equivalent PGA at the two states, with the same R–μ relation as the demand/capacity indicator of the hazards module
    def r_of_mu(mu: float, T: float) -> float:
        return mu if T >= T2 else math.sqrt(2.0 * mu - 1.0)         # equal displacement (T ≥ T2) / equal energy (short period)
    R_c = min(r_of_mu(mu_cap, Tx), r_of_mu(mu_cap, Ty))
    A_y = A * lam_y * omega / q
    A_c = A * lam_u * omega * R_c / q * (1.0 / u_v if shear_gov else 1.0)
    A_c = max(A_c, A_y * 1.05)
    # damage-state medians (D1..D5): yield → ductility exhausted, interpolated between the two capacities
    med = [A_y + (A_c - A_y) * f for f in (0.0, 0.25, 0.6, 1.0, 1.5)]
    W = max(s["W_kN"] for s in struct["storeys"])
    Vd = max(s["Vx_kN"] for s in struct["storeys"])
    Rd = (d.get("Rd_x") or A * G * phi(Tx, T1, T2) / q)
    states = {"yield": A_y, "collapse": A_c}
    limits = magnitude_limits(states, soil)
    weakest = min(rows, key=lambda r: r["lambda_u"] or 99)
    return {
        "method": "static_report", "program": d.get("program"), "source_pages": struct.get("report_pages"),
        "design": {"zone": d.get("zone"), "a_g": A, "gamma_I": d.get("gamma_I"), "q": q, "soil": soil, "T1": T1, "T2": T2, "Tx": Tx, "Ty": Ty, "Rd_ms2": round(Rd, 2),
                   "concrete": d.get("concrete"), "steel": d.get("steel")},
        "storeys": rows,
        "base": {"W_kN": W, "Vd_kN": Vd, "Cd": round(Vd / W, 3), "Cy": round(Vd / W * lam_y * omega, 3), "Cu": round(Vd / W * lam_u * omega, 3),
                 "Vy_kN": round(Vd * lam_y * omega), "Vu_kN": round(Vd * lam_u * omega)},
        "ductility": {"mu_capacity": mu_cap, "R_collapse": round(R_c, 2)},
        "lambda": {"yield": round(lam_y, 2), "mechanism": round(lam_u, 2), "shear_margin": round(1 / u_v, 2) if u_v > 0 else None},
        "utilisation": {"flex_max": round(u_max, 2), "flex_storey_mean_max": round(u_eff, 2), "shear_max": round(u_v, 2), "shear_governs": shear_gov},
        "material_factor": omega, "overstrength_total": round(lam_u * omega, 2),
        "pga_g": {"design": round(A, 3), "yield": round(A_y, 3), "collapse": round(A_c, 3)},
        "pga_over_design": {"yield": round(A_y / A, 2), "collapse": round(A_c / A, 2)},
        "median_pga_g": [round(x, 3) for x in med],
        "limits": limits, "weakest_storey": weakest["key"], "weakest_storey_name_el": weakest["name_el"], "weakest_storey_name_en": weakest["name_en"],
        "members": len(struct["members"]),
        "quantities": struct.get("quantities"),
        "assumptions_el": [
            "Οι αντοχές προέρχονται από τους ελέγχους του τεύχους στατικών (κάμψη, διάτμηση) στον σεισμό σχεδιασμού A=%.2fg, q=%.1f." % (A, q),
            "Πρώτη διαρροή: το πιο φορτισμένο μέλος φτάνει στην αντοχή του. «Κατάρρευση» = εξάντληση πλαστιμότητας (μ=q) με την (μέση) χρησιμοποίηση του πιο ευάλωτου ορόφου, δηλαδή οιονεί κατάρρευση (βλάβη D4)· η πλήρης κατάρρευση (D5) έπεται σε ελαφρώς μεγαλύτερη διέγερση.",
            "Αναλογία αναμενόμενης/υπολογιστικής αντοχής υλικών Ω=%.2f (επεξεργάσιμη). Δεν υπολογίζεται η συμβολή τοιχοπληρώσεων και πλακών, άρα η εκτίμηση είναι συντηρητική." % omega,
            "Το μέγεθος (Ρίχτερ, Ms) προκύπτει με αντιστροφή του νόμου απόσβεσης Ambraseys et al. (1996), μέση τιμή και ±1σ· ισχύει για Ms 4–7,5 και αποστάσεις έως ~200 km.",
            "Επίπεδο προμελέτης· δεν αντικαθιστά αποτίμηση ΚΑΝ.ΕΠΕ. (μη γραμμική ανάλυση/έλεγχος επιτόπου).",
        ],
        "assumptions_en": [
            "Resistances come from the member checks of the static report (flexure, shear) at the design earthquake A=%.2fg, q=%.1f." % (A, q),
            "First yield: the most stressed member reaches its resistance. \"Collapse\" = ductility exhausted (μ=q) with the (mean) utilisation of the weakest storey, i.e. near-collapse (damage D4); full collapse (D5) follows at a somewhat stronger shaking.",
            "Expected-to-design material strength ratio Ω=%.2f (editable). The contribution of infills and slabs is ignored, so the estimate is conservative." % omega,
            "Magnitude (Richter, Ms) is the inverse of the Ambraseys et al. (1996) attenuation law, median and ±1σ; valid for Ms 4–7.5 and distances up to ~200 km.",
            "Pre-design level; it does not replace a ΚΑΝ.ΕΠΕ. assessment (non-linear analysis / on-site checks).",
        ],
    }


# ------------------------------------------------------------------------------------------------
# fall-back: from the sections of the model
# ------------------------------------------------------------------------------------------------
def estimate_from_model(project: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Hassan–Sozen type index for projects without a static study: collapse when the mean shear stress of the vertical members
    reaches τ_col / τ_wall. Rough (factor 2 in resistance), flagged as such in the result."""
    params = params or {}
    st = project["meta"].get("structure", {})
    A = float(params.get("a_g") or st.get("a_g") or 0.24)
    q = float(st.get("q") or 3.0)
    soil = str(params.get("soil") or st.get("soil") or "B")
    tau_c, tau_w = float(params.get("tau_col_MPa", 0.5)), float(params.get("tau_wall_MPa", 1.0))
    above = sorted([s for s in project["storeys"] if s["elevation_m"] >= -0.01], key=lambda s: s["elevation_m"])
    if not above:
        raise ValueError("Δεν βρέθηκαν όροφοι πάνω από το έδαφος.")
    base = above[0]
    Ac = Aw = 0.0
    for e in project["elements"]:
        if e.get("storey") != base["id"]:
            continue
        h = e["qty"].get("height_m") or base["height_m"]
        if e["kind"] == "column":
            Ac += e["qty"].get("volume_m3", 0.0) / max(h, 0.3)
        elif e["kind"] == "wall" and e.get("material") == "concrete" and not (e.get("props") or {}).get("retaining"):
            Aw += e["qty"].get("volume_m3", 0.0) / max(h, 0.3)
    from . import hazards
    areas = hazards.storey_areas(project)
    gfa = sum(a for sid, a in areas.items() if any(sid == s["id"] for s in above))
    W = max(gfa * 11.0, 1.0)                                              # ≈ 11 kN/m² per level (frame + finishes + 30 % live)
    Vu = (tau_c * 1000.0 * Ac + tau_w * 1000.0 * Aw)                      # kN (MPa → kN/m²)
    Cu = Vu / W
    phx = phi(float(st.get("Tx", 0.4)), float(st.get("T1", 0.15)), float(st.get("T2", 0.60)), float(st.get("beta0", 2.5)))
    R_c = q if float(st.get("Tx", 0.4)) >= float(st.get("T2", 0.60)) else math.sqrt(2.0 * q - 1.0)
    A_c = Cu * R_c / phx                                                  # ductility q used up; τ values are expected strengths
    A_y = max(Cu * 0.7 / phx, 0.02)                                       # first yield ≈ 0.7 of the collapse base shear, elastic (no ductility)
    A_c = max(A_c, A_y * 1.05)
    med = [A_y, A_y + 0.25 * (A_c - A_y), A_y + 0.60 * (A_c - A_y), A_c, A_c * 1.35]
    states = {"yield": A_y, "collapse": A_c}
    return {"method": "sections", "design": {"a_g": A, "q": q, "soil": soil}, "base": {"W_kN": round(W), "Vu_kN": round(Vu), "Cu": round(Cu, 3), "A_columns_m2": round(Ac, 2), "A_walls_m2": round(Aw, 2)},
            "pga_g": {"design": round(A, 3), "yield": round(A_y, 3), "collapse": round(A_c, 3)}, "pga_over_design": {"yield": round(A_y / A, 2), "collapse": round(A_c / A, 2)},
            "median_pga_g": [round(x, 3) for x in med], "limits": magnitude_limits(states, soil), "storeys": [], "overstrength_total": None,
            "assumptions_el": ["Χωρίς τεύχος στατικών: χονδρική εκτίμηση από τις διατομές υποστυλωμάτων/τοιχωμάτων του ισογείου (δείκτης διατμητικής τάσης τύπου Hassan–Sozen, τ_υποστ=%.1f MPa, τ_τοιχ=%.1f MPa)· ακρίβεια ±2×." % (tau_c, tau_w),
                               "Ανεβάστε το τεύχος στατικών (Statics) ή συμπληρώστε τα στοιχεία για ακριβέστερο αποτέλεσμα."],
            "assumptions_en": ["No static study: rough estimate from the column/wall sections of the ground storey (Hassan–Sozen type shear-stress index, τ_col=%.1f MPa, τ_wall=%.1f MPa); accuracy ±2×." % (tau_c, tau_w),
                               "Upload the static report (Statics) or fill in the data for a more accurate result."]}


_RB_CACHE: dict[str, Any] = {}


def rebar_capacity(project: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Resistance from the real reinforcement of the formwork drawings (frame_capacity) – the Kifisia project."""
    from . import frame_capacity as fc
    if project.get("id") != "demo-kifisia" or project["meta"].get("frame_source") == "off":
        return None
    fr = fc.load_frame()
    if not fr:
        return None
    p2 = {"a_g": (params or {}).get("a_g")} if (params or {}).get("a_g") else {}
    key = json.dumps(p2, sort_keys=True)                          # only the design acceleration changes the resistance
    if key not in _RB_CACHE:
        _RB_CACHE.clear()
        _RB_CACHE[key] = fc.analyse(fr, project["meta"].get("structural"), fc.floors_from_demo(), p2)
    return _RB_CACHE[key]


def for_project(project: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Capacity of the project: from the real reinforcement of the formwork drawings if available, else from its static study
    (member utilisation), otherwise from the model sections."""
    st = project["meta"].get("structural")
    base = None
    if st:
        try:
            base = capacity(st, project, params)
        except ValueError:
            base = None
    rb = rebar_capacity(project, params)
    if rb and base:
        A = base["design"]["a_g"]
        A_y, A_c = rb["pga_g"]["yield"], rb["pga_g"]["collapse"]
        med = [A_y + (A_c - A_y) * f for f in (0.0, 0.25, 0.6, 1.0, 1.5)]
        g = rb["governing"]
        out = dict(base)
        out.update({"method": "rebar_model", "report_based": {"pga_g": base["pga_g"], "pga_over_design": base["pga_over_design"]},
                    "pga_g": {"design": A, "yield": A_y, "collapse": A_c}, "pga_over_design": {"yield": round(A_y / A, 2), "collapse": round(A_c / A, 2)},
                    "median_pga_g": [round(x, 3) for x in med], "limits": magnitude_limits({"yield": A_y, "collapse": A_c}, base["design"]["soil"]),
                    "weakest_storey": g["storey"], "weakest_storey_name_el": f"{g['name_el']} ({g['dir'].upper()})", "weakest_storey_name_en": f"{g['name_en']} ({g['dir'].upper()})",
                    "overstrength_total": round(min(s[f"ratio_{ax}"] for s in rb["storeys"] for ax in ("x", "y") if s.get(f"ratio_{ax}")), 2),
                    "rebar": rb, "assumptions_el": rb["assumptions_el"], "assumptions_en": rb["assumptions_en"]})
        return out
    if base:
        return base
    return estimate_from_model(project, params)
