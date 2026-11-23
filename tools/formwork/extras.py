"""Extra top bars over the supports of the beams: texts like «2Φ16» drawn on a bracket line that crosses the support."""
import re, glob, math
import pymupdf
from segs import segments
from sheet import extract, SHEETS
from reg import register, PT
def extra_bars(key):
    e=extract(SHEETS[key]); p,m=e['p'],e['m']
    (X0,_,_),(Y0,_,_)=register(e)
    f=lambda x,y: ((x-X0)/PT,(Y0-y)/PT)
    segs=[s for s in segments(SHEETS[key]) if s[4]<=0.6]
    d=p.get_text("dict"); out=[]
    for b in d["blocks"]:
        for l in b.get("lines",[]):
            t="".join(s["text"] for s in l["spans"]).strip()
            if not re.fullmatch(r"\d+Φ\d+(\+\d+Φ\d+)?",t): continue
            r=pymupdf.Rect(l["bbox"])*m
            if not e['region'].contains(pymupdf_point(r)): continue
            dx,dy=l["dir"]; v=pymupdf.Point(dx,dy)*pymupdf.Matrix(m.a,m.b,m.c,m.d,0,0)
            horiz=abs(v.x)>abs(v.y)
            cx,cy=(r.x0+r.x1)/2,(r.y0+r.y1)/2
            best=None
            for x0,y0,x1,y1,w in segs:
                if horiz and abs(y0-y1)<0.3 and min(x0,x1)-2<=cx<=max(x0,x1)+2:
                    dd=y0-cy
                    if 0<dd<9 and abs(x1-x0)>20 and (best is None or dd<best[0]): best=(dd,min(x0,x1),max(x0,x1),y0)
                if not horiz and abs(x0-x1)<0.3 and min(y0,y1)-2<=cy<=max(y0,y1)+2:
                    dd=x0-cx
                    if 0<dd<9 and abs(y1-y0)>20 and (best is None or dd<best[0]): best=(dd,min(y0,y1),max(y0,y1),x0)
            if not best: continue
            _,s0,s1,c=best
            if horiz: a,b2=f(s0,c),f(s1,c)
            else: a,b2=f(c,s1),f(c,s0)
            out.append({"t":t,"horiz":horiz,"a":a,"b":b2})
    return out
def pymupdf_point(r):
    from shapely.geometry import Point
    return Point(r.x0,r.y0)
if __name__=="__main__":
    for k in SHEETS:
        x=extra_bars(k); print(k,len(x),x[:3])
