"""Traspaso del tipo de cambio a precios, como indicador de cuánto se "piensa
en dólares" (dolarización de la unidad de cuenta).

Si los precios se fijan mirando el dólar, una depreciación se traslada rápido
y en buena parte a la inflación. Se estima con una regresión móvil:

    π_t = a + Σ_{k=0..K} β_k · d_{t-k} + ρ · π_{t-1} + γ · x_t + e_t

con π la inflación mensual del IPC (desestacionalizada), d la depreciación
mensual del tipo de cambio (promedio del mes) y x la inflación de las materias
primas en dólares (control externo). El indicador es el traspaso acumulado
Σβ_k (qué parte de una depreciación aparece en los precios en K+1 meses) y el
de largo plazo Σβ_k / (1 − ρ). La banda es ±1,96 errores estándar de
Newey-West (HAC). Como chequeo, proyecciones locales (Jordà): cociente entre la
respuesta acumulada de los precios y la del tipo de cambio a h meses.

Cuando el tipo de cambio casi no se mueve en la ventana (tipo de cambio fijo),
el traspaso no está identificado y no se reporta.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

VENTANA = 36        # meses
REZAGOS = 6         # rezagos de la depreciación (0..6)
MIN_OBS = 30        # observaciones mínimas en la ventana
MIN_MESES_MOV = 8   # meses con |depreciación| ≥ 0,5% en la ventana
MIN_SD = 0.5        # desvío mínimo de la depreciación mensual (pp)
HAC_LAGS = 3
HORIZONTE_LP = 6


def variacion(s: pd.Series) -> pd.Series:
    """Variación mensual en logaritmos, en %."""
    return (np.log(s.astype(float)).diff() * 100).dropna()


def mensual_promedio(s: pd.Series) -> pd.Series:
    s = s.dropna()
    return s.resample("ME").mean().dropna()


def desestacionalizar(pi: pd.Series, años: int = 10) -> pd.Series:
    """Resta el factor estacional de cada mes calendario: la mediana, en los
    últimos `años` años, del desvío respecto del promedio centrado de 12 meses.
    Mediana para que los saltos (devaluaciones) no contaminen el factor."""
    pi = pi.dropna()
    tend = pi.rolling(12, center=True, min_periods=12).mean()
    dev = (pi - tend).dropna()
    dev = dev[dev.index >= dev.index.max() - pd.DateOffset(years=años)] if len(dev) else dev
    if len(dev) < 36:
        return pi
    fac = dev.groupby(dev.index.month).median()
    fac = fac - fac.mean()
    return pi - fac.reindex(pi.index.month).values


def ols_hac(y: np.ndarray, X: np.ndarray, lags: int = HAC_LAGS) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MCO con covarianza de Newey-West. Devuelve (beta, cov, residuos)."""
    XtX_inv = np.linalg.pinv(X.T @ X)
    b = XtX_inv @ X.T @ y
    u = y - X @ b
    Xu = X * u[:, None]
    S = Xu.T @ Xu
    for l in range(1, lags + 1):
        w = 1 - l / (lags + 1)
        G = Xu[l:].T @ Xu[:-l]
        S += w * (G + G.T)
    n, k = X.shape
    cov = XtX_inv @ S @ XtX_inv * (n / max(n - k, 1))
    return b, cov, u


def armar(pi: pd.Series, dep: pd.Series, ext: pd.Series | None = None, rezagos: int = REZAGOS) -> pd.DataFrame:
    df = pd.DataFrame({"pi": pi, "d0": dep})
    for k in range(1, rezagos + 1):
        df[f"d{k}"] = dep.shift(k)
    df["pi1"] = pi.shift(1)
    if ext is not None and not ext.dropna().empty:
        df["x"] = ext
    return df.dropna()


