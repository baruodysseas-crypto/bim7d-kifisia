"""PDF study generator (ReportLab + matplotlib). Greek / English. Everything in the PDF comes from the same engines as the UI."""
from __future__ import annotations

import io
import math
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)

from . import hazards as hz_mod
from . import ingest, store

FONTS = Path(__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("DJ", str(FONTS / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DJB", str(FONTS / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("DJ", normal="DJ", bold="DJB", italic="DJ", boldItalic="DJB")

# validated reference palette (categorical order, light surface) + ink
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#d9d8d4"
NAVY, ZEBRA = "#184f95", "#f4f6f9"
BAL_COL = ["#1baf7a", "#eda100", "#eb6834", "#e34948", "#a32c2c", "#6b1c1c"]

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": "#ececea", "grid.linewidth": 0.6, "axes.axisbelow": True,
                     "legend.frameon": False, "figure.dpi": 100, "savefig.dpi": 170, "axes.titlesize": 9, "axes.titleweight": "bold", "axes.titlecolor": INK})


def fmt(x: float | None, d: int = 0, lang: str = "el") -> str:
    if x is None:
        return "–"
    s = f"{x:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") if lang == "el" else s


def eur(x: float | None, lang: str = "el", d: int = 0) -> str:
    return "–" if x is None else f"{fmt(x, d, lang)} €"


def _png(fig, w_mm: float) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    from PIL import Image as PI
    iw, ih = PI.open(buf).size
    buf.seek(0)
    w = w_mm * mm
    return Image(buf, width=w, height=w * ih / iw)


# ------------------------------------------------------------------------------------------------
class Doc:
    def __init__(self, project: dict[str, Any], lang: str, author: str):
        self.p, self.lang, self.author = project, lang, author
        self.buf = io.BytesIO()
        self.W, self.H = A4
        self.title = project.get("name") if lang == "el" else project.get("name_en") or project.get("name")
        st = {}
        st["body"] = ParagraphStyle("body", fontName="DJ", fontSize=8.8, leading=12.2, textColor=colors.HexColor(INK), spaceAfter=4)
        st["small"] = ParagraphStyle("small", parent=st["body"], fontSize=7.4, leading=10, textColor=colors.HexColor(INK2))
        st["h1"] = ParagraphStyle("h1", fontName="DJB", fontSize=15, leading=19, textColor=colors.HexColor(NAVY), spaceBefore=4, spaceAfter=8)
        st["h2"] = ParagraphStyle("h2", fontName="DJB", fontSize=10.5, leading=14, textColor=colors.HexColor(INK), spaceBefore=8, spaceAfter=4)
        st["cell"] = ParagraphStyle("cell", fontName="DJ", fontSize=7.6, leading=9.6, textColor=colors.HexColor(INK))
        st["cellb"] = ParagraphStyle("cellb", parent=st["cell"], fontName="DJB")
        st["cellh"] = ParagraphStyle("cellh", parent=st["cell"], fontName="DJB", textColor=colors.white)
        st["cap"] = ParagraphStyle("cap", parent=st["small"], spaceBefore=1, spaceAfter=6)
        st["cover_t"] = ParagraphStyle("cover_t", fontName="DJB", fontSize=24, leading=30, textColor=colors.HexColor(NAVY), spaceAfter=8)
        st["cover_s"] = ParagraphStyle("cover_s", fontName="DJ", fontSize=12, leading=16, textColor=colors.HexColor(INK2), spaceAfter=4)
        st["kpi_v"] = ParagraphStyle("kpi_v", fontName="DJB", fontSize=13, leading=16, textColor=colors.HexColor(NAVY), alignment=TA_CENTER)
        st["kpi_l"] = ParagraphStyle("kpi_l", fontName="DJ", fontSize=7, leading=9, textColor=colors.HexColor(INK2), alignment=TA_CENTER)
        st["warn"] = ParagraphStyle("warn", parent=st["small"], backColor=colors.HexColor("#fff6e0"), borderColor=colors.HexColor("#eda100"), borderWidth=0.6, borderPadding=5, leading=10)
        self.st = st
        self.story: list[Any] = []
        self.sec_no = 0

    def T(self, el: str, en: str) -> str:
        return el if self.lang == "el" else en

    def P(self, text: str, style: str = "body") -> None:
        self.story.append(Paragraph(text, self.st[style]))

    def H1(self, el: str, en: str) -> None:
        self.sec_no += 1
        self.story.append(Paragraph(f"{self.sec_no}. {self.T(el, en)}", self.st["h1"]))

    def H2(self, el: str, en: str) -> None:
        self.story.append(Paragraph(self.T(el, en), self.st["h2"]))

    def img(self, fig, w_mm: float = 170, cap: tuple[str, str] | None = None) -> None:
        items: list[Any] = [_png(fig, w_mm)]
        if cap:
            items.append(Paragraph(self.T(*cap), self.st["cap"]))
        self.story.append(KeepTogether(items))

    def table(self, header: list[str], rows: list[list[Any]], widths_mm: list[float], align_right_from: int = 1, total_last: bool = False, repeat: int = 1) -> None:
        st = self.st
        data = [[Paragraph(str(h), st["cellh"]) for h in header]]
        for r in rows:
            data.append([c if not isinstance(c, str) else Paragraph(c, st["cell"]) for c in r])
        t = Table(data, colWidths=[w * mm for w in widths_mm], repeatRows=repeat)
        sty = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor(GRID)),
               ("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
        for i in range(1, len(data)):
            if i % 2 == 0:
                sty.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor(ZEBRA)))
        if total_last and len(data) > 2:
            sty.append(("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor(INK)))
        t.setStyle(TableStyle(sty))
        # right-align numeric columns via paragraph style is awkward: wrap strings starting at column align_right_from
        for ri in range(1, len(data)):
            for ci in range(align_right_from, len(header)):
                cell = data[ri][ci]
                if isinstance(cell, Paragraph):
                    data[ri][ci] = Paragraph(cell.text, ParagraphStyle("r", parent=st["cellb"] if (total_last and ri == len(data) - 1) else st["cell"], alignment=2))
        t = Table(data, colWidths=[w * mm for w in widths_mm], repeatRows=repeat)
        t.setStyle(TableStyle(sty))
        self.story.append(t)
        self.story.append(Spacer(1, 4))

    def kpis(self, items: list[tuple[str, str]]) -> None:
        cells = [[Paragraph(v, self.st["kpi_v"]), ] for v, _ in items]
        row1 = [Paragraph(v, self.st["kpi_v"]) for v, _ in items]
        row2 = [Paragraph(l, self.st["kpi_l"]) for _, l in items]
        n = len(items)
        t = Table([row1, row2], colWidths=[170 * mm / n] * n)
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor(GRID)), ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor(GRID)), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                               ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 1), (-1, 1), 6)]))
        self.story.append(t)
        self.story.append(Spacer(1, 6))

    def _page(self, canv, doc) -> None:
        canv.saveState()
        canv.setFont("DJ", 7)
        canv.setFillColor(colors.HexColor(INK2))
        if doc.page > 1:
            canv.drawString(20 * mm, self.H - 12 * mm, (self.title or "")[:90])
            canv.drawRightString(self.W - 20 * mm, self.H - 12 * mm, self.T("Μελέτη 7D-BIM και κύκλου ζωής", "7D-BIM and life-cycle study"))
            canv.setStrokeColor(colors.HexColor(GRID))
            canv.line(20 * mm, self.H - 14 * mm, self.W - 20 * mm, self.H - 14 * mm)
            canv.drawString(20 * mm, 10 * mm, self.T("Ενδεικτική μελέτη επιπέδου προμελέτης – δεν υποκαθιστά μελέτες ΚΕΝΑΚ/ΕΑΚ/ΠΥΣ.", "Screening-level study – does not replace KENAK/EAK/fire-code studies."))
            canv.drawRightString(self.W - 20 * mm, 10 * mm, f"{doc.page}")
        canv.restoreState()

    def build(self) -> bytes:
        doc = BaseDocTemplate(self.buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=20 * mm, bottomMargin=18 * mm,
                              title=self.title or "7D-BIM", author=self.author or "7D-BIM tool")
        fr = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
        doc.addPageTemplates([PageTemplate(id="p", frames=[fr], onPage=self._page)])
        doc.build(self.story)
        return self.buf.getvalue()


# ------------------------------------------------------------------------------------------------
def _model_view(project: dict[str, Any]):
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    els = [e for e in project["elements"] if e["kind"] not in ("vegetation",)]
    fig = plt.figure(figsize=(7.2, 3.9))
    ax = fig.add_subplot(111, projection="3d")
    polys, cols = [], []
    order = {"site": 0, "footing": 1, "slab": 2, "roof": 2, "wall": 3, "column": 4, "beam": 4, "window": 5, "railing": 5, "pergola": 5, "fence": 5, "stair": 4, "door": 5}
    for e in sorted(els, key=lambda e: order.get(e["kind"], 3)):
        x0, y0, z0, x1, y1, z1 = e["bbox"]
        if e["kind"] == "site":
            continue
        v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]])
        faces = [[0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4], [2, 3, 7, 6], [1, 2, 6, 5], [0, 3, 7, 4]]
        for f in faces:
            polys.append(v[f])
            cols.append((e.get("props") or {}).get("color") or ingest.KIND_COLORS.get(e["kind"], "#c0c0c0"))
    pc = Poly3DCollection(polys, facecolors=cols, edgecolors="#6b6b6b", linewidths=0.15, alpha=0.9)
    ax.add_collection3d(pc)
    allb = np.array([e["bbox"] for e in els if e["kind"] != "site"])
    mn, mx = allb[:, :3].min(0), allb[:, 3:].max(0)
    ax.set_xlim(mn[0], mx[0]); ax.set_ylim(mn[1], mx[1]); ax.set_zlim(mn[2], mx[2])
    ax.set_box_aspect((mx - mn))
    ax.view_init(24, -58)
    ax.set_axis_off()
    return fig


def _gantt(project, sch, lang):
    tasks = sch["tasks"]
    fig, ax = plt.subplots(figsize=(7.2, 0.19 * len(tasks) + 0.9))
    cp = set(sch["critical_path"])
    for i, t in enumerate(tasks):
        for a, b in t["segments"]:
            ax.barh(i, b - a + 1, left=a - 1, height=0.62, color=C[1] if t["id"] in cp else C[0], edgecolor="white", linewidth=0.8)
    ax.set_yticks(range(len(tasks)))
    ax.set_yticklabels([f"{t['id']}. {t['name'][:34]}" for t in tasks], fontsize=6.2)
    ax.invert_yaxis()
    ax.set_xlabel("εβδομάδες από την έναρξη" if lang == "el" else "weeks from start")
    ax.grid(axis="y", visible=False)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=C[0], label="Εργασία" if lang == "el" else "Task"), Patch(color=C[1], label="Κρίσιμη διαδρομή" if lang == "el" else "Critical path")], loc="lower right", fontsize=7)
    return fig


def _scurve(sch, lang):
    cur = sch["curve"]
    fig, ax = plt.subplots(figsize=(7.2, 2.4))
    ax.plot([c["week"] for c in cur], [c["cumulative"] / 1000 for c in cur], color=C[0], lw=2)
    ax.set_xlabel("εβδομάδα" if lang == "el" else "week")
    ax.set_ylabel("αθροιστικό κόστος (k€, καθαρό)" if lang == "el" else "cumulative cost (k€, net)")
    ax.fill_between([c["week"] for c in cur], [c["cumulative"] / 1000 for c in cur], color=C[0], alpha=0.08)
    return fig


def _trade_chart(cost, lang):
    names = {"mep": ("Η/Μ & ανελκυστήρας", "MEP & lift"), "finishes": ("Φινιρίσματα", "Finishes"), "structure": ("Φέρων οργανισμός", "Structure"), "envelope": ("Κέλυφος", "Envelope"),
             "site": ("Περιβάλλων χώρος", "Site"), "earthworks": ("Χωματουργικά", "Earthworks"), "general": ("Γενικά", "General")}
    items = list(cost["by_trade"].items())
    fig, ax = plt.subplots(figsize=(7.2, 2.5))
    ax.barh([names.get(k, (k, k))[0 if lang == "el" else 1] for k, _ in items], [v / 1000 for _, v in items], color=C[0], height=0.6)
    for i, (_, v) in enumerate(items):
        ax.text(v / 1000, i, f" {fmt(v / 1000, 0, lang)}", va="center", fontsize=7, color=INK2)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("k€ (καθαρό, με γενικά έξοδα/όφελος)" if lang == "el" else "k€ (net, incl. overheads/profit)")
    return fig


def _sens_chart(sens, lang):
    top = sens[:8]
    fig, ax = plt.subplots(figsize=(7.2, 2.4))
    ax.barh([s["label_el" if lang == "el" else "label_en"][:38] for s in top], [s["delta_eur"] / 1000 for s in top], color=C[1], height=0.6)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("μεταβολή κόστους για +10% στον δείκτη (k€)" if lang == "el" else "cost change for +10% in the index (k€)")
    return fig


def _mc_chart(mc, lang):
    edges = np.array(mc["edges"]) / 1000
    fig, ax = plt.subplots(figsize=(7.2, 2.5))
    ax.bar((edges[:-1] + edges[1:]) / 2, mc["hist"], width=(edges[1] - edges[0]) * 0.9, color=C[0], alpha=0.85)
    for key, col, lab in (("today", INK, "σήμερα" if lang == "el" else "today"), ("p50", C[2], "P50"), ("p90", C[1], "P90")):
        ax.axvline(mc[key] / 1000, color=col, lw=1.4)
        ax.text(mc[key] / 1000, ax.get_ylim()[1] * 0.97, f" {lab}", color=INK2, fontsize=7, va="top")
    ax.set_xlabel("καθαρό κόστος κατασκευής (k€)" if lang == "el" else "net construction cost (k€)")
    ax.set_ylabel("πλήθος σεναρίων" if lang == "el" else "scenarios")
    return fig


