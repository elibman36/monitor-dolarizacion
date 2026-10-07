import re, io, requests, collections
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
def get(u, **k):
    try:
        r = S.get(u, timeout=90, **k); print(f"\n=== {r.status_code} {u} {k.get('params','')} ({len(r.content)} bytes)"); return r
    except Exception as e:
        print(f"\n=== ERROR {u}: {e}"); return None
# ArgentinaDatos coverage
for casa in ["oficial","mayorista","bolsa","contadoconliqui","blue"]:
    r = get(f"https://api.argentinadatos.com/v1/cotizaciones/dolares/{casa}")
    if r is not None and r.ok:
        d = r.json(); print(casa, len(d), d[0], d[-1])
r = get("https://api.argentinadatos.com/v1/finanzas/indices/riesgo-pais")
if r is not None and r.ok: d = r.json(); print("riesgo", len(d), d[0], d[-1])
# A3 history variants
A3 = "https://apicem.matbarofex.com.ar/api/v2/closing-prices"
for a, b in [("2020-01-01","2020-12-31"),("2019-06-01","2019-12-31"),("2015-01-01","2015-12-31"),("2010-01-01","2010-12-31"),("2003-01-01","2003-12-31")]:
    for params in [{"product":"DLR","segment":"Monedas","type":"FUT"},{"product":"DLR"},{"segment":"Monedas","type":"FUT"}]:
        p = dict(params, **{"excludeEmptyVol":"false","from":a,"to":b,"_ds":"1","pageSize":1000})
        r = get(A3, params=p)
        if r is not None and r.ok:
            d = r.json(); data = d.get("data", [])
            print("total", d.get("totalEntries"), "pageSize", d.get("pageSize"), "rows", len(data), collections.Counter(x.get("symbol","")[:8] for x in data).most_common(6))
# BCRA anexo
r = get("https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/informes/anexo-estadistico-mercado-cambios-balance-cambiario.xlsx")
if r is not None and r.ok:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)
    for ws in wb.worksheets:
        print("\n--- HOJA", ws.title, ws.max_row, ws.max_column)
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            vals = [v for v in row if v is not None]
            txt = " | ".join(str(v)[:40] for v in row[:12])
            if i < 12 or any(isinstance(v, str) and re.search(r"humana|formaci|atesor|billete|FAE|persona", v, re.I) for v in vals):
                print(i, txt)
            if i > 400: break
