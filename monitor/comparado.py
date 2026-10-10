"""Núcleo comparable entre países: presión cambiaria en % de depreciación equivalente.

Sigue la idea de Girton y Roper (1977), Weymark (1995) y Patnaik, Felman y
Shah (2017): la presión sobre una moneda se ve en lo que se deprecia y en lo
que el banco central vende para evitarlo. Cada mes:

    presión = depreciación (%) + ρ × intervención vendedora neta (% de las reservas del mes anterior)

ρ convierte la intervención en puntos de depreciación. Es el mismo para todos
los países (si no, las unidades dejarían de ser comparables) y se fija con la
dispersión del panel: ρ = MAD(depreciación) / MAD(intervención), de modo que
una intervención "típica" (de los meses en que hubo intervención) equivale a una
depreciación "típica". Es la versión
en unidades de tipo de cambio de la ponderación por precisión del EMP clásico.

A diferencia del índice 0-100 de cada país, acá el nivel sí se compara: un 5%
en Argentina y un 5% en Perú son la misma presión.

Uso: python -m monitor.comparado   (lee las series guardadas de cada país)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import build, config, peru

log = logging.getLogger("monitor.comparado")

OUTPUT_JSON = config.DATA_DIR / "comparado.json"
DESDE = "2003-01"


def _fin_de_mes(s: pd.Series) -> pd.Series:
    return s.dropna().resample("ME").last()


def _componentes(tc: pd.Series, ventas_mes: pd.Series, reservas: pd.Series) -> pd.DataFrame:
    """Depreciación mensual (%) e intervención (% de reservas del mes anterior)."""
    e = _fin_de_mes(tc)
    dep = np.log(e).diff() * 100
    r_prev = _fin_de_mes(reservas).shift(1)
    x = ventas_mes.reindex(dep.index) / r_prev.reindex(dep.index) * 100
    return pd.DataFrame({"depreciacion": dep, "intervencion": x})


def argentina() -> pd.DataFrame:
    """Oficial A3500, compras del BCRA (signo invertido) y cambio en su posición vendida de futuros."""
    tc = build.load_cached("tc_a3500")
    compras = build.load_cached("compras_bcra")
    reservas = build.load_cached("reservas")
    ventas = -compras.resample("ME").sum(min_count=1)
    pos_path = config.SERIES_DIR / "posicion_futuros_bcra.csv"
    if pos_path.exists():
        pos = pd.read_csv(pos_path, dtype={"fecha": str})
        fut = pd.Series(pd.to_numeric(pos["vendida_neta_usd_millones"], errors="coerce").values,
                        index=pd.to_datetime(pos["fecha"] + "-01") + pd.offsets.MonthEnd(0))
        # Ampliar la posición vendida es vender dólares a futuro.
        ventas = ventas.add(fut.diff().reindex(ventas.index).fillna(0.0), fill_value=0.0).where(ventas.notna())
    return _componentes(tc, ventas, reservas)


def peru_() -> pd.DataFrame:
    """Sol interbancario, ventas spot y swaps cambiarios del BCRP."""
    flujos = {k: peru._cache(k) for k in ["mesa_compras_netas", "sc_venta_pactado", "sc_venta_vencido",
                                          "sc_compra_pactado", "sc_compra_vencido"]}
    flujos = {k: v for k, v in flujos.items() if not v.empty}
    if not flujos:
        return pd.DataFrame(columns=["depreciacion", "intervencion"])
    idx = pd.DatetimeIndex(sorted(set().union(*[v.index for v in flujos.values()])))
    df = pd.DataFrame({k: v.reindex(idx) for k, v in flujos.items()})
    ventas = peru.intervencion_diaria(df).resample("ME").sum(min_count=1)
    return _componentes(peru._cache("tc"), ventas, peru._cache("rin"))


def uruguay_() -> pd.DataFrame:
    """Peso uruguayo interbancario; intervención aproximada por la caída de la
    posición en moneda extranjera del BCU (no hay serie pública de sus
    operaciones cambiarias diarias). Incluye efectos de valuación y de
    operaciones con el Tesoro, así que es una aproximación."""
    from . import uruguay
    pos = uruguay._cache("posicion_me")
    if pos.empty:
        return pd.DataFrame(columns=["depreciacion", "intervencion"])
    ventas = -_fin_de_mes(pos).diff()
    return _componentes(uruguay._cache("tc"), ventas, uruguay._cache("reservas"))


def brasil_() -> pd.DataFrame:
    """Real (PTAX); intervención: ventas netas spot del BCB en el mes más la
    variación del stock de swaps cambiales y de líneas con recompra."""
    from . import brasil, comun
    c = lambda k: comun.cache(brasil.SERIES_DIR, k)  # noqa: E731
    spot = c("ventas_spot")
    if spot.empty:
        return pd.DataFrame(columns=["depreciacion", "intervencion"])
    ventas = spot.resample("ME").sum(min_count=1)
    for k in ["swaps", "linhas"]:
        st = c(k)
        if not st.empty:
            ventas = ventas.add(_fin_de_mes(st).diff().reindex(ventas.index).fillna(0.0), fill_value=0.0)
    ventas = ventas.reindex(pd.date_range(ventas.index.min(), ventas.index.max(), freq="ME")).fillna(0.0)
    return _componentes(c("tc"), ventas, c("reservas"))


def colombia_() -> pd.DataFrame:
    """TRM; intervención: ventas netas del Banco de la República en el mercado
    cambiario (compras directas, opciones, NDF y swaps; − compras)."""
    from . import colombia, comun
    c = lambda k: comun.cache(colombia.SERIES_DIR, k)  # noqa: E731
    compras = c("compras_netas")
    if compras.empty:
        return pd.DataFrame(columns=["depreciacion", "intervencion"])
    ventas = -compras.resample("ME").sum()
    ventas = ventas.reindex(pd.date_range("2000-01-31", ventas.index.max(), freq="ME")).fillna(0.0)
    return _componentes(c("tc"), ventas, c("reservas"))


PAISES = {"ar": ("Argentina", argentina), "pe": ("Perú", peru_), "uy": ("Uruguay", uruguay_), "br": ("Brasil", brasil_),
          "co": ("Colombia", colombia_)}


def _mad(x: pd.Series) -> float:
    x = x.dropna()
    return float((x - x.median()).abs().median() * 1.4826)


def calcular(paises: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], float]:
    desde = pd.Timestamp(DESDE)
    paises = {k: v[v.index >= desde] for k, v in paises.items() if not v.empty}
    dep = pd.concat([v["depreciacion"] for v in paises.values()])
    x = pd.concat([v["intervencion"] for v in paises.values()])
    # Sólo los meses con intervención: los países que intervienen poco (muchos
    # meses en cero) achicarían la dispersión y cambiarían la escala de todos.
    x_activa = x[x.abs() > 1e-9]
    rho = _mad(dep) / _mad(x_activa) if _mad(x_activa) > 0 else np.nan
    out = {}
    for k, v in paises.items():
        v = v.copy()
        v["intervencion_eq"] = rho * v["intervencion"]
        v["presion"] = v["depreciacion"] + v["intervencion_eq"]
        v["presion_3m"] = v["presion"].rolling(3, min_periods=3).mean()
        out[k] = v
    return out, rho


def run() -> dict:
    datos = {}
    for k, (nombre, f) in PAISES.items():
        try:
            datos[k] = f()
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: no se pudo armar el núcleo comparable (%s)", nombre, exc)
    res, rho = calcular(datos)

    def fila(fecha, r):
        return [fecha.strftime("%Y-%m")] + [build._clean(r[c]) for c in
                                            ["presion", "presion_3m", "depreciacion", "intervencion_eq", "intervencion"]]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rho": build._clean(rho),
        "columnas": ["mes", "presion", "presion_3m", "depreciacion", "intervencion_eq", "intervencion_pct_reservas"],
        "paises": {k: {"nombre": PAISES[k][0],
                       "data": [fila(f, r) for f, r in v.dropna(subset=["presion"]).iterrows()]}
                   for k, v in res.items()},
    }
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for k, v in res.items():
        u = v.dropna(subset=["presion"]).iloc[-1:] if not v.empty else v
        if not u.empty:
            log.info("%s %s: presión %.2f%% (3m %.2f%%), ρ = %.3f", k, u.index[0].strftime("%Y-%m"),
                     u["presion"].iloc[0], u["presion_3m"].iloc[0], rho)
    return payload


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run()


if __name__ == "__main__":
    main()
