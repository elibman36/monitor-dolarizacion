"""Orquestador: descarga, calcula el IPD y publica data/monitor.json.

Uso:
    python -m monitor.build            # descarga todo y recalcula
    python -m monitor.build --offline  # recalcula con las series ya guardadas
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import datetime, timezone

import pandas as pd

from . import config, indicators, sources

log = logging.getLogger("monitor")


# ---------------------------------------------------------------------------
# Persistencia de series crudas
# ---------------------------------------------------------------------------

def _cache_path(key: str):
    return config.SERIES_DIR / f"{key}.csv"


def load_cached(key: str) -> pd.Series:
    path = _cache_path(key)
    if not path.exists():
        return pd.Series(dtype=float, name=key)
    df = pd.read_csv(path, parse_dates=["fecha"])
    s = df.set_index("fecha")["valor"].rename(key)
    return s


def save_series(key: str, s: pd.Series) -> None:
    config.SERIES_DIR.mkdir(parents=True, exist_ok=True)
    s = s.rename("valor").rename_axis("fecha")
    s.to_frame().to_csv(_cache_path(key), date_format="%Y-%m-%d", float_format="%.6g")


def refresh(key: str, fetch) -> tuple[pd.Series, str]:
    """Descarga una serie y la combina con la copia guardada.

    Los datos nuevos tienen prioridad (las fuentes revisan valores), pero si la
    descarga falla o viene vacía se conserva la historia previa.
    """
    cached = load_cached(key)
    try:
        fresh = fetch()
        if fresh is None or fresh.empty:
            raise RuntimeError("respuesta vacía")
        merged = fresh.combine_first(cached).sort_index()
        save_series(key, merged)
        return merged, "ok"
    except Exception as exc:  # noqa: BLE001 - una fuente caída no frena el resto
        log.warning("%s: fallo la descarga (%s); uso copia guardada (%d obs)", key, exc, len(cached))
        return cached, f"error: {exc}"


FUTURES_CACHE = "futuros_dolar"


def load_futures(offline: bool) -> pd.DataFrame:
    """Futuros de A3 (descarga incremental) + correcciones manuales."""
    path = config.SERIES_DIR / f"{FUTURES_CACHE}.csv"
    cached = pd.read_csv(path) if path.exists() else pd.DataFrame()
    fut = cached
    if not offline:
        # Se re-descargan los últimos 10 días por si A3 corrige ajustes.
        desde = config.FUTUROS_START_DATE
        if not cached.empty:
            desde = (pd.to_datetime(cached["fecha"]).max() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        try:
            fresh = sources.a3_futuros_dolar(desde)
            fut = pd.concat([cached, fresh]).drop_duplicates(["fecha", "contrato"], keep="last")
            fut = fut.sort_values(["fecha", "vencimiento"])
            config.SERIES_DIR.mkdir(parents=True, exist_ok=True)
            fut.to_csv(path, index=False)
            log.info("A3: %d filas de futuros (%d nuevas)", len(fut), len(fresh))
        except Exception as exc:  # noqa: BLE001
            log.warning("A3 no disponible (%s); uso copia guardada (%d filas)", exc, len(cached))
    manual = sources.manual_source("futuros_dolar")
    if not manual.empty:
        fut = pd.concat([fut, manual]).drop_duplicates(["fecha", "contrato"], keep="last")
    return fut


def fetch_all(offline: bool) -> tuple[dict[str, pd.Series], dict[str, str]]:
    series: dict[str, pd.Series] = {}
    status: dict[str, str] = {}

    keys = list(config.BCRA_VARIABLES) + list(config.ARGENTINADATOS_DOLARES) + ["riesgo_pais"]
    if offline:
        for key in keys:
            series[key] = load_cached(key)
            status[key] = "offline"
        return series, status

    # BCRA
    try:
        base, catalog = sources.bcra_catalog()
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        catalog.to_csv(config.DATA_DIR / "bcra_catalogo.csv", index=False)
        ids = sources.resolve_bcra_ids(catalog)
    except Exception as exc:  # noqa: BLE001
        log.warning("BCRA no disponible: %s", exc)
        base, ids = None, {}
    for key in config.BCRA_VARIABLES:
        if base and key in ids:
            series[key], status[key] = refresh(
                key, lambda k=key: sources.bcra_series(base, ids[k], k)
            )
        elif base:
            series[key], status[key] = load_cached(key), "n/d: variable no encontrada en el catálogo"
        else:
            series[key], status[key] = load_cached(key), "error: API del BCRA no disponible"

    # ArgentinaDatos
    for key, spec in config.ARGENTINADATOS_DOLARES.items():
        series[key], status[key] = refresh(
            key, lambda k=key, c=spec["casa"]: sources.argentinadatos_dolar(c, k)
        )
    series["riesgo_pais"], status["riesgo_pais"] = refresh(
        "riesgo_pais", sources.argentinadatos_riesgo_pais
    )
    return series, status


# ---------------------------------------------------------------------------
# Publicación
# ---------------------------------------------------------------------------

SERIES_META = {
    "ipd": ("Índice de Presión de Dolarización", "desvíos estándar", "IPD"),
    "tc_oficial_ref": ("Tipo de cambio oficial mayorista (A3500)", "$ por USD", "BCRA"),
    "usd_ccl": ("Dólar contado con liquidación", "$ por USD", "ArgentinaDatos"),
    "usd_mep": ("Dólar MEP", "$ por USD", "ArgentinaDatos"),
    "usd_blue": ("Dólar blue", "$ por USD", "ArgentinaDatos"),
    "brecha_ccl": ("Brecha CCL / oficial", "%", "Cálculo propio"),
    "brecha_mep": ("Brecha MEP / oficial", "%", "Cálculo propio"),
    "riesgo_pais": ("Riesgo país", "pb", "ArgentinaDatos (JP Morgan EMBI)"),
    "reservas": ("Reservas internacionales brutas", "millones de USD", "BCRA"),
    "tasa": ("Tasa de referencia (TAMAR / BADLAR privados)", "% n.a.", "BCRA"),
    "depositos_usd": ("Depósitos en dólares", "millones de USD", "BCRA"),
    "deval_implicita": ("Devaluación implícita en futuros a 90 días", "% TNA", "A3 Mercados"),
    "deval_implicita_mensual": ("Devaluación mensual implícita en futuros (90 días)", "% mensual", "A3 Mercados"),
    "futuros_interes_abierto": ("Interés abierto futuros de dólar", "contratos", "A3 Mercados"),
}


def _clean(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 4) if math.isfinite(f) else None


def _pairs(s: pd.Series) -> list[list]:
    s = s.dropna()
    return [[d.strftime("%Y-%m-%d"), _clean(v)] for d, v in s.items()]


def _last(s: pd.Series, lag_days: int = 0):
    s = s.dropna()
    if s.empty:
        return None, None
    if lag_days:
        target = s.index[-1] - pd.Timedelta(days=lag_days)
        s = s[s.index <= target]
        if s.empty:
            return None, None
    return s.index[-1].strftime("%Y-%m-%d"), _clean(s.iloc[-1])


def build_payload(panel: pd.DataFrame, ipd: dict, compras: pd.DataFrame,
                  licitaciones: pd.DataFrame, fetch_status: dict[str, str],
                  raw: dict[str, pd.Series] | None = None) -> dict:
    raw = raw or {}
    series_out = {}
    for key, (label, unit, source) in SERIES_META.items():
        # Las series descargadas se publican sin el relleno del panel, para que
        # la fecha del último dato sea la real.
        if key == "ipd":
            s = ipd["ipd"]
        elif key in raw:
            s = raw[key][raw[key].index >= panel.index.min()]
        else:
            s = panel.get(key)
        if s is None or s.dropna().empty:
            continue
        d_last, v_last = _last(s)
        _, v_week = _last(s, 7)
        _, v_month = _last(s, 30)
        series_out[key] = {
            "label": label, "unit": unit, "source": source,
            "last_date": d_last, "last": v_last, "prev_7d": v_week, "prev_30d": v_month,
            "data": _pairs(s),
        }

    components_meta = []
    for bkey, block in config.IPD_BLOCKS.items():
        for ckey, spec in block["components"].items():
            z = ipd["components"].get(ckey)
            d, v = _last(z) if z is not None else (None, None)
            components_meta.append({
                "key": ckey, "block": bkey, "label": spec["label"],
                "transform": spec["transform"], "weight": spec["weight"],
                "last_date": d, "z": v,
                "data": _pairs(z) if z is not None else [],
            })

    d_ipd, v_ipd = _last(ipd["ipd"])
    _, pct = _last(ipd["percentil"])
    st_key, st_label = indicators.status_for(pct)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "horizon": config.IPD_HORIZON,
            "zscore_window": config.IPD_ZSCORE_WINDOW,
            "percentile_window": config.IPD_PERCENTILE_WINDOW,
            "status_thresholds": [{"pct": p, "key": k, "label": l} for p, k, l in config.IPD_STATUS],
        },
        "headline": {
            "date": d_ipd, "ipd": v_ipd, "percentile": pct,
            "status": st_key, "status_label": st_label,
            "ipd_7d": _last(ipd["ipd"], 7)[1], "ipd_30d": _last(ipd["ipd"], 30)[1],
        },
        "ipd": {
            "data": _pairs(ipd["ipd"]),
            "percentile": _pairs(ipd["percentil"]),
            "blocks": {
                b: {"label": config.IPD_BLOCKS[b]["label"], "data": _pairs(ipd["blocks"][b])}
                for b in ipd["blocks"].columns
            },
            "components": components_meta,
        },
        "series": series_out,
        "monthly": {
            "compras_personas_humanas": [
                {k: (v.strftime("%Y-%m") if isinstance(v, pd.Timestamp) else
                     (_clean(v) if not isinstance(v, str) else v))
                 for k, v in row.items()}
                for row in compras.to_dict("records")
            ] if not compras.empty else [],
            "licitaciones": [
                {"fecha": r["fecha"].strftime("%Y-%m-%d"),
                 "total_millones_ars": _clean(r["total_millones_ars"]),
                 "cobertura_millones_ars": _clean(r["cobertura_millones_ars"]),
                 "share_cobertura": _clean(r["share_cobertura"])}
                for r in licitaciones.to_dict("records")
            ] if not licitaciones.empty else [],
        },
        "events": config.EVENTS,
        "sources_status": fetch_status,
    }


def run(offline: bool = False) -> dict:
    raw, status = fetch_all(offline)
    daily = {k: v for k, v in raw.items() if v is not None and not v.empty}
    if not daily:
        raise SystemExit("No hay ninguna serie disponible (ni descargada ni guardada).")
    index = indicators.business_days(daily)
    panel = indicators.align(daily, index)

    futuros = load_futures(offline)
    panel = indicators.derived_series(panel, futuros)
    ipd = indicators.compute_ipd(panel)

    compras = indicators.monthly_fx_purchases(sources.manual_source("compras_personas_humanas"))
    licitaciones = indicators.auction_dollar_share(sources.manual_source("licitaciones_tesoro"))

    payload = build_payload(panel, ipd, compras, licitaciones, status, daily)

    # Panel diario completo, útil para análisis en Excel / R / Stata.
    out_panel = panel.copy()
    out_panel["ipd"] = ipd["ipd"]
    out_panel["ipd_percentil"] = ipd["percentil"]
    for b in ipd["blocks"].columns:
        out_panel[f"ipd_bloque_{b}"] = ipd["blocks"][b]
    for c in ipd["components"].columns:
        out_panel[f"z_{c}"] = ipd["components"][c]
    out_panel.to_csv(config.DATA_DIR / "panel_diario.csv", date_format="%Y-%m-%d", float_format="%.6g")

    config.OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    h = payload["headline"]
    log.info("IPD %s = %s (percentil %s, %s)", h["date"], h["ipd"], h["percentile"], h["status_label"])
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="no descargar; usar series guardadas")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run(offline=args.offline)


if __name__ == "__main__":
    main()
