import re, requests, urllib3
urllib3.disable_warnings()
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
def get(u, **kw):
    kw.setdefault("timeout", 60)
    try:
        r = S.get(u, **kw); print(f"\n=== {r.status_code} {u} ({len(r.content)} b, {r.headers.get('content-type')})"); return r
    except Exception as e: print("\nERR", u, str(e)[:200])
def links(r, pat, maxn=80):
    if r is None: return []
    out = []
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r.text, re.S | re.I):
        txt = re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()
        if re.search(pat, m.group(1) + " " + txt, re.I):
            print("  LINK", m.group(1)[:160], "|", txt[:100]); out.append(m.group(1))
            if len(out) >= maxn: break
    return out
# ---------- Perú: largo de las series ----------
API = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/{}/json/1990-01-01/2026-12-31"
for c in ["PD04638PD", "PD04650MD", "PD04659MD", "PD04660MD", "PD37515TD", "PD37516TD", "PD37521TD", "PD04692MD", "PD04709XD", "PD31893DD", "PD04649MD"]:
    r = get(API.format(c))
    try:
        j = r.json(); p = [x for x in j["periods"] if x["values"] and x["values"][0] not in ("n.d.", "")]
        print("  ", c, j["config"]["series"][0]["name"], "| obs", len(p), "|", p[0]["name"] if p else None, "->", p[-1]["name"] if p else None, p[-1]["values"] if p else None)
    except Exception as e: print("  fallo", e)
APIm = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/{}/json/1990-1/2026-12"
for c in ["PN00025MM", "PN00143MM", "PN00511MM", "PN41478MM", "PN01033MM"]:
    r = get(APIm.format(c))
    try:
        j = r.json(); p = [x for x in j["periods"] if x["values"] and x["values"][0] not in ("n.d.", "")]
        print("  ", c, j["config"]["series"][0]["name"], "| obs", len(p), "|", p[0]["name"], "->", p[-1]["name"], p[-1]["values"])
    except Exception as e: print("  fallo", e)
# ---------- Uruguay: BCU (certificado incompleto: verify=False sólo para sondear) ----------
B = "https://www.bcu.gub.uy"
found = []
for page in ["/Estadisticas-e-Indicadores/Paginas/Default.aspx",
             "/Estadisticas-e-Indicadores/Paginas/Cotizaciones.aspx",
             "/Estadisticas-e-Indicadores/Paginas/Reservas-Internacionales.aspx",
             "/Estadisticas-e-Indicadores/Paginas/Series-Estadisticas-del-Sistema-Financiero.aspx",
             "/Estadisticas-e-Indicadores/Paginas/Intervenciones-en-el-Mercado-Cambiario.aspx",
             "/Estadisticas-e-Indicadores/Paginas/Tasas-de-Interes.aspx",
             "/Estadisticas-e-Indicadores/Paginas/Activos-de-Reserva.aspx",
             "/Estadisticas-e-Indicadores/Paginas/Operaciones-del-BCU.aspx"]:
    r = get(B + page, verify=False)
    found += links(r, r"\.xls|\.xlsx|\.csv|Paginas/[^\"']*(cotiz|reserv|dep|interv|tasa|dolar|serie|monetar|cambi|operac|riesgo)", 70)
for u in sorted(set(f for f in found if re.search(r"\.xlsx?$|\.csv$", f, re.I)))[:12]:
    url = u if u.startswith("http") else B + u
    r = get(url, verify=False)
    if r is not None and r.ok and len(r.content) > 1000:
        try:
            import pandas as pd, io
            x = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None)
            for sh, df in list(x.items())[:2]:
                print("   HOJA", sh, df.shape); print(df.head(10).to_string()[:1200]); print(df.tail(3).to_string()[:600])
        except Exception as e: print("   no excel", e)
# SOAP cotizaciones: dólar interbancario (2225)
body = """<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:cot="Cotiza"><soapenv:Header/><soapenv:Body>
<cot:wsbcucotizaciones.Execute><cot:Entrada><cot:Moneda><cot:item>2225</cot:item></cot:Moneda><cot:FechaDesde>2026-09-01</cot:FechaDesde><cot:FechaHasta>2026-09-10</cot:FechaHasta><cot:Grupo>0</cot:Grupo></cot:Entrada></cot:wsbcucotizaciones.Execute></soapenv:Body></soapenv:Envelope>"""
try:
    r = S.post("https://cotizaciones.bcu.gub.uy/wscotizaciones/servlet/awsbcucotizaciones", data=body, headers={"Content-Type": "text/xml; charset=utf-8"}, timeout=60)
    print("\nSOAP", r.status_code, r.text[:1500])
except Exception as e: print("SOAP ERR", e)
# UBI
r = get("https://www.rafap.com.uy/mvdcms/Calculadoras-e-Indicadores/UBI-uc243")
if r is not None:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t); t = re.sub(r"\s+", " ", t)
    i = t.find("UBI"); print("  TEXTO", t[max(0, i-200): i+1500])
    for m in re.finditer(r'(src|href|url)\s*[=:]\s*["\']([^"\']+)', r.text):
        if re.search(r"ubi|json|api|xls|csv|serv", m.group(2), re.I): print("  REF", m.group(2)[:160])
