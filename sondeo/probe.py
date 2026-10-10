import io, re, requests, pdfplumber
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
B = "https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/"
def num(x):
    x = x.strip()
    m = re.search(r"[.,](\d{1,2})$", x)
    if m:
        ent, dec = x[:m.start()], m.group(1)
    else:
        ent, dec = x, "0"
    return float(re.sub(r"[.,]", "", ent) + "." + dec)
N = r"(-?\d[\d.,]*)"
def parse(txt):
    t = re.sub(r"[ \t]+", " ", txt)
    fecha = re.search(r"final del per[ií]odo\)?\s*(\d{2}/\d{2}/\d{2,4})", t)
    i = t.find("liquidados por otros medios")
    if i < 0: return fecha and fecha.group(1), None, None
    seg = t[i:i+700]
    c = re.search(r"Posiciones cortas[^\d\n-]*" + N, seg)
    l = re.search(r"Posiciones largas[^\d\n-]*" + N, seg)
    return fecha and fecha.group(1), c and num(c.group(1)), l and num(l.group(1))
def pdftext(content):
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)
# variantes de nombre para el hueco
for code in ["0723", "1023", "0124", "0524"]:
    mm, yy = code[:2], code[2:]
    for name in [f"Temp{code}.pdf", f"temp{mm}20{yy}.pdf", f"temp{int(mm)}{yy}.pdf", f"TEMP{code}.pdf", f"temp{code}.PDF", f"temp{code}_.pdf"]:
        try:
            r = S.get(B + name, timeout=20); print("VAR", name, r.status_code, r.content[:4])
        except Exception as e: print("VAR", name, "ERR", e)
    for snap in ["2024", "2023"]:
        u = f"https://web.archive.org/web/{snap}id_/{B}temp{code}.pdf"
        try:
            r = S.get(u, timeout=40); print("WB", code, snap, r.status_code, r.content[:4], len(r.content))
            if r.content[:4] == b"%PDF": print("   WBPARSE", parse(pdftext(r.content)))
        except Exception as e: print("WB", code, "ERR", e)
    try:
        r = S.get(f"https://archive.org/wayback/available?url={B}temp{code}.pdf", timeout=30); print("AVAIL", code, r.text[:300])
    except Exception as e: print("AVAIL ERR", e)
# historia vieja y re-parseo de casos con decimales ingleses
for y in list(range(1, 14)) + [16, 17, 18, 19]:
    for m in (1, 6) if y < 14 else (6, 12):
        code = f"{m:02d}{y:02d}"
        try:
            r = S.get(B + f"temp{code}.pdf", timeout=40)
        except Exception as e:
            print(code, "ERR", e); continue
        if r.content[:4] != b"%PDF":
            print(code, "NOPDF", r.status_code); continue
        print(code, parse(pdftext(r.content)))
