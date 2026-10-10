import re, json, requests
import urllib3; urllib3.disable_warnings()
S = requests.Session(); S.verify = False; S.headers["User-Agent"] = "Mozilla/5.0"; S.headers["Accept"] = "application/json"
B = "https://suameca.banrep.gov.co"
def get(u, **kw):
    try:
        r = S.get(u, timeout=60, **kw); print(f"\n=== {r.status_code} {u[:180]} ({len(r.content)} b)"); return r
    except Exception as e: print("ERR", u, e)
# endpoints declarados en los bundles JS
r = get(B + "/graficador-interactivo/")
js = set(re.findall(r'src="([^"]+\.js)"', r.text)) if r is not None else set()
print("JS", js)
endpoints = set()
for j in js:
    u = j if j.startswith("http") else B + ("/graficador-interactivo/" + j.lstrip("./") if not j.startswith("/") else j)
    t = get(u)
    if t is None: continue
    endpoints |= set(re.findall(r'["\'`](/?[\w\-/]*rest/[\w\-/]+(?:\?[\w=&]+)?)', t.text))
    endpoints |= set(re.findall(r'["\'`]((?:graficadorService|buscadorSeriesRestService|estadisticaEconomicaRestService)/[\w]+)', t.text))
for e in sorted(endpoints): print("  EP", e)
# catálogo
r = get(B + "/graficador-series/rest/graficadorService/consultaCatalogo")
try:
    cat = r.json(); txt = json.dumps(cat, ensure_ascii=False)
    print("  catálogo:", type(cat), len(txt)); print(txt[:1500])
    for m in re.finditer(r'\{[^{}]*?(reserv|pol[ií]tica monetaria|compra|interven|IBR|forward|swap)[^{}]*?\}', txt, re.I):
        print("  CAT", m.group(0)[:300])
except Exception as e: print("no json", e, r.text[:300] if r is not None else "")
r = get(B + "/graficador-series/rest/graficadorService/principalesIndicadores")
if r is not None: print(r.text[:1500])
