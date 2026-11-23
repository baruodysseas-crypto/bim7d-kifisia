import pymupdf,glob,re,json,math
from shapely.geometry import Polygon, box, Point
from shapely.ops import unary_union
PT_M = 1/56.6929   # 1:50 -> metres per pt
def load(prefix):
    fn=glob.glob(f"/mnt/user-data/uploads/{prefix}*")[0]; p=pymupdf.open(fn)[0]; m=p.rotation_matrix
    return p,m
def columns(prefix, plan_box=None):
    p,m=load(prefix)
    rects=[]
    for d in p.get_drawings():
        if d['type'] in('fs','f') and d.get('fill')==(0.0,0.0,0.0):
            pts=[]; parts=[]
            for it in d['items']:
                if it[0]=='l':
                    a,b=it[1]*m,it[2]*m
                    if pts and (abs(pts[-1].x-a.x)>0.05 or abs(pts[-1].y-a.y)>0.05):     # new sub-path
                        if len(pts)>=3: parts.append(Polygon([(q.x,q.y) for q in pts]).buffer(0))
                        pts=[]
                    if not pts: pts.append(a)
                    pts.append(b)
                elif it[0]=='re':
                    r=it[1]*m; parts.append(box(r.x0,r.y0,r.x1,r.y1))
                elif it[0]=='qu':
                    q=it[1]; parts.append(Polygon([(p_.x,p_.y) for p_ in (q.ul*m,q.ur*m,q.lr*m,q.ll*m)]).buffer(0))
            if len(pts)>=3: parts.append(Polygon([(q.x,q.y) for q in pts]).buffer(0))
            for P in parts:
                if P.area>20: rects.append(P)
    shapes=unary_union([r.buffer(0.6) for r in rects]).buffer(-0.6)
    shapes=list(getattr(shapes,'geoms',[shapes]))
    words=[(pymupdf.Rect(w[:4])*m, w[4]) for w in p.get_text("words")]
    labels=[(r,t) for r,t in words if re.fullmatch(r"[KΚ]\d+",t)]
    return p,m,shapes,labels,words
if __name__=="__main__":
    import sys
    p,m,shapes,labels,words=columns(sys.argv[1])
    print(len(shapes), "shapes;", len(labels), "labels")
    for s in shapes: print([round(v) for v in s.bounds], round(s.area))
    for r,t in labels: print(t, round(r.x0), round(r.y0))
