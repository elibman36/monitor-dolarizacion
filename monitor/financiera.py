"""Monitor de Dolarización Financiera.

A diferencia del Índice de Dolarización (estrés cambiario), acá se sigue la
dolarización como la mide la literatura (Ize y Levy Yeyati, 2003; FMI): qué
parte de los depósitos, del crédito y del dinero amplio está en moneda
extranjera, con la mayor frecuencia que permite cada fuente.

Indicadores por país:

- dolarización de los depósitos del sector privado (% en moneda extranjera);
- dolarización del crédito al sector privado;
- dolarización de la liquidez (dinero amplio, con el circulante cuando hay dato);
- descomposición de cada cambio en efecto valuación (el tipo de cambio
  revalúa los saldos en dólares) y efecto portafolio (la gente cambia la
  composición de sus depósitos);
- depósitos de residentes no bancarios en bancos del exterior (BIS,
  estadísticas bancarias territoriales, trimestral): la dolarización que se
  va del sistema local. Es la única medida comparable para Brasil, Chile y
  Colombia, donde los depósitos locales en dólares están restringidos o no
  hay una serie pública sin registro.

Uso: python -m monitor.financiera [--offline]
"""

from __future__ import annotations

import argparse
import io
import json
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import comun, config, sources

log = logging.getLogger("monitor.financiera")

DATA_DIR = config.DATA_DIR / "financiera"
SERIES_DIR = DATA_DIR / "series"

# Argentina (API del BCRA, diaria): saldos del sector privado.
BCRA_IDS = {
    "dep_pesos": 1527,   # depósitos totales de efectivo del sector privado (millones de $)
    "dep_usd": 1564,     # depósitos del sector privado no financiero en dólares (millones de USD)
    "cred_pesos": 1342,  # préstamos de efectivo al sector privado (millones de $)
    "cred_usd": 1356,    # préstamos de efectivo al sector privado en dólares (millones de USD)
    "circulante": 17,    # billetes y monedas en poder del público (millones de $)
    "m3_total": 1623,    # M3 en moneda local y extranjera (mensual, miles de $)
    "m3_local": 1624,    # M3 en moneda local (mensual, miles de $)
}
# Perú (BCRP, mensual).
BCRP_CODES = {
    "liq_mn_circ": "PN00020MM",   # liquidez MN: circulante (millones S/)
    "liq_mn_vista": "PN00021MM",  # liquidez MN: depósitos a la vista
    "liq_mn_cuasi": "PN00022MM",  # liquidez MN: cuasidinero
    "liq_me_soles": "PN00023MM",  # liquidez ME (millones S/)
    "liq_me_usd": "PN00024MM",    # liquidez ME (millones US$)
    "cred_coef": "PN00511MM",     # coeficiente de dolarización del crédito (%)
}
BCU_CREDITOS_XLSX = "https://www.bcu.gub.uy/Servicios-Financieros-SSF/Series%20IF/Creditos.xlsx"
BIS_URL = "https://stats.bis.org/api/v1/data/WS_LBS_D_PUB/Q.S.L.A.TO1.A.5J.A.5A.N.{pais}.N?startPeriod=2000&format=csv"
BIS_PAISES = {"ar": "AR", "pe": "PE", "uy": "UY", "br": "BR", "cl": "CL", "co": "CO"}
NOMBRES = {"ar": "Argentina", "pe": "Perú", "uy": "Uruguay", "br": "Brasil", "cl": "Chile", "co": "Colombia"}
NOTAS = {
    "br": "En Brasil los residentes no pueden tener depósitos en dólares en el sistema local (salvo excepciones), así que la dolarización financiera local es prácticamente nula. La que existe se ve afuera: depósitos en bancos del exterior.",
    "co": "En Colombia los depósitos locales en moneda extranjera de residentes están muy restringidos: la dolarización local es baja por regulación. La medida comparable es la de depósitos en bancos del exterior.",
    "cl": "Chile permite depósitos en dólares, pero la serie del Banco Central requiere registro en su API. Mientras tanto se muestran los depósitos en bancos del exterior.",
}


