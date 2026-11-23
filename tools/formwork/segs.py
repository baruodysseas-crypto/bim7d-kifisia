import pymupdf,glob
def segments(prefix):
    fn=glob.glob(f"/mnt/user-data/uploads/{prefix}*")[0]; p=pymupdf.open(fn)[0]; m=p.rotation_matrix
    out=[]
    for d in p.get_drawings():
        if d['type']!='s': continue
        for it in d['items']:
            if it[0]=='l':
                a,b=it[1]*m,it[2]*m
                out.append((a.x,a.y,b.x,b.y,round(d['width'],2)))
            elif it[0]=='re':
                r=it[1]*m
                for (ax,ay,bx,by) in ((r.x0,r.y0,r.x1,r.y0),(r.x0,r.y1,r.x1,r.y1),(r.x0,r.y0,r.x0,r.y1),(r.x1,r.y0,r.x1,r.y1)):
                    out.append((ax,ay,bx,by,round(d['width'],2)))
    return out
