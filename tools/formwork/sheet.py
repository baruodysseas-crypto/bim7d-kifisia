import re, glob, json
import pymupdf
from beams import *
SHEETS={"01":"edcbfb83","02":"d8ff8bad","03":"4aee75ad","04":"242f4507","05":"ef367244","06":"08a205f2"}
def title(prefix):
    fn=glob.glob(f"/mnt/user-data/uploads/{prefix}*")[0]; t=pymupdf.open(fn)[0].get_text()
    m=re.search(r"ΞΥΛΟΤΥΠΟΣ[^\n]*",t); return m.group(0) if m else "?"
def extract(prefix):
    p,m,cols,lab,words=columns(prefix)
    # plan region: where the Latin K labels are
    xs=[r.x0 for r,t in lab if t.startswith('K')]; ys=[r.y0 for r,t in lab if t.startswith('K')]
    region=box(min(xs)-150,min(ys)-150,max(xs)+150,max(ys)+150)
    cols=[c for c in cols if region.contains(c.centroid)]
    S=segments(prefix)
    S=[s for s in S if region.contains(Point(s[0],s[1]))]
    ST=strips(S,cols,True)+strips(S,cols,False)
    L=[l for l in labels(prefix) if region.contains(Point(l['rect'].x0,l['rect'].y0))]
    A=assign(ST,L)
    return dict(p=p,m=m,cols=cols,lab=[(r,t) for r,t in lab if t.startswith('K') and region.contains(Point(r.x0,r.y0))],words=words,ST=ST,L=L,A=A,region=region)
if __name__=="__main__":
    for k,pre in SHEETS.items():
        e=extract(pre)
        nb=sum(1 for l in e['L'] if re.match(r'(ΠΔ|Δ)\d',l['t'])); un=[l['t'] for l,kk,d in e['A'] if kk is None]
        print(k,title(pre),"| cols",len(e['cols']),"labels",len(e['lab']),"| beams",nb,"walls lab",sum(1 for l in e['L'] if '#Φ' in l['t']),"| unassigned",un)