# ---------------------------------------------------------------------------
# Cálculos
# ---------------------------------------------------------------------------

def ratio(me_local: pd.Series, mn: pd.Series) -> pd.Series:
    """Participación de la moneda extranjera (%), con todo en moneda local."""
    tot = me_local + mn
    return (me_local / tot * 100).where(tot > 0)


def descomponer(mn: pd.Series, me_usd: pd.Series, tc: pd.Series, freq: str = "ME") -> pd.DataFrame:
    """Cambio de la dolarización entre fines de período, separado en:

    - portafolio: el cambio que habría con el tipo de cambio del período
      anterior (la gente movió sus saldos entre monedas);
    - valuación: el resto, que viene sólo de que el tipo de cambio revalúa
      los saldos en dólares.
    Los dos suman exactamente el cambio total.
    """
    df = pd.concat({"mn": mn, "me": me_usd, "tc": tc}, axis=1).sort_index().ffill().dropna()
    m = df.resample(freq).last().dropna()
    d = lambda me, mnv, e: me * e / (me * e + mnv) * 100  # noqa: E731
    prev = m.shift(1)
    total = d(m.me, m.mn, m.tc) - d(prev.me, prev.mn, prev.tc)
    port = d(m.me, m.mn, prev.tc) - d(prev.me, prev.mn, prev.tc)
    out = pd.DataFrame({"total": total, "portafolio": port, "valuacion": total - port}).dropna()
    return out


def _cambio(s: pd.Series, dias: int) -> float | None:
    s = s.dropna()
    if s.empty:
        return None
    prev = s[s.index <= s.index[-1] - pd.Timedelta(days=dias)]
    return None if prev.empty else float(s.iloc[-1] - prev.iloc[-1])


def _pairs(s: pd.Series, dec: int = 2) -> list:
    s = s.dropna()
    return [[d.strftime("%Y-%m-%d"), round(float(v), dec)] for d, v in s.items()]


def indicador(s: pd.Series, label: str, unidad: str, frecuencia: str, fuente: str, dec: int = 2) -> dict:
    s = s.dropna()
    return {
        "label": label, "unidad": unidad, "frecuencia": frecuencia, "fuente": fuente,
        "last": round(float(s.iloc[-1]), dec) if not s.empty else None,
        "last_date": s.index[-1].strftime("%Y-%m-%d") if not s.empty else None,
        "cambio_1m": _cambio(s, 30), "cambio_12m": _cambio(s, 365),
        "data": _pairs(s, dec),
    }


def _desc_pairs(dec: pd.DataFrame) -> list:
    return [[d.strftime("%Y-%m"), round(r.total, 3), round(r.valuacion, 3), round(r.portafolio, 3)]
            for d, r in dec.iterrows()]


# ---------------------------------------------------------------------------
# Fuentes
# ---------------------------------------------------------------------------

def _bcra(base: str, var_id: int, key: str, offline: bool) -> pd.Series:
    def fetch(desde, hasta):
        return sources.bcra_series(base, var_id, key, start=desde.strftime("%Y-%m-%d"))
    inicio = "1940-01-01" if key.startswith("m3") else "1996-01-01"
    s, _ = comun.actualizar(SERIES_DIR / "ar", key, fetch, inicio, offline=offline or base is None)
    return s


def _tc_cache(path) -> pd.Series:
    if not path.exists():
        return pd.Series(dtype=float)
    return pd.read_csv(path, parse_dates=["fecha"]).set_index("fecha")["valor"]


