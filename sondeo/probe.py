import re, json, requests, urllib3
urllib3.disable_warnings()
S = requests.Session(); S.verify = False; S.headers["User-Agent"] = "Mozilla/5.0"; S.headers["Accept"] = "application/json"
B = "https://suameca.banrep.gov.co"
SVC = B + "/graficador-series/rest/graficadorService"
js = S.get(B + "/graficador-interactivo/main-IXSDOCJ3.js", timeout=90).text
i = js.find("graficador-series/rest/graficadorService")
print("contexto:", js[max(0, i-300): i+300].replace("\n", " "))
metodos = sorted(set(re.findall(r'["\'`]/((?:consulta|obtener|listar|buscar|descarga|generar|exportar)[A-Za-z]*)', js)))
print("METODOS", metodos)
for m in re.finditer(r'(consulta[A-Za-z]*|obtener[A-Za-z]*|descarga[A-Za-z]*)\??[^"\'`]{0,80}', js):
    pass
for m in sorted(set(re.findall(r'["\'`]/?(consulta[A-Za-z]+\?[a-zA-Z]+=)', js))): print("  QS", m)
cat = S.get(SVC + "/consultaCatalogo", timeout=120).json()
m2 = cat.get("mapCategoriaNivel2", {})
for k in ["Reservas internacionales", "Operaciones en el mercado cambiario", "Tasas de interés", "Tasas de cambio nominales"]:
    for it in m2.get(k, [])[:60]:
        print(" ", k[:18], "|", it.get("id"), "|", it.get("nombre", "")[:90], "|", it.get("periodicidad") or it.get("idPeriodicidad"))
print("CLAVES item:", list((m2.get("Reservas internacionales") or [{}])[0].keys()))
# probar métodos candidatos con una serie
ids = [it["id"] for it in m2.get("Reservas internacionales", [])[:1]]
for met in metodos[:25]:
    for q in ["idSerie", "idsSerie", "id"]:
        for sid in ids:
            u = f"{SVC}/{met}?{q}={sid}"
            try:
                r = S.get(u, timeout=40)
                if r.ok and len(r.content) > 200: print("  OK", r.status_code, u, len(r.content), r.text[:250].replace("\n", " "))
            except Exception as e: pass
