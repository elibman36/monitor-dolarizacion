"""Monitor de Dolarización - Brasil.

Brasil no tiene depósitos en dólares ni brecha: la presión se ve en el real,
en las reservas y, sobre todo, en la intervención del Banco Central do Brasil
(BCB), que da cobertura cambiaria con swaps (liquidados en reales, como los
futuros del BCRA) y presta dólares con líneas con recompra.

Fuentes (automáticas): SGS del BCB (PTAX, reservas, stock de swaps cambiales,
líneas con recompra, meta Selic) y EMBIG Brasil publicado por el BCRP.

Uso: python -m monitor.brasil [--offline]
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from . import comun, config

log = logging.getLogger("monitor.brasil")

PAIS = {"codigo": "br", "nombre": "Brasil", "publicar_desde": "2003-01-01"}
DATA_DIR = config.DATA_DIR / "br"
SERIES_DIR = DATA_DIR / "series"

SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json&dataInicial={d}&dataFinal={h}"
SGS = {
    "tc": 1,               # PTAX venta (R$ por US$)
    "reservas": 13621,     # reservas internacionales, concepto caja (US$ millones)
    "swaps": 29723,        # stock nocional de swaps cambiales (US$ millones)
    "linhas": 29722,       # stock de líneas con recompra (US$ millones)
    "selic": 432,          # meta Selic (% a.a.)
}
DESDE = "2000-01-01"
# Histórico de todas las operaciones del BCB en el mercado de cambios (desde 1999).
ATUACOES_CSV = "https://www.bcb.gov.br/conteudo/dadosabertos/BCBDepin/historico-atuacoes-mercado-cambio.csv"
# Ventas netas spot acumuladas en este número de días hábiles, en % de las reservas.
VENTANA_SPOT = 20
EMBIG = "PD04711XD"

IPD_BLOCKS = {
    "cambiaria": {
        "label": "Presión cambiaria",
        "weight": 0.5,
        "components": {
            "tc": {"transform": "dlog", "sign": +1, "weight": 1.0, "label": "Depreciación del real",
                   "frases": ("el real se depreció más que lo habitual", "el real se depreció menos que lo habitual")},
            "vol_tc": {"transform": "level", "sign": +1, "weight": 1.0, "label": "Volatilidad del tipo de cambio",
                       "frases": ("la volatilidad del real está por encima de lo habitual",
                                  "la volatilidad del real está por debajo de lo habitual")},
            "reservas": {"transform": "dlog", "sign": -1, "weight": 1.0, "label": "Reservas internacionales",
                         "frases": ("las reservas cayeron más que lo habitual", "las reservas evolucionaron mejor que lo habitual")},
            # Ampliar el stock de swaps es vender cobertura cambiaria (como los
            # futuros del BCRA): presión absorbida que no se ve en el precio.
            "ventas_spot": {"transform": "level", "sign": +1, "weight": 1.0,
                            "label": "Ventas de dólares del BCB (spot)",
                            "frases": ("el BCB vendió más dólares en el mercado spot que lo habitual",
                                       "el BCB vendió menos dólares en el mercado spot que lo habitual")},
            "swaps": {"transform": "diff", "horizonte": 21, "sign": +1, "weight": 1.0,
                      "label": "Swaps cambiales vendidos por el BCB",
                      "frases": ("el BCB amplió su stock de swaps cambiales", "el BCB redujo su stock de swaps cambiales")},
            "linhas": {"transform": "diff", "horizonte": 21, "sign": +1, "weight": 1.0,
                       "label": "Líneas con recompra del BCB",
                       "frases": ("el BCB prestó más dólares con líneas con recompra",
                                  "el BCB redujo sus líneas con recompra")},
        },
    },
    "riesgo": {
        "label": "Riesgo y tasas",
        "weight": 0.5,
        "components": {
            "embig": {"transform": "diff", "sign": +1, "weight": 1.0, "label": "Riesgo país (EMBIG)",
                      "frases": ("subió el riesgo país", "bajó el riesgo país")},
            "selic": {"transform": "diff", "horizonte": 21, "sign": +1, "weight": 1.0, "label": "Meta Selic",
                      "frases": ("el BCB subió la Selic", "el BCB bajó la Selic")},
        },
    },
}

SERIES_META = {
    "ipd": ("Índice de Presión de Dolarización", "desvíos estándar", "IPD"),
    "tc": ("Tipo de cambio PTAX", "R$ por USD", "BCB"),
    "reservas": ("Reservas internacionales (concepto caja)", "millones de USD", "BCB"),
    "swaps": ("Stock de swaps cambiales del BCB", "millones de USD", "BCB"),
    "linhas": ("Líneas con recompra del BCB", "millones de USD", "BCB"),
    "selic": ("Meta Selic", "% anual", "BCB"),
    "ventas_spot_usd": ("Ventas netas spot del BCB (20 días)", "millones de USD", "BCB, histórico de actuaciones"),
    "embig": ("Riesgo país (EMBIG Brasil)", "pb", "BCRP (JP Morgan)"),
    "vol_tc": ("Volatilidad del tipo de cambio (20 días)", "% anualizada", "Cálculo propio"),
}

EVENTS = [
    {"date": "2002-10-06", "label": "Elecciones 2002", "tipo": "electoral"},
    {"date": "2006-10-01", "label": "Elecciones 2006", "tipo": "electoral"},
    {"date": "2008-09-15", "label": "Quiebra de Lehman", "tipo": "cambiario"},
    {"date": "2010-10-03", "label": "Elecciones 2010", "tipo": "electoral"},
    {"date": "2013-05-22", "label": "Taper tantrum", "tipo": "cambiario"},
    {"date": "2014-10-05", "label": "Elecciones 2014", "tipo": "electoral"},
    {"date": "2015-09-09", "label": "Pérdida del grado de inversión", "tipo": "cambiario"},
    {"date": "2016-08-31", "label": "Destitución de Rousseff", "tipo": "cambiario"},
    {"date": "2018-10-07", "label": "Elecciones 2018", "tipo": "electoral"},
    {"date": "2020-03-11", "label": "Pandemia", "tipo": "cambiario"},
    {"date": "2022-10-02", "label": "Elecciones 2022", "tipo": "electoral"},
    {"date": "2024-12-18", "label": "Turbulencia fiscal", "tipo": "cambiario"},
    {"date": "2026-10-04", "label": "Elecciones 2026", "tipo": "electoral"},
]


def parse_sgs(registros: list[dict], name: str) -> pd.Series:
    if not registros:
        return pd.Series(dtype=float, name=name, index=pd.DatetimeIndex([], name="fecha"))
    df = pd.DataFrame(registros)
    s = pd.Series(pd.to_numeric(df["valor"], errors="coerce").values,
                  index=pd.DatetimeIndex(pd.to_datetime(df["data"], format="%d/%m/%Y"), name="fecha"), name=name)
    return s[~s.index.duplicated(keep="last")].sort_index()


def sgs(codigo: int, name: str):
    """El SGS limita las series diarias a 10 años por consulta: se pide por tramos."""
    def f(desde: pd.Timestamp, hasta: pd.Timestamp) -> pd.Series:
        partes, ini = [], desde
        while ini <= hasta:
            fin = min(ini + pd.DateOffset(years=9), hasta)
            r = comun.get(SGS_URL.format(codigo=codigo, d=ini.strftime("%d/%m/%Y"), h=fin.strftime("%d/%m/%Y")))
            partes.append(parse_sgs(r.json(), name))
            ini = fin + pd.Timedelta(days=1)
        s = pd.concat(partes)
        return s[~s.index.duplicated(keep="last")]
    return f


def parse_atuacoes(texto: str) -> pd.Series:
    """Ventas netas spot del BCB por día (millones de USD; + = vende): ventas
    a la vista menos compras a la vista, por volumen aceptado."""
    import io
    df = pd.read_csv(io.StringIO(texto), dtype=str)
    df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]
    col_inst = next(c for c in df.columns if c.lower().startswith("instrumento"))
    col_fecha = next(c for c in df.columns if c.strip().lower() == "data")
    col_vol = next(c for c in df.columns if "aceito" in c.lower())
    vol = pd.to_numeric(df[col_vol].str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
                        errors="coerce") / 1e6
    inst = df[col_inst].str.lower().fillna("")
    signo = inst.map(lambda x: 1.0 if x.startswith("venda a vista") else (-1.0 if x.startswith("compra a vista") else 0.0))
    fechas = pd.to_datetime(df[col_fecha], errors="coerce").dt.normalize()
    s = (vol * signo).groupby(fechas).sum()
    s.index = pd.DatetimeIndex(s.index, name="fecha")
    return s.rename("ventas_spot").sort_index()


def atuacoes(desde: pd.Timestamp, hasta: pd.Timestamp) -> pd.Series:
    r = comun.get(ATUACOES_CSV)
    return parse_atuacoes(r.content.decode("utf-8-sig", errors="replace"))


def fetch_all(offline: bool) -> tuple[dict, dict]:
    raw, status = {}, {}
    for key, codigo in SGS.items():
        raw[key], status[key] = comun.actualizar(SERIES_DIR, key, sgs(codigo, key), DESDE, offline=offline)
    raw["embig"], status["embig"] = comun.actualizar(SERIES_DIR, "embig", comun.embig_bcrp(EMBIG), "1998-01-01",
                                                     solapamiento_dias=120, offline=offline)
    # El CSV trae toda la historia: se reemplaza entero.
    raw["ventas_spot"], status["ventas_spot"] = comun.actualizar(SERIES_DIR, "ventas_spot", atuacoes, "1999-01-01",
                                                                 solapamiento_dias=100000, offline=offline)
    return raw, status


def derived_series(raw: dict) -> pd.DataFrame:
    df = comun.panel_diario(raw, ["tc", "reservas", "swaps", "linhas", "selic", "embig"])
    # Antes de 2002 no había swaps ni líneas: cuentan cero.
    for k in ["swaps", "linhas"]:
        if k in df:
            df[k] = df[k].fillna(0.0).where(df.index >= pd.Timestamp(DESDE))
    df["vol_tc"] = comun.vol(df["tc"])
    # Ventas spot: un día sin operaciones es cero.
    spot = raw.get("ventas_spot")
    if spot is not None and not spot.empty:
        diaria = spot.reindex(df.index).fillna(0.0).where(df.index >= spot.index.min())
        df["ventas_spot_usd"] = diaria.rolling(VENTANA_SPOT, min_periods=10).sum()
        df["ventas_spot"] = df["ventas_spot_usd"] / df["reservas"].shift(VENTANA_SPOT) * 100
    return df


def run(offline: bool = False) -> dict:
    raw, status = fetch_all(offline)
    if raw["tc"].empty:
        raise SystemExit("Brasil: no hay tipo de cambio disponible.")
    return comun.publicar(PAIS, IPD_BLOCKS, SERIES_META, EVENTS, raw, status, derived_series(raw), DATA_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run(offline=parser.parse_args().offline)


if __name__ == "__main__":
    main()