def argentina(offline: bool) -> dict:
    base = None
    if not offline:
        try:
            base, _ = sources.bcra_catalog()
        except Exception as exc:  # noqa: BLE001
            log.warning("BCRA no disponible (%s): uso copias guardadas", exc)
    raw = {k: _bcra(base, i, k, offline) for k, i in BCRA_IDS.items()}
    tc = _tc_cache(config.SERIES_DIR / "tc_a3500.csv")
    # Antes del A3500 (2002) rige la convertibilidad: 1 peso por dólar.
    tc = tc.combine_first(pd.Series(1.0, index=pd.date_range("1996-01-01", "2002-01-10", freq="D")))
    idx = raw["dep_pesos"].index.union(raw["dep_usd"].index)
    al = lambda s: s.reindex(idx.union(s.index)).sort_index().ffill().reindex(idx)  # noqa: E731
    e = al(tc)
    dep = ratio(al(raw["dep_usd"]) * e, al(raw["dep_pesos"]))
    idc = raw["cred_pesos"].index.union(raw["cred_usd"].index)
    alc = lambda s: s.reindex(idc.union(s.index)).sort_index().ffill().reindex(idc)  # noqa: E731
    cred = ratio(alc(raw["cred_usd"]) * alc(tc), alc(raw["cred_pesos"]))
    liq = ratio(al(raw["dep_usd"]) * e, al(raw["dep_pesos"]) + al(raw["circulante"]))
    m3 = ((raw["m3_total"] - raw["m3_local"]) / raw["m3_total"] * 100).dropna()
    # Antes de mediados de los setenta no había depósitos en moneda extranjera.
    m3 = m3[m3.index >= m3[m3 > 0.5].index.min()] if (m3 > 0.5).any() else m3
    fuente = "BCRA (API de series estadísticas)"
    return {
        "frecuencia": "diaria",
        "indicadores": {
            "depositos": indicador(dep, "Dolarización de los depósitos del sector privado", "% en dólares", "diaria", fuente),
            "credito": indicador(cred, "Dolarización del crédito al sector privado", "% en dólares", "diaria", fuente),
            "liquidez": indicador(liq, "Dolarización de la liquidez (circulante + depósitos privados)", "% en dólares", "diaria", fuente),
            "m3": indicador(m3, "Dolarización de M3 (serie larga)", "% en moneda extranjera", "mensual", "BCRA, agregados monetarios"),
            "depositos_usd": indicador(raw["dep_usd"], "Depósitos privados en dólares", "millones de USD", "diaria", fuente, 0),
        },
        "descomposicion": {
            "depositos": _desc_pairs(descomponer(raw["dep_pesos"], raw["dep_usd"], tc)),
            "credito": _desc_pairs(descomponer(raw["cred_pesos"], raw["cred_usd"], tc)),
        },
    }


def peru(offline: bool) -> dict:
    from . import peru as pe

    raw = {}
    for k, cod in BCRP_CODES.items():
        def fetch(desde, hasta, cod=cod, k=k):
            return pe.bcrp_series(cod, desde.strftime("%Y-%m"), hasta.strftime("%Y-%m"), k)
        raw[k], _ = comun.actualizar(SERIES_DIR / "pe", k, fetch, "1992-01-01", solapamiento_dias=400, offline=offline)
    mn = raw["liq_mn_circ"].add(raw["liq_mn_vista"], fill_value=np.nan).add(raw["liq_mn_cuasi"], fill_value=np.nan)
    tc_fin = (raw["liq_me_soles"] / raw["liq_me_usd"]).dropna()   # tipo de cambio de valuación del BCRP
    liq = ratio(raw["liq_me_soles"], mn)
    # Sin circulante: dolarización de los depósitos (vista + cuasidinero).
    dep = ratio(raw["liq_me_soles"], raw["liq_mn_vista"] + raw["liq_mn_cuasi"])
    fuente = "BCRP (liquidez y crédito de las sociedades creadoras de depósito)"
    return {
        "frecuencia": "mensual",
        "indicadores": {
            "depositos": indicador(dep, "Dolarización de los depósitos", "% en dólares", "mensual", fuente),
            "credito": indicador(raw["cred_coef"], "Dolarización del crédito al sector privado", "% en dólares", "mensual", fuente),
            "liquidez": indicador(liq, "Dolarización de la liquidez (coeficiente del BCRP)", "% en dólares", "mensual", fuente),
            "depositos_usd": indicador(raw["liq_me_usd"], "Liquidez en dólares", "millones de USD", "mensual", fuente, 0),
        },
        "descomposicion": {
            "depositos": _desc_pairs(descomponer(raw["liq_mn_vista"] + raw["liq_mn_cuasi"], raw["liq_me_usd"], tc_fin)),
        },
    }


