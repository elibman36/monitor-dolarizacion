import requests, io, pandas as pd
A={"Accept":"application/vnd.sdmx.data+csv;version=1.0.0","User-Agent":"Mozilla/5.0"}
for key in ["W00.PALLFNF.IX.M","G001.PALLFNF.INDEX.M","W00.PALLFNF.INDEX.M","..IX.M","W00.PALLFNF..M","W00...M"]:
    try:
        r=requests.get(f"https://api.imf.org/external/sdmx/2.1/data/IMF.RES,PCPS/{key}?startPeriod=2024",headers=A,timeout=(15,60))
        d=pd.read_csv(io.StringIO(r.text),low_memory=False)
        print(key,r.status_code,len(d))
        if len(d): print(d[["COUNTRY","INDICATOR","DATA_TRANSFORMATION","FREQUENCY"]].drop_duplicates().head(30).to_string()); print(d[["TIME_PERIOD","OBS_VALUE"]].tail(3))
    except Exception as e: print(key,"ERR",e)