def _energy_charts(en, lang):
    b, k = en["baseline"], en["package"]
    uses = [("heating", "Θέρμανση", "Heating"), ("cooling", "Ψύξη", "Cooling"), ("dhw", "ΖΝΧ", "DHW"), ("ventilation_fans", "Ανεμιστήρες", "Fans")]
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.7), gridspec_kw={"width_ratios": [1, 1.25]})
    ax = axs[0]
    labels = ["Αφετηρία" if lang == "el" else "Baseline", "Πακέτο" if lang == "el" else "Package"]
    bottoms = np.zeros(2)
    for i, (key, el, en_) in enumerate(uses):
        vals = np.array([max(b["by_use"].get(key, 0), 0), max(k["by_use"].get(key, 0), 0)])
        ax.bar(labels, vals, bottom=bottoms, color=C[i], width=0.55, label=el if lang == "el" else en_, edgecolor="white", linewidth=1.2)
        bottoms += vals
    ax.axhline(b["reference_kwh_m2"], color=INK2, lw=0.8, ls="--")
    ax.text(1.45, b["reference_kwh_m2"], " " + ("κτίριο αναφοράς" if lang == "el" else "reference"), fontsize=6.5, color=INK2, va="bottom", ha="right")
    ax.set_ylabel("kWh/m²·έτος πρωτ. ενέργειας" if lang == "el" else "kWh/m²·y primary energy", fontsize=7)
    ax.legend(fontsize=6.5, loc="upper right")
    ax.grid(axis="x", visible=False)
    ax = axs[1]
    m = np.arange(12)
    names = ["Ιαν", "Φεβ", "Μαρ", "Απρ", "Μάι", "Ιουν", "Ιουλ", "Αυγ", "Σεπ", "Οκτ", "Νοε", "Δεκ"] if lang == "el" else ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    ax.plot(m, b["needs"]["heating_month"], color=C[1], lw=2, label="Θέρμανση (αφετηρία)" if lang == "el" else "Heating (baseline)")
    ax.plot(m, b["needs"]["cooling_month"], color=C[0], lw=2, label="Ψύξη (αφετηρία)" if lang == "el" else "Cooling (baseline)")
    ax.plot(m, k["needs"]["heating_month"], color=C[1], lw=1.4, ls="--", label="Θέρμανση (πακέτο)" if lang == "el" else "Heating (package)")
    ax.plot(m, k["needs"]["cooling_month"], color=C[0], lw=1.4, ls="--", label="Ψύξη (πακέτο)" if lang == "el" else "Cooling (package)")
    ax.set_xticks(m)
    ax.set_xticklabels(names, fontsize=6.5)
    ax.set_ylabel("kWh/μήνα (ωφέλιμη, μη βαθμονομημένη)" if lang == "el" else "kWh/month (useful, uncalibrated)", fontsize=7)
    ax.legend(fontsize=6.3, ncol=2, loc="upper center")
    fig.tight_layout()
    return fig


def _class_bar(en, lang):
    classes = en["classes"]
    fig, ax = plt.subplots(figsize=(7.2, 1.0))
    lo = 0.0
    cols = ["#0ca30c", "#5bb85b", "#9bcf53", "#d8d83a", "#fab219", "#ec835a", "#e34948", "#b83030", "#7a1f1f"]
    for (name, thr), col in zip(classes, cols):
        hi = min(thr, 3.0)
        ax.barh(0, hi - lo, left=lo, color=col, height=0.55, edgecolor="white", linewidth=1)
        ax.text((lo + hi) / 2, 0, name, ha="center", va="center", fontsize=7.5, color="white", fontweight="bold")
        lo = hi
    for lab, r, col, y in ((("Αφετηρία" if lang == "el" else "Baseline"), en["baseline"]["ratio"], INK, 0.62), (("Πακέτο" if lang == "el" else "Package"), en["package"]["ratio"], INK2, -0.62)):
        ax.plot([min(r, 3.0)], [0.33 if y > 0 else -0.33], marker="v" if y > 0 else "^", color=col, ms=6)
        ax.text(min(r, 3.0), y, f"{lab} {r:.2f}", ha="center", va="center", fontsize=6.8, color=col)
    ax.set_xlim(0, 3.0); ax.set_ylim(-1, 1)
    ax.axis("off")
    return fig


def _lcc_charts(lc, lang):
    base, up = lc["base"], lc["upgrade"]
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.7), gridspec_kw={"width_ratios": [1.3, 1]})
    ax = axs[0]
    y = [r["year"] for r in base["series"]]
    ax.plot(y, [r["cumulative_discounted"] / 1e6 for r in base["series"]], color=C[0], lw=2, label="Αφετηρία" if lang == "el" else "Baseline")
    if up:
        ax.plot(y, [r["cumulative_discounted"] / 1e6 for r in up["series"]], color=C[2], lw=2, label="Με αναβαθμίσεις" if lang == "el" else "With upgrades")
    ax.set_xlabel("έτος" if lang == "el" else "year")
    ax.set_ylabel("αθροιστικό προεξοφλημένο κόστος (M€)" if lang == "el" else "cumulative discounted cost (M€)", fontsize=7)
    ax.legend(fontsize=7)
    ax = axs[1]
    keys = [("construction", "Κατασκευή", "Construction"), ("retrofit", "Αναβαθμίσεις", "Upgrades"), ("maintenance", "Συντήρηση", "Maintenance"), ("replacement", "Αντικαταστάσεις", "Replacements"),
            ("energy", "Ενέργεια", "Energy"), ("other", "Λοιπά", "Other")]
    sets = [("Αφετηρία" if lang == "el" else "Baseline", base)] + ([("Αναβαθμ." if lang == "el" else "Upgrades", up)] if up else [])
    bottoms = np.zeros(len(sets))
    for i, (k, el, en_) in enumerate(keys):
        vals = np.array([s[1]["npv_breakdown"][k] / 1e6 for s in sets])
        if vals.sum() <= 0:
            continue
        ax.bar([s[0] for s in sets], vals, bottom=bottoms, color=C[i], width=0.5, edgecolor="white", linewidth=1.2, label=el if lang == "el" else en_)
        bottoms += vals
    ax.legend(fontsize=6.3, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    ax.set_ylabel("M€ (παρούσα αξία)" if lang == "el" else "M€ (present value)", fontsize=7)
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig


def _lca_charts(lca, lang):
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.5))
    ax = axs[0]
    mods = [("A1_A3_kg", "A1–A3", C[0]), ("A4_A5_kg", "A4–A5", C[2]), ("measures_kg", "Αναβ." if lang == "el" else "Upgr.", C[3]), ("B4_kg", "B4", C[1]), ("B6_kg", "B6", C[6]), ("C_kg", "C", C[4]), ("D_kg", "D", C[5])]
    vals = [lca[k] / 1000 for k, _, _ in mods]
    ax.bar([m[1] for m in mods], vals, color=[m[2] for m in mods], width=0.6)
    ax.set_ylabel("tCO₂e")
    ax.set_title("Στάδια κύκλου ζωής (EN 15978)" if lang == "el" else "Life-cycle modules (EN 15978)")
    ax.grid(axis="x", visible=False)
    ax = axs[1]
    g = lca["by_group"]
    names = {k: v["el" if lang == "el" else "en"] for k, v in lca["groups"].items()}
    items = sorted(g.items(), key=lambda kv: -kv[1])
    ax.barh([names[k] for k, _ in items], [v / 1000 for _, v in items], color=C[0], height=0.6)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("tCO₂e (A1–A3)")
    ax.set_title("Ενσωματωμένος άνθρακας ανά ομάδα" if lang == "el" else "Embodied carbon by group")
    fig.tight_layout()
    return fig


def _live_charts(sq, cl, lang):
    el = lang == "el"
    n = (1 if sq else 0) + (1 if cl else 0)
    fig, axs = plt.subplots(max(n, 1), 2, figsize=(7.2, 2.6 * max(n, 1)))
    axs = list(np.atleast_1d(axs).ravel())
    i = 0
    if sq:
        ax = axs[i]; i += 1
        ev = sq["events"]
        m = np.array([e["mag"] for e in ev]); y = np.array([e["year"] for e in ev])
        ax.scatter(y, m, s=(m - 3.8) ** 2 * 6, c=[C[7] if x >= 6 else C[1] if x >= 5 else C[3] for x in m], alpha=0.55, linewidths=0)
        ax.set_xlabel("έτος" if el else "year"); ax.set_ylabel("M"); ax.set_title("Σεισμοί M≥4 σε 150 km" if el else "M≥4 earthquakes within 150 km")
        hz = (sq.get("gr") or {}).get("hazard")
        if hz:
            ax = axs[i]; i += 1
            ax.loglog(hz["pga_g"], hz["annual_rate"], color=C[0], lw=1.8)
            ax.axhline(1 / 475, color=C[1], ls="--", lw=1); ax.axvline(0.24, color=C[2], ls=":", lw=1.2)
            ax.set_ylim(1e-5, 1); ax.set_xlim(0.01, 1)
            ax.set_xlabel("PGA (g)"); ax.set_ylabel("συχνότητα/έτος" if el else "rate/year")
            ax.set_title("Καμπύλη επικινδυνότητας θέσης" if el else "Site hazard curve")
    if cl:
        ax = axs[i] if i < len(axs) else axs[-1]; i += 1
        ax.plot(range(1, 13), [x["t_mean"] for x in cl["monthly"]], color=C[1], lw=1.8, marker="o", ms=2.5, label="θέση" if el else "site")
        if cl.get("design_T_ext"):
            ax.plot(range(1, 13), cl["design_T_ext"], color="#8a8984", lw=1.4, label="μελέτη" if el else "design")
        ax.set_xticks(range(1, 13)); ax.set_ylabel("°C"); ax.legend(fontsize=6, frameon=False)
        ax.set_title("Μηνιαία θερμοκρασία" if el else "Monthly temperature")
        if i < len(axs):
            ax = axs[i]; i += 1
            ys = [r["year"] for r in cl["years"]]
            ax.bar(ys, [r["hdd"] for r in cl["years"]], color=C[0], width=0.8, label="HDD")
            ax.bar(ys, [r["cdd"] for r in cl["years"]], color=C[1], width=0.8, label="CDD")
            ax.legend(fontsize=6, frameon=False); ax.set_title("Βαθμοημέρες ανά έτος" if el else "Degree days per year")
    for ax in axs[i:]:
        ax.axis("off")
    fig.tight_layout()
    return fig


def _seismic_charts(seis, ref, lang):
    runs = seis["runs"]
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.8))
    ax = axs[0]
    sp = runs["moderate"]["spectrum"]
    ax.plot(sp["T"], sp["design_elastic"], color=INK, lw=1.6, label="Ελαστικό φάσμα σχεδιασμού ΕΑΚ" if lang == "el" else "EAK design elastic spectrum")
    ax.plot(sp["T"], sp["design_q"], color=INK2, lw=1.2, ls="--", label="Φάσμα σχεδιασμού (q)" if lang == "el" else "Design spectrum (q)")
    for i, k in enumerate(("small", "moderate", "large")):
        ax.plot(runs[k]["spectrum"]["T"], runs[k]["spectrum"]["scenario"], color=C[i], lw=1.6, label=(runs[k]["label_el"] if lang == "el" else runs[k]["label_en"]))
    for m in runs["large"]["markers"][:1]:
        ax.axvline(m["T"], color=GRID, lw=1)
        ax.text(m["T"], ax.get_ylim()[1] * 0.97, " T", fontsize=7, color=INK2, va="top")
    ax.set_xlabel("T (s)")
    ax.set_ylabel("Sa (g)")
    ax.legend(fontsize=6, loc="upper right")
    ax = axs[1]
    w = 0.25
    for i, k in enumerate(("small", "moderate", "large")):
        d = runs[k]["distribution"]
        ax.bar(np.arange(6) + (i - 1) * w, d, width=w * 0.92, color=C[i], label=(runs[k]["label_el"] if lang == "el" else runs[k]["label_en"]))
    ax.set_xticks(range(6))
    ax.set_xlabel("βαθμός βλάβης (0–5)" if lang == "el" else "damage grade (0–5)")
    ax.set_ylabel("πιθανότητα" if lang == "el" else "probability")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig


def _plot_chart(site_rec, lang):
    m = (site_rec.get("parcel") or {}).get("metrics")
    if not m or not m.get("local"):
        return None
    pts = m["local"]
    fig, ax = plt.subplots(figsize=(5.4, 3.6))
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    ax.fill(xs, ys, color=C[0], alpha=0.18)
    ax.plot(xs, ys, color=C[0], lw=1.8)
    n = len(pts) - 1
    cx, cy = sum(xs[:n]) / n, sum(ys[:n]) / n
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    for i in range(n):
        e = m["edges_m"][i]
        if e < 0.05 * span:
            continue
        mx, my = (xs[i] + xs[i + 1]) / 2, (ys[i] + ys[i + 1]) / 2
        dx, dy = xs[i + 1] - xs[i], ys[i + 1] - ys[i]
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        if (mx - cx) * nx + (my - cy) * ny < 0:
            nx, ny = -nx, -ny
        ax.text(mx + nx * 0.035 * span, my + ny * 0.035 * span, f"{e:.1f}".replace(".", ",") if lang == "el" else f"{e:.1f}", fontsize=6.5, ha="center", va="center", color=INK2)
    ax.set_aspect("equal")
    ax.set_xlabel("m")
    ax.set_title(("Γεωμετρία οικοπέδου" if lang == "el" else "Plot geometry") + f" – {m['area_m2']:.2f} m²", fontsize=8)
    ax.annotate("B" if lang == "el" else "N", xy=(0.96, 0.95), xytext=(0.96, 0.80), xycoords="axes fraction", fontsize=7, ha="center", arrowprops=dict(arrowstyle="->", color=INK2))
    ax.grid(color=GRID, lw=0.5)
    fig.tight_layout()
    return fig


