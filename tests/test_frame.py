"""Structural skeleton read from the formwork drawings S.01–S.06 and the seismic resistance from the real reinforcement."""
from shapely.geometry import Polygon

from app import demo, frame_capacity as fc, structural


def test_frame_from_the_formwork_drawings():
    fr = fc.load_frame()
    n = {k: (len(v["columns"]), len(v["beams"])) for k, v in fr["levels"].items()}
    assert n["basement"] == (30, 18) and n["ground"][0] == 20 and n["first"][0] == 14 and n["second"][0] == 14 and n["attic"][0] == 8
    # every column of a storey stands on a column of the storey below (registration of the six sheets)
    order = ["basement", "ground", "first", "second", "attic"]
    for lo, up in zip(order, order[1:]):
        below = [Polygon(c["poly"]).buffer(0) for c in fr["levels"][lo]["columns"]]
        for c in fr["levels"][up]["columns"]:
            P = Polygon(c["poly"]).buffer(0)
            assert max(P.intersection(Q).area for Q in below) > 0.9 * P.area, (up, c["id"])
    # sections of the drawing = sections of the column table, columns inside the basement outline of the architecture
    base = demo._poly(demo.G["basement"]).buffer(0.05)
    for c in fr["levels"]["basement"]["columns"]:
        P = Polygon(c["poly"])
        assert c.get("long_bars") and c.get("stirrup_d")
        if c["id"] not in ("K25", "K26", "K27", "K28", "K29", "K30"):          # light-well columns outside the basement box
            assert base.contains(P.centroid), c["id"]


def test_resistance_from_the_reinforcement():
    cap = fc.analyse(fc.load_frame(), structural.load_demo(), fc.floors_from_demo())
    pg = cap["pga_g"]
    assert 0.1 < pg["yield"] < pg["collapse"] and pg["collapse"] > 0.24          # survives the design earthquake
    st = {s["key"]: s for s in cap["storeys"]}
    assert st["basement"]["V_R_x_kN"] > 3 * st["ground"]["V_R_x_kN"]           # the basement box with its RC walls is far stronger
    assert all(s["ratio_x"] > 1.0 and s["ratio_y"] > 1.0 for s in cap["storeys"])
    assert cap["joints"]["checked"] > 40
    e = next(e for e in cap["elements"] if e["storey"] == "ground" and e["id"] == "K1")
    assert 150 < e["M_R_x"] < 450 and e["long"] == "8Φ18"
