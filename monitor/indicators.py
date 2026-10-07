"""Series derivadas y cálculo del Índice de Presión de Dolarización (IPD)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import config


def business_days(series: dict[str, pd.Series]) -> pd.DatetimeIndex:
    """Calendario de días hábiles: días de semana con dato en alguna serie diaria."""
    dates = pd.DatetimeIndex([])
    for s in series.values():
        if s is not None and not s.empty:
            dates = dates.union(s.index)
    dates = dates[dates.dayofweek < 5]
    return dates.sort_values()


def align(series: dict[str, pd.Series], index: pd.DatetimeIndex, ffill_limit: int = 5) -> pd.DataFrame:
    df = pd.DataFrame(index=index)
    for key, s in series.items():
        if s is None or s.empty:
            continue
        # Se reindexa sobre la unión para que el ffill no salte fines de semana con dato.
        full = s.reindex(index.union(s.index)).ffill(limit=ffill_limit)
        df[key] = full.reindex(index)
    df.index.name = "fecha"
    return df


def official_rate(df: pd.DataFrame) -> pd.Series:
    """A3500 del BCRA; si falta, el mayorista de ArgentinaDatos."""
    a3500 = df["tc_a3500"] if "tc_a3500" in df else pd.Series(np.nan, index=df.index)
    if "usd_mayorista" in df:
        a3500 = a3500.fillna(df["usd_mayorista"])
    return a3500


def implied_devaluation(futuros: pd.DataFrame, spot: pd.Series) -> pd.DataFrame:
    """Devaluación implícita en futuros a plazo constante.

    Para cada fecha se toma la tasa nominal anual (TNA) implícita de cada
    contrato -la que publica A3 (`tasa_implicita_a3`) o, si falta,
    (F / S - 1) * 365 / días contra el A3500- y se interpola linealmente en
    días al plazo FUTUROS_PLAZO_CONSTANTE_DIAS. Usar TNA y no tasa efectiva
    evita que contratos muy cortos exploten al anualizar.
    También suma el interés abierto de todos los contratos.
    """
    cols = ["deval_implicita", "deval_implicita_mensual", "futuros_interes_abierto"]
    if futuros.empty:
        return pd.DataFrame(columns=cols)
    f = futuros.copy()
    f["fecha"] = pd.to_datetime(f["fecha"])
    f["vencimiento"] = pd.to_datetime(f["vencimiento"])
    f["precio_ajuste"] = pd.to_numeric(f["precio_ajuste"], errors="coerce")
    f["dias"] = (f["vencimiento"] - f["fecha"]).dt.days
    s = spot.reindex(f["fecha"]).to_numpy()
    tna_propia = (f["precio_ajuste"].to_numpy() / s - 1) * 365 / f["dias"].to_numpy() * 100
    tna_a3 = pd.to_numeric(f["tasa_implicita_a3"], errors="coerce") if "tasa_implicita_a3" in f \
        else pd.Series(np.nan, index=f.index)
    f["tna"] = tna_a3.fillna(pd.Series(tna_propia, index=f.index))
    if "interes_abierto" not in f:
        f["interes_abierto"] = np.nan
    f["interes_abierto"] = pd.to_numeric(f["interes_abierto"], errors="coerce")

    target = config.FUTUROS_PLAZO_CONSTANTE_DIAS
    minimo = config.FUTUROS_PLAZO_MINIMO_DIAS
    rows = []
    for fecha, g in f.groupby("fecha"):
        oi = g["interes_abierto"].sum(min_count=1)
        g = g[(g["dias"] >= minimo) & g["tna"].notna()].sort_values("dias")
        if g.empty:
            rows.append((fecha, np.nan, np.nan, oi))
            continue
        tna = float(np.interp(target, g["dias"], g["tna"]))  # extremos: valor del contrato más cercano
        rows.append((fecha, tna, tna * 30 / 365, oi))
    return pd.DataFrame(rows, columns=["fecha", *cols]).set_index("fecha").sort_index()


def derived_series(df: pd.DataFrame, futuros: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    oficial = official_rate(df)
    out["tc_oficial_ref"] = oficial
    if "usd_ccl" in df:
        out["brecha_ccl"] = (df["usd_ccl"] / oficial - 1) * 100
        # Antes de que haya CCL (2011-2012) se usa la brecha con el blue.
        if "usd_blue" in df:
            primer_ccl = df["usd_ccl"].first_valid_index()
            blue = (df["usd_blue"] / oficial - 1) * 100
            if primer_ccl is not None:
                out.loc[out.index < primer_ccl, "brecha_ccl"] = blue[out.index < primer_ccl]
    out["vol_oficial"] = realized_vol(oficial, config.IPD_VOL_VENTANA)
    if "usd_ccl" in df:
        out["vol_ccl"] = realized_vol(df["usd_ccl"], config.IPD_VOL_VENTANA)
    if "usd_mep" in df:
        out["brecha_mep"] = (df["usd_mep"] / oficial - 1) * 100
    if "usd_blue" in df:
        out["brecha_blue"] = (df["usd_blue"] / oficial - 1) * 100
    # Tasa de referencia: BADLAR (serie larga y homogénea desde 1999); TAMAR
    # sólo cubre huecos, para no introducir un salto de nivel en oct-24.
    tasa = pd.Series(np.nan, index=df.index)
    if "badlar" in df:
        tasa = df["badlar"]
    if "tamar" in df:
        tasa = tasa.fillna(df["tamar"])
    out["tasa"] = tasa
    dev = implied_devaluation(futuros, oficial)
    if not dev.empty:
        dev = dev.reindex(out.index.union(dev.index)).ffill(limit=3).reindex(out.index)
        for c in dev.columns:
            out[c] = dev[c]
    return out


# ---------------------------------------------------------------------------
# IPD
# ---------------------------------------------------------------------------

def transform(s: pd.Series, kind: str, horizon: int) -> pd.Series:
    if kind == "dlog":
        return np.log(s).diff(horizon) * 100
    if kind == "diff":
        return s.diff(horizon)
    if kind == "level":
        return s
    raise ValueError(f"transform desconocida: {kind}")


def rolling_z(x: pd.Series, window: int, min_obs: int, clip: float) -> pd.Series:
    if config.IPD_ZSCORE_METODO == "robusto":
        med = x.rolling(window, min_periods=min_obs).median()
        mad = (x - med).abs().rolling(window, min_periods=min_obs).median() * 1.4826
        z = (x - med) / mad.replace(0, np.nan)
    else:
        roll = x.rolling(window, min_periods=min_obs)
        z = (x - roll.mean()) / roll.std()
    return z.clip(-clip, clip)


def realized_vol(s: pd.Series, window: int) -> pd.Series:
    """Volatilidad anualizada (%) de las variaciones diarias en `window` días hábiles."""
    r = np.log(s).diff()
    return r.rolling(window, min_periods=max(5, int(window * 0.75))).std() * math.sqrt(252) * 100


def _weighted_mean(frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Promedio ponderado renormalizando por los componentes disponibles."""
    if frame.empty:
        return pd.Series(dtype=float)
    w = pd.Series(weights).reindex(frame.columns).fillna(0.0)
    avail = frame.notna().mul(w, axis=1)
    total = w.sum()
    num = frame.fillna(0.0).mul(w, axis=1).sum(axis=1)
    den = avail.sum(axis=1)
    out = num / den.replace(0, np.nan)
    out[den < config.IPD_MIN_WEIGHT_SHARE * total] = np.nan
    return out


