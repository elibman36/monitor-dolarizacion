import requests, urllib3, io, re, pandas as pd
urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
pd.set_option("display.width",250); pd.set_option("display.max_columns",60)
r=requests.get("https://www.bcb.gob.bo/webdocs/05_estadisticassemanales/Semanal%2042_2026.xlsx",timeout=120,headers=H,verify=False)
d=pd.read_excel(io.BytesIO(r.content),header=None)
print("SHAPE",d.shape)
cab=d.iloc[0:5,:]
# tipos de encabezado por columna
prev=None
for c in range(4,d.shape[1]):
    v=[str(x)[:22] for x in cab.iloc[:,c].tolist()]
    kind="fecha" if re.match(r"\d{4}-\d{2}-\d{2}",v[2]) else v[2]
    if kind!=prev or c>d.shape[1]-35: print(c,v,"| dep:",d.iloc[90,c],"| bol:",d.iloc[94,c])
    prev=kind
r=requests.get("https://www.bcb.gob.bo/?q=estad-sticas-semanales",timeout=60,headers=H,verify=False)
print(sorted(set(re.findall(r'href="([^"]+Semanal[^"]+\.xlsx)"',r.text)))[-5:])
