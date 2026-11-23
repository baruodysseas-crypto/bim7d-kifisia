import json, re, math
from shapely.geometry import Polygon, LineString
from model import sheet_model
from coltab import table
from sheet import SHEETS
STOREY={"02":"basement","03":"ground","04":"first","05":"second","06":"attic"}
def section_area(sec):
    v=[int(x)/100 for x in sec.split("/")]
    if len(v)==2: return v[0]*v[1]
    a,b,t=v          # L / U style legs a x b with thickness t (L); the lift core is a U: 2 legs b + web a
    return a*t+b*t-t*t
def As(bars): return sum(n*math.pi*(d/10)**2/4 for n,d in bars)   # cm2
F={}
for k in SHEETS:
    sm=sheet_model(k); tb=table(k)
    for c in sm['columns']:
        t=tb.get(c['id'])
        P=Polygon(c['poly']).buffer(0)
        c['area_drawn_m2']=round(P.area,4)
        if t:
            c.update(t); c['area_table_m2']=round(section_area(t['section']),4); c['As_cm2']=round(As(t['long_bars']),1)
            c['rho_pct']=round(c['As_cm2']/(c['area_drawn_m2']*1e4)*100,2)
    F[k]=sm
json.dump(F,open("frames.json","w"),ensure_ascii=False)
for k,sm in F.items():
    for c in sm['columns']:
        if 'section' not in c: print(k,c['id'],"NO TABLE ROW"); continue
        if abs(c['area_drawn_m2']-c['area_table_m2'])/c['area_table_m2']>0.12: print(k,c['id'],"area drawn",c['area_drawn_m2'],"table",c['section'],c['area_table_m2'])
