"""Monitor de Dolarización - Perú.

Usa el mismo motor que Argentina (indicators.compute_ipd) con componentes
propios: en Perú no hay brecha ni canje, así que la presión se ve en el tipo de
cambio, en la intervención del BCRP y en la dolarización de la liquidez.

Uso:
    python -m monitor.peru            # descarga y recalcula
    python -m monitor.peru --offline  # recalcula con las series guardadas
"""

from __future__ import annotations

import argparse
import json
import logging
import time

import numpy as np
import pandas as pd
import requests

from . import build, config, indicators

log = logging.getLogger("monitor.peru")

PAIS = {"codigo": "pe", "nombre": "Perú", "publicar_desde": "2003-01-01"}
DATA_DIR = config.DATA_DIR / "pe"
SERIES_DIR = DATA_DIR / "series"
OUTPUT_JSON = DATA_DIR / "monitor.json"

BCRP_API = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/{codigo}/json/{desde}/{hasta}"
DESDE_DIARIO = "1995-01-01"
DESDE_MENSUAL = "1992-1"
# En cada corrida se vuelven a pedir los últimos días (el BCRP revisa datos).
SOLAPAMIENTO_DIAS = 120

# Series del BCRP (códigos verificados contra la API).
SERIES_DIARIAS = {
    "tc": "PD04638PD",                 # TC interbancario venta (S/ por US$)
    "rin": "PD04650MD",                # Reservas internacionales netas (M US$)
    "posicion_cambio": "PD04649MD",    # Posición de cambio del BCRP (M US$)
    "mesa_compras_netas": "PD04659MD", # Compras netas en la mesa de negociación (M US$)
    "contado_compras": "PD37515TD",    # Operaciones con bancos, al contado (desde 2014)
    "contado_ventas": "PD37516TD",
    "sc_venta_pactado": "PD37521TD",   # Swaps cambiarios venta (el BCRP da cobertura en dólares)
    "sc_venta_vencido": "PD37522TD",
    "sc_compra_pactado": "PD37523TD",
    "sc_compra_vencido": "PD37524TD",
    "tasa_interbancaria": "PD04692MD", # Interbancaria en soles (%)
    "embig": "PD04709XD",              # Spread EMBIG Perú (pb)
    "bono_10a": "PD31893DD",           # Rendimiento del bono soberano en soles a 10 años
}
SERIES_MENSUALES = {
    "dolarizacion_liquidez": "PN00025MM",  # Coeficiente de dolarización de la liquidez (%)
    "dolarizacion_credito": "PN00511MM",   # Coeficiente de dolarización del crédito (%)
}
# El dato mensual de dolarización se publica unas 4 semanas después del cierre.
DOLARIZACION_REZAGO_DIAS = 30
# Intervención: ventas netas de dólares del BCRP acumuladas en este número de
# días hábiles, en % de las reservas netas.
INTERVENCION_VENTANA = 20

