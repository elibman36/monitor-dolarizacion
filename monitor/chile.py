"""Monitor de Dolarización - Chile.

Chile tiene tipo de cambio flotante y el Banco Central interviene sólo en
episodios puntuales (2008, 2011, 2019-2020, 2022). La versión actual usa las
fuentes abiertas que no requieren registro:

- dólar observado, tasa de política monetaria (TPM) y precio del cobre:
  mindicador.cl, que replica los datos oficiales del Banco Central de Chile;
- EMBIG Chile, publicado por el BCRP.

Las reservas y la intervención del Banco Central de Chile están en su API
(BDE), que exige registrarse y una clave. Con la clave (secreto
BCCH_USER / BCCH_PASS) se pueden sumar como componentes.

Uso: python -m monitor.chile [--offline]
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from . import comun, config

log = logging.getLogger("monitor.chile")

PAIS = {"codigo": "cl", "nombre": "Chile", "publicar_desde": "2003-01-01"}
DATA_DIR = config.DATA_DIR / "cl"
SERIES_DIR = DATA_DIR / "series"
MINDICADOR = "https://mindicador.cl/api/{indicador}/{anio}"
INDICADORES = {"tc": "dolar", "tpm": "tpm", "cobre": "libra_cobre"}
DESDE = "1999-01-01"
EMBIG = "PD38581XD"

IPD_BLOCKS = {
    "cambiaria": {
        "label": "Presión cambiaria",
        "weight": 0.5,
        "components": {
            "tc": {"transform": "dlog", "sign": +1, "weight": 1.0, "label": "Depreciación del peso",
                   "frases": ("el peso se depreció más que lo habitual", "el peso se depreció menos que lo habitual")},
            "vol_tc": {"transform": "level", "sign": +1, "weight": 1.0, "label": "Volatilidad del tipo de cambio",
                       "frases": ("la volatilidad del peso está por encima de lo habitual",
                                  "la volatilidad del peso está por debajo de lo habitual")},
            # El cobre explica buena parte del peso chileno: su caída es
            # presión sobre la moneda (menos dólares de exportación).
            "cobre": {"transform": "dlog", "sign": -1, "weight": 1.0, "label": "Precio del cobre",
                      "frases": ("cayó el precio del cobre más que lo habitual", "el precio del cobre evolucionó mejor que lo habitual")},
        },
    },
    "riesgo": {
        "label": "Riesgo y tasas",
        "weight": 0.5,
        "components": {
            "embig": {"transform": "diff", "sign": +1, "weight": 1.0, "label": "Riesgo país (EMBIG)",
                      "frases": ("subió el riesgo país", "bajó el riesgo país")},
            "tpm": {"transform": "diff", "horizonte": 21, "sign": +1, "weight": 1.0, "label": "Tasa de política monetaria",
                    "frases": ("el Banco Central subió la TPM", "el Banco Central bajó la TPM")},
        },
    },
}

SERIES_META = {
    "ipd": ("Índice de Presión de Dolarización", "desvíos estándar", "IPD"),
    "tc": ("Dólar observado", "$ por USD", "Banco Central de Chile (vía mindicador.cl)"),
    "cobre": ("Precio del cobre", "USD por libra", "Banco Central de Chile (vía mindicador.cl)"),
    "tpm": ("Tasa de política monetaria", "%", "Banco Central de Chile (vía mindicador.cl)"),
    "embig": ("Riesgo país (EMBIG Chile)", "pb", "BCRP (JP Morgan)"),
    "vol_tc": ("Volatilidad del tipo de cambio (20 días)", "% anualizada", "Cálculo propio"),
}

EVENTS = [
    {"date": "2005-12-11", "label": "Elecciones 2005", "tipo": "electoral"},
    {"date": "2008-09-15", "label": "Quiebra de Lehman", "tipo": "cambiario"},
    {"date": "2009-12-13", "label": "Elecciones 2009", "tipo": "electoral"},
    {"date": "2013-11-17", "label": "Elecciones 2013", "tipo": "electoral"},
    {"date": "2017-11-19", "label": "Elecciones 2017", "tipo": "electoral"},
    {"date": "2019-10-18", "label": "Estallido social", "tipo": "cambiario"},
    {"date": "2020-03-11", "label": "Pandemia", "tipo": "cambiario"},
    {"date": "2021-11-21", "label": "Elecciones 2021", "tipo": "electoral"},
    {"date": "2022-09-04", "label": "Plebiscito constitucional", "tipo": "electoral"},
    {"date": "2025-11-16", "label": "Elecciones 2025", "tipo": "electoral"},
]


def parse_mindicador(payload: dict, name: str) -> pd.Series:
    serie = payload.get("serie", []) or []
    if not serie:
        return pd.Series(dtype=float, name=name, index=pd.DatetimeIndex([], name="fecha"))
    # Las fechas vienen en UTC a las 03:00 (medianoche en Chile).
    fechas = pd.to_datetime([x["fecha"] for x in serie], utc=True).tz_convert("America/Santiago").tz_localize(None).normalize()
    s = pd.Series([float(x["valor"]) for x in serie], index=pd.DatetimeIndex(fechas, name="fecha"), name=name)
    return s[~s.index.duplicated(keep="last")].sort_index()


def mindicador(indicador: str, name: str):
    def f(desde: pd.Timestamp, hasta: pd.Timestamp) -> pd.Series:
        partes = [parse_mindicador(comun.get(MINDICADOR.format(indicador=indicador, anio=a)).json(), name)
                  for a in range(desde.year, hasta.year + 1)]
        s = pd.concat(partes)
        return s[(s.index >= desde) & ~s.index.duplicated(keep="last")]
    return f


def fetch_all(offline: bool) -> tuple[dict, dict]:
    raw, status = {}, {}
    for key, ind in INDICADORES.items():
        raw[key], status[key] = comun.actualizar(SERIES_DIR, key, mindicador(ind, key), DESDE, offline=offline)
    raw["embig"], status["embig"] = comun.actualizar(SERIES_DIR, "embig", comun.embig_bcrp(EMBIG), "1999-01-01",
                                                     solapamiento_dias=120, offline=offline)
    return raw, status


def derived_series(raw: dict) -> pd.DataFrame:
    df = comun.panel_diario(raw, ["tc", "cobre", "tpm", "embig"])
    df["vol_tc"] = comun.vol(df["tc"])
    return df


def run(offline: bool = False) -> dict:
    raw, status = fetch_all(offline)
    if raw["tc"].empty:
        raise SystemExit("Chile: no hay tipo de cambio disponible.")
    return comun.publicar(PAIS, IPD_BLOCKS, SERIES_META, EVENTS, raw, status, derived_series(raw), DATA_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run(offline=parser.parse_args().offline)


if __name__ == "__main__":
    main()