def parse_creditos_bcu(df: pd.DataFrame) -> pd.DataFrame:
    """Hoja 'Total Sist. Banc.' de Creditos.xlsx: tres bloques (total MN+ME en
    pesos, moneda nacional en pesos y moneda extranjera en dólares), cada uno
    con sector privado (vigentes, vencidos, total) primero. Se toma el total
    del sector privado de cada bloque, ubicándolo por el título del bloque."""
    fila = next(i for i in range(min(40, len(df))) if str(df.iloc[i, 0]).strip().lower() == "mes")
    cab = df.iloc[max(0, fila - 6):fila + 1].astype(str)

    def col_total(clave: str) -> int:
        for c in range(df.shape[1]):
            if cab[c].str.upper().str.contains(clave, regex=False).any():
                return c + 2
        raise ValueError(f"Créditos BCU: no encuentro el bloque {clave!r}")
    c_tot, c_mn, c_me = col_total("TOTAL (MN + ME)"), col_total("MONEDA NACIONAL"), col_total("MONEDA EXTRANJERA")
    d = df.iloc[fila + 1:, [0, c_tot, c_mn, c_me]].copy()
    d.columns = ["fecha", "total", "mn", "me_usd"]
    d["fecha"] = pd.to_datetime(d["fecha"], errors="coerce")
    d = d.dropna(subset=["fecha"])
    for c in ["total", "mn", "me_usd"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["total", "mn"])
    d["fecha"] = d["fecha"] + pd.offsets.MonthEnd(0)
    d["me"] = d["total"] - d["mn"]          # moneda extranjera, en pesos
    return d.set_index("fecha")[["mn", "me", "total", "me_usd"]].sort_index()


def _bcu_hoja(url: str, key: str, offline: bool) -> pd.DataFrame:
    """Hoja 'Total Sist. Banc.' de un archivo de la SSF (depósitos o créditos):
    sector no financiero en MN y ME, millones de pesos."""
    from . import uruguay as uy

    path = SERIES_DIR / "uy" / f"{key}.csv"
    if not offline:
        try:
            hoja = pd.read_excel(io.BytesIO(uy._get(url).content), sheet_name=uy.DEPOSITOS_HOJA, header=None)
            d = parse_creditos_bcu(hoja) if key == "creditos" else uy.parse_depositos(hoja)[["mn", "me", "total"]]
            path.parent.mkdir(parents=True, exist_ok=True)
            d.to_csv(path, date_format="%Y-%m-%d")
        except Exception as exc:  # noqa: BLE001
            log.warning("BCU %s: %s; uso copia guardada", key, exc)
    if not path.exists():
        return pd.DataFrame(columns=["mn", "me", "total"])
    return pd.read_csv(path, parse_dates=["fecha"]).set_index("fecha")