def rolling_percentile(x: pd.Series, window: int, min_obs: int) -> pd.Series:
    def pct(a: np.ndarray) -> float:
        last = a[-1]
        valid = a[~np.isnan(a)]
        return float((valid <= last).mean() * 100) if valid.size else np.nan

    return x.rolling(window, min_periods=min_obs).apply(pct, raw=True)


def compute_ipd(df: pd.DataFrame) -> dict[str, pd.DataFrame | pd.Series]:
    h = config.IPD_HORIZON
    components: dict[str, pd.Series] = {}
    block_series: dict[str, pd.Series] = {}
    for bkey, block in config.IPD_BLOCKS.items():
        zs = {}
        for ckey, spec in block["components"].items():
            if ckey not in df or df[ckey].dropna().empty:
                continue
            x = transform(df[ckey], spec["transform"], h) * spec["sign"]
            z = rolling_z(x, config.IPD_ZSCORE_WINDOW, config.IPD_ZSCORE_MIN_OBS, config.IPD_Z_CLIP)
            if z.dropna().empty:
                continue
            zs[ckey] = z
            components[ckey] = z
        if zs:
            weights = {k: block["components"][k]["weight"] for k in zs}
            block_series[bkey] = _weighted_mean(pd.DataFrame(zs), weights)
    blocks = pd.DataFrame(block_series, index=df.index)
    ipd = _weighted_mean(blocks, {k: config.IPD_BLOCKS[k]["weight"] for k in blocks.columns})
    ipd = ipd.reindex(df.index)
    # Antes de IPD_PUBLICAR_DESDE los datos sólo sirven de ventana de referencia.
    publicar = df.index >= pd.Timestamp(config.IPD_PUBLICAR_DESDE)
    ipd = ipd.where(publicar)
    blocks.loc[~publicar] = np.nan
    components = {k: v.where(publicar) for k, v in components.items()}
    pct = rolling_percentile(ipd, config.IPD_PERCENTILE_WINDOW, config.IPD_ZSCORE_MIN_OBS)
    comps = pd.DataFrame(components, index=df.index)
    n_comp = comps.notna().sum(axis=1).where(ipd.notna())
    indice, sigma = pressure_index(ipd)
    return {
        "ipd": ipd,
        "indice": indice,
        "indice_sigma": sigma,
        "percentil": pct,
        "n_componentes": n_comp,
        "blocks": blocks,
        "components": comps,
    }


