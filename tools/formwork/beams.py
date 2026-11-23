import re, math, glob
import pymupdf
from shapely.geometry import box, Point, LineString
from segs import segments
from xt import columns
PT=56.6929
def merge_lines(segs, cols, horiz):
    # group by perpendicular coordinate
    L=[]
    for x0,y0,x1,y1,w in segs:
        if w!=0.84: continue
        if horiz and abs(y0-y1)<0.3: L.append(((y0+y1)/2, min(x0,x1), max(x0,x1)))
        if not horiz and abs(x0-x1)<0.3: L.append(((x0+x1)/2, min(y0,y1), max(y0,y1)))
    L.sort()
    groups=[]
    for c,a,b in L:
        for g in groups:
            if abs(g['c']-c)<0.4: g['iv'].append((a,b)); break
        else: groups.append({'c':c,'iv':[(a,b)]})
    out=[]
    for g in groups:
        iv=sorted(g['iv']); cur=list(iv[0])
        def gap_blocked(a,b):
            mid=(a+b)/2
            pt=Point(mid,g['c']) if horiz else Point(g['c'],mid)
            return any(s.buffer(1.0).contains(pt) for s in cols)
        for a,b in iv[1:]:
            if a<=cur[1]+0.5 or (a-cur[1]<40 and not gap_blocked(cur[1],a)): cur[1]=max(cur[1],b)
            else: out.append((g['c'],cur[0],cur[1])); cur=[a,b]
        out.append((g['c'],cur[0],cur[1]))
    return [o for o in out if o[2]-o[1]>8]
def strips(segs, cols, horiz):
    Ls=merge_lines(segs, cols, horiz)
    res=[]
    for i,(c,a,b) in enumerate(Ls):
        cands=[]
        for j,(c2,a2,b2) in enumerate(Ls):
            d=c2-c
            if j==i or not (0.17*PT<=d<=1.25*PT): continue
            ov=min(b,b2)-max(a,a2)
            if ov<8 or ov< 0.5*min(b-a,b2-a2): continue
            cands.append((d,j,max(a,a2),min(b,b2)))
        if not cands: continue
        dmin=min(x[0] for x in cands)
        for d,j,a0,b0 in cands:
            if d<=dmin+0.6:
                res.append({'horiz':horiz,'c0':c,'c1':Ls[j][0],'a':a0,'b':b0,'w_pt':d})
    # split at columns: a strip crossing a column becomes two strips
    out=[]
    for s in res:
        pieces=[(s['a'],s['b'])]
        for col in cols:
            x0,y0,x1,y1=col.bounds
            ca,cb=(x0,x1) if horiz else (y0,y1)
            pa,pb=(y0,y1) if horiz else (x0,x1)
            if pb < min(s['c0'],s['c1'])-0.5 or pa > max(s['c0'],s['c1'])+0.5: continue
            np_=[]
            for a,b in pieces:
                if cb<=a or ca>=b: np_.append((a,b)); continue
                if ca-a>4: np_.append((a,ca))
                if b-cb>4: np_.append((cb,b))
            pieces=np_
        for a,b in pieces:
            if b-a>8: out.append({**s,'a':a,'b':b})
    return out

def labels(prefix):
    fn=glob.glob(f"/mnt/user-data/uploads/{prefix}*")[0]; p=pymupdf.open(fn)[0]; m=p.rotation_matrix
    d=p.get_text("dict"); out=[]
    for bl in d["blocks"]:
        for l in bl.get("lines",[]):
            t="".join(s["text"] for s in l["spans"]).strip()
            r=pymupdf.Rect(l["bbox"])*m
            # text direction in display coords
            dx,dy=l["dir"]; v=pymupdf.Point(dx,dy)*pymupdf.Matrix(m.a,m.b,m.c,m.d,0,0)
            horiz=abs(v.x)>abs(v.y)
            if re.match(r"(ΠΔ|Δ)\d+",t) or "#Φ" in t or re.match(r"[πκ]\d*Φ",t) or re.match(r"Σ\s*\d*Φ",t):
                out.append({'t':t,'rect':r,'horiz':horiz})
    return out

def assign(strips_, labs):
    """label -> strip (same orientation, label centre over the strip, nearest)"""
    out=[]
    for L in labs:
        if not (L['t'].startswith('Δ') or L['t'].startswith('ΠΔ') or '#Φ' in L['t']): continue
        cx,cy=(L['rect'].x0+L['rect'].x1)/2,(L['rect'].y0+L['rect'].y1)/2
        best=None
        for k,s in enumerate(strips_):
            if s['horiz']!=L['horiz']: continue
            along=cx if s['horiz'] else cy
            perp=cy if s['horiz'] else cx
            if not (s['a']-5<=along<=s['b']+5): continue
            mid=(s['c0']+s['c1'])/2
            d=abs(perp-mid)
            if d>60: continue
            if best is None or d<best[0]: best=(d,k)
        out.append((L,best[1] if best else None, best[0] if best else None))
    return out