def _richter_chart(cap, lang):
    lim = cap["limits"]
    fig, ax = plt.subplots(figsize=(7.2, 2.5))
    x = [r["distance_km"] for r in lim]
    cl = lambda v: [min(a[v], 9.2) for a in lim]
    ax.fill_between(x, cl("collapse_lo"), cl("collapse_hi"), color=C[1], alpha=0.12, lw=0)
    ax.fill_between(x, cl("yield_lo"), cl("yield_hi"), color=C[0], alpha=0.12, lw=0)
    ax.plot(x, cl("collapse"), color=C[1], lw=1.8, marker="o", ms=3, label="Οιονεί κατάρρευση" if lang == "el" else "Near-collapse")
    ax.plot(x, cl("yield"), color=C[0], lw=1.8, marker="o", ms=3, label="Πρώτη διαρροή" if lang == "el" else "First yield")
    ax.axhline(7.5, color=GRID, lw=1, ls="--")
    ax.text(x[-1], 7.55, " Ms 7,5" if lang == "el" else " Ms 7.5", fontsize=6, color=INK2, ha="right")
    ax.set_xscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels([str(v) for v in x])
    ax.set_ylim(3.5, 9.2)
    ax.set_xlabel("Απόσταση επικέντρου (km)" if lang == "el" else "Epicentral distance (km)")
    ax.set_ylabel("Ms (Ρίχτερ)" if lang == "el" else "Ms (Richter)")
    ax.legend(fontsize=6.5, loc="upper left")
    fig.tight_layout()
    return fig


def _fire_charts(fi, wild, lang):
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.6))
    ax = axs[0]
    ax.plot(fi["curve"]["t_min"], fi["curve"]["gas_C"], color=C[1], lw=2, label="Παραμετρική πυρκαγιά (EC1)" if lang == "el" else "Parametric fire (EC1)")
    ax.plot(fi["curve"]["t_min"], fi["curve"]["standard_C"], color=INK2, lw=1.2, ls="--", label="Standard ISO 834")
    ax.set_xlabel("min"); ax.set_ylabel("°C")
    ax.legend(fontsize=6.5)
    ax = axs[1]
    dc = wild["distance_curve"]
    ax.plot([d["d"] for d in dc], [d["q"] for d in dc], color=C[1], lw=2)
    for thr, name, col in zip([12.5, 19, 29, 40], ["12,5", "19", "29", "40"], BAL_COL[1:5]):
        ax.axhline(thr, color=col, lw=0.8, ls="--")
        ax.text(78, thr, f" BAL-{name}", fontsize=6, va="bottom", ha="right", color=INK2)
    ax.plot([wild["distance_m"]], [wild["flux_kW_m2"]], "o", color=C[0], ms=6, label=("Θέση κτιρίου" if lang == "el" else "Building"))
    ax.set_xlabel("απόσταση από τη βλάστηση (m)" if lang == "el" else "distance to vegetation (m)")
    ax.set_ylabel("kW/m²")
    ax.legend(fontsize=6.5, loc="upper right")
    fig.tight_layout()
    return fig


def _flood_chart(fl, lang):
    runs = fl["runs"]
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.5))
    ax = axs[0]
    cu = runs["moderate"]["curve"]
    ax.plot([c["depth"] for c in cu], [c["ratio"] for c in cu], color=C[0], lw=2)
    for i, k in enumerate(("minor", "moderate", "severe")):
        r = runs[k]
        ax.plot([r["depth_m"]], [np.interp(r["depth_m"], [c["depth"] for c in cu], [c["ratio"] for c in cu])], "o", color=C[i + 1], ms=6, label=r["label_el" if lang == "el" else "label_en"][:22])
    ax.set_xlabel("βάθος νερού (m)" if lang == "el" else "water depth (m)")
    ax.set_ylabel("λόγος ζημιάς" if lang == "el" else "damage ratio")
    ax.legend(fontsize=6)
    ax = axs[1]
    names = [r["label_el" if lang == "el" else "label_en"][:18] for r in runs.values()]
    ax.bar(names, [r["loss_eur"] / 1000 for r in runs.values()], color=[C[1], C[2], C[3]], width=0.55)
    ax.set_ylabel("k€")
    ax.grid(axis="x", visible=False)
    ax.tick_params(axis="x", labelsize=6)
    fig.tight_layout()
    return fig


def _risk_charts(risk, lang):
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.5), gridspec_kw={"width_ratios": [1, 1.4]})
    ax = axs[0]
    names = {"seismic": ("Σεισμός", "Earthquake"), "fire_internal": ("Εσωτ. φωτιά", "Internal fire"), "wildfire": ("Δασική πυρκ.", "Wildfire"), "flood": ("Πλημμύρα", "Flood")}
    ks = list(risk["hazards"])
    ax.bar([names[k][0 if lang == "el" else 1] for k in ks], [risk["hazards"][k] for k in ks], color=C[0], width=0.55)
    ax.set_ylabel("€/έτος" if lang == "el" else "€/year")
    ax.set_title("Αναμενόμενη ετήσια ζημιά" if lang == "el" else "Expected annual loss")
    ax.tick_params(axis="x", labelsize=6.5, rotation=15)
    ax.grid(axis="x", visible=False)
    ax = axs[1]
    ms = [m for m in risk["mitigations"] if m["bcr"] is not None][:8]
    ax.barh([m["el" if lang == "el" else "en"][:34] for m in ms], [m["bcr"] for m in ms], color=[C[2] if m["bcr"] >= 1 else C[7] for m in ms], height=0.6)
    ax.axvline(1, color=INK, lw=1)
    ax.invert_yaxis()
    ax.tick_params(axis="y", labelsize=6)
    ax.grid(axis="y", visible=False)
    ax.set_title("Λόγος οφέλους/κόστους μέτρων (BCR)" if lang == "el" else "Mitigation benefit–cost ratio (BCR)")
    fig.tight_layout()
    return fig


# ------------------------------------------------------------------------------------------------
ALL_SECTIONS = ["summary", "model", "site", "quantities", "cost", "schedule", "energy", "lifecycle", "fm", "hazards", "assumptions"]