def pressure_index(ipd: pd.Series) -> tuple[pd.Series, float]:
    """Lleva el IPD a una escala 0-100 con 50 = neutral (ver config)."""
    smooth = ipd.rolling(config.INDICE_SUAVIZADO, min_periods=config.INDICE_SUAVIZADO).mean()
    sigma = config.INDICE_SIGMA or float(smooth.std())
    if not np.isfinite(sigma) or sigma <= 0:
        return pd.Series(np.nan, index=ipd.index), np.nan
    z = (smooth / sigma).to_numpy()
    phi = 0.5 * (1 + np.vectorize(math.erf, otypes=[float])(z / math.sqrt(2)))
    return pd.Series(phi * 100, index=ipd.index).where(smooth.notna()), sigma


def status_for(indice: float) -> tuple[str, str]:
    if indice is None or not np.isfinite(indice):
        return "unknown", "Sin datos suficientes"
    for lo, hi, key, label in config.INDICE_TRAMOS:
        if lo <= indice < hi:
            return key, label
    return "unknown", "Sin datos suficientes"


# ---------------------------------------------------------------------------
# Series mensuales / por evento
# ---------------------------------------------------------------------------

def monthly_fx_purchases(df: pd.DataFrame) -> pd.DataFrame:
    """Compras netas de USD de personas humanas (FAE), millones de USD."""
    if df.empty:
        return df
    out = df.copy()
    out["fecha"] = pd.to_datetime(out["fecha"].astype(str).str[:7] + "-01")
    for c in ("compras_usd_millones", "ventas_usd_millones", "personas_compradoras_miles"):
        if c in out:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    if {"compras_usd_millones", "ventas_usd_millones"} <= set(out.columns):
        out["netas_usd_millones"] = out["compras_usd_millones"] - out["ventas_usd_millones"].fillna(0)
    return out.sort_values("fecha")
