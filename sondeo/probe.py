import re, sys, requests, json
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
def get(u, **k):
    try:
        r = S.get(u, timeout=40, **k); print(f"\n=== {r.status_code} {u} ({r.headers.get('content-type')}, {len(r.content)} bytes)"); return r
    except Exception as e:
        print(f"\n=== ERROR {u}: {e}"); return None
def links(r, pat):
    if r is None: return []
    hs = sorted(set(re.findall(r'href=["\']([^"\']+)["\']', r.text)))
    out = [h for h in hs if re.search(pat, h, re.I)]
    for h in out[:80]: print("  ", h)
    return out
# 1) BCRA balance cambiario
r = get("https://www.bcra.gob.ar/publicaciones/informe-de-evolucion-del-mercado-de-cambios-y-balance-cambiario-agosto-de-2026/")
links(r, r"xls|xlsx|zip|anexo|pdf")
r = get("https://www.bcra.gob.ar/PublicacionesEstadisticas/Mercado_de_cambios.asp")
links(r, r"xls|xlsx|zip|anexo")
r = get("https://www.bcra.gob.ar/estadisticas-indicadores/")
links(r, r"cambi|xls")
# 2) A3 Mercados
for u in ["https://www.a3mercados.com.ar/", "https://apicem.matbarofex.com.ar/api/v2/closing-prices?product=DLR&segment=Monedas&type=FUT&excludeEmptyVol=false&from=2026-09-01&to=2026-10-06&_ds=1",
          "https://api.a3mercados.com.ar/", "https://www.a3mercados.com.ar/market-data"]:
    r = get(u)
    if r is not None: print(r.text[:1500])
# 3) Finanzas licitaciones
r = get("https://www.argentina.gob.ar/economia/finanzas/licitaciones")
links(r, r"licitac|resultado|xls")
r = get("https://www.argentina.gob.ar/economia/finanzas/licitaciones/resultados")
links(r, r"licitac|resultado|xls")
