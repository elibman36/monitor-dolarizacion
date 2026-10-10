"""Monitor de Dolarización - Uruguay.

Mismo motor que Argentina y Perú (indicators.compute_ipd). Uruguay es una
economía muy dolarizada (más del 60% de los depósitos privados están en
dólares) y sin restricciones cambiarias: la presión se ve en el tipo de cambio,
en la posición en moneda extranjera del BCU y en la dolarización de los
depósitos.

Fuentes (todas del BCU, automáticas):
- tipo de cambio interbancario: servicio web de cotizaciones (diario, desde 2000);
- reservas y posición en moneda extranjera del BCU: planilla diaria de activos
  de reserva (desde 2002);
- depósitos del sector privado por moneda: series de la Superintendencia de
  Servicios Financieros (mensual, desde 1998).

Todavía no hay fuentes automáticas para la tasa de política monetaria reciente
ni para el riesgo país (UBI), así que no forman parte del índice.

Uso:
    python -m monitor.uruguay            # descarga y recalcula
    python -m monitor.uruguay --offline  # recalcula con las series guardadas
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import time

import numpy as np
import pandas as pd
import requests
import urllib3

from . import build, config, indicators
from .peru import mensual_a_diario

log = logging.getLogger("monitor.uruguay")

PAIS = {"codigo": "uy", "nombre": "Uruguay", "publicar_desde": "2003-01-01"}
DATA_DIR = config.DATA_DIR / "uy"
SERIES_DIR = DATA_DIR / "series"
OUTPUT_JSON = DATA_DIR / "monitor.json"

COTIZACIONES_WS = "https://cotizaciones.bcu.gub.uy/wscotizaciones/servlet/awsbcucotizaciones"
MONEDA_DOLAR = 2225          # dólar billete interbancario
COTIZ_DESDE = 2000
RESERVAS_XLS = "https://www.bcu.gub.uy/Estadisticas-e-Indicadores/MonedayCredito/Activos-de-Reserva/reservas.xls"
DEPOSITOS_XLSX = "https://www.bcu.gub.uy/Servicios-Financieros-SSF/Series%20IF/Depositos.xlsx"
DEPOSITOS_HOJA = "Total Sist. Banc."
# El sitio del BCU tiene la cadena de certificados incompleta: sólo para el BCU
# se puede desactivar la verificación con BCU_SSL_VERIFY=0 (como con el BCRA).
DEPOSITOS_REZAGO_DIAS = 45   # el dato mensual se publica con unas 6 semanas de rezago

IPD_BLOCKS = {
    "cambiaria": {
        "label": "Presión cambiaria",
        "weight": 0.5,
        "components": {
            "tc": {"transform": "dlog", "sign": +1, "weight": 1.0,
                   "label": "Depreciación del peso",
                   "frases": ("el peso se depreció más que lo habitual", "el peso se depreció menos que lo habitual")},
            "vol_tc": {"transform": "level", "sign": +1, "weight": 1.0,
                       "label": "Volatilidad del tipo de cambio",
                       "frases": ("la volatilidad del peso está por encima de lo habitual",
                                  "la volatilidad del peso está por debajo de lo habitual")},
            # Posición en moneda extranjera: reservas del BCU netas de sus
            # obligaciones en dólares con el sector público y el financiero
            # (los encajes en dólares mueven las reservas sin ser presión).
            "posicion_me": {"transform": "dlog", "sign": -1, "weight": 1.0,
                            "label": "Posición en moneda extranjera del BCU",
                            "frases": ("la posición en moneda extranjera del BCU cayó más que lo habitual",
                                       "la posición en moneda extranjera del BCU evolucionó mejor que lo habitual")},
            "reservas": {"transform": "dlog", "sign": -1, "weight": 1.0,
                         "label": "Reservas internacionales",
                         "frases": ("las reservas cayeron más que lo habitual",
                                    "las reservas evolucionaron mejor que lo habitual")},
        },
    },
    "dolarizacion": {
        "label": "Dolarización",
        "weight": 0.5,
        "components": {
            # Cambio en 3 meses: la dolarización tiene tendencias largas.
            "dolarizacion_depositos": {"transform": "diff", "horizonte": 63, "sign": +1, "weight": 1.0,
                                       "label": "Dolarización de los depósitos privados",
                                       "frases": ("aumentó la dolarización de los depósitos",
                                                  "bajó la dolarización de los depósitos")},
            "depositos_me_usd": {"transform": "dlog", "horizonte": 63, "sign": +1, "weight": 1.0,
                                 "label": "Depósitos privados en dólares",
                                 "frases": ("crecieron los depósitos privados en dólares",
                                            "cayeron los depósitos privados en dólares")},
        },
    },
}

SERIES_META = {
    "ipd": ("Índice de Presión de Dolarización", "desvíos estándar", "IPD"),
    "tc": ("Tipo de cambio interbancario", "$U por USD", "BCU"),
    "reservas": ("Activos de reserva del BCU", "millones de USD", "BCU"),
    "posicion_me": ("Posición en moneda extranjera del BCU", "millones de USD", "BCU"),
    "vol_tc": ("Volatilidad del tipo de cambio (20 días)", "% anualizada", "Cálculo propio"),
    "dolarizacion_depositos": ("Dolarización de los depósitos privados (fin de mes)", "%", "BCU (SSF) / cálculo propio"),
    "depositos_me_usd": ("Depósitos privados en dólares (fin de mes)", "millones de USD", "BCU (SSF) / cálculo propio"),
}

SERIES_DIARIAS = ["tc", "reservas", "posicion_me"]
SERIES_MENSUALES = ["dolarizacion_depositos", "depositos_me_usd"]

EVENTS = [
    {"date": "2004-10-31", "label": "Elecciones 2004", "tipo": "electoral"},
    {"date": "2008-09-15", "label": "Quiebra de Lehman", "tipo": "cambiario"},
    {"date": "2009-10-25", "label": "Elecciones 2009", "tipo": "electoral"},
    {"date": "2013-05-22", "label": "Taper tantrum", "tipo": "cambiario"},
    {"date": "2014-10-26", "label": "Elecciones 2014", "tipo": "electoral"},
    {"date": "2018-05-03", "label": "Corrida en Argentina", "tipo": "cambiario"},
    {"date": "2019-10-27", "label": "Elecciones 2019", "tipo": "electoral"},
    {"date": "2020-03-13", "label": "Pandemia", "tipo": "cambiario"},
    {"date": "2024-10-27", "label": "Elecciones 2024", "tipo": "electoral"},
]

_session = requests.Session()
_session.headers.update({"User-Agent": "monitor-dolarizacion/1.0 (+https://github.com/elibman36/monitor-dolarizacion)"})


def _verify() -> bool:
    import os
    v = os.environ.get("BCU_SSL_VERIFY", "1") != "0"
    if not v:
        urllib3.disable_warnings()
    return v


def _get(url: str, **kw) -> requests.Response:
    last = None
    for intento in range(3):
        try:
            r = _session.get(url, timeout=120, verify=_verify(), **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            last = exc
            time.sleep(3 * (intento + 1))
    raise RuntimeError(f"BCU {url}: {last}")


# ---------------------------------------------------------------------------
# Fuentes del BCU
# ---------------------------------------------------------------------------

_SOAP = """<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:cot="Cotiza"><soapenv:Header/><soapenv:Body>
<cot:wsbcucotizaciones.Execute><cot:Entrada><cot:Moneda><cot:item>{moneda}</cot:item></cot:Moneda><cot:FechaDesde>{desde}</cot:FechaDesde><cot:FechaHasta>{hasta}</cot:FechaHasta><cot:Grupo>0</cot:Grupo></cot:Entrada></cot:wsbcucotizaciones.Execute></soapenv:Body></soapenv:Envelope>"""


def parse_cotizaciones(xml: str, name: str = "tc") -> pd.Series:
    fechas = re.findall(r"<Fecha>([\d-]+)</Fecha>", xml)
    valores = re.findall(r"<TCV>([\d.]+)</TCV>", xml)
    s = pd.Series(pd.to_numeric(valores, errors="coerce"), index=pd.DatetimeIndex(pd.to_datetime(fechas), name="fecha"),
                  name=name, dtype=float)
    return s[s > 0].sort_index()


def bcu_cotizaciones(desde: pd.Timestamp, hasta: pd.Timestamp) -> pd.Series:
    """Dólar interbancario. El servicio acepta hasta un año por consulta."""
    partes = []
    ini = desde
    while ini <= hasta:
        fin = min(ini + pd.DateOffset(years=1) - pd.Timedelta(days=1), hasta)
        body = _SOAP.format(moneda=MONEDA_DOLAR, desde=ini.strftime("%Y-%m-%d"), hasta=fin.strftime("%Y-%m-%d"))
        r = _session.post(COTIZACIONES_WS, data=body.encode(), timeout=120,
                          headers={"Content-Type": "text/xml; charset=utf-8"})
        r.raise_for_status()
        partes.append(parse_cotizaciones(r.text))
        ini = fin + pd.Timedelta(days=1)
    s = pd.concat(partes) if partes else pd.Series(dtype=float)
    return s[~s.index.duplicated(keep="last")].rename("tc")


def parse_reservas(df: pd.DataFrame) -> pd.DataFrame:
    """Planilla diaria de activos de reserva: fecha, activos de reserva y posición en ME."""
    fila = next(i for i in range(min(30, len(df))) if df.iloc[i].astype(str).str.strip().str.lower().eq("fecha").any())
    cols = df.iloc[fila].astype(str).str.lower()
    c_fecha = int(np.flatnonzero(cols.str.strip().eq("fecha"))[0])
    c_res = int(np.flatnonzero(cols.str.contains("activos de reserva") & ~cols.str.contains("sin contrapart"))[0])
    c_pos = int(np.flatnonzero(cols.str.contains("posici"))[0])
    d = df.iloc[fila + 1:, [c_fecha, c_res, c_pos]].copy()
    d.columns = ["fecha", "reservas", "posicion_me"]
    d["fecha"] = pd.to_datetime(d["fecha"], errors="coerce")
    d = d.dropna(subset=["fecha"])
    for c in ["reservas", "posicion_me"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d.set_index("fecha").sort_index()


def parse_depositos(df: pd.DataFrame) -> pd.DataFrame:
    """Hoja 'Total Sist. Banc.': sector privado en MN y ME (millones de pesos) y,
    con el tipo de cambio de fin de mes, los depósitos en dólares."""
    fila = next(i for i in range(min(30, len(df))) if str(df.iloc[i, 0]).strip().lower() == "mes")
    d = df.iloc[fila + 2:, [0, 1, 2, 3]].copy()
    d.columns = ["fecha", "mn", "me", "total"]
    d["fecha"] = pd.to_datetime(d["fecha"], errors="coerce")
    d = d.dropna(subset=["fecha"])
    for c in ["mn", "me", "total"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["total"])
    d["fecha"] = d["fecha"] + pd.offsets.MonthEnd(0)
    d["dolarizacion_depositos"] = d["me"] / d["total"] * 100
    return d.set_index("fecha").sort_index()


def _cache(key: str) -> pd.Series:
    path = SERIES_DIR / f"{key}.csv"
    if not path.exists():
        return pd.Series(dtype=float, name=key, index=pd.DatetimeIndex([], name="fecha"))
    return pd.read_csv(path, parse_dates=["fecha"]).set_index("fecha")["valor"].rename(key)


def _guardar(key: str, s: pd.Series) -> None:
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    s.dropna().rename("valor").rename_axis("fecha").to_frame().to_csv(
        SERIES_DIR / f"{key}.csv", date_format="%Y-%m-%d", float_format="%.6g")


def fetch_all(offline: bool) -> tuple[dict[str, pd.Series], dict[str, str]]:
    keys = SERIES_DIARIAS + SERIES_MENSUALES + ["depositos_me_pesos"]
    series = {k: _cache(k) for k in keys}
    status = {k: "offline" for k in keys}
    if offline:
        return series, status
    hoy = pd.Timestamp.today().normalize()
    # Tipo de cambio (incremental)
    try:
        tc = series["tc"]
        desde = pd.Timestamp(f"{COTIZ_DESDE}-01-01") if tc.empty else tc.index.max() - pd.Timedelta(days=60)
        fresh = bcu_cotizaciones(desde, hoy)
        series["tc"] = fresh.combine_first(tc).sort_index()
        _guardar("tc", series["tc"])
        status["tc"] = "ok"
    except Exception as exc:  # noqa: BLE001
        log.warning("BCU cotizaciones: %s", exc)
        status["tc"] = f"error: {exc}"
    # Reservas y posición (planilla completa)
    try:
        res = parse_reservas(pd.read_excel(io.BytesIO(_get(RESERVAS_XLS).content), header=None))
        for k in ["reservas", "posicion_me"]:
            series[k] = res[k].dropna().combine_first(series[k]).sort_index().rename(k)
            _guardar(k, series[k])
            status[k] = "ok"
    except Exception as exc:  # noqa: BLE001
        log.warning("BCU reservas: %s", exc)
        status["reservas"] = status["posicion_me"] = f"error: {exc}"
    # Depósitos por moneda
    try:
        hoja = pd.read_excel(io.BytesIO(_get(DEPOSITOS_XLSX).content), sheet_name=DEPOSITOS_HOJA, header=None)
        dep = parse_depositos(hoja)
        series["dolarizacion_depositos"] = dep["dolarizacion_depositos"].rename("dolarizacion_depositos")
        series["depositos_me_pesos"] = dep["me"].rename("depositos_me_pesos")
        for k in ["dolarizacion_depositos", "depositos_me_pesos"]:
            _guardar(k, series[k])
            status[k] = "ok"
    except Exception as exc:  # noqa: BLE001
        log.warning("BCU depósitos: %s", exc)
        status["dolarizacion_depositos"] = f"error: {exc}"
    # Depósitos en dólares: los pesos de la planilla al tipo de cambio de fin de mes.
    tc_m = series["tc"].resample("ME").last()
    me = series["depositos_me_pesos"]
    series["depositos_me_usd"] = (me / tc_m.reindex(me.index)).dropna().rename("depositos_me_usd")
    status["depositos_me_usd"] = status.get("depositos_me_pesos", "offline")
    series.pop("depositos_me_pesos")
    status.pop("depositos_me_pesos", None)
    return series, status


# ---------------------------------------------------------------------------
# Series derivadas y orquestación
# ---------------------------------------------------------------------------

def derived_series(raw: dict[str, pd.Series]) -> pd.DataFrame:
    diarias = {k: v for k, v in raw.items() if k in SERIES_DIARIAS and v is not None and not v.empty}
    index = indicators.business_days(diarias)
    df = indicators.align(diarias, index)
    df["vol_tc"] = indicators.realized_vol(df["tc"], config.IPD_VOL_VENTANA)
    for k in SERIES_MENSUALES:
        if k in raw and raw[k] is not None and not raw[k].empty:
            df[k] = mensual_a_diario(raw[k], index, DEPOSITOS_REZAGO_DIAS)
    return df


def run(offline: bool = False) -> dict:
    raw, status = fetch_all(offline)
    if raw.get("tc") is None or raw["tc"].empty:
        raise SystemExit("Uruguay: no hay tipo de cambio disponible.")
    panel = derived_series(raw)
    ipd = indicators.compute_ipd(panel, IPD_BLOCKS, PAIS["publicar_desde"])
    payload = build.build_payload(panel, ipd, None, status, raw,
                                  series_meta=SERIES_META, blocks_cfg=IPD_BLOCKS, events=EVENTS, pais=PAIS)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = panel.copy()
    out["ipd"] = ipd["ipd"]
    out["indice_0_100"] = ipd["indice"]
    out["ipd_n_componentes"] = ipd["n_componentes"]
    for b in ipd["blocks"].columns:
        out[f"ipd_bloque_{b}"] = ipd["blocks"][b]
    for c in ipd["components"].columns:
        out[f"z_{c}"] = ipd["components"][c]
    for c in ipd["aportes"].columns:
        out[f"pts_{c}"] = ipd["aportes"][c]
    out.to_csv(DATA_DIR / "panel_diario.csv", date_format="%Y-%m-%d", float_format="%.6g")
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    h = payload["headline"]
    log.info("Uruguay: IPD %s = %s | índice 0-100 = %s (%s)", h["date"], h["ipd"], h["indice"], h["status_label"])
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run(offline=args.offline)


if __name__ == "__main__":
    main()
