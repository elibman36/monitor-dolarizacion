import re, io, json, requests, urllib3, pandas as pd
urllib3.disable_warnings()
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
B = "https://www.bcu.gub.uy"
def get(u, **kw):
    kw.setdefault("timeout", 60); kw.setdefault("verify", False)
    try:
        r = S.get(u, **kw); print(f"\n=== {r.status_code} {u[:200]} ({len(r.content)} b, {r.headers.get('content-type')})"); return r
    except Exception as e: print("\nERR", u, str(e)[:200])
hits = {}
for q in ["reservas internacionales", "activos de reserva", "base monetaria diario", "intervenciones cambiarias", "compras de divisas",
          "tasa de politica monetaria", "planilla reservas liquidez moneda extranjera", "UBI", "dolarizacion depositos", "TMM call"]:
    u = B + "/_api/search/query?querytext='" + requests.utils.quote(q) + "'&rowlimit=25&selectproperties='Title,Path,LastModifiedTime'"
    r = get(u, headers={"Accept": "application/json;odata=nometadata"})
    if r is None or not r.ok: 
        if r is not None: print(r.text[:300])
        continue
    try:
        rows = r.json()["PrimaryQueryResult"]["RelevantResults"]["Table"]["Rows"]
    except Exception as e:
        print("  parse", e, r.text[:300]); continue
    for row in rows:
        c = {x["Key"]: x["Value"] for x in row["Cells"]}
        p = c.get("Path") or ""
        print("  HIT", q[:20], "|", (c.get("Title") or "")[:70], "|", p[:170], "|", (c.get("LastModifiedTime") or "")[:10])
        if re.search(r"\.(xlsx?|csv|pdf)$", p, re.I): hits[p] = c.get("Title")
# bajar algunos excel para ver estructura
n = 0
for p, t in hits.items():
    if not re.search(r"\.xlsx?$", p, re.I) or not re.search(r"reserv|activ|base|interv|divisa|tasa|tpm|monetar", p + str(t), re.I): continue
    n += 1
    if n > 8: break
    r = get(p)
    if r is None or not r.ok: continue
    try:
        x = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None)
        for sh, df in list(x.items())[:2]:
            df = df.dropna(how="all").dropna(axis=1, how="all")
            print("   HOJA", sh, df.shape); print(df.head(10).to_string(max_colwidth=35)[:1500]); print("   ...", df.tail(3).to_string(max_colwidth=25)[:700])
    except Exception as e: print("   no excel", e)
# historia del servicio de cotizaciones
body = """<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:cot="Cotiza"><soapenv:Header/><soapenv:Body>
<cot:wsbcucotizaciones.Execute><cot:Entrada><cot:Moneda><cot:item>2225</cot:item></cot:Moneda><cot:FechaDesde>{d}</cot:FechaDesde><cot:FechaHasta>{h}</cot:FechaHasta><cot:Grupo>0</cot:Grupo></cot:Entrada></cot:wsbcucotizaciones.Execute></soapenv:Body></soapenv:Envelope>"""
for d, h in [("2000-01-01", "2000-01-31"), ("2005-01-01", "2005-01-31"), ("2010-01-01", "2010-12-31"), ("2025-01-01", "2026-10-09")]:
    try:
        r = S.post("https://cotizaciones.bcu.gub.uy/wscotizaciones/servlet/awsbcucotizaciones", data=body.format(d=d, h=h), headers={"Content-Type": "text/xml; charset=utf-8"}, timeout=90)
        f = re.findall(r"<Fecha>([\d-]+)</Fecha>", r.text); v = re.findall(r"<TCV>([\d.]+)</TCV>", r.text)
        print("SOAP", d, h, r.status_code, len(f), f[:1], v[:1], f[-1:], v[-1:], re.findall(r"<mensaje>(.*?)</mensaje>", r.text)[:1])
    except Exception as e: print("SOAP ERR", e)
