import io, re, requests, pdfplumber
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
B = "https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/"
for code in ["0103", "0606", "1208", "0110", "0611", "1211"]:
    r = S.get(B + f"temp{code}.pdf", timeout=40)
    print("\n#####", code, r.status_code, len(r.content), r.content[:8])
    if r.content[:4] != b"%PDF": continue
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        print("paginas", len(pdf.pages))
        txt = "\n".join((p.extract_text() or "") for p in pdf.pages)
    print("chars", len(txt))
    t = re.sub(r"[ \t]+", " ", txt)
    print("HEAD:", repr(t[:300]))
    for kw in ["liquidad", "otros medios", "moneda nacional", "IV.", "futuros", "Posiciones cortas", "short"]:
        for m in list(re.finditer(re.escape(kw), t))[:3]:
            print(f"  [{kw}] ...{t[max(0, m.start()-150):m.start()+350]!r}")
