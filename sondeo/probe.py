import logging, sys
sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO)
from monitor import build, config
df = build.load_posicion_bcra(False)
print("CSVSTART"); print(df.to_csv(index=False)); print("CSVEND")
print(open(config.SERIES_DIR / "_descargas.json").read())
