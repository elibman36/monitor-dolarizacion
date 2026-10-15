import requests, urllib3, re, io, pandas as pd, json
urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
def get(u, **kw):
    try: return requests.get(u,timeout=90,headers={**H,**kw.pop("headers",{})},verify=False,**kw)
    except Exception as e: print("ERR",u,e); return None
def links(u, pat, n=40):
    r=get(u)
    if r is None: return
    print("PAGE",u,r.status_code,len(r.text))
    hs=sorted(set(re.findall(r'href=["\']([^"\']+)["\']',r.text)))
    k=0
    for h in hs:
        if re.search(pat,h,re.I):
            print("   ",h[:200]); k+=1
            if k>=n: break
links("https://www.asfi.gob.bo/pb/estadisticas-intermediacion-financiera", r"xls|zip|boletin|mensual|estadist", 60)
links("https://www.bcb.gob.bo/?q=estad-sticas-semanales", r"xls|pdf|semanal", 30)
links("https://www.bcb.gob.bo/bcb_estadisticas/index.php", r".", 40)
links("https://sdd.bccr.fi.cr/es/IndicadoresEconomicos/Inicio/Contenedor/6?Cuadro=1", r".", 60)
# IMF: dataflows con FSI
r=get("https://api.imf.org/external/sdmx/2.1/dataflow")
if r is not None:
    for m in re.finditer(r'<str:Dataflow[^>]*id="([^"]+)"[^>]*agencyID="([^"]+)"[^>]*version="([^"]+)".*?<com:Name[^>]*>([^<]+)<', r.text, re.S):
        if re.search("FSI|Soundness|Monetary|MFS",m.group(4)+m.group(1),re.I): print("DF",m.group(2),m.group(1),m.group(3),m.group(4)[:80])
for u in ["https://api.imf.org/external/sdmx/2.1/data/IMF.STA,FSIC/BOL..?startPeriod=2024&format=csv",
          "https://api.imf.org/external/sdmx/2.1/data/IMF.STA,FSIC/BOL?startPeriod=2024",
          "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA/FSIC/+/BOL.*.*?c[TIME_PERIOD]=ge:2024"]:
    r=get(u, headers={"Accept":"application/vnd.sdmx.data+csv;version=1.0.0"})
    if r is not None: print("IMFDATA",u[-60:],r.status_code,r.text[:1500].replace("\n"," || "))
