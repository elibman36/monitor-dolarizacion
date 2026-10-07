import re, requests, json, collections
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
def get(u, **k):
    try:
        r = S.get(u, timeout=60, **k); print(f"\n=== {r.status_code} {u} ({r.headers.get('content-type')}, {len(r.content)} bytes)"); return r
    except Exception as e:
        print(f"\n=== ERROR {u}: {e}"); return None
def links(r, pat, n=120):
    if r is None: return []
    hs = sorted(set(re.findall(r'href=["\']([^"\']+)["\']', r.text)))
    out = [h for h in hs if re.search(pat, h, re.I)]
    for h in out[:n]: print("  ", h)
    return out
A3 = "https://apicem.matbarofex.com.ar/api/v2/closing-prices"
for a, b in [("2019-01-01", "2019-01-31"), ("2023-01-01", "2023-12-31"), ("2025-01-01", "2026-10-06")]:
    r = get(A3, params={"product": "DLR", "segment": "Monedas", "type": "FUT", "excludeEmptyVol": "false", "from": a, "to": b, "_ds": "1"})
    if r is not None and r.ok:
        d = r.json(); data = d.get("data", [])
        print("keys:", [k for k in d if k != "data"], {k: d[k] for k in d if k != "data"})
        print("rows", len(data), "dates", min((x["dateTime"] for x in data), default=None), max((x["dateTime"] for x in data), default=None))
        print("symbols", collections.Counter(re.sub(r"\d", "#", x["symbol"]) for x in data).most_common(10))
        print(sorted(set(x["symbol"] for x in data))[:30])
# BCRA
r = get("https://www.bcra.gob.ar/estadisticas-estandarizadas-sobre-la-evolucion-del-mercado-de-cambios/")
links(r, r"xls|xlsx|zip|csv|archivos")
r = get("https://www.bcra.gob.ar/publicaciones/informe-de-evolucion-del-mercado-de-cambios-y-balance-cambiario-agosto-de-2026/")
links(r, r"archivos|xls")
# Finanzas
for u in ["https://www.argentina.gob.ar/economia/finanzas", "https://www.argentina.gob.ar/economia/finanzas/licitaciones-y-colocaciones",
          "https://www.argentina.gob.ar/economia/finanzas/llamados-y-resultados-de-licitaciones"]:
    r = get(u); links(r, r"licitac|resultad|coloca", 60)
