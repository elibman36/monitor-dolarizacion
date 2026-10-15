import requests, urllib3, io, pandas as pd, json
urllib3.disable_warnings()
H={"User-Agent":"Mozilla/5.0"}
def bcrp(codes):
    url="https://estadisticas.bcrp.gob.pe/estadisticas/series/api/"+"-".join(codes)+"/json/2025-01/2026-12"
    try:
        r=requests.get(url,timeout=60,headers=H).json()
        for s,c in zip(r["config"]["series"],codes): print("BCRP",c,"|",s["name"][:110],"| ult:",r["periods"][-1]["name"] if r.get("periods") else None)
    except Exception as e: print("BCRP err",codes[:2],e)
cands=[f"PN{n:05d}MM" for n in list(range(20,34))+list(range(505,520))]
for i in range(0,len(cands),6): bcrp(cands[i:i+6])
# semanales candidatos
for c in ["PS00000SM","PN01207PM","PD37960DS"]: bcrp([c])
# Uruguay BCU: archivos de series IF
for f in ["Depositos.xlsx","Creditos.xlsx","Credito.xlsx","Creditos%20al%20SNF.xlsx","Activos.xlsx","Colocaciones.xlsx"]:
    u="https://www.bcu.gub.uy/Servicios-Financieros-SSF/Series%20IF/"+f
    try:
        r=requests.get(u,timeout=60,verify=False,headers=H); print("BCU",f,r.status_code,len(r.content))
        if r.status_code==200 and len(r.content)>1000:
            x=pd.ExcelFile(io.BytesIO(r.content)); print("   hojas",x.sheet_names[:15])
            d=pd.read_excel(x,sheet_name=x.sheet_names[0],header=None); print(d.iloc[:12,:8].to_string()[:1500])
    except Exception as e: print("BCU",f,e)
# BIS LBS
for key in ["Q.S.L.A.TO1.A.5J.A.5A.N.AR.N","Q.S.L.D.TO1.A.5J.A.5A.N.AR.N","Q.S.L.A.USD.A.5J.A.5A.N.AR.N"]:
    for base in ["https://stats.bis.org/api/v2/data/dataflow/BIS/WS_LBS_D_PUB/1.0/","https://stats.bis.org/api/v1/data/WS_LBS_D_PUB/"]:
        u=base+key+"?startPeriod=2023&format=csv"
        try:
            r=requests.get(u,timeout=60,headers=H); print("BIS",base[-30:],key,r.status_code,r.text[:300].replace("\n"," | "))
        except Exception as e: print("BIS err",e)