IPD_BLOCKS = {
    "cambiaria": {
        "label": "Presión cambiaria",
        "weight": 0.5,
        "components": {
            "tc": {"transform": "dlog", "sign": +1, "weight": 1.0,
                   "label": "Depreciación del sol",
                   "frases": ("el sol se depreció más que lo habitual", "el sol se depreció menos que lo habitual")},
            "vol_tc": {"transform": "level", "sign": +1, "weight": 1.0,
                       "label": "Volatilidad del tipo de cambio",
                       "frases": ("la volatilidad del sol está por encima de lo habitual",
                                  "la volatilidad del sol está por debajo de lo habitual")},
            # Ventas spot y swaps cambiarios: presión que el BCRP absorbe y que
            # no se ve en el precio (equivalente a los futuros del BCRA).
            "intervencion": {"transform": "level", "sign": +1, "weight": 1.0,
                             "label": "Intervención vendedora del BCRP",
                             "frases": ("el BCRP vendió más dólares (spot y swaps) que lo habitual",
                                        "el BCRP vendió menos dólares (spot y swaps) que lo habitual")},
            # Posición de cambio: reservas propias del BCRP, sin los encajes en
            # dólares de los bancos (que mueven las reservas netas sin ser presión).
            "posicion_cambio": {"transform": "dlog", "sign": -1, "weight": 1.0,
                                "label": "Posición de cambio del BCRP",
                                "frases": ("la posición de cambio del BCRP cayó más que lo habitual",
                                           "la posición de cambio del BCRP evolucionó mejor que lo habitual")},
            "tasa_interbancaria": {"transform": "diff", "sign": +1, "weight": 1.0,
                                   "label": "Tasa interbancaria en soles",
                                   "frases": ("subió la tasa interbancaria en soles", "bajó la tasa interbancaria en soles")},
        },
    },
    "dolarizacion": {
        "label": "Dolarización y riesgo",
        "weight": 0.5,
        "components": {
            # La dolarización tiene una tendencia de largo plazo a la baja
            # (desdolarización): se mide su cambio en 3 meses, no el nivel.
            "dolarizacion_liquidez": {"transform": "diff", "horizonte": 63, "sign": +1, "weight": 1.0,
                                      "label": "Dolarización de la liquidez",
                                      "frases": ("aumentó la dolarización de la liquidez",
                                                 "bajó la dolarización de la liquidez")},
            "embig": {"transform": "diff", "sign": +1, "weight": 1.0,
                      "label": "Riesgo país (EMBIG)",
                      "frases": ("subió el riesgo país", "bajó el riesgo país")},
            "bono_10a": {"transform": "diff", "sign": +1, "weight": 1.0,
                         "label": "Tasa del bono soberano en soles a 10 años",
                         "frases": ("subió la tasa del bono en soles", "bajó la tasa del bono en soles")},
        },
    },
}

SERIES_META = {
    "ipd": ("Índice de Presión de Dolarización", "desvíos estándar", "IPD"),
    "tc": ("Tipo de cambio interbancario", "S/ por USD", "BCRP"),
    "embig": ("Riesgo país (EMBIG Perú)", "pb", "BCRP (JP Morgan)"),
    "rin": ("Reservas internacionales netas", "millones de USD", "BCRP"),
    "posicion_cambio": ("Posición de cambio del BCRP", "millones de USD", "BCRP"),
    "intervencion_usd": ("Intervención vendedora neta del BCRP (20 días)", "millones de USD", "BCRP / cálculo propio"),
    "tasa_interbancaria": ("Tasa interbancaria en soles", "%", "BCRP"),
    "bono_10a": ("Bono soberano en soles a 10 años", "%", "BCRP"),
    "vol_tc": ("Volatilidad del tipo de cambio (20 días)", "% anualizada", "Cálculo propio"),
    "dolarizacion_liquidez": ("Dolarización de la liquidez (fin de mes)", "%", "BCRP"),
    "dolarizacion_credito": ("Dolarización del crédito al sector privado (fin de mes)", "%", "BCRP"),
}

EVENTS = [
    {"date": "2006-04-09", "label": "Generales 2006", "tipo": "electoral"},
    {"date": "2008-09-15", "label": "Quiebra de Lehman", "tipo": "cambiario"},
    {"date": "2011-04-10", "label": "Generales 2011", "tipo": "electoral"},
    {"date": "2013-05-22", "label": "Taper tantrum", "tipo": "cambiario"},
    {"date": "2016-04-10", "label": "Generales 2016", "tipo": "electoral"},
    {"date": "2019-09-30", "label": "Disolución del Congreso", "tipo": "cambiario"},
    {"date": "2020-11-09", "label": "Vacancia de Vizcarra", "tipo": "cambiario"},
    {"date": "2021-04-11", "label": "Generales 2021", "tipo": "electoral"},
    {"date": "2021-06-06", "label": "Segunda vuelta 2021", "tipo": "electoral"},
    {"date": "2022-12-07", "label": "Destitución de Castillo", "tipo": "cambiario"},
    {"date": "2026-04-12", "label": "Generales 2026", "tipo": "electoral"},
]

