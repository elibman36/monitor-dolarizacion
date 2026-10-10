import io, requests, urllib3, pandas as pd
urllib3.disable_warnings()
pd.set_option("display.width", 250)
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"
r = S.get("https://www.bcu.gub.uy/Estadisticas-e-Indicadores/MonedayCredito/Activos-de-Reserva/reservas.xls", verify=False, timeout=90)
df = pd.read_excel(io.BytesIO(r.content), header=None)
print(df.shape)
for i in range(3, 12): print(i, [str(x)[:60] for x in df.iloc[i].tolist()])
d = df[pd.to_datetime(df[3], errors="coerce").notna()]
print("filas con fecha", len(d), d[3].iloc[0], "->", d[3].iloc[-1])
print(d.head(3).to_string()); print(d.tail(5).to_string())
print(df.iloc[-14:, 2:5].to_string())
r = S.get("https://www.bcu.gub.uy/Servicios-Financieros-SSF/Series%20IF/Depositos.xlsx", verify=False, timeout=90)
x = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None)
print("HOJAS", list(x))
for sh in x:
    if "total" in sh.lower() or "sist" in sh.lower():
        t = x[sh]; print("=== ", sh, t.shape)
        for i in range(0, 14): print(i, [str(v)[:28] for v in t.iloc[i].tolist()])
        tt = t[pd.to_datetime(t[0], errors="coerce").notna()]
        print("filas fecha", len(tt)); print(tt.head(2).to_string()[:1500]); print(tt.tail(3).to_string()[:1500])
