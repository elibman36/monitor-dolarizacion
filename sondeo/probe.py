import re, io, requests, urllib3, pandas as pd
urllib3.disable_warnings()
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
B = "https://www.bcu.gub.uy"
def get(u, **kw):
    kw.setdefault("timeout", 60); kw.setdefault("verify", False)
    try:
        r = S.get(u, **kw); print(f"\n=== {r.status_code} {u} ({len(r.content)} b, {r.headers.get('content-type')})"); return r
    except Exception as e: print("\nERR", u, str(e)[:200])
def archivos(r):
    out = []
    if r is None: return out
    for m in re.finditer(r'href=["\']([^"\']+\.(?:xlsx?|csv|pdf))["\']', r.text, re.I):
        h = m.group(1)
        if "Seguros" in h: continue
        # texto cercano
        ctx = re.sub(r"<[^>]+>|\s+", " ", r.text[max(0, m.start()-300):m.start()]).strip()[-90:]
        print("  FILE", h[:150], "|", ctx); out.append(h)
    return out
files = []
for page in ["/Estadisticas-e-Indicadores/Paginas/Activos-de-reserva.aspx",
             "/Estadisticas-e-Indicadores/Paginas/Moneda-y-credito.aspx",
             "/Estadisticas-e-Indicadores/Paginas/Cotizaciones.aspx",
             "/Servicios-Financieros-SSF/Paginas/Series-estadisticas-Depositos.aspx",
             "/Politica-Economica-y-Mercados/Paginas/Tasa-1-Dia.aspx",
             "/Politica-Economica-y-Mercados/Paginas/Default.aspx",
             "/Politica-Economica-y-Mercados/Paginas/Operaciones-de-Mercado-Abierto.aspx",
             "/Politica-Economica-y-Mercados/Paginas/Intervenciones-Cambiarias.aspx"]:
    r = get(B + page)
    files += archivos(r)
    if r is not None and "Politica-Economica-y-Mercados/Paginas/Default" in page:
        for m in re.finditer(r'href=["\'](/Politica-Economica-y-Mercados/Paginas/[^"\']+)["\']', r.text):
            print("  PAG", m.group(1))
pat = re.compile(r"reserv|activo|cambi|cotiz|dep[oó]s|dolar|interv|base|monet|tasa|call|1.?d", re.I)
vistos = set()
for f in files:
    if not pat.search(f) or f in vistos or not re.search(r"xlsx?$", f, re.I): continue
    vistos.add(f)
    if len(vistos) > 10: break
    url = f if f.startswith("http") else B + f
    r = get(url)
    if r is None or not r.ok: continue
    try:
        x = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None)
        for sh, df in list(x.items())[:2]:
            df = df.dropna(how="all").dropna(axis=1, how="all")
            print("   HOJA", sh, df.shape)
            print(df.head(12).to_string(max_colwidth=40)[:1800]); print("   ...", df.tail(3).to_string(max_colwidth=30)[:800])
    except Exception as e: print("   no excel", e)
# UBI: República AFAP
r = get("https://www.rafap.com.uy/mvdcms/", verify=True)
if r is not None:
    for m in re.finditer(r'href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r.text, re.S | re.I):
        t = re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()
        if re.search(r"ubi|indicador|riesgo", m.group(1) + t, re.I): print("  RAFAP", m.group(1)[:150], "|", t[:80])
