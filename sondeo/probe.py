import requests, urllib3, re, io, pandas as pd
urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
pd.set_option("display.width",250); pd.set_option("display.max_colwidth",70); pd.set_option("display.max_columns",20)
# IMF FSIC: indicadores de moneda extranjera
for c in ["BOL","CRI","CHL","COL","BRA","URY","PER","ARG"]:
    r=requests.get(f"https://api.imf.org/external/sdmx/2.1/data/IMF.STA,FSIC/{c}?startPeriod=2025&format=csv",timeout=120,headers=H)
    if not r.ok: print(c,r.status_code); continue
    d=pd.read_csv(io.StringIO(r.text),low_memory=False)
    m=d[d["SERIES_NAME"].astype(str).str.contains("oreign|urrency",regex=True)]
    g=m.groupby(["INDICATOR","FREQUENCY"]).agg(n=("OBS_VALUE","size"),ult=("TIME_PERIOD","max"),val=("OBS_VALUE","last"),name=("SERIES_NAME","first"))
    print("==",c); print(g.to_string()[:3000])
# BCB semanal
r=requests.get("https://www.bcb.gob.bo/webdocs/05_estadisticassemanales/Semanal%2042_2026.xlsx",timeout=120,headers=H,verify=False)
print("BCB",r.status_code,len(r.content))
x=pd.ExcelFile(io.BytesIO(r.content)); print("HOJAS",x.sheet_names)
for s in x.sheet_names:
    d=pd.read_excel(x,sheet_name=s,header=None)
    txt=d.astype(str).apply(lambda col: col.str.contains("olivianiz|oneda extranjera|M/E|ME ",regex=True)).any(axis=1)
    if txt.any():
        print("--- HOJA",s,d.shape); print(d.iloc[:14,:10].to_string()[:2500])
