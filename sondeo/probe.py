import io, re, requests, pdfplumber
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
B = "https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/"
NUM = r"(-?[\d\.]+,\d+)"
def parse(txt):
    t = re.sub(r"[ \t]+", " ", txt)
    fecha = re.search(r"final del per[ií]odo\)?\s*(\d{2}/\d{2}/\d{2,4})", t)
    i = t.find("liquidados por otros medios")
    if i < 0: return fecha and fecha.group(1), None, None, t[:0]
    seg = t[i:i+900]
    c = re.search(r"Posiciones cortas\s*\(?\s*[-–]?\s*\)?\s*" + NUM, seg)
    l = re.search(r"Posiciones largas\s*\(?\s*\+?\s*\)?\s*" + NUM, seg)
    return fecha and fecha.group(1), c and c.group(1), l and l.group(1), seg
for y in [10, 11, 12, 13]:
    h = S.get(B + f"temp01{y}.pdf", timeout=30); print("OLD", y, h.status_code, h.content[:4])
first = set()
for y in range(14, 27):
    for m in range(1, 13):
        if y == 26 and m > 9: break
        code = f"{m:02d}{y:02d}"
        try:
            r = S.get(B + f"temp{code}.pdf", timeout=40)
        except Exception as e:
            print(code, "ERR", e); continue
        if r.content[:4] != b"%PDF":
            print(code, "NOPDF", r.status_code); continue
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            txt = "\n".join((p.extract_text() or "") for p in pdf.pages)
        f, c, l, seg = parse(txt)
        print(code, "fecha", f, "cortas", c, "largas", l)
        if y not in first or c is None:
            first.add(y)
            print("   CTX:", repr(seg[:700]))
