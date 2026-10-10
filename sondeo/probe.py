import re, io, requests
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
B = "https://www.bcra.gob.ar"
def get(u):
    try:
        r = S.get(u, timeout=90); print(f"\n=== {r.status_code} {u} ({len(r.content)} bytes, {r.headers.get('content-type')})"); return r
    except Exception as e: print("ERR", u, e)
def links(r, pat):
    if r is None: return []
    hs = sorted(set(re.findall(r'href=["\']([^"\']+)["\']', r.text)))
    out = [h for h in hs if re.search(pat, h, re.I)]
    for h in out[:60]: print("  ", h)
    return out
found = []
for u in [B + "/estadisticas-indicadores/", B + "/publicaciones-estadisticas/", B]:
    r = get(u); found += links(r, r"reserv|liquidez|fmi|sdds")
cands = [h if h.startswith("http") else B + h for h in found if not h.endswith((".pdf",))]
xls = []
for u in dict.fromkeys(cands):
    if re.search(r"\.xls", u, re.I): xls.append(u); continue
    r = get(u); xls += [h if h.startswith("http") else B + h for h in links(r, r"\.xls|\.xlsx|\.zip")]
print("\nXLS:", xls[:30])
import openpyxl, xlrd
for u in list(dict.fromkeys(xls))[:6]:
    r = get(u)
    if r is None or not r.ok: continue
    try:
        if u.lower().endswith(".xls"):
            wb = xlrd.open_workbook(file_contents=r.content)
            for sh in wb.sheets()[:6]:
                print("--- HOJA", sh.name, sh.nrows, sh.ncols)
                for i in range(min(sh.nrows, 400)):
                    row = [str(v)[:30] for v in sh.row_values(i)[:10]]
                    txt = " | ".join(row)
                    if i < 8 or re.search(r"futur|forward|derivad|short|long", txt, re.I): print(i, txt)
        else:
            wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)
            for ws in wb.worksheets[:6]:
                print("--- HOJA", ws.title)
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    txt = " | ".join(str(v)[:30] for v in row[:10])
                    if i < 8 or re.search(r"futur|forward|derivad|short|long", txt, re.I): print(i, txt)
                    if i > 400: break
    except Exception as e: print("parse err", e)
