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


def fae_daily(compras: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """Compras netas mensuales de personas humanas llevadas al calendario diario.

    El dato de cada mes entra FAE_REZAGO_DIAS después de su cierre (cuando el
    BCRA ya lo publicó) y se mantiene hasta el siguiente, para no usar
    información que en esa fecha todavía no existía.
    """
    if compras is None or compras.empty or "netas_usd_millones" not in compras:
        return pd.Series(np.nan, index=index)
    fechas = pd.to_datetime(compras["fecha"].astype(str).str[:7] + "-01") + pd.offsets.MonthEnd(0) \
        + pd.Timedelta(days=config.FAE_REZAGO_DIAS)
    s = pd.Series(pd.to_numeric(compras["netas_usd_millones"], errors="coerce").values, index=fechas)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.reindex(index.union(s.index)).ffill(limit=80).reindex(index)


def posicion_bcra_mensual(posicion: pd.DataFrame | None) -> pd.Series:
    """Posición vendida neta del BCRA en futuros (millones de USD) a fin de mes."""
    if posicion is None or posicion.empty or "vendida_neta_usd_millones" not in posicion:
        return pd.Series(dtype=float, name="posicion_bcra", index=pd.DatetimeIndex([], name="fecha"))
    fechas = pd.to_datetime(posicion["fecha"].astype(str).str[:7] + "-01") + pd.offsets.MonthEnd(0)
    s = pd.Series(pd.to_numeric(posicion["vendida_neta_usd_millones"], errors="coerce").values,
                  index=fechas, name="posicion_bcra")
    s.index.name = "fecha"
    return s[~s.index.duplicated(keep="last")].sort_index()


def posicion_bcra_daily(posicion: pd.DataFrame | None, index: pd.DatetimeIndex) -> pd.Series:
    """La posición de cada fin de mes entra POSICION_BCRA_REZAGO_DIAS después,
    cuando el BCRA publica la planilla, y se mantiene hasta la siguiente."""
    s = posicion_bcra_mensual(posicion)
    if s.empty:
        return pd.Series(np.nan, index=index)
    s.index = s.index + pd.Timedelta(days=config.POSICION_BCRA_REZAGO_DIAS)
    return s.reindex(index.union(s.index)).ffill(limit=80).reindex(index)


def derived_series(df: pd.DataFrame, futuros: pd.DataFrame, compras: pd.DataFrame | None = None,
                   posicion_bcra: pd.DataFrame | None = None) -> pd.DataFrame:
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
        # Antes de que haya MEP (2018) se usa la brecha CCL (o blue): con
        # canje casi nulo, son equivalentes.
        if "brecha_ccl" in out:
            primer_mep = df["usd_mep"].first_valid_index()
            if primer_mep is not None:
                antes = out.index < primer_mep
                out.loc[antes, "brecha_mep"] = out.loc[antes, "brecha_ccl"]
        if "usd_ccl" in df:
            # Canje: cuánto más vale el dólar afuera (CCL) que adentro (MEP).
            out["canje"] = (df["usd_ccl"] / df["usd_mep"] - 1) * 100
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
        if "futuros_interes_abierto" in out:
            out["futuros_oi"] = out["futuros_interes_abierto"].rolling(
                config.FUTUROS_OI_SUAVIZADO, min_periods=10).mean()
    out["compras_ph"] = fae_daily(compras, out.index)
    out["posicion_bcra"] = posicion_bcra_daily(posicion_bcra, out.index)
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
    if kind == "desvio_12m":
        # Distancia al promedio de los últimos 12 meses: útil cuando un cambio
        # de régimen (p. ej. la salida del cepo) mueve el nivel de la serie.
        return s - s.rolling(252, min_periods=120).mean()
    raise ValueError(f"transform desconocida: {kind}")


def rolling_z(x: pd.Series, window: int, min_obs: int, clip: float) -> pd.Series:
    if config.IPD_ZSCORE_METODO == "robusto":
        med = x.rolling(window, min_periods=min_obs).median()
        mad = (x - med).abs().rolling(window, min_periods=min_obs).median() * 1.4826
        # Si más de la mitad de la ventana es un mismo valor (p. ej. el BCRA sin
        # futuros en 2024), el MAD es 0: se usa el desvío estándar.
        std = x.rolling(window, min_periods=min_obs).std()
        z = (x - med) / mad.where(mad > 0, std).replace(0, np.nan)
    else:
        roll = x.rolling(window, min_periods=min_obs)
        z = (x - roll.mean()) / roll.std()
    return z.clip(-clip, clip)


def realized_vol(s: pd.Series, window: int) -> pd.Series:
    """Volatilidad anualizada (%) de las variaciones diarias en `window` días hábiles."""
    r = np.log(s).diff()
    return r.rolling(window, min_periods=max(5, int(window * 0.75))).std() * math.sqrt(252) * 100


def _weighted_mean(frame: pd.DataFrame, weights: dict[str, float], min_share: float | None = None) -> pd.Series:
    """Promedio ponderado renormalizando por los componentes disponibles."""
    if frame.empty:
        return pd.Series(dtype=float)
    w = pd.Series(weights).reindex(frame.columns).fillna(0.0)
    avail = frame.notna().mul(w, axis=1)
    total = w.sum()
    num = frame.fillna(0.0).mul(w, axis=1).sum(axis=1)
    den = avail.sum(axis=1)
    out = num / den.replace(0, np.nan)
    share = config.IPD_MIN_WEIGHT_SHARE if min_share is None else min_share
    out[(den <= 0) | (den < share * total)] = np.nan
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
    pesos: dict[str, dict[str, float]] = {}
    pesos_info: dict[str, dict] = {}
    for bkey, block in config.IPD_BLOCKS.items():
        zs = {}
        for ckey, spec in block["components"].items():
            if ckey not in df or df[ckey].dropna().empty:
                continue
            serie = df[ckey]
            if "piso" in spec:
                serie = serie.clip(lower=spec["piso"])
            x = transform(serie, spec["transform"], spec.get("horizonte", h)) * spec["sign"]
            z = rolling_z(x, config.IPD_ZSCORE_WINDOW, config.IPD_ZSCORE_MIN_OBS, config.IPD_Z_CLIP)
            if z.dropna().empty:
                continue
            zs[ckey] = z
            components[ckey] = z
        if zs:
            weights = {k: block["components"][k]["weight"] for k in zs}
            if config.IPD_PONDERACION == "pca":
                pca = pca_weights(pd.DataFrame(zs))
                if pca is not None:
                    weights, var_expl = pca
                    pesos_info[bkey] = {"varianza_explicada": var_expl}
            pesos[bkey] = weights
            block_series[bkey] = _weighted_mean(pd.DataFrame(zs), weights, config.IPD_MIN_WEIGHT_SHARE_BLOQUE)
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
    aportes = contributions_points(comps, blocks, pesos, ipd, indice, sigma)
    return {
        "aportes": aportes,
        "pesos": pesos,
        "pesos_info": pesos_info,
        "ipd": ipd,
        "indice": indice,
        "indice_sigma": sigma,
        "percentil": pct,
        "n_componentes": n_comp,
        "blocks": blocks,
        "components": comps,
    }


def contributions_points(comps: pd.DataFrame, blocks: pd.DataFrame, pesos: dict, ipd: pd.Series,
                         indice: pd.Series, sigma: float) -> pd.DataFrame:
    """Aporte de cada componente al índice 0-100, en puntos respecto de 50.

    Cada día, el IPD es la suma de peso efectivo x z-score de cada componente
    (los pesos se renormalizan cuando falta alguno). Esos aportes se promedian
    con la misma ventana que el índice y se reparte la distancia del índice a
    50 en proporción: los aportes suman exactamente (índice - 50).
    """
    if comps.empty:
        return comps
    aporte = pd.DataFrame(0.0, index=comps.index, columns=comps.columns)
    bw = pd.Series({b: config.IPD_BLOCKS[b]["weight"] for b in blocks.columns})
    bw_avail = blocks.notna().mul(bw, axis=1)
    bw_eff = bw_avail.div(bw_avail.sum(axis=1).replace(0, np.nan), axis=0)
    for b in blocks.columns:
        cols = [c for c in pesos.get(b, {}) if c in comps]
        if not cols:
            continue
        w = pd.Series({c: pesos[b][c] for c in cols})
        avail = comps[cols].notna().mul(w, axis=1)
        w_eff = avail.div(avail.sum(axis=1).replace(0, np.nan), axis=0)
        aporte[cols] = w_eff.mul(comps[cols].fillna(0.0)).mul(bw_eff[b], axis=0).fillna(0.0)
    aporte = aporte.where(ipd.notna(), np.nan)
    n = config.INDICE_SUAVIZADO
    suav = aporte.rolling(n, min_periods=n).mean()
    total = suav.sum(axis=1, min_count=1)
    gap = indice - 50
    # Factor puntos por desvío; cerca de 0 se usa la pendiente de la normal en 0.
    lineal = 100 / math.sqrt(2 * math.pi) / sigma if sigma and np.isfinite(sigma) else np.nan
    factor = (gap / total).where(total.abs() > 1e-3, lineal)
    return suav.mul(factor, axis=0).where(indice.notna())


def pca_weights(zs: pd.DataFrame) -> tuple[dict[str, float], float] | None:
    """Pesos de un bloque según su primer componente principal.

    Se usa la matriz de correlaciones de los promedios mensuales de los
    z-scores (desde IPD_PUBLICAR_DESDE, con datos de a pares), para capturar
    los ciclos comunes y no el ruido diario. Las cargas se orientan para que
    sumen positivo; las negativas valen 0 (no se invierte el sentido económico
    de ningún componente). Devuelve (pesos que suman 1, varianza explicada).
    """
    m = zs[zs.index >= pd.Timestamp(config.IPD_PUBLICAR_DESDE)].resample(config.IPD_PCA_FRECUENCIA).mean()
    corr = m.corr(min_periods=config.IPD_PCA_MIN_OBS).dropna(how="all").dropna(axis=1, how="all")
    if corr.shape[0] < 2 or corr.isna().any().any():
        return None
    vals, vecs = np.linalg.eigh(corr.to_numpy())
    carga = pd.Series(vecs[:, -1], index=corr.columns)
    if carga.sum() < 0:
        carga = -carga
    w = carga.clip(lower=0)
    if w.sum() <= 0:
        return None
    w = (w / w.sum()).reindex(zs.columns).fillna(0.0)
    w = apply_min_weight(w, config.IPD_PCA_PESO_MINIMO)
    return {k: float(v) for k, v in w.items()}, float(vals[-1] / vals.sum())


def apply_min_weight(w: pd.Series, minimo: float) -> pd.Series:
    """Garantiza un peso mínimo a cada componente y reparte el resto en proporción.

    Los componentes por debajo del mínimo quedan en el mínimo; el peso restante
    se distribuye entre los demás según sus pesos originales. Se repite hasta
    que ninguno quede por debajo (puede pasar al reescalar).
    """
    if not minimo or minimo * len(w) >= 1:
        return w
    fijos = pd.Series(False, index=w.index)
    for _ in range(len(w)):
        libres = ~fijos
        resto = 1 - minimo * fijos.sum()
        base = w[libres]
        nuevo = base / base.sum() * resto if base.sum() > 0 else pd.Series(resto / libres.sum(), index=base.index)
        bajo = nuevo < minimo
        if not bajo.any():
            return pd.concat([pd.Series(minimo, index=w.index[fijos]), nuevo]).reindex(w.index)
        fijos[nuevo.index[bajo]] = True
    return pd.Series(1 / len(w), index=w.index)


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
        out = out.sort_values("fecha")
        out["netas_prom_12m"] = out["netas_usd_millones"].rolling(12, min_periods=12).mean()
    return out.sort_values("fecha")
