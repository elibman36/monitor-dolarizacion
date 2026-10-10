"""Monitor de Dolarización - Colombia.

Tipo de cambio flotante; el Banco de la República interviene en episodios
puntuales (compras directas, opciones, subastas de NDF y swaps). Fuentes
automáticas:

- tasa representativa del mercado (TRM, certificada por la Superintendencia
  Financiera): datos.gov.co, diaria desde 1991;
- tasa de política monetaria (diaria), reservas internacionales (mensual) y
  operaciones del Banco en el mercado cambiario (diarias): portal de
  estadísticas del Banco de la República (suameca);
- EMBIG Colombia, publicado por el BCRP.

El portal del Banco tiene la cadena de certificados incompleta: el workflow
usa SUAMECA_SSL_VERIFY=0 sólo para ese sitio.

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
SUAMECA = "https://suameca.banrep.gov.co/graficador-series/rest/graficadorService/consultaSerieParaGraficar?idSerie={id}"
SUAMECA_SERIES = {"tpm": 59, "reservas": 15050}
# Operaciones del Banco en el mercado cambiario (millones de USD). Signo con el
# que cada serie suma a las compras netas del Banco (+ compra, − vende): las
# subastas de NDF y FX swaps ya vienen con signo; las de opciones call y la
# desacumulación son ventas aunque se publiquen en positivo.
INTERVENCION = {16651: "+", 16650: "+", 16654: "+", 16652: "+", 16655: "-abs", 16653: "-abs", 16656: "stock", 16657: "+"}
# Los NDF del Banco eran de corto plazo y se renovaban en cada subasta: sumar
# las subastas contaría varias veces la misma cobertura. Se aproxima el stock
# vigente como lo subastado en esta ventana y se toma su variación.
NDF_PLAZO = "30D"
RESERVAS_REZAGO_DIAS = 10    # el dato mensual se publica a comienzos del mes siguiente
VENTANA_INTERVENCION = 20
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
            "reservas": {"transform": "dlog", "horizonte": 21, "sign": -1, "weight": 1.0, "label": "Reservas internacionales",
                         "frases": ("las reservas cayeron más que lo habitual", "las reservas evolucionaron mejor que lo habitual")},
            # Intervención esporádica: recorte más estricto del z-score.
            "intervencion": {"transform": "level", "sign": +1, "weight": 1.0, "clip": 2.0,
                             "label": "Ventas de dólares del Banco de la República",
                             "frases": ("el Banco de la República vendió dólares", "el Banco de la República compró dólares")},
        },
    },
    "riesgo": {
        "label": "Riesgo y tasas",
        "weight": 0.5,
        "components": {
            "embig": {"transform": "diff", "sign": +1, "weight": 1.0, "label": "Riesgo país (EMBIG)",
                      "frases": ("subió el riesgo país", "bajó el riesgo país")},
            "tpm": {"transform": "diff", "horizonte": 21, "sign": +1, "weight": 1.0, "label": "Tasa de política monetaria",
                    "frases": ("el Banco de la República subió su tasa", "el Banco de la República bajó su tasa")},
        },
    },
}

SERIES_META = {
    "ipd": ("Índice de Presión de Dolarización", "desvíos estándar", "IPD"),
    "tc": ("Tasa representativa del mercado (TRM)", "$ por USD", "Superintendencia Financiera (datos.gov.co)"),
    "embig": ("Riesgo país (EMBIG Colombia)", "pb", "BCRP (JP Morgan)"),
    "tpm": ("Tasa de política monetaria", "% efectivo anual", "Banco de la República"),
    "reservas": ("Reservas internacionales brutas (fin de mes)", "millones de USD", "Banco de la República"),
    "intervencion_usd": ("Ventas netas de dólares del Banco de la República (20 días)", "millones de USD", "Banco de la República / cálculo propio"),
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


def _verify() -> bool:
    import os
    v = os.environ.get("SUAMECA_SSL_VERIFY", "1") != "0"
    if not v:
        import urllib3
        urllib3.disable_warnings()
    return v


def parse_suameca(payload, name: str) -> pd.Series:
    x = payload[0] if isinstance(payload, list) and payload else payload
    datos = (x or {}).get("data") or []
    if not datos:
        return pd.Series(dtype=float, name=name, index=pd.DatetimeIndex([], name="fecha"))
    # Fechas en milisegundos UTC a las 05:00 (medianoche en Bogotá).
    fechas = pd.to_datetime([d[0] for d in datos], unit="ms", utc=True).tz_convert("America/Bogota").tz_localize(None).normalize()
    s = pd.Series([float(d[1]) for d in datos], index=pd.DatetimeIndex(fechas, name="fecha"), name=name)
    return s[~s.index.duplicated(keep="last")].sort_index()


def suameca(id_serie: int, name: str):
    def f(desde: pd.Timestamp, hasta: pd.Timestamp) -> pd.Series:
        return parse_suameca(comun.get(SUAMECA.format(id=id_serie), verify=_verify()).json(), name)
    return f


def intervencion(desde: pd.Timestamp, hasta: pd.Timestamp) -> pd.Series:
    """Compras netas diarias del Banco (millones de USD; − = vende)."""
    partes = []
    for i, signo in INTERVENCION.items():
        s = parse_suameca(comun.get(SUAMECA.format(id=i), verify=_verify()).json(), "intervencion")
        if signo == "-abs":
            s = -s.abs()
        elif signo == "stock":
            diaria = s.resample("D").sum()
            s = diaria.rolling(NDF_PLAZO).sum().diff().fillna(diaria)
            s = s[s != 0]
        partes.append(s)
    s = pd.concat(partes).groupby(level=0).sum()
    s.index.name = "fecha"
    return s.rename("compras_netas")


def fetch_all(offline: bool) -> tuple[dict, dict]:
    raw, status = {}, {}
    raw["tc"], status["tc"] = comun.actualizar(SERIES_DIR, "tc", trm, DESDE, offline=offline)
    for k, i in SUAMECA_SERIES.items():
        raw[k], status[k] = comun.actualizar(SERIES_DIR, k, suameca(i, k), DESDE, solapamiento_dias=100000, offline=offline)
    raw["compras_netas"], status["compras_netas"] = comun.actualizar(SERIES_DIR, "compras_netas", intervencion, DESDE,
                                                                     solapamiento_dias=100000, offline=offline)
    raw["embig"], status["embig"] = comun.actualizar(SERIES_DIR, "embig", comun.embig_bcrp(EMBIG), "1998-01-01",
                                                     solapamiento_dias=120, offline=offline)
    return raw, status


def derived_series(raw: dict) -> pd.DataFrame:
    df = comun.panel_diario(raw, ["tc", "embig", "tpm"], {"reservas": RESERVAS_REZAGO_DIAS})
    df["vol_tc"] = comun.vol(df["tc"])
    compras = raw.get("compras_netas")
    if compras is not None and not compras.empty and "reservas" in df:
        # Un día sin subastas es cero (las series de operaciones empiezan en 1999).
        ventas = -compras.reindex(df.index).fillna(0.0).where(df.index >= pd.Timestamp("1999-12-01"))
        df["intervencion_usd"] = ventas.rolling(VENTANA_INTERVENCION, min_periods=10).sum()
        df["intervencion"] = df["intervencion_usd"] / df["reservas"] * 100
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
