import re, io, json, requests, urllib3, pandas as pd
urllib3.disable_warnings()
pd.set_option("display.width", 220)
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
def get(u, **kw):
    kw.setdefault("timeout", 60)
    try:
        r = S.get(u, **kw); print(f"\n=== {r.status_code} {u[:200]} ({len(r.content)} b, {r.headers.get('content-type','')[:35]})"); return r
    except Exception as e: print("\nERR", u[:150], str(e)[:150])
def head(r, n=400):
    if r is not None: print("  ", r.text[:n].replace("\n", " "))
def js(r):
    try: return r.json()
    except Exception: head(r); return None
SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{c}/dados?formato=json&dataInicial={d}&dataFinal={h}"
for c in [29722, 29723, 29724, 1, 13621]:
    for d, h in [("01/01/2000", "31/12/2009"), ("01/01/2010", "31/12/2019"), ("01/09/2026", "10/10/2026")]:
        r = get(SGS.format(c=c, d=d, h=h)); j = js(r)
        if j: print("  ", c, d, len(j), j[:1], j[-1:])
# BCB datos abiertos: atuações
for q in ["atuacoes", "atua%C3%A7%C3%B5es%20c%C3%A2mbio", "historico%20atuacoes%20mercado%20cambio", "leiloes%20cambio"]:
    r = get(f"https://dadosabertos.bcb.gov.br/api/3/action/package_search?q={q}&rows=8"); j = js(r)
    if j:
        for p in j["result"]["results"]:
            print("  PKG", p["name"], "|", p["title"][:80])
            for res in p.get("resources", [])[:4]: print("     RES", res.get("format"), res.get("url", "")[:160])
# ---------------- CHILE ----------------
for u in ["https://mindicador.cl/api/dolar/2008", "https://mindicador.cl/api/dolar/2026", "https://mindicador.cl/api/tpm/2026", "https://mindicador.cl/api/libra_cobre/2026"]:
    r = get(u); j = js(r)
    if j: print("  ", j.get("nombre"), len(j.get("serie", [])), j.get("serie", [])[:1])
# ---------------- COLOMBIA ----------------
r = get("https://www.datos.gov.co/resource/32sa-8pi3.json?$order=vigenciadesde%20ASC&$limit=2"); head(r, 300)
r = get("https://www.datos.gov.co/resource/32sa-8pi3.json?$order=vigenciadesde%20DESC&$limit=2"); head(r, 300)
r = get("https://www.datos.gov.co/resource/32sa-8pi3.json?$select=count(*)"); head(r, 100)
r = get("https://www.banrep.gov.co/sites/default/files/resumen-semanal%E2%80%93estadisticas-monetarias-y-cambiarias.xlsx")
if r is not None and r.ok and r.content[:2] == b"PK":
    x = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None)
    print("HOJAS", list(x)[:30])
    for sh, df in list(x.items())[:6]:
        df = df.dropna(how="all").dropna(axis=1, how="all")
        print("   HOJA", sh, df.shape); print(df.head(12).to_string(max_colwidth=28)[:1600])
else: head(r, 200)
for u in ["https://www.banrep.gov.co/es/estadisticas/reservas-internacionales", "https://www.banrep.gov.co/es/estadisticas/trm",
          "https://www.banrep.gov.co/es/estadisticas/tasas-interes-politica-monetaria", "https://www.banrep.gov.co/es/estadisticas/intervencion-cambiaria"]:
    r = get(u)
    if r is not None:
        for m in sorted(set(re.findall(r'(?:href|src)="([^"]+\.(?:xlsx?|csv|json)[^"]*)"', r.text)))[:12]: print("  FILE", m[:170])
        for m in sorted(set(re.findall(r'(https?://[a-z]+\.banrep\.gov\.co/[^"\' ]{0,120})', r.text)))[:12]: print("  URL", m)
# EMBIG en el BCRP
API = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/{}/json/1998-01-01/2026-10-09"
for c in ["PD04711XD", "PD38581XD", "PD04715XD"]:
    r = get(API.format(c))
    try:
        j = json.loads(r.text); p = [x for x in j["periods"] if x["values"] and x["values"][0] not in ("n.d.", "")]
        print("  ", c, j["config"]["series"][0]["name"], len(p), p[0]["name"], "->", p[-1]["name"])
    except Exception as e: print("  fallo", e)