def uruguay(offline: bool) -> dict:
    from . import uruguay as uy

    dep = _bcu_hoja(uy.DEPOSITOS_XLSX, "depositos", offline)
    cred = _bcu_hoja(BCU_CREDITOS_XLSX, "creditos", offline)
    tc = _tc_cache(config.DATA_DIR / "uy" / "series" / "tc.csv")
    fuente = "BCU, Superintendencia de Servicios Financieros"
    ind = {}
    desc = {}
    if not dep.empty:
        ind["depositos"] = indicador(ratio(dep["me"], dep["mn"]), "Dolarización de los depósitos del sector no financiero", "% en moneda extranjera", "mensual", fuente)
        if not tc.empty:
            me_usd = dep["me"] / tc.reindex(dep.index, method="ffill")
            ind["depositos_usd"] = indicador(me_usd, "Depósitos en moneda extranjera", "millones de USD", "mensual", fuente, 0)
            desc["depositos"] = _desc_pairs(descomponer(dep["mn"], me_usd, tc))
    if not cred.empty:
        ind["credito"] = indicador(ratio(cred["me"], cred["mn"]), "Dolarización del crédito al sector no financiero", "% en moneda extranjera", "mensual", fuente)
        if "me_usd" in cred:
            desc["credito"] = _desc_pairs(descomponer(cred["mn"], cred["me_usd"], (cred["me"] / cred["me_usd"]).dropna()))
    return {"frecuencia": "mensual", "indicadores": ind, "descomposicion": desc}


def parse_bis(texto: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(texto))
    if df.empty or "TIME_PERIOD" not in df:
        return pd.Series(dtype=float)
    mult = 10 ** int(df["UNIT_MULT"].iloc[0]) if "UNIT_MULT" in df else 1
    fechas = pd.PeriodIndex(df["TIME_PERIOD"].astype(str), freq="Q").to_timestamp(how="end").normalize()
    s = pd.Series(pd.to_numeric(df["OBS_VALUE"], errors="coerce").values * mult / 1e9, index=fechas)  # miles de millones de USD
    return s.sort_index().rename("ext")


def bis(pais: str, offline: bool) -> pd.Series:
    def fetch(desde, hasta):
        r = comun.get(BIS_URL.format(pais=BIS_PAISES[pais]))
        return parse_bis(r.text)
    s, _ = comun.actualizar(SERIES_DIR / pais, "depositos_exterior", fetch, "2000-01-01",
                            solapamiento_dias=100000, offline=offline)
    return s


# ---------------------------------------------------------------------------

def run(offline: bool = False) -> dict:
    builders = {"ar": argentina, "pe": peru, "uy": uruguay}
    resumen = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "paises": {}}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for k, nombre in NOMBRES.items():
        try:
            out = builders[k](offline) if k in builders else {"frecuencia": "trimestral", "indicadores": {}, "descomposicion": {}}
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: %s", nombre, exc)
            out = {"frecuencia": None, "indicadores": {}, "descomposicion": {}}
        try:
            ext = bis(k, offline)
            if not ext.empty:
                out["indicadores"]["exterior"] = indicador(
                    ext, "Depósitos de residentes no bancarios en bancos del exterior", "miles de millones de USD",
                    "trimestral", "BIS, estadísticas bancarias territoriales", 1)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s BIS: %s", nombre, exc)
        out.update({"codigo": k, "nombre": nombre, "nota": NOTAS.get(k),
                    "generated_at": resumen["generated_at"]})
        (DATA_DIR / f"{k}.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        resumen["paises"][k] = {
            "nombre": nombre, "frecuencia": out["frecuencia"], "nota": NOTAS.get(k),
            "ultimos": {i: {f: v[f] for f in ["label", "unidad", "frecuencia", "last", "last_date", "cambio_1m", "cambio_12m"]}
                        for i, v in out["indicadores"].items()},
            # Serie mensual de dolarización de depósitos, para comparar entre países.
            "depositos_mensual": _pairs(pd.Series({pd.Timestamp(d): v for d, v in out["indicadores"]["depositos"]["data"]})
                                        .resample("ME").last()) if "depositos" in out["indicadores"] else [],
            "exterior": out["indicadores"].get("exterior", {}).get("data", []),
        }
        ultimos = {i: v["last"] for i, v in out["indicadores"].items()}
        log.info("%s: %s", nombre, ultimos)
    (DATA_DIR / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return resumen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run(offline=parser.parse_args().offline)


if __name__ == "__main__":
    main()
