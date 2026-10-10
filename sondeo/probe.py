import re, json, io, requests, pandas as pd
from playwright.sync_api import sync_playwright
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"
# 1) suameca: capturar las llamadas del graficador / descarga múltiple
urls = set()
with sync_playwright() as p:
    b = p.chromium.launch(); ctx = b.new_context(ignore_https_errors=True); pg = ctx.new_page()
    pg.on("request", lambda r: urls.add((r.method, r.url[:220])) if r.resource_type in ("xhr", "fetch") else None)
    for u in ["https://suameca.banrep.gov.co/descarga-multiple-de-datos/", "https://suameca.banrep.gov.co/graficador-interactivo/",
              "https://suameca.banrep.gov.co/estadisticas-economicas/catalogo"]:
        try:
            pg.goto(u, timeout=90000, wait_until="networkidle"); pg.wait_for_timeout(5000)
            txt = pg.inner_text("body")[:1500].replace("\n", " | ")
            print("\n=== ", u, "\n", txt)
        except Exception as e: print("ERR", u, str(e)[:150])
    b.close()
print("\nXHR:")
for m, u in sorted(urls): print(" ", m, u)
# 2) historial de atuações del BCB (estructura)
r = S.get("https://www.bcb.gov.br/conteudo/dadosabertos/BCBDepin/historico-atuacoes-mercado-cambio.csv", timeout=90)
print("\nBCB atuacoes", r.status_code, len(r.content))
t = r.content.decode("latin-1", "replace")
lines = t.splitlines(); print(len(lines)); print("\n".join(lines[:8])); print("..."); print("\n".join(lines[-5:]))
