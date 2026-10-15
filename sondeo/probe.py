import requests, urllib3, re, io, pandas as pd
urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
def get(u, **kw):
    try:
        r=requests.get(u,timeout=60,headers=H,verify=False,**kw); return r
    except Exception as e: print("ERR",u,e); return None
def links(u, pat):
    r=get(u)
    if r is None: return
    print("PAGE",u,r.status_code,len(r.text))
    hs=sorted(set(re.findall(r'href=["\']([^"\']+)["\']',r.text)))
    for h in hs:
        if re.search(pat,h,re.I): print("   ",h[:180])
# Bolivia
for u in ["https://www.bcb.gob.bo/?q=estadisticas/semanales","https://www.bcb.gob.bo/?q=estadisticas_semanales","https://www.bcb.gob.bo/?q=estadisticas/series_estadisticas","https://www.bcb.gob.bo/?q=servicios/boletines_estadisticos","https://www.bcb.gob.bo"]:
    links(u, r"xls|semanal|mensual|bolivian|estadist")
for u in ["https://www.asfi.gob.bo/index.php/int-fin-estadisticas.html","https://www.asfi.gob.bo"]:
    links(u, r"xls|estadist|boletin")
# Costa Rica
for u in ["https://gee.bccr.fi.cr/indicadoreseconomicos/","https://gee.bccr.fi.cr/indicadoreseconomicos/Cuadros/frmMenuCatalogos.aspx","https://www.bccr.fi.cr/indicadores-economicos"]:
    links(u, r"dolar|moneda|cuadro|catalogo|xls")
r=get("https://gee.bccr.fi.cr/Indicadores/Suscripciones/WS/wsindicadoreseconomicos.asmx/ObtenerIndicadoresEconomicosXML?Indicador=317&FechaInicio=01/01/2026&FechaFinal=10/01/2026&Nombre=x&SubNiveles=N&CorreoElectronico=x@x.com&Token=x")
if r is not None: print("BCCR WS",r.status_code,r.text[:300])
# BIS
for c in ["BO","CR"]:
    r=get(f"https://stats.bis.org/api/v1/data/WS_LBS_D_PUB/Q.S.L.A.TO1.A.5J.A.5A.N.{c}.N?startPeriod=2025&format=csv")
    if r is not None: print("BIS",c,r.status_code,r.text.splitlines()[-1][-60:] if r.ok else r.text[:100])
# IMF FSI
for u in ["https://api.imf.org/external/sdmx/2.1/dataflow","https://dataservices.imf.org/REST/SDMX_JSON.svc/Dataflow"]:
    r=get(u); 
    if r is not None: print("IMF",u,r.status_code,len(r.text), "FSI" in r.text)
