import re, io, json, requests, urllib3, pandas as pd
urllib3.disable_warnings()
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
B = "https://www.bcu.gub.uy"
J = {"Accept": "application/json;odata=nometadata"}
def get(u, **kw):
    kw.setdefault("timeout", 60); kw.setdefault("verify", False)
    try:
        r = S.get(u, **kw); print(f"\n=== {r.status_code} {u[:180]} ({len(r.content)} b)"); return r
    except Exception as e: print("\nERR", u, str(e)[:150])
# 1) referencias a archivos dentro del HTML crudo (incluye scripts)
for page in ["/Estadisticas-e-Indicadores/Paginas/Activos-de-reserva.aspx", "/Estadisticas-e-Indicadores/Paginas/Moneda-y-credito.aspx",
             "/Estadisticas-e-Indicadores/Paginas/Cotizaciones.aspx", "/Politica-Economica-y-Mercados/Paginas/Tasa-1-Dia.aspx"]:
    r = get(B + page)
    if r is None: continue
    refs = set(re.findall(r'[\w%/\-\.]+\.(?:xlsx?|csv)', r.text, re.I))
    for x in sorted(refs)[:40]: print("  REF", x)
    for m in re.findall(r"(/_api/[^\"' ]{0,150}|_vti_bin/[^\"' ]{0,120}|ListId[^,]{0,80}|listTitle[^,]{0,80})", r.text)[:15]: print("  API", m)
# 2) bibliotecas de los subsitios
for site in ["/Estadisticas-e-Indicadores", "/Politica-Economica-y-Mercados", "/Servicios-Financieros-SSF"]:
    r = get(B + site + "/_api/web/lists?$select=Title,ItemCount&$filter=BaseTemplate eq 101", headers=J)
    if r is not None and r.ok:
        try:
            for l in r.json().get("value", []): print("  LIB", site, "|", l.get("Title"), l.get("ItemCount"))
        except Exception as e: print("  no json", r.text[:200])
    elif r is not None: print("  ", r.text[:200])
# 3) carpetas de Documents de Estadísticas
def carpeta(url, nivel=0):
    if nivel > 2: return
    r = get(B + "/Estadisticas-e-Indicadores/_api/web/GetFolderByServerRelativeUrl('" + url + "')?$expand=Folders,Files", headers=J)
    if r is None or not r.ok:
        if r is not None: print("  ", r.text[:200])
        return
    d = r.json()
    for f in d.get("Files", [])[:60]:
        print("  " * nivel, "FILE", f.get("ServerRelativeUrl"), f.get("TimeLastModified", "")[:10])
    for c in d.get("Folders", [])[:40]:
        print("  " * nivel, "DIR", c.get("ServerRelativeUrl"), c.get("ItemCount"))
        if re.search(r"reserv|activ|monet|cambi|interv|tasa|base|cotiz|indicador|serie", c.get("Name", ""), re.I):
            carpeta(c["ServerRelativeUrl"], nivel + 1)
carpeta("/Estadisticas-e-Indicadores/Documents")
carpeta("/Estadisticas-e-Indicadores")
