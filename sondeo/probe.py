import re, json, requests, urllib3
urllib3.disable_warnings()
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
def get(u, **kw):
    kw.setdefault("timeout", 60)
    try:
        r = S.get(u, **kw); print(f"\n=== {r.status_code} {u[:200]} ({len(r.content)} b, {r.headers.get('content-type','')[:30]})"); return r
    except Exception as e: print("\nERR", u[:150], str(e)[:150])
def head(r, n=400):
    if r is not None: print("  ", r.text[:n].replace("\n", " "))
# ---------------- BRASIL: SGS del BCB ----------------
SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{c}/dados?formato=json&dataInicial={d}&dataFinal={h}"
for c, n in [(1, "PTAX venta"), (10813, "PTAX venta (otra)"), (13621, "Reservas diarias caja"), (3546, "Reservas liquidez internacional mensual"),
             (432, "Meta Selic"), (11, "Selic diaria"), (4389, "CDI anual"), (22701, "?"), (22704, "?"), (22707, "?"), (13961, "?"),
             (24364, "?"), (12070, "?"), (21633, "?"), (22850, "?"), (23013, "?"), (24305, "?"), (24306, "?")]:
    r = get(SGS.format(c=c, d="01/08/2026", h="10/10/2026"))
    if r is not None and r.ok:
        try:
            j = r.json(); print("  ", c, n, len(j), j[:1], j[-1:])
        except Exception: head(r)
# metadatos de series (catálogo)
r = get("https://dadosabertos.bcb.gov.br/api/3/action/package_search?q=swap%20cambial&rows=10")
if r is not None and r.ok:
    for p in r.json()["result"]["results"]: print("  PKG", p["name"], "|", p["title"][:90])
for q in ["interven%C3%A7%C3%B5es%20mercado%20de%20c%C3%A2mbio", "fluxo%20cambial", "leil%C3%A3o%20d%C3%B3lar"]:
    r = get(f"https://dadosabertos.bcb.gov.br/api/3/action/package_search?q={q}&rows=10")
    if r is not None and r.ok:
        for p in r.json()["result"]["results"]: print("  PKG", q[:12], p["name"], "|", p["title"][:90])
# ---------------- CHILE ----------------
r = get("https://mindicador.cl/api/dolar/2026"); head(r, 300)
r = get("https://mindicador.cl/api/tpm/2026"); head(r, 300)
r = get("https://mindicador.cl/api"); head(r, 600)
r = get("https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx?user=x&pass=y&function=GetSeries&timeseries=F073.TCO.PRE.Z.D"); head(r, 300)
r = get("https://si3.bcentral.cl/Siete/ES/Siete/Cuadro/CAP_EI/MN_EI11/EI_EXTERNO1/637185066927145616"); 
# ---------------- COLOMBIA ----------------
r = get("https://www.datos.gov.co/resource/32sa-8pi3.json?$order=vigenciadesde%20DESC&$limit=3"); head(r, 400)
r = get("https://www.datos.gov.co/api/catalog/v1?q=reservas%20internacionales&limit=10")
if r is not None and r.ok:
    for x in r.json().get("results", []): print("  DS", x["resource"]["id"], "|", x["resource"]["name"][:90], "|", x["resource"].get("attribution"))
for q in ["banco%20de%20la%20republica%20compras%20divisas", "tasa%20de%20politica%20monetaria", "IBR", "tasa%20interbancaria"]:
    r = get(f"https://www.datos.gov.co/api/catalog/v1?q={q}&limit=8")
    if r is not None and r.ok:
        for x in r.json().get("results", []): print("  DS", q[:12], x["resource"]["id"], "|", x["resource"]["name"][:90], "|", x["resource"].get("attribution"))
r = get("https://suameca.banrep.gov.co/estadisticas-economicas/"); head(r, 200)
r = get("https://www.banrep.gov.co/es/estadisticas/reservas-internacionales"); 
if r is not None:
    for m in re.findall(r'href="([^"]+\.(?:xlsx?|csv))"', r.text)[:15]: print("  FILE", m)
r = get("https://totoro.banrep.gov.co/analytics/saw.dll?Download&Format=excel2007&Extension=.xlsx&BypassCache=true&path=%2Fshared%2FSeries%20Estad%C3%ADsticas_T%2F1.%20Tasa%20de%20Cambio%20Peso%20Colombiano%2F1.1%20TRM%20-%20Disponible%20desde%20el%2027%20de%20noviembre%20de%201991%2F1.1.1.TCM_Serie%20historica%20IQY&lang=es")
# ---------------- EMBIG en el BCRP ----------------
API = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/{}/json/2026-09-01/2026-10-09"
for c in ["PD04711XD", "PD38581XD", "PD04715XD"]:
    r = get(API.format(c))
    try: j = json.loads(r.text); print("  ", c, j["config"]["series"][0]["name"], j["periods"][-1])
    except Exception as e: print("  fallo", e)
