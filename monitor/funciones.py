"""Índice de las tres funciones del dinero: cuánto cumple el dólar cada una en
Argentina.

- Medio de pago: participación de los dólares en los depósitos a la vista del
  sector privado (cuentas corrientes y cajas de ahorro).
- Unidad de cuenta: traspaso del tipo de cambio a precios (regresión móvil de
  `traspaso.py`, con el dólar paralelo), acotado a [0, 1].
- Reserva de valor: promedio de la dolarización de los depósitos y la del
  crédito al sector privado.

Cada pata va de 0 a 1 en su escala natural (participación o coeficiente), así
que se lee directo. El índice es el promedio simple; como chequeo, la
ponderación por el primer componente principal, como en el Índice de
Dolarización.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, indicators

PATAS = {
    "medio_pago": "Medio de pago",
    "unidad_cuenta": "Unidad de cuenta",
    "reserva_valor": "Reserva de valor",
}
AÑOS_TRIANGULO = [2007, 2015, 2019, 2023]


def _mensual(s: pd.Series) -> pd.Series:
    s = s.dropna()
    return s.resample("ME").mean() if len(s) else s


def patas(vista: pd.Series, traspaso: pd.Series, depositos: pd.Series, credito: pd.Series) -> pd.DataFrame:
    """Las tres patas, mensuales y entre 0 y 1. Las participaciones entran en %
    (promedio del mes) y el traspaso como fracción."""
    rv = pd.concat([_mensual(depositos), _mensual(credito)], axis=1).mean(axis=1, skipna=False) / 100
    return pd.DataFrame({
        "medio_pago": _mensual(vista) / 100,
        "unidad_cuenta": _mensual(traspaso).clip(0, 1),
        "reserva_valor": rv,
    })


def indice(p: pd.DataFrame) -> tuple[pd.Series, pd.Series, dict | None]:
    """Promedio simple de las tres patas (sólo meses con las tres) y, como
    chequeo, el ponderado por componentes principales. Devuelve (simple, PCA,
    {pesos, varianza explicada})."""
    comun = p[list(PATAS)].dropna()
    simple = comun.mean(axis=1)
    pca = None
    if len(comun) >= config.IPD_PCA_MIN_OBS:
        pca = indicators.pca_weights(comun, str(comun.index.min().date()))
    if pca is None:
        return simple, pd.Series(dtype=float), None
    w, var = pca
    ponderado = sum(comun[k] * w[k] for k in PATAS)
    return simple, ponderado, {"pesos": {k: round(w[k], 3) for k in PATAS}, "varianza_explicada": round(var, 3)}


def triangulo(p: pd.DataFrame, años: list[int] = AÑOS_TRIANGULO) -> list[dict]:
    """Promedios anuales de las patas para el gráfico de triángulo, más los
    últimos 12 meses con las tres patas."""
    comun = p[list(PATAS)].dropna()
    out = []
    for a in años:
        x = comun[comun.index.year == a]
        if len(x) >= 6:
            out.append({"etiqueta": str(a), **{k: round(float(x[k].mean()), 3) for k in PATAS}})
    if len(comun):
        fin = comun.index.max()
        x = comun[comun.index > fin - pd.DateOffset(months=12)]
        out.append({"etiqueta": "Últimos 12 meses", "hasta": fin.strftime("%Y-%m-%d"), **{k: round(float(x[k].mean()), 3) for k in PATAS}})
    return out


def bloque(vista: pd.Series, traspaso: pd.Series, depositos: pd.Series, credito: pd.Series) -> dict | None:
    p = patas(vista, traspaso, depositos, credito)
    if p.dropna(how="all").empty:
        return None
    simple, ponderado, pca = indice(p)
    par = lambda s: [[d.strftime("%Y-%m-%d"), None if pd.isna(v) else round(float(v), 3)] for d, v in s.items()]  # noqa: E731
    p = p[p.index >= p.dropna(how="all").index.min()]
    return {
        "patas": {k: {"label": PATAS[k], "data": par(p[k])} for k in PATAS},
        "indice": par(simple),
        "indice_pca": par(ponderado),
        "pca": pca,
        "triangulo": triangulo(p),
        "ultimo": {**{k: (None if p[k].dropna().empty else round(float(p[k].dropna().iloc[-1]), 3)) for k in PATAS},
                   "indice": None if simple.empty else round(float(simple.iloc[-1]), 3),
                   "fecha": None if simple.empty else simple.index[-1].strftime("%Y-%m-%d")},
    }
