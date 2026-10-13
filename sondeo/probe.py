import io, requests, pandas as pd, urllib3
urllib3.disable_warnings()
URL = "https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/informes/anexo-estadistico-mercado-cambios-balance-cambiario.xlsx"
r = requests.get(URL, timeout=180, verify=False, headers={"Accept": "*/*", "User-Agent": "Mozilla/5.0"})
print(r.status_code, len(r.content))
x = pd.ExcelFile(io.BytesIO(r.content), engine="openpyxl")
print("HOJAS", x.sheet_names)
d = pd.read_excel(x, sheet_name="Datos Mercado de Cambios")
d.columns = [str(c).strip() for c in d.columns]
print("COLS", list(d.columns), len(d))
print("ANEXOS", d["Anexo"].astype(str).str.strip().unique()[:40].tolist())
print("SECTORES", d["Sector"].astype(str).str.strip().unique().tolist())
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 90); pd.set_option("display.max_rows", 400)
m = d["Mes"].max(); print("ULTIMO MES", m)
nr = d[d.apply(lambda r: "no resid" in " ".join(str(v) for v in r.values).lower(), axis=1)]
print("FILAS CON 'no resid':", len(nr))
g = nr.groupby(["Anexo", "Sector", "A", "B", "C", "D"], dropna=False)["Monto"].sum()
print(g.round(-6).to_string()[:12000])
u = d[pd.to_datetime(d["Mes"]) >= "2026-01-01"]
k = u.groupby(["Sector", "A", "B", "C"], dropna=False)["Monto"].sum() / 1e6
print("RESUMEN 2026 POR SECTOR/CONCEPTO (M USD)")
print(k.round(0).to_string()[:15000])
for mes in ["2026-06", "2026-07", "2026-08", "2026-09"]:
    mm = nr[pd.to_datetime(nr["Mes"]).dt.strftime("%Y-%m") == mes]
    print("MES", mes, (mm.groupby(["B", "C"])["Monto"].sum() / 1e6).round(0).to_dict())
