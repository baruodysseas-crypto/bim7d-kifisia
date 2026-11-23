import re, statistics
import pymupdf
from sheet import extract, SHEETS
PT=56.6929
def register(e):
    p,m=e['p'],e['m']
    cx0,cy0,cx1,cy1=e['region'].bounds
    nums=[]
    for w in p.get_text("words"):
        if re.fullmatch(r"-?\d+\.\d\d",w[4]):
            r=pymupdf.Rect(w[:4])*m; nums.append((float(w[4]),(r.x0+r.x1)/2,(r.y0+r.y1)/2,r.width<r.height))
    # vertical axis labels: left or right of the plan, horizontal text; value v at display y: y = Y0 - v*PT
    def fit(cands):
        offs=[c[1]+c[0]*PT for c in cands]
        best=None
        for o in offs:
            n=sum(1 for q in offs if abs(q-o)<2.5)
            if best is None or n>best[0]: best=(n,o)
        n,o=best; sel=[q for q in offs if abs(q-o)<2.5]
        return statistics.median(sel), n, len(offs)
    left=[(v,y) for v,x,y,vert in nums if not vert and (x<cx0+120 or x>cx1-120)]
    Y0=fit([(v,y) for v,y in left])
    top=[(v,x) for v,x,y,vert in nums if vert and (y<cy0+120 or y>cy1-120)]
    offs=[x - v*PT for v,x in top]
    best=None
    for o in offs:
        n=sum(1 for q in offs if abs(q-o)<2.5)
        if best is None or n>best[0]: best=(n,o)
    X0=(statistics.median([q for q in offs if abs(q-best[1])<2.5]), best[0], len(offs))
    return X0, Y0
if __name__=="__main__":
    for k,pre in SHEETS.items():
        e=extract(pre); print(k, register(e))
