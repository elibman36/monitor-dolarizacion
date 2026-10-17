import requests, json, concurrent.futures as cf
H={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
def f(n):
    cod=f"PN{n:05d}MM"
    try:
        r=requests.get(f"https://estadisticas.bcrp.gob.pe/estadisticas/series/api/{cod}/json/2026-6/2026-8",timeout=(10,30),headers=H)
        j=json.loads(r.text); return cod, j["config"]["series"][0]["name"], j["periods"][-1]["values"]
    except Exception: return cod, None, None
with cf.ThreadPoolExecutor(8) as ex:
    for cod,name,v in ex.map(f, range(60,1300)):
        if name and ("ista" in name or "Ahorro" in name or "ahorro" in name): print(cod, name[:170], v)
