import re, json, requests
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
def get(u, **kw):
    try:
        r = S.get(u, timeout=60, **kw); print(f"\n=== {r.status_code} {u} ({len(r.content)} b, {r.headers.get('content-type')})"); return r
    except Exception as e: print("\nERR", u, e)
def links(r, pat, maxn=60):
    if r is None: return
    n = 0
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r.text, re.S | re.I):
        txt = re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()
        if re.search(pat, m.group(1) + " " + txt, re.I):
            print("  LINK", m.group(1)[:140], "|", txt[:100]); n += 1
            if n >= maxn: break
# ---------------- PERU: BCRP ----------------
API = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/{}/json/{}/{}"
cand = ["PD04637PD", "PD04638PD", "PD04639PD", "PD04640PD", "PD04650MD", "PN00027MM", "PD04722MD", "PD04701XD", "PD04702XD",
        "PD31893DD", "PD04692MD", "PD04693MD", "PD04694MD", "PD04704XD", "PD04705XD", "PD04706XD", "PD04707XD", "PD04708XD", "PD04709XD", "PD04710XD", "PD04711XD", "PD04712XD"]
for c in cand:
    r = get(API.format(c, "2026-09-01", "2026-09-15"))
    if r is not None and r.ok:
        try:
            j = r.json(); print("  ", c, j.get("config", {}).get("series"), j.get("periods", [])[:2])
        except Exception as e: print("  no json", r.text[:200])
for page in ["https://estadisticas.bcrp.gob.pe/estadisticas/series/diarias",
             "https://estadisticas.bcrp.gob.pe/estadisticas/series/mensuales",
             "https://estadisticas.bcrp.gob.pe/estadisticas/series/ayuda/api"]:
    r = get(page); links(r, r"tipo de cambio|reserva|intervenci|swap|interbancari|embi|spread|dolariza|coeficiente|compra|venta|cdr|cdbcrp|derivad|posici", 80)
# ---------------- URUGUAY: BCU ----------------
for page in ["https://www.bcu.gub.uy/Estadisticas-e-Indicadores/Paginas/Default.aspx",
             "https://www.bcu.gub.uy/Estadisticas-e-Indicadores/Paginas/Cotizaciones.aspx",
             "https://www.bcu.gub.uy/Estadisticas-e-Indicadores/Paginas/Reservas-Internacionales.aspx",
             "https://www.bcu.gub.uy/Estadisticas-e-Indicadores/Paginas/Series-Estadisticas-del-Sistema-Financiero.aspx",
             "https://www.bcu.gub.uy/Estadisticas-e-Indicadores/Paginas/Intervenciones-en-el-Mercado-Cambiario.aspx",
             "https://www.bcu.gub.uy/Estadisticas-e-Indicadores/Paginas/Tasas-de-Interes.aspx"]:
    r = get(page); links(r, r"\.xls|\.xlsx|\.csv|cotiz|reserva|dep[oó]sit|interven|tasa|dolar|serie", 50)
# web service de cotizaciones
r = get("https://cotizaciones.bcu.gub.uy/wscotizaciones/servlet/awsbcucotizaciones?wsdl")
if r is not None: print(r.text[:600])
# UBI
for page in ["https://www.rafap.com.uy/mvdcms/Calculadoras-e-Indicadores/UBI-uc243", "https://www.rafap.com.uy/", "https://www.bevsa.com.uy/"]:
    r = get(page); links(r, r"ubi|riesgo|\.xls|curva|indice", 30)