_MESES = {"Ene": 1, "Feb": 2, "Mar": 3, "Abr": 4, "May": 5, "Jun": 6, "Jul": 7,
          "Ago": 8, "Set": 9, "Sep": 9, "Oct": 10, "Nov": 11, "Dic": 12}

_session = requests.Session()
_session.headers.update({"User-Agent": "monitor-dolarizacion/1.0 (+https://github.com/elibman36/monitor-dolarizacion)"})


# ---------------------------------------------------------------------------
# Fuente: API del BCRP
# ---------------------------------------------------------------------------

def parse_fecha_bcrp(txt: str) -> pd.Timestamp | None:
    """'02.Ene.97' (diaria) o 'Ene.1992' (mensual, fin de mes)."""
    partes = txt.strip().split(".")
    try:
        if len(partes) == 3:
            d, m, y = partes
            y = int(y)
            y += 2000 if y < 50 else (1900 if y < 100 else 0)
            return pd.Timestamp(y, _MESES[m], int(d))
        if len(partes) == 2:
            m, y = partes
            return pd.Timestamp(int(y), _MESES[m], 1) + pd.offsets.MonthEnd(0)
    except (KeyError, ValueError):
        return None
    return None


def parse_bcrp(payload: dict, name: str) -> pd.Series:
    fechas, valores = [], []
    for p in payload.get("periods", []):
        f = parse_fecha_bcrp(p.get("name", ""))
        v = (p.get("values") or [None])[0]
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue  # "n.d."
        if f is not None:
            fechas.append(f)
            valores.append(v)
    s = pd.Series(valores, index=pd.DatetimeIndex(fechas, name="fecha"), name=name, dtype=float)
    return s[~s.index.duplicated(keep="last")].sort_index()


def bcrp_series(codigo: str, desde: str, hasta: str, name: str, retries: int = 4) -> pd.Series:
    url = BCRP_API.format(codigo=codigo, desde=desde, hasta=hasta)
    last = None
    for intento in range(retries):
        try:
            r = _session.get(url, timeout=90)
            r.raise_for_status()
            # La API responde JSON con content-type text/html; a veces el
            # firewall devuelve una página de verificación: se reintenta.
            return parse_bcrp(json.loads(r.text), name)
        except (requests.RequestException, ValueError) as exc:
            last = exc
            time.sleep(3 * (intento + 1))
    raise RuntimeError(f"BCRP {codigo}: {last}")


def _cache(key: str) -> pd.Series:
    path = SERIES_DIR / f"{key}.csv"
    if not path.exists():
        return pd.Series(dtype=float, name=key, index=pd.DatetimeIndex([], name="fecha"))
    df = pd.read_csv(path, parse_dates=["fecha"])
    return df.set_index("fecha")["valor"].rename(key)


def _guardar(key: str, s: pd.Series) -> None:
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    s.rename("valor").rename_axis("fecha").to_frame().to_csv(
        SERIES_DIR / f"{key}.csv", date_format="%Y-%m-%d", float_format="%.6g")


def fetch_all(offline: bool) -> tuple[dict[str, pd.Series], dict[str, str]]:
    series, status = {}, {}
    hoy = pd.Timestamp.today().normalize()
    for key, codigo in {**SERIES_DIARIAS, **SERIES_MENSUALES}.items():
        cached = _cache(key)
        if offline:
            series[key], status[key] = cached, "offline"
            continue
        mensual = key in SERIES_MENSUALES
        if cached.empty:
            desde = DESDE_MENSUAL if mensual else DESDE_DIARIO
        else:
            d0 = cached.index.max() - pd.Timedelta(days=SOLAPAMIENTO_DIAS if not mensual else 400)
            desde = f"{d0.year}-{d0.month}" if mensual else d0.strftime("%Y-%m-%d")
        hasta = f"{hoy.year}-{hoy.month}" if mensual else hoy.strftime("%Y-%m-%d")
        try:
            fresh = bcrp_series(codigo, desde, hasta, key)
            if fresh.empty and cached.empty:
                raise RuntimeError("respuesta vacía")
            merged = fresh.combine_first(cached).sort_index()
            _guardar(key, merged)
            series[key], status[key] = merged, "ok"
        except Exception as exc:  # noqa: BLE001 - una serie caída no frena el resto
            log.warning("%s: fallo la descarga (%s); uso copia guardada (%d obs)", key, exc, len(cached))
            series[key], status[key] = cached, f"error: {exc}"
    return series, status


