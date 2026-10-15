import requests, urllib3, io, pandas as pd
urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0"}
pd.set_option("display.width",250); pd.set_option("display.max_columns",40); pd.set_option("display.max_colwidth",40)
r=requests.get("https://www.bcu.gub.uy/Servicios-Financieros-SSF/Series%20IF/Creditos.xlsx",timeout=90,verify=False,headers=H)
d=pd.read_excel(io.BytesIO(r.content),sheet_name="Total Sist. Banc.",header=None)
fila=next(i for i in range(40) if str(d.iloc[i,0]).strip().lower()=="mes")
print(d.iloc[max(0,fila-6):fila+4,:16].to_string())
print(d.iloc[-3:,:16].to_string())
r=requests.get("https://www.bcu.gub.uy/Servicios-Financieros-SSF/Series%20IF/Depositos.xlsx",timeout=90,verify=False,headers=H)
d=pd.read_excel(io.BytesIO(r.content),sheet_name="Total Sist. Banc.",header=None)
fila=next(i for i in range(40) if str(d.iloc[i,0]).strip().lower()=="mes")
print("DEPOSITOS"); print(d.iloc[max(0,fila-6):fila+4,:12].to_string())
for c in ["AR","BR"]:
    t=requests.get(f"https://stats.bis.org/api/v1/data/WS_LBS_D_PUB/Q.S.L.D.TO1.A.5J.A.5A.N.{c}.N?startPeriod=2025&format=csv",timeout=60,headers=H).text
    df=pd.read_csv(io.StringIO(t)); print(c, df[["UNIT_MEASURE","UNIT_MULT","TIME_PERIOD","OBS_VALUE"]].tail(3).to_string())
    t=requests.get(f"https://stats.bis.org/api/v1/data/WS_LBS_D_PUB/Q.S.L.A.TO1.A.5J.A.5A.N.{c}.N?startPeriod=2025&format=csv",timeout=60,headers=H).text
    df=pd.read_csv(io.StringIO(t)); print(c,"ALL INSTR", df[["UNIT_MULT","TIME_PERIOD","OBS_VALUE"]].tail(2).to_string())
