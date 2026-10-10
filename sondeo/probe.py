import re, json, requests, urllib3
from datetime import datetime, timezone
urllib3.disable_warnings()
S = requests.Session(); S.verify = False; S.headers["User-Agent"] = "Mozilla/5.0"; S.headers["Accept"] = "application/json"
SVC = "https://suameca.banrep.gov.co/graficador-series/rest/graficadorService"
cat = S.get(SVC + "/consultaCatalogo", timeout=120).json()
todos = [it for v in cat.get("mapCategoriaNivel2", {}).values() for it in v]
for it in todos:
    n = it.get("nombre", "")
    if re.search(r"reservas internacionales|pol[ií]tica monetaria|intervenci|compra directa|venta de d[oó]lares|NDF|FX Swap|opciones put|opciones call|IBR\) overnight", n, re.I) and not re.search(r"Cupo|Prima|presentado|demandado|Tasa de co", n):
        print(it["id"], "|", n[:95], "|", it.get("descripcionPeriodicidad"), "|", it.get("fechaInicialFormateada"), "->", it.get("fechaFinalFormateada"), "|", it.get("unidad"))
def serie(i):
    r = S.get(f"{SVC}/consultaSerieParaGraficar?idSerie={i}", timeout=90)
    j = r.json(); x = j[0] if isinstance(j, list) else j
    d = x.get("data") or []
    f = lambda ms: datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    print("  SERIE", i, x.get("nombre"), x.get("descripcionPeriodicidad"), len(d), (f(d[0][0]), d[0][1]) if d else None, (f(d[-1][0]), d[-1][1]) if d else None, "| claves", [k for k in x.keys() if "data" in k.lower()])
for i in [15050, 15053, 16650, 16651, 16656, 16657, 241]:
    try: serie(i)
    except Exception as e: print("  ERR", i, e)
for it in todos:
    if re.search(r"tasa de pol[ií]tica|tasa de intervenci", it.get("nombre", ""), re.I):
        try: serie(it["id"])
        except Exception as e: print("  ERR", it["id"], e)