# ---------------------------------------------------------------------------
# Series derivadas
# ---------------------------------------------------------------------------

def mensual_a_diario(s: pd.Series, index: pd.DatetimeIndex, rezago_dias: int) -> pd.Series:
    """Dato de fin de mes llevado al calendario diario, a partir de que se publica."""
    s = s.dropna()
    if s.empty:
        return pd.Series(np.nan, index=index)
    s = s.copy()
    s.index = s.index + pd.Timedelta(days=rezago_dias)
    return s.reindex(index.union(s.index)).ffill(limit=80).reindex(index)


def intervencion_diaria(df: pd.DataFrame) -> pd.Series:
    """Ventas netas de dólares del BCRP por día (millones de USD; + = vende).

    Spot: compras netas en la mesa con signo invertido (toda la historia).
    Swaps cambiarios (desde 2014): los SC venta pactados dan cobertura en
    dólares (como vender futuros) y los vencidos la devuelven; los SC compra,
    al revés. Antes de 2014 no había swaps cambiarios: cuentan cero.
    """
    spot = -df.get("mesa_compras_netas", pd.Series(np.nan, index=df.index))
    sc = pd.Series(0.0, index=df.index)
    for col, signo in [("sc_venta_pactado", 1), ("sc_venta_vencido", -1),
                       ("sc_compra_pactado", -1), ("sc_compra_vencido", 1)]:
        if col in df:
            sc = sc + signo * df[col].fillna(0.0)
    return spot.fillna(0.0).where(spot.notna() | (sc != 0)) + sc


def derived_series(raw: dict[str, pd.Series]) -> pd.DataFrame:
    diarias = {k: v for k, v in raw.items() if k in SERIES_DIARIAS and v is not None and not v.empty}
    index = indicators.business_days(diarias)
    # Los flujos (intervención) no se rellenan: un día sin operaciones es cero.
    flujos = {"mesa_compras_netas", "contado_compras", "contado_ventas", "sc_venta_pactado",
              "sc_venta_vencido", "sc_compra_pactado", "sc_compra_vencido"}
    df = indicators.align({k: v for k, v in diarias.items() if k not in flujos}, index)
    for k in flujos & set(diarias):
        df[k] = diarias[k].reindex(index)
    df["vol_tc"] = indicators.realized_vol(df["tc"], config.IPD_VOL_VENTANA)
    inter = intervencion_diaria(df)
    df["intervencion_usd"] = inter.rolling(INTERVENCION_VENTANA, min_periods=10).sum()
    df["intervencion"] = df["intervencion_usd"] / df["rin"].shift(INTERVENCION_VENTANA) * 100
    for k in SERIES_MENSUALES:
        if k in raw:
            df[k] = mensual_a_diario(raw[k], index, DOLARIZACION_REZAGO_DIAS)
    return df


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------

def run(offline: bool = False) -> dict:
    raw, status = fetch_all(offline)
    if not any(v is not None and not v.empty for v in raw.values()):
        raise SystemExit("Perú: no hay ninguna serie disponible.")
    panel = derived_series(raw)
    ipd = indicators.compute_ipd(panel, IPD_BLOCKS, PAIS["publicar_desde"])
    # Las mensuales se publican con su fecha real (fin de mes).
    publicar = {k: v for k, v in raw.items() if k in SERIES_MENSUALES or k in {"tc", "embig", "rin", "posicion_cambio",
                                                                              "tasa_interbancaria", "bono_10a"}}
    payload = build.build_payload(panel, ipd, None, status, publicar,
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
    log.info("Perú: IPD %s = %s | índice 0-100 = %s (%s)", h["date"], h["ipd"], h["indice"], h["status_label"])
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run(offline=args.offline)


if __name__ == "__main__":
    main()
