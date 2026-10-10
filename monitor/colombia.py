"""Monitor de Dolarización - Colombia.

Tipo de cambio flotante; el Banco de la República interviene poco (subastas de
opciones, forwards y swaps en episodios puntuales). Fuentes automáticas:

- tasa representativa del mercado (TRM, certificada por la Superintendencia
  Financiera): datos.gov.co, diaria desde 1991;
- EMBIG Colombia, publicado por el BCRP.

Reservas, intervención y tasa de política del Banco de la República todavía no
tienen una fuente automática estable: se suman cuando la haya.

Uso: python -m monitor.colombia [--offline]
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from . import comun, config

log = logging.getLogger("monitor.colombia")

PAIS = {"codigo": "co", "nombre": "Colombia", "publicar_desde": "2003-01-01"}
DATA_DIR = config.DATA_DIR / "co"
SERIES_DIR = DATA_DIR / "series"
TRM_URL = "https://www.datos.gov.co/resource/32sa-8pi3.json"
DESDE = "1995-01-01"
EMBIG = "PD04715XD"

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
        },
    },
    "riesgo": {
        "label": "Riesgo",
        "weight": 0.5,
        "components": {
            "embig": {"transform": "diff", "sign": +1, "weight": 1.0, "label": "Riesgo país (EMBIG)",
                      "frases": ("subió el riesgo país", "bajó el riesgo país")},
        },
    },
}

SERIES_META = {
    "ipd": ("Índice de Presión de Dolarización", "desvíos estándar", "IPD"),
    "tc": ("Tasa representativa del mercado (TRM)", "$ por USD", "Superintendencia Financiera (datos.gov.co)"),
    "embig": ("Riesgo país (EMBIG Colombia)", "pb", "BCRP (JP Morgan)"),
    "vol_tc": ("Volatilidad del tipo de cambio (20 días)", "% anualizada", "Cálculo propio"),
}

EVENTS = [
    {"date": "2006-05-28", "label": "Elecciones 2006", "tipo": "electoral"},
    {"date": "2008-09-15", "label": "Quiebra de Lehman", "tipo": "cambiario"},
    {"date": "2010-05-30", "label": "Elecciones 2010", "tipo": "electoral"},
    {"date": "2014-05-25", "label": "Elecciones 2014", "tipo": "electoral"},
    {"date": "2014-11-27", "label": "Caída del petróleo", "tipo": "cambiario"},
    {"date": "2018-05-27", "label": "Elecciones 2018", "tipo": "electoral"},
    {"date": "2020-03-11", "label": "Pandemia", "tipo": "cambiario"},
    {"date": "2021-04-28", "label": "Paro nacional", "tipo": "cambiario"},
    {"date": "2022-05-29", "label": "Elecciones 2022", "tipo": "electoral"},
    {"date": "2026-05-31", "label": "Elecciones 2026", "tipo": "electoral"},
]


def parse_trm(registros: list[dict]) -> pd.Series:
    """Cada registro vale de `vigenciadesde` a `vigenciahasta` (fines de semana
    y feriados incluidos): se toma el día de inicio, que es día hábil."""
    if not registros:
        return pd.Series(dtype=float, name="tc", index=pd.DatetimeIndex([], name="fecha"))
    df = pd.DataFrame(registros)
    s = pd.Series(pd.to_numeric(df["valor"], errors="coerce").values,
                  index=pd.DatetimeIndex(pd.to_datetime(df["vigenciadesde"]).dt.normalize(), name="fecha"), name="tc")
    return s[~s.index.duplicated(keep="last")].sort_index()


def trm(desde: pd.Timestamp, hasta: pd.Timestamp) -> pd.Series:
    params = {"$where": f"vigenciadesde >= '{desde:%Y-%m-%d}T00:00:00'", "$order": "vigenciadesde ASC", "$limit": 50000}
    return parse_trm(comun.get(TRM_URL, params=params).json())


def fetch_all(offline: bool) -> tuple[dict, dict]:
    raw, status = {}, {}
    raw["tc"], status["tc"] = comun.actualizar(SERIES_DIR, "tc", trm, DESDE, offline=offline)
    raw["embig"], status["embig"] = comun.actualizar(SERIES_DIR, "embig", comun.embig_bcrp(EMBIG), "1998-01-01",
                                                     solapamiento_dias=120, offline=offline)
    return raw, status


def derived_series(raw: dict) -> pd.DataFrame:
    df = comun.panel_diario(raw, ["tc", "embig"])
    df["vol_tc"] = comun.vol(df["tc"])
    return df


def run(offline: bool = False) -> dict:
    raw, status = fetch_all(offline)
    if raw["tc"].empty:
        raise SystemExit("Colombia: no hay tipo de cambio disponible.")
    return comun.publicar(PAIS, IPD_BLOCKS, SERIES_META, EVENTS, raw, status, derived_series(raw), DATA_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run(offline=parser.parse_args().offline)


if __name__ == "__main__":
    main()