def build(project: dict[str, Any], pstate: dict[str, Any], data: dict[str, Any], lang: str = "el", sections: list[str] | None = None, notes: str = "", author: str = "") -> bytes:
    sections = sections or ALL_SECTIONS
    d = Doc(project, lang, author)
    T = d.T
    F = lambda x, n=0: fmt(x, n, lang)
    E = lambda x, n=0: eur(x, lang, n)
    meta = project["meta"]
    cost, q, en, lc, sch = data["cost"], data["quantities"]["quantities"], data["energy"], data["lifecycle"], data["schedule"]
    up = lc["upgrade"]
    # ---- cover
    d.story.append(Spacer(1, 38 * mm))
    d.P(T("Μελέτη 7D-BIM και ανάλυση κύκλου ζωής", "7D-BIM study and life-cycle analysis"), "cover_t")
    d.P(d.title or "", "cover_s")
    loc = meta.get("location", {})
    perm = meta.get("permit", {})
    d.P(f"{loc.get('address', '')} – {loc.get('municipality', '')}", "cover_s")
    if perm.get("number"):
        d.P(T(f"Οικοδομική άδεια {perm['number']} / {perm.get('date', '')} – {perm.get('authority', '')}", f"Building permit {perm['number']} / {perm.get('date', '')} – {perm.get('authority', '')}"), "cover_s")
    d.story.append(Spacer(1, 12 * mm))
    d.P(T("Διαστάσεις BIM: 1D–3D σχέδια και ψηφιακό δίδυμο · 4D χρόνος κατασκευής και διάρκεια ζωής · 5D κόστος κατασκευής και κόστος στον χρόνο · 6D ενέργεια και περιβαλλοντικό αποτύπωμα · 7D διαχείριση εγκαταστάσεων και ιδιοκτησιών, κίνδυνοι.", "BIM dimensions: 1D–3D drawings and digital twin · 4D construction time and service life · 5D construction cost and cost over time · 6D energy and environmental footprint · 7D facility and property management, risks."), "body")
    d.story.append(Spacer(1, 40 * mm))
    d.P(f"{T('Ημερομηνία', 'Date')}: {date.today().strftime('%d/%m/%Y')}" + (f" · {T('Συντάκτης', 'Author')}: {author}" if author else ""), "small")
    d.P(T("Η μελέτη παράγεται από το εργαλείο 7D-BIM Lifecycle και έχει χαρακτήρα προμελέτης (screening): τα αποτελέσματα ενέργειας, κόστους και κινδύνων είναι ενδεικτικά και δεν υποκαθιστούν "
          "την ενεργειακή πιστοποίηση (ΚΕΝΑΚ), τη στατική επάρκεια (ΕΑΚ/ΚΑΝ.ΕΠΕ./Ευρωκώδικες), τη μελέτη πυροπροστασίας (ΠΥΣ) ή υδραυλική μελέτη. Οι παραδοχές αναφέρονται στο Κεφάλαιο «Παραδοχές».",
          "This study is produced by the 7D-BIM Lifecycle tool at screening level: energy, cost and hazard results are indicative and do not replace energy certification (KENAK), structural assessment "
          "(EAK/KAN.EPE/Eurocodes), fire-safety design or hydraulic studies. Assumptions are listed in the 'Assumptions' chapter."), "warn")
    if meta.get("synthetic_geometry"):
        d.story.append(Spacer(1, 4))
        d.P(T("ΠΡΟΣΟΧΗ: Η γεωμετρία 3D αυτού του έργου είναι συνθετική: παράγεται από τις συντεταγμένες και τα περιγράμματα της άδειας (υπόγειο, ισόγειο, όροφοι, εξώστες, εκσκαφή), τις στάθμες των τομών και τους πίνακες ξυλοτύπων, όχι το πραγματικό μοντέλο Rhino. Ανεβάστε ελαφριά εξαγωγή του μοντέλου για ακριβείς ποσότητες.",
              "NOTE: The 3D geometry of this project is synthetic: it is generated from the permit coordinates and floor outlines (basement, ground, upper floors, balconies, excavation), the section levels and the formwork tables, not from the actual Rhino model. Upload a lightweight export of the model for exact quantities."), "warn")
    d.story.append(PageBreak())

    # ---- 1 summary
    if "summary" in sections:
        d.H1("Συνοπτικά αποτελέσματα", "Executive summary")
        fmr = data.get("fm") or {}
        d.kpis([(str(len(fmr.get("properties", []))), T("Αυτοτελείς ιδιοκτησίες (7D)", "Independent properties (7D)")),
                (f"{F(meta.get('gfa_m2', 0))} m²", T("Συνολική επιφάνεια ορόφων (με υπόγειο)", "Total floor area (incl. basement)")),
                (E(cost["net"]), T("Κόστος κατασκευής (χωρίς ΦΠΑ)", "Construction cost (excl. VAT)")),
                (f"{F(cost['net_per_m2_gfa'])} €/m²", T("Κόστος ανά m² συνολικής επιφάνειας", "Cost per m² of total floor area"))])
        d.kpis([(f"{en['baseline']['class']} → {en['package']['class']}" if en["selected"] else en["baseline"]["class"], T("Ενεργειακή κλάση (αφετηρία → πακέτο)", "Energy class (baseline → package)")),
                (E(lc["base"]["npv_total"]), T(f"Κόστος κύκλου ζωής ({lc['base']['horizon']} έτη, ΠΑ)", f"Life-cycle cost ({lc['base']['horizon']} y, PV)")),
                (f"{F(lc['base']['lca']['per_m2_gfa'])} kgCO₂e/m²", T("Αποτύπωμα κύκλου ζωής", "Life-cycle footprint")), (E(data["risk"]["total_eal_eur"]), T("Αναμενόμενη ετήσια ζημιά (κίνδυνοι)", "Expected annual hazard loss"))])
        runs = data["seismic"]["runs"]
        rows = [[T("Κατασκευή (καθαρό κόστος)", "Construction (net cost)"), E(cost["net"]), f"{T('με ΦΠΑ', 'incl. VAT')}: {E(cost['total_with_vat'])}"],
                [T("Διάρκεια κατασκευής", "Construction duration"), f"{sch['weeks']} {T('εβδ.', 'wk')}", T("σύμφωνα με το χρονοδιάγραμμα 4D", "per the 4D schedule")],
                [T("Εύρος κόστους με κινδύνους τιμών (P10–P90)", "Cost range with price risk (P10–P90)"), f"{E(data['monte_carlo']['p10'])} – {E(data['monte_carlo']['p90'])}", T(f"έναρξη σε {data['monte_carlo']['start_in_months']:.0f} μήνες", f"start in {data['monte_carlo']['start_in_months']:.0f} months")],
                [T("Ενεργειακή κατάσταση", "Energy status"), f"{en['baseline']['primary_kwh_m2']} kWh/m²·{T('έτος', 'y')} ({en['baseline']['class']})", T("πρωτογενής ενέργεια", "primary energy")],
                [T("Σεισμός: μικρός / μέτριος / μεγάλος", "Earthquake: small / moderate / large"), " / ".join(f"{runs[k]['loss_ratio'] * 100:.1f}%" for k in ("small", "moderate", "large")), T("λόγος ζημιάς προς αξία αντικατάστασης", "loss ratio to replacement value")],
                [T("Εσωτ. φωτιά / δασική πυρκαγιά", "Internal fire / wildfire"), f"{data['fire_internal']['loss_ratio'] * 100:.1f}% / {data['wildfire']['loss_ratio'] * 100:.1f}% ({data['wildfire']['bal']})", T("σενάρια προεπιλογής", "default scenarios")],
                [T("Πλημμύρα: ήπια / μέτρια / σοβαρή", "Flood: minor / moderate / severe"), " / ".join(f"{r['loss_ratio'] * 100:.1f}%" for r in data["flood"]["runs"].values()), T("λόγος ζημιάς", "loss ratio")]]
        d.table([T("Μέγεθος", "Item"), T("Τιμή", "Value"), T("Σχόλιο", "Note")], rows, [62, 62, 46], align_right_from=9)
        if notes:
            d.H2("Σημειώσεις μελετητή", "Author's notes")
            d.P(notes.replace("\n", "<br/>"))
        d.story.append(PageBreak())

    if "model" in sections:
        d.H1("Μοντέλο BIM (3D)", "BIM model (3D)")
        d.P(T("Το μοντέλο οργανώνεται σε στοιχεία τύπου IFC (υποστυλώματα, δοκοί, πλάκες, τοίχοι, ανοίγματα κ.λπ.) που ταξινομούνται από τα layers/ονόματα της εισόδου και αντιστοιχίζονται σε ορόφους. "
              "Κάθε στοιχείο φέρει ποσότητες (όγκος, επιφάνεια, μήκος) που τροφοδοτούν τα 4D–7D.", "The model is organised in IFC-type elements (columns, beams, slabs, walls, openings…) classified from input layers/names and assigned to storeys. "
              "Each element carries quantities (volume, area, length) that feed the 4D–7D dimensions."))
        try:
            d.img(_model_view(project), 165, ("Αξονομετρική όψη του μοντέλου (χρώμα ανά τύπο στοιχείου).", "Axonometric view of the model (colour by element type)."))
        except Exception:
            pass
        decl_areas = ((meta.get("permit") or {}).get("declared") or {}).get("areas_m2") or {}          # floor areas of the permit's area-calculation sheet
        rows = [[s["name_el" if lang == "el" else "name_en"], F(s["elevation_m"], 2), F(s["height_m"], 2), F(decl_areas.get(s.get("key")) or hz_mod.storey_areas(project).get(s["id"], 0), 2 if decl_areas else 1),
                str(sum(1 for e in project["elements"] if e.get("storey") == s["id"]))] for s in project["storeys"]]
        d.H2("Όροφοι", "Storeys")
        d.table([T("Όροφος", "Storey"), T("Στάθμη (m)", "Level (m)"), T("Ύψος (m)", "Height (m)"), T("Επιφάνεια (m²)", "Area (m²)"), T("Στοιχεία", "Elements")], rows, [50, 30, 30, 32, 28])
        if decl_areas:
            d.P(T("Επιφάνειες ορόφων από τους πίνακες επιφανειών των σχεδίων (υπόγειο 330,27 m² + 13,68 m² κλιμακοστάσιο· σοφίτα: τμήμα με ύψος ≥ 1,80 m). Σύνολο όλων των επιπέδων ",
                  "Floor areas from the area tables of the drawings (basement 330.27 m² + 13.68 m² stairwell; attic: part with height ≥ 1.80 m). Total of all levels ") + f"{F(meta.get('gfa_m2', 0), 2)} m².")
        kinds = data["quantities"]["by_kind"]
        names = {"footing": ("Θεμελίωση", "Footing"), "column": ("Υποστυλώματα", "Columns"), "beam": ("Δοκοί", "Beams"), "slab": ("Πλάκες", "Slabs"), "wall": ("Τοίχοι", "Walls"), "window": ("Ανοίγματα", "Windows"),
                 "door": ("Πόρτες", "Doors"), "roof": ("Δώμα/στέγη", "Roof"), "stair": ("Σκάλες", "Stairs"), "railing": ("Κιγκλιδώματα", "Railings"), "pergola": ("Πέργκολες", "Pergolas"), "fence": ("Περίφραξη", "Fence"),
                 "site": ("Έδαφος", "Site"), "vegetation": ("Βλάστηση", "Vegetation"), "other": ("Άλλα", "Other"), "lintel": ("Πρέκια ανοιγμάτων", "Lintels")}
        rows = [[names.get(k, (k, k))[0 if lang == "el" else 1], str(v["count"]), F(v["volume_m3"], 1)] for k, v in kinds.items()]
        d.H2("Στοιχεία ανά τύπο", "Elements by type")
        d.table([T("Τύπος", "Type"), T("Πλήθος", "Count"), T("Όγκος (m³)", "Volume (m³)")], rows, [70, 40, 50])
        d.story.append(PageBreak())

    # ---- 3 quantities
    if "quantities" in sections:
        d.H1("Προμέτρηση", "Quantity take-off")
        d.P(T("Οι ποσότητες προκύπτουν αυτόματα από το μοντέλο και τις παραδοχές (οπλισμός kg/m³, μόνωση, εσωτερικές τοιχοποιίες κ.λπ.). Οι τιμές που τροποποίησε ο χρήστης σημειώνονται με *.",
              "Quantities are derived automatically from the model and the assumptions (rebar kg/m³, insulation, interior walls…). Values edited by the user are marked with *."))
        qn = {"excavation_area_m2": ("Εμβαδόν εκσκαφής (διάγραμμα)", "Excavation area (diagram)", "m²"), "excavation_depth_m": ("Βάθος εκσκαφής", "Excavation depth", "m"),
              "excavation_m3": ("Εκσκαφές", "Excavation", "m³"), "excavation_haul_m3": ("Μεταφορά προϊόντων εκσκαφής (χαλαρός όγκος)", "Excavated soil to haul (loose)", "m³"),
              "waterproof_basement_m2": ("Στεγάνωση υπογείου", "Basement waterproofing", "m²"), "basement_floor_m2": ("Δάπεδο υπογείου", "Basement floor", "m²"), "fence_length_m": ("Περίφραξη", "Fence", "m"),
              "coverage_m2": ("Κάλυψη", "Coverage", "m²"), "planting_area_m2": ("Φυτεμένη επιφάνεια", "Planted area", "m²"), "backfill_m3": ("Επιχώσεις", "Backfill", "m³"), "concrete_foundation_m3": ("Σκυρόδεμα θεμελίωσης", "Foundation concrete", "m³"),
              "formwork_foundation_m2": ("Ξυλότυποι θεμελίωσης", "Foundation formwork", "m²"), "rebar_foundation_kg": ("Οπλισμός θεμελίωσης", "Foundation rebar", "kg"),
              "concrete_structure_m3": ("Σκυρόδεμα ανωδομής", "Superstructure concrete", "m³"), "formwork_structure_m2": ("Ξυλότυποι ανωδομής", "Superstructure formwork", "m²"),
              "rebar_structure_kg": ("Οπλισμός ανωδομής", "Superstructure rebar", "kg"), "masonry_external_m2": ("Εξωτερικές τοιχοποιίες", "External masonry", "m²"), "masonry_internal_m2": ("Εσωτερικές τοιχοποιίες", "Internal masonry", "m²"),
              "insulation_wall_m2": ("Θερμομόνωση όψεων", "Facade insulation", "m²"), "plaster_m2": ("Επιχρίσματα", "Plaster", "m²"), "paint_m2": ("Χρωματισμοί", "Painting", "m²"), "floor_finish_m2": ("Δάπεδα", "Floors", "m²"),
              "window_area_m2": ("Κουφώματα αλουμινίου (παράθυρα, μπαλκονόπορτες, είσοδος)", "Aluminium frames (windows, balcony doors, entrance)", "m²"), "interior_doors": ("Εσωτερικές πόρτες", "Interior doors", "τεμ."),
              "security_doors": ("Πόρτες ασφαλείας διαμερισμάτων", "Apartment security doors", "τεμ."), "garage_door_area_m2": ("Πόρτα γκαράζ", "Garage door", "m²"),
              "lintel_count": ("Πρέκια (πλήθος)", "Lintels (count)", "τεμ."), "lintel_length_m": ("Πρέκια (μήκος με έδραση)", "Lintels (length incl. bearing)", "m"), "lintel_concrete_m3": ("Σκυρόδεμα πρεκιών", "Lintel concrete", "m³"),
              "reveal_plaster_m2": ("Επιχρίσματα λαμπάδων (ραβδώσεις ανοιγμάτων)", "Plaster on opening reveals", "m²"), "railing_length_m": ("Κιγκλιδώματα", "Railings", "m"), "pergola_area_m2": ("Πέργκολες", "Pergolas", "m²"),
              "roof_area_m2": ("Δώμα/στέγη", "Roof", "m²"), "gfa_m2": ("Συνολική επιφάνεια ορόφων (με υπόγειο)", "Total floor area (incl. basement)", "m²"), "conditioned_area_m2": ("Θερμαινόμενη επιφάνεια", "Conditioned area", "m²"), "site_area_m2": ("Περιβάλλων χώρος", "Site", "m²"),
              "paving_m2": ("Πλακοστρώσεις", "Paving", "m²"), "planting_m2": ("Φυτεύσεις", "Planting", "m²"), "apartments": ("Διαμερίσματα", "Apartments", "τεμ."), "elevators": ("Ανελκυστήρες", "Elevators", "τεμ.")}
        ov = set(data["quantities"].get("overridden", []))
        _openings_table(d, project, lang, T)
        rows = [[qn[k][0 if lang == "el" else 1] + (" *" if k in ov else ""), F(v, 1), qn[k][2]] for k, v in q.items() if k in qn]
        d.table([T("Εργασία / μέγεθος", "Item"), T("Ποσότητα", "Quantity"), T("Μον.", "Unit")], rows, [90, 45, 25])
        d.story.append(PageBreak())

    # ---- 4 cost
    if "cost" in sections:
        d.H1("Κοστολόγιο (5D)", "Cost estimate (5D)")
        d.P(T(f"Τιμές μονάδας από ενδεικτικό τιμολόγιο (βάση {cost['base_period']}), προσαρμοσμένες με τους τρέχοντες δείκτες τιμών (ΕΛΣΤΑΤ, εμπορεύματα, ενέργεια, εργατικά) ανά συνιστώσα. "
              f"Η επίδραση των δεικτών στο άμεσο κόστος είναι {cost['index_effect_pct']:+.1f}% σε σχέση με τη βάση.",
              f"Unit prices come from an indicative price book (base {cost['base_period']}), adjusted by current price indices (ELSTAT, commodities, energy, labour) per component. The index effect on direct cost is {cost['index_effect_pct']:+.1f}% vs. base."))
        d.img(_trade_chart(cost, lang), 165, ("Κόστος ανά ειδικότητα (καθαρό, με γενικά έξοδα, όφελος και απρόβλεπτα).", "Cost by trade (net, including overheads, profit and contingency)."))
        oh = cost["overheads"]
        rows = [[T("Άμεσο κόστος", "Direct cost"), E(cost["direct"])], [T(f"Γενικά έξοδα ({oh['general_expenses_pct']:.0f}%)", f"General expenses ({oh['general_expenses_pct']:.0f}%)"), E(cost["general_expenses"])],
                [T(f"Όφελος ({oh['profit_pct']:.0f}%)", f"Profit ({oh['profit_pct']:.0f}%)"), E(cost["profit"])], [T(f"Απρόβλεπτα ({oh.get('contingency_pct', 0):.0f}%)", f"Contingency ({oh.get('contingency_pct', 0):.0f}%)"), E(cost["contingency"])],
                [T("Σύνολο χωρίς ΦΠΑ", "Total excl. VAT"), E(cost["net"])], [T(f"ΦΠΑ ({oh['vat_pct']:.0f}%)", f"VAT ({oh['vat_pct']:.0f}%)"), E(cost["vat"])], [T("Γενικό σύνολο", "Grand total"), E(cost["total_with_vat"])]]
        d.table([T("Κατηγορία", "Category"), T("Ποσό", "Amount")], rows, [100, 60], total_last=True)
        d.H2("Αναλυτικό τιμολόγιο εργασιών", "Itemised bill of quantities")
        rows = [[l["el" if lang == "el" else "en"], l["unit"], F(l["qty"], 1), F(l["price_now"], 2), E(l["total"])] for l in cost["lines"] if l["qty"] > 0]
        d.table([T("Εργασία", "Item"), T("Μον.", "Unit"), T("Ποσότητα", "Qty"), T("Τιμή μον. (€)", "Unit price (€)"), T("Σύνολο", "Total")], rows, [78, 14, 26, 24, 28])
        d.H2("Συμπεριφορά τιμών και ευαισθησία", "Price behaviour and sensitivity")
        beh = [r for r in data["behaviour"]]
        rows = [[r["label_el" if lang == "el" else "label_en"], F(r["ratio_now"], 3), f"{r['mu'] * 100:.1f}%", f"{r['sigma'] * 100:.0f}%", f"{F(r['p10_1y'], 2)} – {F(r['p90_1y'], 2)}"] for r in beh]
        d.table([T("Δείκτης", "Index"), T("Λόγος vs βάση", "Ratio vs base"), T("Τάση/έτος", "Drift/y"), T("Μεταβλητότητα", "Volatility"), T("1 έτος P10–P90", "1-year P10–P90")], rows, [66, 26, 22, 24, 32])
        d.P(T("Οι παράμετροι τάσης και μεταβλητότητας προέρχονται από ιστορική συμπεριφορά των δεικτών/χρηματιστηριακών προϊόντων (π.χ. χάλυβας οπλισμού, χαλκός, αλουμίνιο, πετρέλαιο, ηλεκτρισμός) και είναι επεξεργάσιμες.",
              "Drift and volatility parameters reflect the historical behaviour of the indices / traded commodities (e.g. rebar steel, copper, aluminium, oil, electricity) and are editable."), "small")
        d.img(_sens_chart(data["sensitivity"], lang), 160, ("Κύριοι παράγοντες κόστους: επίδραση +10% στον κάθε δείκτη.", "Main cost drivers: effect of +10% in each index."))
        mc = data["monte_carlo"]
        d.img(_mc_chart(mc, lang), 160, (f"Προσομοίωση Monte Carlo ({mc['n']} σενάρια): η τιμή κάθε εργασίας ακολουθεί τη στοχαστική πορεία των δεικτών της μέχρι την εβδομάδα εκτέλεσης. P50 {eur(mc['p50'], lang)}, P90 {eur(mc['p90'], lang)}.",
                                         f"Monte Carlo simulation ({mc['n']} scenarios): each task price follows the stochastic path of its indices up to its execution week. P50 {eur(mc['p50'], lang)}, P90 {eur(mc['p90'], lang)}."))
        d.story.append(PageBreak())

    # ---- 5 schedule
    if "schedule" in sections:
        d.H1("Χρονοδιάγραμμα (4D)", "Schedule (4D)")
        d.P(T(f"Το χρονοδιάγραμμα ({sch['weeks']} εβδομάδες) συνδέεται με τα στοιχεία του μοντέλου και με το κόστος κάθε εργασίας. Με πορτοκαλί σημειώνεται η κρίσιμη διαδρομή (απλοποιημένη λογική τέλους–έναρξης).",
              f"The schedule ({sch['weeks']} weeks) is linked to the model elements and to the cost of each task. Orange marks the critical path (simplified finish-to-start logic)."))
        d.img(_gantt(project, sch, lang), 165, ("Διάγραμμα Gantt.", "Gantt chart."))
        d.img(_scurve(sch, lang), 160, ("Καμπύλη S: αθροιστικό κόστος κατασκευής.", "S-curve: cumulative construction cost."))
        d.story.append(PageBreak())

    # ---- 6 energy
    if "energy" in sections:
        d.H1("Ενεργειακή συμπεριφορά (6D)", "Energy performance (6D)")
        b, k = en["baseline"], en["package"]
        pre = en.get("presets", {}).get(en.get("preset", "as_certified"), {})
        d.P(T(f"Αφετηρία: {pre.get('el', '')}. Πρωτογενής ενέργεια {b['primary_kwh_m2']} kWh/m²·έτος, κτίριο αναφοράς {b['reference_kwh_m2']} kWh/m²·έτος, λόγος {b['ratio']:.2f} → κατηγορία {b['class']}. "
              "Το ισοζύγιο θερμότητας υπολογίζεται μηνιαία (μέθοδος ISO 13790) και βαθμονομείται στο πιστοποιητικό ΚΕΝΑΚ της μελέτης: οι αναβαθμίσεις μετακινούν τα αποτελέσματα αναλογικά.",
              f"Baseline: {pre.get('en', '')}. Primary energy {b['primary_kwh_m2']} kWh/m²·y, reference building {b['reference_kwh_m2']} kWh/m²·y, ratio {b['ratio']:.2f} → class {b['class']}. "
              "The heat balance is computed monthly (ISO 13790) and calibrated to the KENAK certificate of the design: upgrades move the results proportionally."))
        d.img(_class_bar(en, lang), 165)
        d.img(_energy_charts(en, lang), 165, ("Πρωτογενής ενέργεια ανά χρήση και μηνιαίες ανάγκες.", "Primary energy by end-use and monthly needs."))
        rows = [[m["el" if lang == "el" else "en"], F(m["delta_kwh_m2"], 1), m["class"], E(m["cost_eur"]), E(m["saving_eur_year"]), F(m["payback_years"], 1) if m["payback_years"] else "–"] for m in en["measures"]]
        d.H2("Μέτρα αναβάθμισης (το καθένα μόνο του)", "Upgrade measures (each on its own)")
        d.table([T("Μέτρο", "Measure"), T("Δ kWh/m²", "Δ kWh/m²"), T("Κλάση", "Class"), T("Κόστος", "Cost"), T("Εξοικονόμηση/έτος", "Saving/y"), T("Απόσβεση (έτη)", "Payback (y)")], rows, [66, 18, 14, 24, 26, 22])
        if en["selected"]:
            names = {m["id"]: m["el" if lang == "el" else "en"] for m in en["measures"]}
            d.P(T(f"<b>Επιλεγμένο πακέτο:</b> {', '.join(names[i] for i in en['selected'])}. Αποτέλεσμα: {k['primary_kwh_m2']} kWh/m²·έτος, κατηγορία <b>{k['class']}</b>, "
                  f"κόστος {E(en['package_cost_eur'])}, εξοικονόμηση {E(en['package_saving_eur_year'])}/έτος, απόσβεση {F(en['package_payback_years'], 1)} έτη, CO₂ {k['co2_kg_m2']} kg/m²·έτος.",
                  f"<b>Selected package:</b> {', '.join(names[i] for i in en['selected'])}. Result: {k['primary_kwh_m2']} kWh/m²·y, class <b>{k['class']}</b>, "
                  f"cost {E(en['package_cost_eur'])}, saving {E(en['package_saving_eur_year'])}/y, payback {F(en['package_payback_years'], 1)} years, CO₂ {k['co2_kg_m2']} kg/m²·y."))
        d.P(T("Σημείωση: ενδεικτική εκτίμηση. Η επίσημη ενεργειακή κατάταξη απαιτεί πιστοποιητικό από εγκεκριμένο ενεργειακό επιθεωρητή (ΤΕΕ-ΚΕΝΑΚ).", "Note: indicative estimate. Official energy rating requires a certificate from an accredited energy inspector (TEE-KENAK)."), "small")
        d.story.append(PageBreak())

    # ---- 7 lifecycle
    if "lifecycle" in sections:
        base = lc["base"]
        d.H1("Κόστος στον χρόνο: συντήρηση, αντικαταστάσεις, ενέργεια (5D)", "Cost over time: maintenance, replacements, energy (5D)")
        a = base["assumptions"]
        d.P(T(f"Κόστος κύκλου ζωής σε {base['horizon']} έτη με πραγματικό προεξοφλητικό επιτόκιο {a['real_discount_pct']}% και πραγματική αύξηση τιμών ενέργειας {a['energy_escalation_pct']}%/έτος (EN 15459). "
              f"Παρούσα αξία: <b>{E(base['npv_total'])}</b> ({F(base['npv_per_m2_gfa'])} €/m² συνολικής επιφάνειας), ισοδύναμο ετήσιο κόστος {E(base['annual_equivalent'])}.",
              f"Life-cycle cost over {base['horizon']} years with a real discount rate of {a['real_discount_pct']}% and real energy price escalation of {a['energy_escalation_pct']}%/y (EN 15459). "
              f"Present value: <b>{E(base['npv_total'])}</b> ({F(base['npv_per_m2_gfa'])} €/m² total floor area), equivalent annual cost {E(base['annual_equivalent'])}."))
        d.img(_lcc_charts(lc, lang), 165, ("Αθροιστικό προεξοφλημένο κόστος και ανάλυση παρούσας αξίας.", "Cumulative discounted cost and present-value breakdown."))
        d.H2("Πρόγραμμα συντήρησης και αντικαταστάσεων", "Maintenance and replacement plan")
        rows = [[c["el" if lang == "el" else "en"], E(c["initial_cost"]), f"{c['annual_pct']:.1f}%", str(c["replace_every"]) if c["replace_every"] else "–", f"{(c['replace_pct'] or 0) * 100:.0f}%" if c["replace_every"] else "–"] for c in base["components"]]
        d.table([T("Στοιχείο", "Component"), T("Αρχικό κόστος", "Initial cost"), T("Ετήσια συντήρηση", "Annual maint."), T("Αντικατάσταση (έτη)", "Replace every (y)"), T("Ποσοστό", "Share")], rows, [66, 30, 24, 26, 22])
        L = base["lca"]
        d.H2("6D – Περιβαλλοντικό αποτύπωμα κύκλου ζωής (LCA, EN 15978)", "6D – Life-cycle environmental footprint (LCA, EN 15978)")
        d.P(T(f"Συνολικό αποτύπωμα {F(L['total_kg'] / 1000, 0)} tCO₂e σε {L['horizon']} έτη ({F(L['per_m2_gfa'])} kgCO₂e/m², {L['per_m2_gfa_year']} kgCO₂e/m²·έτος). Ενσωματωμένο: {L['embodied_share_pct']}%· λειτουργικό (B6): {100 - L['embodied_share_pct']:.0f}%. "
              "Οι συντελεστές είναι ενδεικτικοί (τύπου ICE/EPD) και επεξεργάσιμοι· η ηλεκτρική ενέργεια απανθρακοποιείται 2,5%/έτος.",
              f"Total footprint {F(L['total_kg'] / 1000, 0)} tCO₂e over {L['horizon']} years ({F(L['per_m2_gfa'])} kgCO₂e/m², {L['per_m2_gfa_year']} kgCO₂e/m²·y). Embodied: {L['embodied_share_pct']}%; operational (B6): {100 - L['embodied_share_pct']:.0f}%. "
              "Factors are indicative (ICE/EPD-type) and editable; grid electricity decarbonises at 2.5%/y."))
        d.img(_lca_charts(L, lang), 165, ("Αποτύπωμα ανά στάδιο και ανά ομάδα υλικών.", "Footprint by module and material group."))
        rows = [[i["el" if lang == "el" else "en"], f"{F(i['qty'], 1)} {i['unit']}", F(i["kg"] / 1000, 1)] for i in L["by_item"]]
        d.table([T("Κυριότερες συνεισφορές (A1–A3)", "Top contributors (A1–A3)"), T("Ποσότητα", "Quantity"), T("tCO₂e", "tCO₂e")], rows, [90, 40, 30])
        d.story.append(PageBreak())

    # ---- live site data (cadastre, earthquakes, climate)
    lv = project.get("live") or {}
    if "site" in sections and (lv.get("cadastre") or lv.get("seismic") or lv.get("climate")):
        cad, sq, cl = lv.get("cadastre"), lv.get("seismic"), lv.get("climate")
        use = lv.get("use") or {}
        d.H1("Περιοχή του έργου – live δεδομένα", "Project site – live data")
        d.P(T("Η εφαρμογή φέρνει live από δημόσιες υπηρεσίες τα στοιχεία του γεωτεμαχίου (Κτηματολόγιο), το ιστορικό των σεισμών της περιοχής (USGS) και το ιστορικό κλίματος της θέσης (Open-Meteo, ERA5). "
              "Από αυτά υπολογίζονται η σεισμική επικινδυνότητα και το κλίμα της θέσης, που τροφοδοτούν τους κινδύνους (7D) και την ενέργεια (6D).",
              "The app fetches live from public services the parcel data (Hellenic Cadastre), the earthquake history of the area (USGS) and the climate history of the site (Open-Meteo, ERA5). "
              "From them it computes the seismic hazard and the climate of the site, which feed the risks (7D) and the energy (6D)."))
        if cad:
            a = cad.get("attributes") or {}
            d.H2("Κτηματολόγιο", "Cadastre")
            rows = [["ΚΑΕΚ" if lang == "el" else "KAEK", cad["kaek_fmt"]], [T("Εμβαδόν", "Area"), F(cad["area_m2"], 2) + " m²"], [T("Περίμετρος", "Perimeter"), F(cad["perimeter_m"], 2) + " m"],
                    [T("Περιγραφή", "Description"), a.get("DESCR") or "–"], [T("Οριζόντιες ιδιοκτησίες", "Horizontal properties"), str(a.get("PROP_HOR", "–"))],
                    [T("Δήμος / Νομός", "Municipality / prefecture"), f"{(cad.get('ota') or {}).get('OTA_NAME', '–')} / {(cad.get('ota') or {}).get('NOMOS_NAME', '–')}"],
                    [T("Κέντρο (WGS84)", "Centre (WGS84)"), f"{cad['lat']:.6f}, {cad['lon']:.6f}"], [T("Λήψη", "Fetched"), cad["fetched"][:10]]]
            d.table([T("Στοιχείο", "Item"), T("Τιμή", "Value")], rows, [60, 110], align_right_from=9)
            d.P(cad.get("source", ""), "small")
        if sq and sq.get("n"):
            gr = sq.get("gr") or {}
            rp = (gr.get("hazard") or {}).get("pga_for_return_period") or {}
            st_ = sq["strongest_at_site"]; lg = sq["largest"]
            d.H2("Ιστορικό σεισμών και σεισμική επικινδυνότητα", "Earthquake history and seismic hazard")
            d.P(T(f"{sq['n']} σεισμοί M≥4 σε ακτίνα {sq['radius_km']:.0f} km ({sq['period'][0][:4]}–{sq['period'][1][:4]}). Μεγαλύτερος: M {lg['mag']} ({lg['time']}, {lg['dist_km']:.0f} km). "
                  f"Ισχυρότερη επίδραση στη θέση (M≥5): M {st_['mag']} ({st_['time']}, {st_['dist_km']:.0f} km) με PGA ≈ {st_['pga_g']:.3f} g. "
                  f"Gutenberg–Richter (M≥{gr.get('Mc')}, από {gr.get('from_year')}): b = {gr.get('b')}, a = {gr.get('a')}. "
                  f"Καμπύλη επικινδυνότητας (PSHA με τις θέσεις των ιστορικών επικέντρων, Ambraseys 1996): PGA 475 ετών ≈ {rp.get('475')} g (ΕΑΚ ζώνη ΙΙ: 0,24 g), 975 ετών ≈ {rp.get('975')} g.",
                  f"{sq['n']} earthquakes M≥4 within {sq['radius_km']:.0f} km ({sq['period'][0][:4]}–{sq['period'][1][:4]}). Largest: M {lg['mag']} ({lg['time']}, {lg['dist_km']:.0f} km). "
                  f"Strongest effect at the site (M≥5): M {st_['mag']} ({st_['time']}, {st_['dist_km']:.0f} km), PGA ≈ {st_['pga_g']:.3f} g. "
                  f"Gutenberg–Richter (M≥{gr.get('Mc')}, since {gr.get('from_year')}): b = {gr.get('b')}, a = {gr.get('a')}. "
                  f"Hazard curve (PSHA over the historical epicentres, Ambraseys 1996): 475-year PGA ≈ {rp.get('475')} g (Greek code zone II: 0.24 g), 975-year ≈ {rp.get('975')} g."))
            sr = sq.get("scenario_rates") or {}
            if sr:
                scn = hz_mod.load()["seismic"]["scenarios"]
                rows = [[scn.get(k, {}).get("el" if lang == "el" else "en", k), f"{r['Ms']}/{r['distance_km']:.0f}", f"{r['pga_g']:.3f}", f"{(r.get('assumed') or 0) * 100:.2f}%", f"{r['annual_probability'] * 100:.3f}%", F(r["return_period_y"]) if r.get("return_period_y") else "–"] for k, r in sr.items()]
                d.table([T("Σενάριο 7D", "7D scenario"), "Ms/km", "PGA g", T("Ετήσια πιθ. – παραδοχή", "Annual prob. – assumed"), T("– από ιστορικό", "– from history"), T("Περ. επαναφοράς (έτη)", "Return period (y)")], rows, [30, 18, 18, 34, 30, 30], align_right_from=1)
                d.P(T("Στους κινδύνους του 7D χρησιμοποιούνται " + ("οι πιθανότητες από το ιστορικό." if use.get("seismic_rates") else "οι παραδοχές (οι πιθανότητες από το ιστορικό δίνονται για σύγκριση)."),
                      "The 7D risks use " + ("the probabilities from history." if use.get("seismic_rates") else "the assumptions (the probabilities from history are given for comparison).")), "small")
        if cl and cl.get("years"):
            m_, tr = cl["mean"], cl["trend_per_decade"]
            d.H2("Ιστορικό κλίματος της θέσης", "Climate history of the site")
            d.P(T(f"Περίοδος {cl['period'][0]}–{cl['period'][1]}: μέση θερμοκρασία {m_['t_mean']:.1f} °C ({tr['t_mean']:+.2f} °C/δεκαετία), HDD {m_['hdd']:.0f} ({tr['hdd']:+.0f}/δεκαετία), CDD {m_['cdd']:.0f} ({tr['cdd']:+.0f}/δεκαετία), "
                  f"{m_['hot_days_35']:.1f} ημέρες/έτος με Tmax ≥ 35 °C, {m_['tropical_nights']:.0f} τροπικές νύχτες, βροχή {m_['rain_mm']:.0f} mm/έτος (μέγιστη ημερήσια κατά μέσο όρο {m_['rain_max_day_mm']:.0f} mm). "
                  + ("Το 6D υπολογίζεται με το κλίμα της θέσης." if use.get("climate") else "Το 6D υπολογίζεται με το τυπικό κλίμα της μελέτης ΚΕΝΑΚ."),
                  f"Period {cl['period'][0]}–{cl['period'][1]}: mean temperature {m_['t_mean']:.1f} °C ({tr['t_mean']:+.2f} °C/decade), HDD {m_['hdd']:.0f} ({tr['hdd']:+.0f}/decade), CDD {m_['cdd']:.0f} ({tr['cdd']:+.0f}/decade), "
                  f"{m_['hot_days_35']:.1f} days/year with Tmax ≥ 35 °C, {m_['tropical_nights']:.0f} tropical nights, rain {m_['rain_mm']:.0f} mm/year (average maximum daily {m_['rain_max_day_mm']:.0f} mm). "
                  + ("6D uses the site climate." if use.get("climate") else "6D uses the typical climate of the KENAK study.")))
            d.P(f"{cl.get('source', '')} · {cl.get('definitions', '')}", "small")
        d.img(_live_charts(sq if sq and sq.get("n") else None, cl if cl and cl.get("years") else None, lang), 165,
              ("Σεισμοί της περιοχής, καμπύλη σεισμικής επικινδυνότητας της θέσης, κλίμα της θέσης έναντι του τυπικού κλίματος της μελέτης και βαθμοημέρες ανά έτος.",
               "Earthquakes of the area, seismic hazard curve of the site, site climate vs the design climate and degree days per year."))
        d.story.append(PageBreak())

    # ---- 7D facility and asset management
    if "fm" in sections and data.get("fm"):
        f = data["fm"]
        P_ = f["properties"]
        d.H1("Διαχείριση εγκαταστάσεων και περιουσιακών στοιχείων (7D)", "Facility and asset management (7D)")
        d.P(T("Οι ιδιοκτησίες προκύπτουν από τη σύσταση οριζόντιας ιδιοκτησίας (πίνακας ποσοστών και δαπανών). Το κόστος λειτουργίας του 5D επιμερίζεται σε κάθε ιδιοκτησία: τα κοινόχρηστα με τα χιλιοστά της αντίστοιχης στήλης (φωτισμός, ανελκυστήρας, καθαριότητα, συντήρηση, χιλιοστά οικοπέδου, κήπος), τα ιδιωτικά (κουφώματα, δάπεδα, εσωτερικά, θέρμανση/ψύξη, ενέργεια διαμερίσματος) με το εμβαδόν κάθε διαμερίσματος. "
              f"Πηγή: {f.get('source') or ''}",
              "The properties follow the deed of horizontal ownership (table of shares and expenses). The 5D running cost is allocated to each property: common costs by the shares of the matching column (lighting, lift, cleaning, maintenance, plot shares, garden), private costs (windows, floors, fit-out, heating/cooling, apartment energy) by the area of each apartment. "
              f"Source: {f.get('source_en') or ''}"))
        keys = list(f["keys"])
        kl = lambda k: f["keys"][k][0 if lang == "el" else 1]
        rows = [[p["id"], p["name_el" if lang == "el" else "name_en"], F(p.get("total_m2") or p.get("area_m2") or 0, 2)] + [F(p["keys"].get(k, 0)) for k in keys] for p in P_]
        rows.append([T("Σύνολο", "Total"), "", F(sum(p.get("total_m2") or p.get("area_m2") or 0 for p in P_), 2)] + [F(sum(float(p["keys"].get(k, 0) or 0) for p in P_)) for k in keys])
        d.table([T("Κωδ.", "Code"), T("Ιδιοκτησία", "Property"), "m²"] + [kl(k) for k in keys], rows, [12, 40, 16] + [14.5] * len(keys), align_right_from=2, total_last=True)
        d.H2("Επιμερισμός κόστους λειτουργίας ανά ιδιοκτησία", "Running cost per property")
        cats = [("maintenance", "Συντήρηση", "Maint."), ("replacement", "Αντικατ.", "Repl."), ("energy", "Ενέργεια", "Energy"), ("insurance", "Ασφάλ.", "Insur."), ("cleaning", "Καθαρ.", "Clean."), ("measures", "Αναβαθμ.", "Upgr.")]
        rows = [[p["id"]] + [F(p["avg_annual"].get(k, 0)) for k, _, _ in cats] + [F(p["avg_annual_total"]), F(p["eur_per_m2_year"] or 0, 1), F(p["pv_total"]), F(p["risk_eal"])] for p in P_]
        rows.append([T("Σύνολο", "Total")] + [F(sum(p["avg_annual"].get(k, 0) for p in P_)) for k, _, _ in cats] + [F(sum(p["avg_annual_total"] for p in P_)), "", F(sum(p["pv_total"] for p in P_)), F(sum(p["risk_eal"] for p in P_))])
        d.table([T("Ιδιοκτ.", "Prop.")] + [c[1] if lang == "el" else c[2] for c in cats] + [T("€/έτος", "€/y"), "€/m²·" + T("έτος", "y"), T(f"ΠΑ {f['horizon']} ετών", f"PV {f['horizon']} y"), T("Ετ. ζημιά", "EAL")], rows,
                [14, 15, 15, 15, 14, 14, 14, 16, 14, 18, 15], align_right_from=1, total_last=True)
        rc = f["reconciliation"]
        d.P(T(f"Μέσος όρος ανά έτος στον ορίζοντα {f['horizon']} ετών, σε σημερινές τιμές. Έλεγχος: το σύνολο που επιμερίζεται ({E(rc['allocated_total'])}) ισούται με το κόστος λειτουργίας του 5D ({E(rc['building_running_total'])}). Η ετήσια αναμενόμενη ζημιά από τους κινδύνους μοιράζεται με τα χιλιοστά οικοπέδου και δεν περιλαμβάνεται στο σύνολο.",
              f"Yearly average over the {f['horizon']}-year horizon, at today's prices. Check: the allocated total ({E(rc['allocated_total'])}) equals the 5D running cost ({E(rc['building_running_total'])}). The expected annual hazard loss is split by plot shares and is not part of the total."), "small")
        d.H2("Μητρώο εγκαταστάσεων και περιοδικές εργασίες", "Asset register and periodic tasks")
        rows = []
        for a_ in f["assets"]:
            tasks = "; ".join(f"{t['el' if lang == 'el' else 'en']} ({T('κάθε', 'every')} {t['every_months']} {T('μήνες', 'months')})" for t in a_.get("tasks", []))
            rows.append([a_["el" if lang == "el" else "en"], tasks, E(a_["initial_cost"]) if a_.get("initial_cost") is not None else "–", str(a_.get("replace_every") or "–")])
        d.table([T("Εγκατάσταση", "Asset"), T("Περιοδικές εργασίες", "Periodic tasks"), T("Αξία", "Value"), T("Αντικ. (έτη)", "Repl. (y)")], rows, [34, 96, 22, 18], align_right_from=2)
        d.H2("Ημερολόγιο επεμβάσεων (πρώτα 30 έτη)", "Works calendar (first 30 years)")
        rows = [[str(e["year"]), e["el" if lang == "el" else "en"], T("Αντικατάσταση", "Replacement") if e["action"] == "replacement" else T("Επιθεώρηση", "Inspection"), E(e["cost"])] for e in f["calendar"] if e["year"] <= 30]
        d.table([T("Έτος", "Year"), T("Στοιχείο", "Component"), T("Εργασία", "Work"), T("Κόστος", "Cost")], rows, [16, 90, 34, 30], align_right_from=3)
        d.story.append(PageBreak())

    # ---- 8 hazards
    if "hazards" in sections:
        seis, fi, wild, fl, risk = data["seismic"], data["fire_internal"], data["wildfire"], data["flood"], data["risk"]
        d.H1("7D – Κίνδυνοι: σενάρια και συμπεριφορά του κτιρίου", "7D – Risks: hazard scenarios and building behaviour")
        d.P(T("Εκτίμηση ζημιών σε επίπεδο προμελέτης για τη φάση χρήσης και συντήρησης. Τα αποτελέσματα δίνουν τάξη μεγέθους και συγκριτικό όφελος μέτρων, όχι έλεγχο επάρκειας.", "Screening-level damage estimates for the use and maintenance phases. Results indicate order of magnitude and relative benefit of measures, not a code compliance check."))
        d.H2("Σεισμός – τρία σενάρια", "Earthquake – three scenarios")
        r0 = seis["runs"]["moderate"]
        _hs = hz_mod.load()["seismic"]; cl = (_hs["code_level_labels"] if lang == "el" else _hs.get("code_level_labels_en", _hs["code_level_labels"])).get(r0["code_level"], r0["code_level"])
        d.P(T(f"Κατηγορία κανονισμού: {cl} (τρωτότητα LM1 V={r0['vulnerability_index']}), έδαφος {r0['soil']}, a<sub>g</sub> σχεδιασμού {project['meta']['structure']['a_g']} g. "
              "Η επιτάχυνση εδάφους υπολογίζεται με τη σχέση απόσβεσης Ambraseys et al. (1996), η βλάβη με λογαριθμοκανονικές καμπύλες τρωτότητας ανά κατηγορία ΕΑΚ και ως διασταύρωση με το μακροσεισμικό μοντέλο Lagomarsino–Giovinazzi (LM1).",
              f"Code level: {cl} (LM1 vulnerability V={r0['vulnerability_index']}), soil {r0['soil']}, design a<sub>g</sub> {project['meta']['structure']['a_g']} g. "
              "Ground motion uses the Ambraseys et al. (1996) attenuation relation; damage uses lognormal fragility curves by code level, cross-checked with the Lagomarsino–Giovinazzi (LM1) macroseismic model."))
        if r0.get("capacity"):
            d.P(T("Οι διάμεσες τιμές PGA των καμπυλών τρωτότητας προέρχονται από την αντοχή του ίδιου του κτιρίου (επόμενη υποενότητα), όχι από γενικές τιμές της βιβλιογραφίας· το κτίριο είναι σχεδιασμένο οριακά (χρησιμοποίηση ≈1,0), γι' αυτό οι ζημιές είναι μεγαλύτερες από των γενικών καμπυλών ΕΑΚ 2000+.",
                  "The median PGAs of the fragility curves come from the capacity of the building itself (next subsection), not from generic literature values; the building is designed at its limit (utilisation ≈1.0), hence damage is larger than the generic EAK 2000+ curves give."), "small")
        rows = []
        for k in ("small", "moderate", "large"):
            r = seis["runs"][k]
            rows.append([r["label_el" if lang == "el" else "label_en"], f"{r['Ms']}/{r['distance_km']:.0f}", f"{r['pga_g']:.3f} ({r['pga_over_design']:.2f}×)", f"{r['intensity_mmi']}", f"{r['mean_grade']:.2f}", f"{r['p_d3plus'] * 100:.0f}%", E(r["loss_eur"]), f"{r['loss_ratio'] * 100:.1f}%", f"{r['downtime_days']}"])
        d.table([T("Σενάριο", "Scenario"), "Ms/km", "PGA g (×a<sub>g</sub>)", "MMI", T("Μ. βαθμός", "Mean grade"), "P(D≥3)", T("Ζημιά", "Loss"), T("Λόγος", "Ratio"), T("Ημέρες εκτός", "Days out")], rows, [30, 14, 26, 11, 16, 14, 22, 14, 13], align_right_from=1)
        d.img(_seismic_charts(seis, r0, lang), 165, ("Φάσματα απόκρισης σεναρίων έναντι σχεδιασμού ΕΑΚ και κατανομή βαθμών βλάβης (0–5).", "Scenario response spectra vs. EAK design and damage-grade distribution (0–5)."))
        mk = seis["runs"]["large"]["markers"]
        d.P(T("Δείκτης ζήτησης/ικανότητας (μεγάλος σεισμός): " + "; ".join(f"{m['name']}: T={m['T']} s, Sa={m['Sa_scenario_g']} g, ζήτηση/ικανότητα {m['demand_to_capacity']} (απαιτούμενη όλκιμότητα {m['ductility_demand']})" for m in mk),
              "Demand/capacity indicator (large earthquake): " + "; ".join(f"{m['name']}: T={m['T']} s, Sa={m['Sa_scenario_g']} g, demand/capacity {m['demand_to_capacity']} (ductility demand {m['ductility_demand']})" for m in mk)), "small")
        rows = [[s["name_el" if lang == "el" else "name_en"]] + [f"{seis['runs'][k]['storeys'][i]['mean_grade']:.2f}" for k in ("small", "moderate", "large")] + [E(seis["runs"]["large"]["storeys"][i]["loss_eur"])] for i, s in enumerate(seis["runs"]["large"]["storeys"])]
        d.table([T("Όροφος", "Storey"), T("Μ. βαθμός – μικρός", "Mean grade – small"), T("μέτριος", "moderate"), T("μεγάλος", "large"), T("Ζημιά (μεγάλος)", "Loss (large)")], rows, [48, 32, 24, 24, 32])

        cap = r0.get("capacity")
        if cap:
            d.H2("Αντοχή σε σεισμό και μέγεθος σε Ρίχτερ", "Seismic resistance and magnitude (Richter)")
            rb = cap["method"] == "rebar_model"
            rep = cap["method"] == "static_report" or rb
            ds = cap["design"]
            if rb:
                R = cap["rebar"]
                d.P(T(f"Η αντοχή υπολογίζεται από τον πραγματικό σκελετό των ξυλοτύπων Σ.01–Σ.06: {len(R['elements'])} υποστυλώματα/τοιχώματα με τη διατομή, τα διαμήκη σίδερα και τους συνδετήρες τους, και {R['joints']['checked']} κόμβοι δοκών–υποστυλωμάτων. "
                      f"Για κάθε στοιχείο: ροπή αντοχής με ανάλυση ινών της πραγματικής διατομής (fcm={R['design']['fcm']:.0f} MPa, fym={R['design']['fym']:.0f} MPa) και διατμητική αντοχή από τους συνδετήρες· η αντοχή του ορόφου είναι το άθροισμα στον μηχανισμό. "
                      f"Διαρροή: PGA {cap['pga_g']['yield']:.3f} g ({cap['pga_over_design']['yield']:.2f}×a<sub>g</sub>)· οιονεί κατάρρευση: PGA {cap['pga_g']['collapse']:.3f} g ({cap['pga_over_design']['collapse']:.2f}×a<sub>g</sub>). Κρίσιμος: {cap['weakest_storey_name_el']}. "
                      f"(Με τη μέθοδο των λόγων εκμετάλλευσης του τεύχους: {cap['report_based']['pga_g']['yield']:.3f} g / {cap['report_based']['pga_g']['collapse']:.3f} g.)",
                      f"Resistance is computed from the real skeleton of the formwork drawings S.01–S.06: {len(R['elements'])} columns/walls with their section, longitudinal bars and stirrups, and {R['joints']['checked']} beam–column joints. "
                      f"For each member: flexural resistance by fibre analysis of the real section (fcm={R['design']['fcm']:.0f} MPa, fym={R['design']['fym']:.0f} MPa) and shear resistance from the stirrups; the storey resistance is their sum in the mechanism. "
                      f"Yield: PGA {cap['pga_g']['yield']:.3f} g ({cap['pga_over_design']['yield']:.2f}×a<sub>g</sub>); near-collapse: PGA {cap['pga_g']['collapse']:.3f} g ({cap['pga_over_design']['collapse']:.2f}×a<sub>g</sub>). Critical: {cap['weakest_storey_name_en']}. "
                      f"(With the report-utilisation method: {cap['report_based']['pga_g']['yield']:.3f} g / {cap['report_based']['pga_g']['collapse']:.3f} g.)"))
                rows = [[s["name_el" if lang == "el" else "name_en"], str(s["elements"]), F(s["Vd_x_kN"]), F(s["V_R_x_kN"]), F(s["ratio_x"], 2), F(s["V_R_y_kN"]), F(s["ratio_y"], 2), f"{s['a_y_x']:.3f}/{s['a_y_y']:.3f}", f"{s['a_c_x']:.3f}/{s['a_c_y']:.3f}"] for s in R["storeys"]]
                d.table([T("Όροφος", "Storey"), T("Μέλη", "Members"), "V<sub>d</sub> kN", "V<sub>R,x</sub> kN", "x/V<sub>d</sub>", "V<sub>R,y</sub> kN", "y/V<sub>d</sub>", T("Διαρροή x/y g", "Yield x/y g"), T("Κατάρρ. x/y g", "Collapse x/y g")], rows, [26, 14, 18, 20, 14, 20, 14, 24, 24])
                if R.get("corrections"):
                    d.P(T("Ασυμφωνίες των σχεδίων και πώς λύθηκαν: ", "Drawing inconsistencies and how they were resolved: ") + " ".join(c["el" if lang == "el" else "en"] for c in R["corrections"]), "small")
                J = R["joints"]
                d.P(T(f"Ικανοτικός έλεγχος κόμβων ΣM<sub>Rc</sub> ≥ 1,3·ΣM<sub>Rb</sub>: {J['checked']} κόμβοι, {J['below_1_3']} κάτω από 1,3 και {J['below_1_0']} κάτω από 1,0 (" + ", ".join(f"{j['id']} {j['storey']} {j['dir'].upper()}: {j['ratio']}" for j in J["worst"] if j["ratio"] < 1.0) + ").",
                      f"Capacity design of joints ΣM<sub>Rc</sub> ≥ 1.3·ΣM<sub>Rb</sub>: {J['checked']} joints, {J['below_1_3']} below 1.3 and {J['below_1_0']} below 1.0 (" + ", ".join(f"{j['id']} {j['storey']} {j['dir'].upper()}: {j['ratio']}" for j in J["worst"] if j["ratio"] < 1.0) + ")."), "small")
            elif rep:
                d.P(T(f"Η αντοχή προκύπτει από τους ελέγχους του τεύχους στατικών ({cap['program']}, {cap['members']} έλεγχοι υποστυλωμάτων/τοιχωμάτων σε {len(cap['storeys'])} στάθμες) στον σεισμό σχεδιασμού a<sub>g</sub>={ds['a_g']} g, q={ds['q']}, έδαφος {ds['soil']}, ζώνη {ds['zone']}. "
                      f"Πρώτη διαρροή (το πιο φορτισμένο μέλος): PGA {cap['pga_g']['yield']:.3f} g ({cap['pga_over_design']['yield']:.2f}×a<sub>g</sub>). Εξάντληση πλαστιμότητας (οιονεί κατάρρευση): PGA {cap['pga_g']['collapse']:.3f} g ({cap['pga_over_design']['collapse']:.2f}×a<sub>g</sub>), με υπεραντοχή μηχανισμού λ={cap['lambda']['mechanism']:.2f}, Ω={cap['material_factor']:.2f}. Κρίσιμος όροφος: {cap['weakest_storey_name_el']}.",
                      f"Resistance is derived from the member checks of the static report ({cap['program']}, {cap['members']} column/wall checks in {len(cap['storeys'])} levels) at the design earthquake a<sub>g</sub>={ds['a_g']} g, q={ds['q']}, soil {ds['soil']}, zone {ds['zone']}. "
                      f"First yield (most stressed member): PGA {cap['pga_g']['yield']:.3f} g ({cap['pga_over_design']['yield']:.2f}×a<sub>g</sub>). Ductility exhausted (near-collapse): PGA {cap['pga_g']['collapse']:.3f} g ({cap['pga_over_design']['collapse']:.2f}×a<sub>g</sub>), mechanism overstrength λ={cap['lambda']['mechanism']:.2f}, Ω={cap['material_factor']:.2f}. Critical storey: {cap['weakest_storey_name_en']}."))
            else:
                d.P(T(f"Χωρίς τεύχος στατικών: χονδρική εκτίμηση από τις διατομές του μοντέλου (±2×). Πρώτη διαρροή PGA {cap['pga_g']['yield']:.3f} g, οιονεί κατάρρευση {cap['pga_g']['collapse']:.3f} g.",
                      f"No static report: rough estimate from the model sections (±2×). First yield PGA {cap['pga_g']['yield']:.3f} g, near-collapse {cap['pga_g']['collapse']:.3f} g."))
            fm = lambda v: (f"{v:.1f}" if v <= 7.5 else "> 7,5" if lang == "el" else "> 7.5")
            rows = [[f"{x['distance_km']:.0f} km", fm(x["yield"]), f"{fm(x['yield_lo'])} – {fm(x['yield_hi'])}", fm(x["collapse"]), f"{fm(x['collapse_lo'])} – {fm(x['collapse_hi'])}"] for x in cap["limits"]]
            d.table([T("Απόσταση επικέντρου", "Epicentral distance"), T("Ms πρώτης διαρροής", "Ms first yield"), "±1σ", T("Ms οιονεί κατάρρευσης", "Ms near-collapse"), "±1σ"], rows, [40, 30, 30, 35, 30])
            d.img(_richter_chart(cap, lang), 165, ("Μέγεθος σεισμού (Ms, «Ρίχτερ») που φέρνει το κτίριο σε κάθε κατάσταση, ανά απόσταση επικέντρου (σκιά: ±1σ της σχέσης απόσβεσης).", "Earthquake magnitude (Ms, “Richter”) bringing the building to each state, by epicentral distance (band: ±1σ of the attenuation law)."))
            if rep and not rb:
                rows = [[s["name_el" if lang == "el" else "name_en"], F(s["dh_m"], 2), F(s["W_kN"]), F(s["Vx_kN"]), str(s["members"]), F(s["u_flex_max"], 2), F(s["u_flex_mean"], 2), F(s["u_shear_max"], 2)] for s in cap["storeys"]]
                d.table([T("Στάθμη", "Level"), "dh (m)", "W (kN)", "V<sub>Ed</sub> (kN)", T("Μέλη", "Members"), T("Κάμψη max", "Flexure max"), T("Κάμψη μέση", "Flexure mean"), T("Διάτμηση max", "Shear max")], rows, [30, 14, 20, 22, 14, 22, 22, 22])
            d.P("<br/>".join(cap["assumptions_el" if lang == "el" else "assumptions_en"]), "small")

        d.H2("Εσωτερική πυρκαγιά", "Internal fire")
        d.P(T(f"Θάλαμος πυρκαγιάς {fi['compartment_area_m2']} m² ({fi['storey_name_el']}), πυροφορτίο q<sub>f,d</sub> = {fi['q_fd_MJ_m2']:.0f} MJ/m², παράγοντας ανοιγμάτων O = {fi['opening_factor']}. "
              f"Παραμετρική πυρκαγιά (EC1-1-2 Παρ. Α): μέγιστη θερμοκρασία {fi['theta_max_C']} °C, διάρκεια πλήρους ανάπτυξης {fi['t_max_min']} min, ισοδύναμος χρόνος πρότυπης πυρκαγιάς {fi['t_e_min']} min "
              f"(ενεργός {fi['t_e_effective_min']} min μετά την κατάσβεση). Πυραντίσταση υποστυλωμάτων R{fi['R_provided_min']:.0f} (απαιτούμενη R{fi['R_required_min']:.0f}), μικρότερη διάσταση {fi['min_column_dim_mm']} mm. "
              f"Αναμενόμενη ζημιά {E(fi['loss_eur'])} ({fi['loss_ratio'] * 100:.1f}% της αξίας), μη χρήση ≈{fi['downtime_days']} ημέρες.",
              f"Fire compartment {fi['compartment_area_m2']} m² ({fi['storey_name_en']}), fire load q<sub>f,d</sub> = {fi['q_fd_MJ_m2']:.0f} MJ/m², opening factor O = {fi['opening_factor']}. "
              f"Parametric fire (EC1-1-2 Annex A): peak temperature {fi['theta_max_C']} °C, fully-developed duration {fi['t_max_min']} min, equivalent standard-fire time {fi['t_e_min']} min "
              f"(effective {fi['t_e_effective_min']} min after suppression). Column fire resistance R{fi['R_provided_min']:.0f} (required R{fi['R_required_min']:.0f}), smallest dimension {fi['min_column_dim_mm']} mm. "
              f"Expected loss {E(fi['loss_eur'])} ({fi['loss_ratio'] * 100:.1f}% of value), downtime ≈{fi['downtime_days']} days."))
        d.H2("Δασική πυρκαγιά στην ευρύτερη περιοχή", "Wildfire in the wider area")
        d.P(T(f"Ένταση μετώπου {wild['intensity_kW_m']:.0f} kW/m → μήκος φλόγας {wild['flame_length_m']} m, απόσταση από βλάστηση {wild['distance_m']} m (ενεργός {wild['effective_distance_m']} m), "
              f"ροή θερμότητας στην όψη <b>{wild['flux_kW_m2']} kW/m²</b> → κατηγορία <b>{wild['bal']}</b> (AS 3959). Πιθανότητα ανάφλεξης από ωλοκάρβουνα {wild['ember_probability'] * 100:.0f}%. "
              f"Αναμενόμενη ζημιά {E(wild['loss_eur'])} ({wild['loss_ratio'] * 100:.1f}%).",
              f"Fire-line intensity {wild['intensity_kW_m']:.0f} kW/m → flame length {wild['flame_length_m']} m, distance to vegetation {wild['distance_m']} m (effective {wild['effective_distance_m']} m), "
              f"facade heat flux <b>{wild['flux_kW_m2']} kW/m²</b> → class <b>{wild['bal']}</b> (AS 3959). Ember ignition probability {wild['ember_probability'] * 100:.0f}%. Expected loss {E(wild['loss_eur'])} ({wild['loss_ratio'] * 100:.1f}%)."))
        d.img(_fire_charts(fi, wild, lang), 165, ("Αριστερά: καμπύλη θερμοκρασίας–χρόνου του θαλάμου. Δεξιά: ροή θερμότητας από δασική πυρκαγιά συναρτήσει της απόστασης.", "Left: compartment time–temperature curve. Right: wildfire heat flux vs. distance."))
        rows = [[m["el" if lang == "el" else "en"], f"{m['threshold_kW_m2']}", T("ΥΠΕΡΒΑΣΗ", "EXCEEDED") if m["exceeded"] else T("ΟΚ", "OK")] for m in wild["materials"]]
        d.table([T("Υλικό / στοιχείο", "Material / element"), T("Όριο (kW/m²)", "Limit (kW/m²)"), T("Κατάσταση", "Status")], rows, [90, 35, 35])

        d.H2("Πλημμύρα", "Flood")
        rows = []
        for k in ("minor", "moderate", "severe"):
            r = fl["runs"][k]
            rows.append([r["label_el" if lang == "el" else "label_en"], f"{r['depth_m']} m", f"{r['basement_flooded_m']} m", E(r["loss_eur"]), f"{r['loss_ratio'] * 100:.1f}%", str(r["downtime_days"])])
        d.table([T("Σενάριο", "Scenario"), T("Βάθος", "Depth"), T("Υπόγειο", "Basement"), T("Ζημιά", "Loss"), T("Λόγος", "Ratio"), T("Ημέρες εκτός", "Days out")], rows, [54, 18, 20, 30, 18, 22])
        d.img(_flood_chart(fl, lang), 160, ("Καμπύλη βάθους–ζημιάς (τύπου JRC) και αναμενόμενη ζημιά ανά σενάριο.", "Depth–damage curve (JRC-type) and expected loss per scenario."))

        d.H2("Συνολικός κίνδυνος και μέτρα προστασίας", "Overall risk and mitigation")
        exp = risk["exposure"]
        d.P(T(f"Αναμενόμενη ετήσια ζημιά (EAL) = Σ πιθανότητα × ζημιά, με συντελεστές έκθεσης θέσης: σεισμός {exp['seismic']}, εσωτ. φωτιά {exp['fire_internal']}, δασική {exp['wildfire']}, πλημμύρα {exp['flood']} (επεξεργάσιμοι). "
              f"Σύνολο: <b>{E(risk['total_eal_eur'])}/έτος</b>. Το όφελος των μέτρων υπολογίζεται ως μείωση της EAL προεξοφλημένη στο ορίζοντα.",
              f"Expected annual loss (EAL) = Σ probability × loss, with site exposure multipliers: earthquake {exp['seismic']}, internal fire {exp['fire_internal']}, wildfire {exp['wildfire']}, flood {exp['flood']} (editable). "
              f"Total: <b>{E(risk['total_eal_eur'])}/year</b>. Mitigation benefit is the discounted reduction of EAL over the horizon."))
        d.img(_risk_charts(risk, lang), 165)
        rows = [[m["el" if lang == "el" else "en"], E(m["cost_eur"]), E(m["eal_reduction_eur_year"]), E(m["benefit_eur"]), F(m["bcr"], 2) if m["bcr"] is not None else "–"] for m in risk["mitigations"]]
        d.table([T("Μέτρο", "Measure"), T("Κόστος", "Cost"), T("Μείωση EAL/έτος", "EAL reduction/y"), T("Όφελος", "Benefit"), "BCR"], rows, [66, 24, 28, 28, 14])
        d.story.append(PageBreak())

    # ---- 9 assumptions
    if "assumptions" in sections:
        d.H1("Παραδοχές, πηγές και περιορισμοί", "Assumptions, sources and limitations")
        a_el = [
            "<b>Γεωμετρία:</b> το μοντέλο ταξινομεί στοιχεία από layers/ονόματα· ποσότητες από όγκους/επιφάνειες των ματιών (meshes). Οι συντελεστές οπλισμού, μόνωσης και τοιχοποιιών είναι παραδοχές (επεξεργάσιμες).",
            "<b>Κόστος:</b> ενδεικτικό τιμολόγιο αγοράς Αττικής (βάση 2025-09), προσαρμοσμένο με τους δείκτες ΕΛΣΤΑΤ υλικών κατασκευής νέων κατοικιών (τελευταία ανακοίνωση που έχει καταχωριστεί: Σεπ 2026) και, προαιρετικά, με διεθνείς τιμές εμπορευμάτων (Yahoo Finance, TradingEconomics, ENTSO-E). Οι τιμές βάσης δεν είναι προσφορές εργολάβων ούτε επίσημο τιμολόγιο· το κόστος ανά m² δεν περιλαμβάνει αμοιβές, τέλη αδειοδότησης, οικόπεδο και αντιστήριξη εκσκαφής.",
            "<b>Ενέργεια:</b> μηνιαίο ισοζύγιο ISO 13790 βαθμονομημένο στο πιστοποιητικό ΚΕΝΑΚ (προσέγγιση διαφορών). Συντελεστές πρωτογενούς ενέργειας: ηλεκτρισμός 2,9, φυσικό αέριο 1,1. Κλίμακα κλάσεων από λόγο προς κτίριο αναφοράς (Α+ ≤0,33 … Η >2,55).",
            "<b>Κύκλος ζωής:</b> EN 15459 (προεξόφληση, κόστη συντήρησης/αντικατάστασης) και EN 15978 (στάδια A–D). Συντελεστές άνθρακα τύπου ICE/EPD, ενδεικτικοί.",
            "<b>Σεισμός:</b> Ambraseys et al. (1996), Wald et al. (1999), καμπύλες τρωτότητας ανά κατηγορία κανονισμού, Lagomarsino &amp; Giovinazzi (2006). Μετρίου βαθμού εμπιστοσύνης· δεν υποκαθιστά ΚΑΝ.ΕΠΕ.",
            "<b>Φωτιά:</b> EC1-1-2 (παραμετρική πυρκαγιά, ισοδύναμη διάρκεια), Byram (μήκος φλόγας), συντελεστής όψης συμπαγούς φλόγας, κατηγορίες BAL (AS 3959). <b>Πλημμύρα:</b> καμπύλες βάθους–ζημιάς τύπου JRC.",
            "<b>Περιορισμοί:</b> τα αποτελέσματα είναι ενδεικτικά (προμελέτη). Για αδειοδότηση, πιστοποίηση ή τεχνικές αποφάσεις απαιτούνται οι αντίστοιχες μελέτες από αρμόδιους μηχανικούς.",
        ]
        a_en = [
            "<b>Geometry:</b> the model classifies elements from layers/names; quantities come from mesh volumes/areas. Rebar, insulation and masonry factors are editable assumptions.",
            "<b>Cost:</b> indicative Attica market price book (base 2025-09) adjusted with the ELSTAT materials indices for new residential buildings (latest entered release: Sep 2026) and, optionally, international commodity prices (Yahoo Finance, TradingEconomics, ENTSO-E). Base prices are not contractor quotes nor an official price list; the cost per m² excludes professional fees, permit charges, land and excavation shoring.",
            "<b>Energy:</b> ISO 13790 monthly balance calibrated to the KENAK certificate (delta approach). Primary energy factors: electricity 2.9, natural gas 1.1. Class scale from the ratio to the reference building (A+ ≤0.33 … H >2.55).",
            "<b>Life cycle:</b> EN 15459 (discounting, maintenance/replacement costs) and EN 15978 (modules A–D). Carbon factors ICE/EPD-type, indicative.",
            "<b>Earthquake:</b> Ambraseys et al. (1996), Wald et al. (1999), fragility curves by code level, Lagomarsino &amp; Giovinazzi (2006). Moderate confidence; does not replace KAN.EPE.",
            "<b>Fire:</b> EC1-1-2 (parametric fire, equivalent duration), Byram (flame length), solid-flame view factor, BAL classes (AS 3959). <b>Flood:</b> JRC-type depth–damage curves.",
            "<b>Limitations:</b> results are indicative (pre-design). Permits, certification or technical decisions require the corresponding studies by competent engineers.",
        ]
        for s in (a_el if lang == "el" else a_en):
            d.P("• " + s)
        d.H2("Πηγές δεδομένων", "Data sources")
        src = [("Πίνακας ποσοστών και δαπανών του κτιρίου (σύσταση οριζόντιας ιδιοκτησίας, Ιανουάριος 2024)", "Table of shares and expenses of the building (deed of horizontal ownership, January 2024)"),
               ("ΕΛΣΤΑΤ – Δείκτες τιμών υλικών κατασκευής νέων κατοικιών", "ELSTAT – Construction materials price indices for new residential buildings"),
               ("TradingEconomics – Steel rebar (εμπορεύματα)", "TradingEconomics – Steel rebar (commodities)"), ("ENTSO-E Transparency Platform – τιμές ηλεκτρισμού day-ahead", "ENTSO-E Transparency Platform – day-ahead electricity prices"),
               ("Yahoo Finance – συμβόλαια χαλκού, αλουμινίου, Brent", "Yahoo Finance – copper, aluminium, Brent futures"), ("Μελέτες του έργου: ΚΕΝΑΚ, στατική μελέτη, ξυλότυποι, χρονοδιάγραμμα, πυροπροστασία", "Project studies: KENAK, structural design, formwork, schedule, fire protection")]
        for el, en_ in src:
            d.P("• " + T(el, en_), "small")
    return d.build()