def estimar(df: pd.DataFrame, rezagos: int = REZAGOS) -> dict | None:
    """Una ventana: traspaso acumulado y de largo plazo, con error HAC."""
    cols_d = [f"d{k}" for k in range(rezagos + 1)]
    y = df["pi"].to_numpy()
    X = np.column_stack([np.ones(len(df)), df[cols_d + [c for c in df.columns if c in ("pi1", "x")]].to_numpy()])
    b, cov, _ = ols_hac(y, X)
    nd = len(cols_d)
    g = np.zeros(len(b)); g[1:1 + nd] = 1
    suma = float(g @ b)
    se = float(np.sqrt(max(g @ cov @ g, 0)))
    rho = float(b[1 + nd])
    lp = lp_se = None
    if rho < 0.9:
        lp = suma / (1 - rho)
        # Delta: ∂LP/∂β_k = 1/(1−ρ); ∂LP/∂ρ = Σβ/(1−ρ)².
        gl = g / (1 - rho); gl[1 + nd] = suma / (1 - rho) ** 2
        lp_se = float(np.sqrt(max(gl @ cov @ gl, 0)))
    return {"suma": suma, "se": se, "rho": rho, "lp": lp, "lp_se": lp_se}


def identificado(dep: pd.Series) -> bool:
    """¿Se movió el tipo de cambio lo suficiente para identificar el traspaso?"""
    dep = dep.dropna()
    return bool(len(dep) and dep.std() >= MIN_SD and (dep.abs() >= 0.5).sum() >= MIN_MESES_MOV)


def movil(pi: pd.Series, dep: pd.Series, ext: pd.Series | None = None, ventana: int = VENTANA,
          rezagos: int = REZAGOS, min_obs: int = MIN_OBS) -> pd.DataFrame:
    """Regresión móvil. Una fila por mes de cierre de la ventana; NaN donde el
    traspaso no está identificado (columna `sin_dato` = True)."""
    df = armar(pi, dep, ext, rezagos)
    filas = {}
    for i in range(len(df)):
        fin = df.index[i]
        w = df[(df.index > fin - pd.DateOffset(months=ventana)) & (df.index <= fin)]
        if len(w) < min_obs:
            continue
        if not identificado(w["d0"]):
            filas[fin] = {"suma": np.nan, "se": np.nan, "lp": np.nan, "lp_se": np.nan, "rho": np.nan, "sin_dato": True}
            continue
        r = estimar(w, rezagos)
        filas[fin] = {**{k: (np.nan if v is None else v) for k, v in r.items()}, "sin_dato": False}
    return pd.DataFrame.from_dict(filas, orient="index")


def proyeccion_local(pi: pd.Series, dep: pd.Series, h: int = HORIZONTE_LP) -> float | None:
    """Cociente de traspaso de Jordà a h meses en una muestra: respuesta
    acumulada de los precios dividida por la del tipo de cambio, ante una
    depreciación en t, controlando por un rezago de inflación y depreciación."""
    p = pi.cumsum(); e = dep.cumsum()
    yp = p.shift(-h) - p.shift(1)
    ye = e.shift(-h) - e.shift(1)
    df = pd.DataFrame({"yp": yp, "ye": ye, "d": dep, "pi1": pi.shift(1), "d1": dep.shift(1)}).dropna()
    if len(df) < 20:
        return None
    X = np.column_stack([np.ones(len(df)), df[["d", "pi1", "d1"]].to_numpy()])
    bp = np.linalg.lstsq(X, df["yp"].to_numpy(), rcond=None)[0][1]
    be = np.linalg.lstsq(X, df["ye"].to_numpy(), rcond=None)[0][1]
    return None if abs(be) < 0.2 else float(bp / be)


def lp_movil(pi: pd.Series, dep: pd.Series, ventana: int = VENTANA, h: int = HORIZONTE_LP) -> pd.Series:
    df = pd.DataFrame({"pi": pi, "d": dep}).dropna()
    out = {}
    for i in range(len(df)):
        fin = df.index[i]
        w = df[(df.index > fin - pd.DateOffset(months=ventana + h)) & (df.index <= fin)]
        if len(w) < MIN_OBS + h or not identificado(w["d"]):
            continue
        r = proyeccion_local(w["pi"], w["d"], h)
        if r is not None:
            out[fin] = r
    return pd.Series(out, dtype=float)
