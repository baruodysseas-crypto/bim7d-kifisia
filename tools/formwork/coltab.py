import re, glob, math
import pymupdf
from sheet import SHEETS
def bars(s):
    """'33Φ20+6Φ18' -> [(33,20),(6,18)]"""
    return [(int(n),int(d)) for n,d in re.findall(r"(\d+)Φ(\d+)",s)]
def table(key):
    fn=glob.glob(f"/mnt/user-data/uploads/{SHEETS[key]}*")[0]; p=pymupdf.open(fn)[0]; m=p.rotation_matrix
    t=p.get_text()
    rows={}
    for mm in re.finditer(r"Κ(\d+)\s+([\d/]+)\s+([\dΦ+]+)\s+Σ\s*Φ(\d+)/(\d+)\s+h κρίσ\.=([\d.]+)m",t):
        rows["K"+mm.group(1)]={"section":mm.group(2),"long":mm.group(3),"long_bars":bars(mm.group(3)),"stirrup_d":int(mm.group(4)),"stirrup_s_cm":int(mm.group(5)),"h_crit_m":float(mm.group(6))}
    # positions of the table labels and of web reinforcement notes (walls)
    d=p.get_text("dict"); labs={}; webs=[]
    lines=[]
    for b in d["blocks"]:
        for l in b.get("lines",[]):
            tx="".join(s["text"] for s in l["spans"]).strip(); r=pymupdf.Rect(l["bbox"])*m
            lines.append((tx,r))
    for i,(tx,r) in enumerate(lines):
        mk=re.match(r"Κ(\d+)",tx)
        if mk: labs["K"+mk.group(1)]=r
        mo=re.match(r"Οριζ:Φ(\d+)/(\d+)",tx)
        if mo:
            # the vertical bars are on the next line
            kv=None
            for tx2,r2 in lines[i+1:i+3]:
                mv=re.match(r"Κατ:Φ(\d+)/(\d+)",tx2)
                if mv: kv=(int(mv.group(1)),int(mv.group(2)))
            webs.append(((r.x0+r.x1)/2,(r.y0+r.y1)/2,(int(mo.group(1)),int(mo.group(2))),kv))
    for x,y,h,v in webs:
        k=min(labs, key=lambda k: math.hypot((labs[k].x0+labs[k].x1)/2-x,(labs[k].y0+labs[k].y1)/2-y))
        if k in rows: rows[k].setdefault("web",[]).append({"horiz":h,"vert":v})
    return rows
if __name__=="__main__":
    for k in SHEETS:
        r=table(k); print(k,len(r)); 
        for kk in list(r)[:40]: print("  ",kk,r[kk])