def _openings_table(d, project: dict, lang: str, T) -> None:
    """Schedule of the openings (windows, balcony doors, doors) with sizes, sills, counts per storey and lintels."""
    els = project["elements"]
    if not any((e.get("props") or {}).get("opening") for e in els):
        return
    F = lambda x, n=0: fmt(x, n, lang)
    keys = [s["key"] for s in project["storeys"]]
    sid_key = {s["id"]: s["key"] for s in project["storeys"]}
    names = {"window": ("Παράθυρο", "Window"), "balcony_door": ("Μπαλκονόπορτα / συρόμενο", "Balcony / sliding door"), "entrance": ("Είσοδος κτιρίου (αλουμίνιο–τζάμι)", "Entrance (aluminium/glass)"),
             "garage_door": ("Πόρτα γκαράζ (ρολό)", "Garage door (roller)"), "apartment_entrance": ("Πόρτα ασφαλείας διαμερίσματος", "Apartment security door"), "interior_door": ("Εσωτερική πόρτα", "Interior door")}
    order = list(names)
    groups: dict[tuple, dict] = {}
    for e in els:
        pr = e.get("props") or {}
        typ = pr.get("opening")
        if not typ or pr.get("lintel"):
            continue
        w, h = pr.get("w_m") or e["qty"].get("width_m", 0), pr.get("h_m") or e["qty"].get("height_m", 0)
        g = groups.setdefault((order.index(typ) if typ in order else 99, typ, round(w, 2), round(h, 2), round(pr.get("sill_m", 0.0), 2)), {"n": defaultdict(int), "area": 0.0})
        g["n"][sid_key.get(e.get("storey"), "?")] += 1
        g["area"] += e["qty"].get("area_m2", w * h)
    sh = {"basement": ("Υπ", "B"), "ground": ("Ισ", "G"), "first": ("Α΄", "1"), "second": ("Β΄", "2"), "attic": ("Σοφ", "A")}
    rows, tot_n, tot_a = [], 0, 0.0
    per_storey: dict[str, int] = defaultdict(int)
    for (_, typ, w, h, sill), g in sorted(groups.items()):
        n = sum(g["n"].values())
        tot_n += n
        tot_a += g["area"]
        for k_, v_ in g["n"].items():
            per_storey[k_] += v_
        rows.append([names.get(typ, (typ, typ))[0 if lang == "el" else 1], f"{w:.2f} × {h:.2f}".replace(".", ",") if lang == "el" else f"{w:.2f} × {h:.2f}", F(sill, 2)] +
                    [str(g["n"].get(k, "")) for k in keys] + [str(n), F(g["area"], 1)])
    rows.append([T("Σύνολο", "Total"), "", ""] + [str(per_storey.get(k, "")) for k in keys] + [str(tot_n), F(tot_a, 1)])
    d.H2("Κατάλογος ανοιγμάτων (από τις κατόψεις)", "Schedule of openings (from the floor plans)")
    d.P(T("Θέση και πλάτος κάθε ανοίγματος διαβάστηκαν από τις κατόψεις (κενά τοίχων, τόξα ανοίγματος θυρών)· ύψη και ποδιές από τον πίνακα κουφωμάτων της ενεργειακής μελέτης και τις όψεις (κεφαλή +2,50 m πάνω από το δάπεδο). Οι τοίχοι κόβονται γύρω από τα ανοίγματα, οπότε οι επιφάνειες τοιχοποιίας, επιχρισμάτων και χρωματισμών είναι καθαρές.",
          "Position and width of every opening were read from the floor plans (wall gaps, door-swing arcs); heights and sills come from the window schedule of the energy study and from the elevations (head at +2.50 m above the floor). Walls are cut around the openings, so masonry, plaster and paint areas are net."), "small")
    d.table([T("Τύπος", "Type"), T("Π × Υ (m)", "W × H (m)"), T("Ποδιά (m)", "Sill (m)")] + [sh.get(k, (k, k))[0 if lang == "el" else 1] for k in keys] + [T("Σύν.", "Total"), T("m²", "m²")],
            rows, [46, 24, 15] + [9] * len(keys) + [12, 16], align_right_from=2, total_last=True)
    lint = [e for e in els if (e.get("props") or {}).get("lintel")]
    if lint:
        ext = [e for e in lint if e["props"].get("opening") != "interior_door"]
        inn = [e for e in lint if e["props"].get("opening") == "interior_door"]
        f = lambda es, k: sum(e["qty"].get(k, 0.0) for e in es)
        d.story.append(Spacer(1, 6))
        d.table([T("Πρέκια (οπλισμένο σκυρόδεμα)", "Lintels (reinforced concrete)"), T("Πλήθος", "Count"), T("Μήκος (m)", "Length (m)"), T("Σκυρόδεμα (m³)", "Concrete (m³)")],
                [[T("Εξωτερικά ανοίγματα (0,20 × 0,20 m, έδραση 0,20 m)", "Exterior openings (0.20 × 0.20 m, bearing 0.20 m)"), str(len(ext)), F(f(ext, "length_m"), 1), F(f(ext, "volume_m3"), 2)],
                 [T("Εσωτερικές πόρτες (πάχος τοίχου × 0,15 m)", "Interior doors (wall thickness × 0.15 m)"), str(len(inn)), F(f(inn, "length_m"), 1), F(f(inn, "volume_m3"), 2)],
                 [T("Σύνολο", "Total"), str(len(lint)), F(f(lint, "length_m"), 1), F(f(lint, "volume_m3"), 2)]], [84, 22, 24, 28], total_last=True)
