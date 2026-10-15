import requests, urllib3, io, pandas as pd
urllib3.disable_warnings()
r=requests.get("https://www.bcu.gub.uy/Servicios-Financieros-SSF/Series%20IF/Creditos.xlsx",timeout=90,verify=False,headers={"User-Agent":"Mozilla/5.0"})
d=pd.read_excel(io.BytesIO(r.content),sheet_name="Total Sist. Banc.",header=None)
print("SHAPE",d.shape)
for c in range(d.shape[1]):
    col=[str(x)[:45] for x in d.iloc[5:12,c].tolist()]
    if any(x!="nan" for x in col): print(c, " | ".join(col), "| ult:", d.iloc[-4,c] if d.shape[0]>4 else "")
# última fila con fecha
fechas=pd.to_datetime(d.iloc[:,0],errors="coerce"); ult=fechas.last_valid_index(); print("ULT FILA",ult,d.iloc[ult,:].tolist()[:60])
