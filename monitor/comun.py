"""Piezas comunes a los módulos de países: caché de series, descarga
incremental y publicación del índice con el mismo formato que Argentina."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Callable

import pandas as pd
import requests

from . import build, config, indicators

log = logging.getLogger("monitor.comun")

session = requests.Session()
session.headers.update({"User-Agent": "monitor-dolarizacion/1.0 (+https://github.com/elibman36/monitor-dolarizacion)"})


def get(url: str, retries: int = 4, **kw) -> requests.Response:
    kw.setdefault("timeout", 90)
    last = None
    for intento in range(retries):
        try:
            r = session.get(url, **kw)
            if 400 <= r.status_code < 500 and r.status_code != 429:
                r.raise_for_status()
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 * (intento + 1))
    raise RuntimeError(f"{url}: {last}")


def cache(series_dir: Path, key: str) -> pd.Series:
    path = series_dir / f"{key}.csv"
    if not path.exists():
        return pd.Series(dtype=float, name=key, index=pd.DatetimeIndex([], name="fecha"))
    return pd.read_csv(path, parse_dates=["fecha"]).set_index("fecha")["valor"].rename(key)


def guardar(series_dir: Path, key: str, s: pd.Series) -> None:
    series_dir.mkdir(parents=True, exist_ok=True)
    s.dropna().rename("valor").rename_axis("fecha").to_frame().to_csv(
        series_dir / f"{key}.csv", date_format="%Y-%m-%d", float_format="%.6g")


def actualizar(series_dir: Path, key: str, fetch: Callable[[pd.Timestamp, pd.Timestamp], pd.Series],
               desde_inicial: str, solapamiento_dias: int = 60, offline: bool = False) -> tuple[pd.Series, str]:
    """Baja `key` desde el último dato guardado (menos un solapamiento, porque
    las fuentes revisan) o desde `desde_inicial` si no hay copia."""
    cached = cache(series_dir, key)
    if offline:
        return cached, "offline"
    hoy = pd.Timestamp.today().normalize()
    desde = pd.Timestamp(desde_inicial) if cached.empty else cached.index.max() - pd.Timedelta(days=solapamiento_dias)
    try:
        fresh = fetch(desde, hoy)
        if (fresh is None or fresh.dropna().empty) and cached.empty:
            raise RuntimeError("respuesta vacía")
        merged = fresh.dropna().combine_first(cached).sort_index().rename(key) if fresh is not None else cached
        merged = merged[~merged.index.duplicated(keep="last")]
        guardar(series_dir, key, merged)
        return merged, "ok"
    except Exception as exc:  # noqa: BLE001 - una serie caída no frena el resto
        log.warning("%s: fallo la descarga (%s); uso copia guardada (%d obs)", key, exc, len(cached))
        return cached, f"error: {exc}"


def panel_diario(raw: dict[str, pd.Series], diarias: list[str], mensuales: dict[str, int] | None = None) -> pd.DataFrame:
    """Panel en días hábiles; las mensuales entran `rezago` días después del fin de mes."""
    from .peru import mensual_a_diario
    d = {k: raw[k] for k in diarias if k in raw and raw[k] is not None and not raw[k].empty}
    index = indicators.business_days(d)
    df = indicators.align(d, index)
    for k, rezago in (mensuales or {}).items():
        if k in raw and raw[k] is not None and not raw[k].empty:
            df[k] = mensual_a_diario(raw[k], index, rezago)
    return df


def publicar(pais: dict, blocks: dict, meta: dict, events: list, raw: dict, status: dict,
             panel: pd.DataFrame, data_dir: Path) -> dict:
    ipd = indicators.compute_ipd(panel, blocks, pais["publicar_desde"])
    payload = build.build_payload(panel, ipd, None, status, raw,
                                  series_meta=meta, blocks_cfg=blocks, events=events, pais=pais)
    data_dir.mkdir(parents=True, exist_ok=True)
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
    out.to_csv(data_dir / "panel_diario.csv", date_format="%Y-%m-%d", float_format="%.6g")
    (data_dir / "monitor.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    h = payload["headline"]
    log.info("%s: IPD %s = %s | índice 0-100 = %s (%s)", pais["nombre"], h["date"], h["ipd"], h["indice"], h["status_label"])
    return payload


def embig_bcrp(codigo: str, name: str = "embig") -> Callable[[pd.Timestamp, pd.Timestamp], pd.Series]:
    """Spread EMBIG de un país, publicado por el BCRP."""
    from . import peru

    def f(desde: pd.Timestamp, hasta: pd.Timestamp) -> pd.Series:
        return peru.bcrp_series(codigo, desde.strftime("%Y-%m-%d"), hasta.strftime("%Y-%m-%d"), name)
    return f


def vol(s: pd.Series) -> pd.Series:
    return indicators.realized_vol(s, config.IPD_VOL_VENTANA)
