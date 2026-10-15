import requests, urllib3, io, re, json, pandas as pd
urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
pd.set_option("display.width",250); pd.set_option("display.max_columns",60)
def g(u, **kw):
    try:
        r=requests.get(u,timeout=90,headers={**H,**kw.pop("headers",{})},verify=False,**kw)
        print("\n###",u,r.status_code,r.headers.get("content-type"),len(r.content)); return r
    except Exception as e:
        print("\n###",u,"ERR",e); return None
def show(r,n=400):
    if r is not None: print(r.text[:n].replace("\n"," | ")); print("...", r.text[-300:].replace("\n"," | "))
# BIS
for c in ["AR","PE","UY","BO","CR","BR","CL","CO","US"]:
    r=g(f"https://stats.bis.org/api/v1/data/WS_LONG_CPI/M.{c}.628?format=csv&startPeriod=1990-01")
    if r is not None and r.ok:
        d=pd.read_csv(io.StringIO(r.text)); print(c,"LONG_CPI",d.TIME_PERIOD.min(),d.TIME_PERIOD.max(),len(d))
    r=g(f"https://stats.bis.org/api/v1/data/WS_XRU/M.{c}..A?format=csv&startPeriod=1990-01")
    if r is not None and r.ok:
        d=pd.read_csv(io.StringIO(r.text)); print(c,"XRU",d.TIME_PERIOD.min(),d.TIME_PERIOD.max(),len(d), d.OBS_VALUE.tail(2).tolist())
# IMF CPI
r=g("https://api.imf.org/external/sdmx/2.1/data/IMF.STA,CPI/ARG+PER+URY+BOL+CRI+BRA+CHL+COL.CPI._T.IX.M?startPeriod=1990",headers={"Accept":"application/vnd.sdmx.data+csv;version=1.0.0"})
if r is not None and r.ok:
    d=pd.read_csv(io.StringIO(r.text),low_memory=False); print(d.columns.tolist()); print(d.groupby(d.columns[1]).TIME_PERIOD.agg(["min","max","count"]))
else: show(r)
# national
show(g("https://apis.datos.gob.ar/series/api/series/?ids=148.3_INIVELNAL_DICI_M_26&limit=3&format=json"))
show(g("https://apis.datos.gob.ar/series/api/search/?q=indice%20precios%20consumidor&limit=40"),4000)
show(g("https://api.argentinadatos.com/v1/finanzas/indices/inflacion"),300)
show(g("https://estadisticas.bcrp.gob.pe/estadisticas/series/api/PN01270PM/json/1990-1/2026-12"),300)
show(g("https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados?formato=json&dataInicial=01/01/1995"),200)
show(g("https://fred.stlouisfed.org/graph/fredgraph.csv?id=PALLFNFINDEXM"),200)
show(g("https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL"),200)
r=g("https://api.imf.org/external/sdmx/2.1/data/IMF.RES,PCPS/W00.PALLFNF.IX.M?startPeriod=2000",headers={"Accept":"application/vnd.sdmx.data+csv;version=1.0.0"}); show(r)
