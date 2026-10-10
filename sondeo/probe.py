import re, io, requests
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (monitor-dolarizacion probe)"
B = "https://www.bcra.gob.ar"
def get(u):
    try:
        r = S.get(u, timeout=90); print(f"\n=== {r.status_code} {u} ({len(r.content)} bytes, {r.headers.get('content-type')})"); return r
    except Exception as e: print("ERR", u, e)
r = get(B + "/normas-especiales-para-la-divulgacion-de-datos-fmi/")
if r is not None:
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r.text, re.S | re.I):
        txt = re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()
        h = m.group(1)
        if "archivos" in h or re.search(r"reserv|liquidez|moneda extranjera", txt, re.I):
            print("  LINK", h, "|", txt[:90])
r = get(B + "/reservas-internacionales-y-base-monetaria/")
if r is not None:
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r.text, re.S | re.I):
        txt = re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()
        if "archivos" in m.group(1): print("  LINK", m.group(1), "|", txt[:90])
