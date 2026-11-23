import re, json, math
import numpy as np
from shapely.geometry import Point, box
from shapely import affinity
from sheet import extract, SHEETS
from reg import register, PT
from scipy.optimize import linear_sum_assignment
def to_m(e):
    (X0,_,_),(Y0,_,_)=register(e)
    f=lambda x,y: ((x-X0)/PT, (Y0-y)/PT)
    return f
def sheet_model(key):
    e=extract(SHEETS[key]); f=to_m(e)
    # columns: assign labels by optimal matching (label near a corner of its column)
    labs=e['lab']; cols=e['cols']
    C=np.zeros((len(cols),len(labs)))
    for i,c in enumerate(cols):
        for j,(r,t) in enumerate(labs):
            C[i,j]=c.distance(Point((r.x0+r.x1)/2,(r.y0+r.y1)/2))
    ri,ci=linear_sum_assignment(C)
    out_cols=[]
    for i,j in zip(ri,ci):
        c=cols[i]; r,t=labs[j]
        ring=[f(x,y) for x,y in c.exterior.coords]
        out_cols.append({"id":"K"+t[1:], "poly":[[round(a,3),round(b,3)] for a,b in ring], "label_dist_pt":round(C[i,j],1)})
    # beams / walls
    tag={}
    for Lb,k,d in e['A']:
        if k is not None: tag.setdefault(k,[]).append(Lb)
    beams=[]; walls=[]
    for k,s in enumerate(e['ST']):
        ls=tag.get(k)
        if not ls: continue
        if s['horiz']: (xa,ya),(xb,yb)=f(s['a'],(s['c0']+s['c1'])/2),f(s['b'],(s['c0']+s['c1'])/2)
        else: (xa,ya),(xb,yb)=f((s['c0']+s['c1'])/2,s['a']),f((s['c0']+s['c1'])/2,s['b'])
        w=s['w_pt']/PT
        for L in ls:
            t=L['t']
            mb=re.match(r"(ΠΔ|Δ)(\d+)\s+(\d+)/(\d+),(\d+)Φ(\d+)",t)
            if mb:
                beams.append({"id":mb.group(1)+mb.group(2),"b_cm":int(mb.group(3)),"h_cm":int(mb.group(4)),"side":f"{mb.group(5)}Φ{mb.group(6)}",
                              "a":[round(xa,3),round(ya,3)],"b":[round(xb,3),round(yb,3)],"w_drawn_m":round(w,3),"label":t,"_rect":L['rect']})
            elif "#Φ" in t:
                walls.append({"label":t,"a":[round(xa,3),round(ya,3)],"b":[round(xb,3),round(yb,3)],"t_m":round(w,3)})
    # extra beam texts: stirrups (Σ ..) and bars (π..,κ..) stacked next to the Δ label, same orientation
    other=[L for L in e['L'] if not re.match(r"(ΠΔ|Δ)\d",L['t']) and "#Φ" not in L['t']]
    for b in beams:
        R=b.pop("_rect"); cx,cy=(R.x0+R.x1)/2,(R.y0+R.y1)/2
        for kind,pat in (("bars",r"[πκ]"),("stirrups",r"Σ")):
            best=None
            for L in other:
                if not re.match(pat,L['t']): continue
                r=L['rect']; ox,oy=(r.x0+r.x1)/2,(r.y0+r.y1)/2
                d=math.hypot(ox-cx,oy-cy)
                if d<40 and (best is None or d<best[0]): best=(d,L['t'])
            b[kind]=best[1] if best else None
    # dedupe walls/beams on the same line
    return {"sheet":key,"columns":sorted(out_cols,key=lambda c:int(c['id'][1:])),"beams":beams,"walls":walls}
if __name__=="__main__":
    import sys
    M={k:sheet_model(k) for k in SHEETS}
    json.dump(M,open("frames_raw.json","w"),ensure_ascii=False,indent=0)
    for k,v in M.items():
        print(k,len(v['columns']),len(v['beams']),len(v['walls']), "max label dist", max(c['label_dist_pt'] for c in v['columns']), "beams w/o bars", sum(1 for b in v['beams'] if not b['bars']), "w/o stirrups", sum(1 for b in v['beams'] if not b['stirrups']))
