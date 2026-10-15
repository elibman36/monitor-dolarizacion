import requests, urllib3, io, pandas as pd
urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
CSV={**H,"Accept":"application/vnd.sdmx.data+csv;version=1.0.0"}
pd.set_option("display.width",250); pd.set_option("display.max_colwidth",90); pd.set_option("display.max_rows",300)
for c in ["BOL","CRI","CHL","COL","BRA"]:
  try:
    r=requests.get(f"https://api.imf.org/external/sdmx/2.1/data/IMF.STA,FSIC/{c}..?startPeriod=2025",timeout=120,headers=CSV)
    d=pd.read_csv(io.StringIO(r.text),low_memory=False)
    m=d[d["SERIES_NAME"].astype(str).str.contains("oreign|urrency",regex=True) & ~d["SERIES_NAME"].astype(str).str.contains("Domestic currency$|US dollar$|Euro$",regex=True)]
    g=m.groupby(["INDICATOR","SECTOR","FREQUENCY"]).agg(n=("OBS_VALUE","size"),ult=("TIME_PERIOD","max"),val=("OBS_VALUE","last"),name=("SERIES_NAME","first"))
    print("==",c,len(d)); print(g.to_string()[:2500])
  except Exception as e: print(c,"ERR",e)
r=requests.get("https://www.bcb.gob.bo/webdocs/05_estadisticassemanales/Semanal%2042_2026.xlsx",timeout=120,headers=H,verify=False)
d=pd.read_excel(io.BytesIO(r.content),header=None)
print("FECHAS ultimas", d.iloc[2,-6:].tolist())
for i in range(d.shape[0]):
    lab=" | ".join(str(x) for x in d.iloc[i,1:4].tolist() if str(x)!="nan")
    if lab: print(i, lab[:110], "|", d.iloc[i,-1])
