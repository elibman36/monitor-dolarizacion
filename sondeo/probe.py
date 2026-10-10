import re, io, json, requests, urllib3, pandas as pd
from playwright.sync_api import sync_playwright
urllib3.disable_warnings()
B = "https://www.bcu.gub.uy"
paginas = ["/Estadisticas-e-Indicadores/Paginas/Activos-de-reserva.aspx", "/Estadisticas-e-Indicadores/Paginas/Moneda-y-credito.aspx",
           "/Estadisticas-e-Indicadores/Paginas/Cotizaciones.aspx", "/Politica-Economica-y-Mercados/Paginas/Tasa-1-Dia.aspx",
           "/Estadisticas-e-Indicadores/Paginas/Default.aspx"]
encontrados = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(ignore_https_errors=True)
    for pg_url in paginas:
        pg = ctx.new_page()
        try:
            pg.goto(B + pg_url, timeout=90000, wait_until="networkidle")
            pg.wait_for_timeout(4000)
            links = pg.eval_on_selector_all("a", "els => els.map(e => [e.href, (e.innerText||'').trim().slice(0,90)])")
            print("\n=== ", pg_url, len(links), "links")
            for h, t in links:
                if re.search(r"\.(xlsx?|csv|pdf)(\?|$)", h, re.I) and "Seguros" not in h:
                    print("  FILE", h[:170], "|", t)
                    encontrados[h] = t
        except Exception as e:
            print("ERR", pg_url, str(e)[:200])
        pg.close()
    b.close()
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"
n = 0
for h, t in encontrados.items():
    if not re.search(r"\.xlsx?", h, re.I) or not re.search(r"reserv|activ|base|interv|divisa|tasa|monet|cotiz|diari", h + t, re.I): continue
    n += 1
    if n > 8: break
    r = S.get(h, verify=False, timeout=60); print("\n### GET", r.status_code, h[:150], len(r.content))
    try:
        x = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None)
        for sh, df in list(x.items())[:2]:
            df = df.dropna(how="all").dropna(axis=1, how="all")
            print("   HOJA", sh, df.shape); print(df.head(8).to_string(max_colwidth=30)[:1200]); print("   ...", df.tail(2).to_string(max_colwidth=25)[:500])
    except Exception as e: print("   no excel", e)
# DBnomics (FMI) para Uruguay
for sid in ["IMF/IFS/M.UY.RAXG_USD", "IMF/IFS/M.UY.ENDE_XDC_USD_RATE", "IMF/IFS/M.UY.FPOLM_PA", "IMF/IFS/M.UY.FIDR_PA",
            "IMF/IRFCL/M.UY.RAF_USD", "IMF/IFS/M.UY.RAFA_USD"]:
    try:
        r = S.get(f"https://api.db.nomics.world/v22/series/{sid}?observations=1", timeout=60)
        d = r.json()["series"]["docs"]
        if d:
            per, val = d[0]["period"], d[0]["value"]
            print("DBN", sid, d[0].get("series_name", "")[:80], "|", per[0], "->", per[-1], val[-1])
        else: print("DBN", sid, "vacío")
    except Exception as e: print("DBN", sid, "ERR", str(e)[:150])
