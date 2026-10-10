import io, re, requests, pdfplumber
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
B = "https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/"
def get(u):
    try:
        r = S.get(u, timeout=60); print(f"=== {r.status_code} {u} ({len(r.content)} b, {r.headers.get('content-type')})"); return r
    except Exception as e: print("ERR", u, e)
r = get(B + "temp0826.pdf")
if r is not None and r.ok and r.content[:4] == b"%PDF":
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        print("paginas", len(pdf.pages))
        for i, p in enumerate(pdf.pages):
            t = p.extract_text() or ""
            print(f"\n----- PAGINA {i+1} -----\n{t[:6000]}")
# historico
for y in range(14, 27):
    for m in (1, 6, 12):
        u = B + f"temp{m:02d}{y:02d}.pdf"
        try:
            h = S.get(u, timeout=30)
            print("HIST", f"{m:02d}{y:02d}", h.status_code, len(h.content), h.content[:4])
        except Exception as e:
            print("HIST", f"{m:02d}{y:02d}", "ERR", e)
for name in ("temp.pdf", "temp0726.pdf", "temp0925.pdf", "temp1025.pdf", "temp1224.pdf"):
    h = get(B + name)
