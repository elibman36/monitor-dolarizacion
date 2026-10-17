import requests, urllib3, io, re, json, pandas as pd
urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
pd.set_option("display.width",250); pd.set_option("display.max_columns",40); pd.set_option("display.max_colwidth",90)
def g(u,**kw):
    try: return requests.get(u,timeout=(15,60),headers=H,verify=False,**kw)
    except Exception as e: print("ERR",u,e)
print("=== BCRP")
for n in list(range(15,60)):
    cod=f"PN{n:05d}MM"
    r=g(f"https://estadisticas.bcrp.gob.pe/estadisticas/series/api/{cod}/json/2026-6/2026-8")
    try:
        j=json.loads(r.text); print(cod, j["config"]["series"][0]["name"][:150], j["periods"][-1]["values"])
    except Exception as e: print(cod,"-")
print("=== BCU")
r=g("https://www.bcu.gub.uy/Servicios-Financieros-SSF/Series%20IF/Depositos.xlsx")
x=pd.ExcelFile(io.BytesIO(r.content)); print(x.sheet_names)
d=pd.read_excel(x,sheet_name="Total Sist. Banc.",header=None)
print(d.iloc[:14,:30].to_string())
print("=== BCB")
r=g("https://www.bcb.gob.bo/?q=estad-sticas-semanales")
links=re.findall(r'href="([^"]*Semanal[^"]*?(\d+)_\s*(\d{4})[^"]*\.xlsx)"', r.text.replace("%20"," "))
url=max(links,key=lambda x:(int(x[2]),int(x[1])))[0].replace(" ","%20")
url=url if url.startswith("http") else "https://www.bcb.gob.bo"+url
d=pd.read_excel(io.BytesIO(g(url).content),header=None)
for i in range(len(d)):
    lab=" ".join(str(v) for v in d.iloc[i,1:4] if pd.notna(v))
    if lab: print(i, lab[:110], "|", d.iloc[i,-1])
