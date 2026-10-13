import io, requests, pandas as pd, urllib3
urllib3.disable_warnings()
URL = "https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/informes/anexo-estadistico-mercado-cambios-balance-cambiario.xlsx"
r = requests.get(URL, timeout=180, verify=False, headers={"Accept": "*/*", "User-Agent": "Mozilla/5.0"})
d = pd.read_excel(io.BytesIO(r.content), sheet_name="Datos Mercado de Cambios", engine="openpyxl")
d.columns = [str(c).strip() for c in d.columns]
d["mes"] = pd.to_datetime(d["Mes"]).dt.strftime("%Y-%m")
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500); pd.set_option("display.max_columns", 30)
for b in d["B"].astype(str).unique():
    if "03- Cuenta" in "": pass
print("B DE CUENTA FINANCIERA:", sorted(d.loc[d["A"].astype(str).str.contains("Financiera"), "B"].astype(str).unique()))
nr = d[d["B"].astype(str).str.startswith("01- Inversi")]
print("D NO RESIDENTES:", sorted(nr["D"].astype(str).unique()))
print("PRIMER MES NR:", nr["mes"].min())
t = (nr.groupby(["mes", "D"])["Monto"].sum() / 1e6).unstack().round(0)
print(t.loc["2023-01":].to_string())
for pref in ["02- Pr", "04- Op", "05-", "06-"]:
    x = d[d["B"].astype(str).str.startswith(pref)]
    if x.empty: continue
    print("B", x["B"].iloc[0], "| D:", sorted(x["D"].astype(str).unique())[:12])
    print((x.groupby(["mes", "C"])["Monto"].sum() / 1e6).unstack().round(0).loc["2024-06":].to_string())
