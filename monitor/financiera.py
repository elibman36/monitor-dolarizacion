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

from . import comun, config, sources, traspaso

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
BIS_PAISES = {"ar": "AR", "pe": "PE", "uy": "UY", "bo": "BO", "cr": "CR", "br": "BR", "cl": "CL", "co": "CO"}
NOMBRES = {"ar": "Argentina", "pe": "Perú", "uy": "Uruguay", "bo": "Bolivia", "cr": "Costa Rica",
           "br": "Brasil", "cl": "Chile", "co": "Colombia"}
NOTAS = {
    "bo": "Bolivia se desdolarizó con fuerza desde 2006 (bolivianización). La devaluación de 2026 subió la dolarización medida en bolivianos: la descomposición separa cuánto fue valuación y cuánto decisión de los ahorristas.",
    "cr": "Costa Rica no publica una serie abierta sin registro: se usan los indicadores de solidez financiera del FMI (bancos), mensuales y con varios meses de rezago. Los pasivos en moneda extranjera aproximan la dolarización de los depósitos.",
    "br": "En Brasil los residentes no pueden tener depósitos en dólares en el sistema local (salvo excepciones), así que la dolarización de los depósitos es prácticamente nula. Se muestran el crédito en moneda extranjera de los bancos (FMI) y los depósitos en bancos del exterior (BIS).",
    "co": "En Colombia los depósitos locales en moneda extranjera de residentes están muy restringidos: la dolarización local es baja por regulación. Se muestran el crédito y los pasivos en moneda extranjera de los bancos (FMI) y los depósitos en bancos del exterior (BIS).",
    "cl": "Chile permite depósitos en dólares, pero la serie del Banco Central requiere registro en su API. Mientras tanto se muestran el crédito en moneda extranjera de los bancos (FMI) y los depósitos en bancos del exterior (BIS).",
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
    # En series trimestrales, "1 mes" es el trimestre anterior.
    if len(s) > 2 and (s.index[-1] - s.index[-2]).days > 80 and dias < 80:
        dias = 85
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
    fae = fae_indicadores(raw["dep_usd"])
    return {
        "frecuencia": "diaria",
        "indicadores": {
            "depositos": indicador(dep, "Dolarización de los depósitos del sector privado", "% en dólares", "diaria", fuente),
            "credito": indicador(cred, "Dolarización del crédito al sector privado", "% en dólares", "diaria", fuente),
            "liquidez": indicador(liq, "Dolarización de la liquidez (circulante + depósitos privados)", "% en dólares", "diaria", fuente),
            "m3": indicador(m3, "Dolarización de M3 (serie larga)", "% en moneda extranjera", "mensual", "BCRA, agregados monetarios"),
            "depositos_usd": indicador(raw["dep_usd"], "Depósitos privados en dólares", "millones de USD", "diaria", fuente, 0),
            **fae,
        },
        "descomposicion": {
            "depositos": _desc_pairs(descomponer(raw["dep_pesos"], raw["dep_usd"], tc)),
            "credito": _desc_pairs(descomponer(raw["cred_pesos"], raw["cred_usd"], tc)),
        },
    }


def fae_indicadores(dep_usd: pd.Series) -> dict:
    """Compras netas de dólares de personas humanas (formación de activos
    externos, anexo del balance cambiario del BCRA): los dólares que la gente
    compra para atesorar. Comparadas con la variación de los depósitos en
    dólares, aproximan cuánto de lo comprado queda en los bancos y cuánto se va
    al colchón o al exterior."""
    path = config.SERIES_DIR / "compras_personas_humanas.csv"
    if not path.exists():
        return {}
    d = pd.read_csv(path, dtype={"fecha": str})
    s = pd.Series((d["compras_usd_millones"] - d["ventas_usd_millones"]).values,
                  index=pd.to_datetime(d["fecha"]) + pd.offsets.MonthEnd(0)).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s12 = s.rolling(12, min_periods=12).sum()
    acum = s.cumsum()
    dep_m = dep_usd.resample("ME").last()
    # Con compras chicas (cepo) o depósitos inflados por el blanqueo de 2024 el cociente no tiene sentido.
    queda = (dep_m.diff(12).reindex(s12.index) / s12 * 100).where(s12 > 5000)
    fuente = "BCRA, anexo del balance cambiario"
    return {
        "fae_mensual": indicador(s, "Compras netas de dólares de personas (FAE), por mes", "millones de USD", "mensual", fuente, 0),
        "fae_12m": indicador(s12, "Compras netas de dólares de personas, últimos 12 meses", "millones de USD", "mensual", fuente, 0),
        "fae_acum": indicador(acum, f"Compras netas de dólares de personas, acumulado desde {s.index[0].year}", "millones de USD", "mensual", fuente, 0),
        "fae_en_bancos": indicador(queda, "Parte de lo comprado en 12 meses que quedó en depósitos", "% de las compras", "mensual",
                                   "BCRA (anexo del balance cambiario y depósitos en dólares)", 1),
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


BCB_LISTADO = "https://www.bcb.gob.bo/?q=estad-sticas-semanales"


def _fila(df: pd.DataFrame, texto: str, desde: int = 0) -> int:
    etiquetas = df.iloc[:, 1:4].apply(lambda fila: " ".join("" if pd.isna(x) else str(x) for x in fila), axis=1).str.strip()
    for i in range(desde, len(df)):
        if etiquetas.iloc[i].lower().startswith(texto.lower()):
            return i
    raise ValueError(f"BCB: no encuentro la fila {texto!r}")


def parse_bcb_semanal(df: pd.DataFrame) -> pd.DataFrame:
    """Hoja 'Estadística Semanal' del BCB: una columna por fecha (anual desde
    1987, mensual y los últimos días hábiles) y una fila por variable."""
    fechas = []
    for c in range(df.shape[1]):
        f = None
        for fila in (3, 2):
            v = df.iloc[fila, c]
            if isinstance(v, (pd.Timestamp, datetime)) or (isinstance(v, str) and len(v) >= 10 and v[:4].isdigit()):
                f = pd.to_datetime(v, errors="coerce")
                if f is not pd.NaT and f is not None:
                    break
        fechas.append(f)
    cols = [c for c, f in enumerate(fechas) if f is not None and not pd.isna(f)]
    idx = pd.DatetimeIndex([fechas[c] for c in cols]).normalize()
    val = lambda fila: pd.Series(pd.to_numeric(df.iloc[fila, cols], errors="coerce").values, index=idx)  # noqa: E731
    dep = _fila(df, "Depósitos en entidades de intermediación financiera")
    cre = _fila(df, "Crédito del sistema financiero al sector privado")
    m3 = _fila(df, "M’3") if any("M’3" in str(x) for x in df.iloc[:, 1:4].values.ravel()) else _fila(df, "M'3")
    # Las filas de cada bloque: moneda nacional (USD), memo en Bs y moneda extranjera (USD).
    out = pd.DataFrame({
        "dep_mn_usd": val(dep + 1), "dep_mn_bs": val(dep + 2), "dep_me_usd": val(dep + 3),
        "cred_mn_usd": val(cre + 1), "cred_mn_bs": val(cre + 2), "cred_me_usd": val(cre + 3),
        "m3_mn_bs": val(m3 + 1), "m3_me_bs": val(m3 + 2),
    })
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.dropna(how="all")


def bolivia(offline: bool) -> dict:
    import re
    path = SERIES_DIR / "bo" / "bcb_semanal.csv"
    if not offline:
        try:
            html = comun.get(BCB_LISTADO, verify=False).text
            links = re.findall(r'href="([^"]*Semanal[^"]*?(\d+)_\s*(\d{4})[^"]*\.xlsx)"', html.replace("%20", " "))
            url = max(links, key=lambda x: (int(x[2]), int(x[1])))[0].replace(" ", "%20")
            df = pd.read_excel(io.BytesIO(comun.get(url if url.startswith("http") else "https://www.bcb.gob.bo" + url, verify=False).content), header=None)
            nuevo = parse_bcb_semanal(df)
            viejo = pd.read_csv(path, parse_dates=["fecha"]).set_index("fecha") if path.exists() else pd.DataFrame()
            d = nuevo.combine_first(viejo) if not viejo.empty else nuevo
            path.parent.mkdir(parents=True, exist_ok=True)
            d.rename_axis("fecha").to_csv(path, date_format="%Y-%m-%d", float_format="%.6g")
        except Exception as exc:  # noqa: BLE001
            log.warning("BCB: %s; uso copia guardada", exc)
    if not path.exists():
        return {"frecuencia": "diaria", "indicadores": {}, "descomposicion": {}}
    d = pd.read_csv(path, parse_dates=["fecha"]).set_index("fecha")
    tc = (d["dep_mn_bs"] / d["dep_mn_usd"]).dropna()
    fuente = "BCB, información estadística semanal"
    return {
        "frecuencia": "diaria",
        "indicadores": {
            "depositos": indicador(ratio(d["dep_me_usd"], d["dep_mn_usd"]), "Dolarización de los depósitos (100 − bolivianización)", "% en moneda extranjera", "diaria", fuente),
            "credito": indicador(ratio(d["cred_me_usd"], d["cred_mn_usd"]), "Dolarización del crédito al sector privado", "% en moneda extranjera", "diaria", fuente),
            "liquidez": indicador(ratio(d["m3_me_bs"], d["m3_mn_bs"]), "Dolarización de la liquidez (M'3)", "% en moneda extranjera", "diaria", fuente),
            "depositos_usd": indicador(d["dep_me_usd"], "Depósitos en moneda extranjera", "millones de USD", "diaria", fuente, 0),
        },
        "descomposicion": {
            "depositos": _desc_pairs(descomponer(d["dep_mn_bs"], d["dep_me_usd"], tc)),
            "credito": _desc_pairs(descomponer(d["cred_mn_bs"], d["cred_me_usd"], tc)),
        },
    }


IMF_URL = "https://api.imf.org/external/sdmx/2.1/data/IMF.STA,FSIC/{iso3}..?startPeriod=2005"
IMF_ISO3 = {"ar": "ARG", "pe": "PER", "uy": "URY", "bo": "BOL", "cr": "CRI", "br": "BRA", "cl": "CHL", "co": "COL"}
IMF_FSI = {
    "credito_fmi": ("FSI131_AFSI_PT", "Crédito en moneda extranjera de los bancos (FMI)"),
    "pasivos_fmi": ("FSI680_AFSI_PT", "Pasivos en moneda extranjera de los bancos (FMI)"),
}


def parse_imf_fsi(texto: str, indicador: str) -> pd.Series:
    """Serie de un indicador de solidez financiera del FMI (bancos, sector
    S12CFSI): mensual si la hay, si no trimestral."""
    df = pd.read_csv(io.StringIO(texto), low_memory=False)
    if df.empty or "INDICATOR" not in df:
        return pd.Series(dtype=float)
    df = df[(df["INDICATOR"] == indicador) & (df.get("SECTOR", "S12CFSI") == "S12CFSI")]
    for freq, fmt in [("M", "M"), ("Q", "Q")]:
        x = df[df["FREQUENCY"] == freq]
        if not x.empty:
            per = pd.PeriodIndex(x["TIME_PERIOD"].astype(str).str.replace(f"-{fmt}", "-" + ("" if fmt == "M" else "Q"), regex=False), freq=fmt)
            s = pd.Series(pd.to_numeric(x["OBS_VALUE"], errors="coerce").values,
                          index=per.to_timestamp(how="end").normalize())
            return s.sort_index().dropna()
    return pd.Series(dtype=float)


def imf(pais: str, offline: bool) -> dict:
    """Crédito y pasivos en moneda extranjera de los bancos (FMI, FSI)."""
    cache = {}

    def texto():
        if "t" not in cache:
            cache["t"] = comun.get(IMF_URL.format(iso3=IMF_ISO3[pais]),
                                   headers={"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"}).text
        return cache["t"]
    out = {}
    for key, (cod, label) in IMF_FSI.items():
        s, _ = comun.actualizar(SERIES_DIR / pais, key, lambda d, h, cod=cod: parse_imf_fsi(texto(), cod),
                                "2005-01-01", solapamiento_dias=100000, offline=offline)
        if not s.empty:
            out[key] = s
    return out


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
# Traspaso del tipo de cambio a precios (dolarización de la unidad de cuenta)
# ---------------------------------------------------------------------------

BIS_CPI_URL = "https://stats.bis.org/api/v1/data/WS_LONG_CPI/M.{pais}.628?format=csv&startPeriod=1990-01"
BIS_XRU_URL = "https://stats.bis.org/api/v1/data/WS_XRU/M.{pais}..A?format=csv&startPeriod=1990-01"
IMF_CPI_URL = "https://api.imf.org/external/sdmx/2.1/data/IMF.STA,CPI/{iso3}.CPI._T.IX.M?startPeriod=1990"
COMMODITIES_URL = "https://api.imf.org/external/sdmx/2.1/data/IMF.RES,PCPS/G001.PALLFNF.INDEX.M?startPeriod=1990"
SGS_IPCA_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados?formato=json&dataInicial=01/01/1990"
# De dónde sale el IPC de cada país (el BIS no publica Uruguay, Bolivia ni Costa Rica).
FUENTE_IPC = {"ar": "BCRA, INDEC", "br": "IPCA, BCB-SGS", "pe": "BIS", "cl": "BIS", "co": "BIS",
              "uy": "FMI", "bo": "FMI", "cr": "FMI"}
# Cambios de régimen cambiario: la ventana de 36 meses que los cruza mezcla dos regímenes.
QUIEBRES = {
    "ar": [("2002-01-31", "Fin de la convertibilidad"), ("2011-10-31", "Cepo"), ("2015-12-31", "Unificación"),
           ("2019-09-30", "Vuelve el cepo"), ("2025-04-30", "Fin del cepo")],
    "br": [("1994-07-31", "Plan Real"), ("1999-01-31", "Flotación")],
    "cl": [("1999-09-30", "Flotación")],
    "co": [("1999-09-30", "Flotación")],
    "uy": [("2002-06-30", "Flotación")],
    "cr": [("2006-10-31", "Bandas cambiarias"), ("2015-02-28", "Flotación administrada")],
    "bo": [("2026-06-30", "Devaluación")],
}
NOTAS_TRASPASO = {
    "uy": "IPC del FMI (INE). Uruguay tiene precios de inmuebles y autos fijados en dólares: ahí el traspaso es completo, pero esos bienes pesan poco en el IPC.",
    "ar": "Con el dólar paralelo: blue entre 2011 y 2012 y contado con liquidación desde 2013, que es el precio marginal del dólar en los años de cepo; fuera del cepo coincide casi con el oficial. IPC: inflación mensual de la API del BCRA (INDEC); entre 2007 y 2015 el IPC oficial subestimó la inflación.",
    "bo": "Bolivia tuvo tipo de cambio fijo hasta la devaluación de 2026: sin movimientos del tipo de cambio el traspaso no está identificado, y todavía no hay meses suficientes después del salto.",
}


def _bis_mensual(url: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(comun.get(url).text))
    if df.empty or "TIME_PERIOD" not in df:
        return pd.Series(dtype=float)
    idx = pd.PeriodIndex(df["TIME_PERIOD"].astype(str), freq="M").to_timestamp(how="end").normalize()
    return pd.Series(pd.to_numeric(df["OBS_VALUE"], errors="coerce").values, index=idx).sort_index().dropna()


def parse_imf_mensual(texto: str) -> pd.Series:
    """Serie mensual de la API SDMX del FMI en CSV (TIME_PERIOD = 2026-M08)."""
    df = pd.read_csv(io.StringIO(texto), low_memory=False)
    if df.empty or "TIME_PERIOD" not in df:
        return pd.Series(dtype=float)
    per = pd.PeriodIndex(df["TIME_PERIOD"].astype(str).str.replace("-M", "-", regex=False), freq="M")
    s = pd.Series(pd.to_numeric(df["OBS_VALUE"], errors="coerce").values, index=per.to_timestamp(how="end").normalize())
    return s[~s.index.duplicated(keep="last")].sort_index().dropna()


def _imf_mensual(url: str) -> pd.Series:
    return parse_imf_mensual(comun.get(url, headers={"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"}).text)


def _sgs_variacion(url: str) -> pd.Series:
    d = pd.DataFrame(comun.get(url).json())
    return pd.Series(pd.to_numeric(d["valor"], errors="coerce").values,
                     index=pd.to_datetime(d["data"], dayfirst=True) + pd.offsets.MonthEnd(0)).dropna()


def ipc_mensual(pais: str, offline: bool) -> pd.Series:
    """Inflación mensual del IPC (%, variación logarítmica)."""
    if pais == "ar":
        # Inflación mensual de la API del BCRA (INDEC), desde 1943: se arma un índice encadenado.
        base = None
        if not offline:
            try:
                base, _ = sources.bcra_catalog()
            except Exception as exc:  # noqa: BLE001
                log.warning("BCRA no disponible (%s)", exc)
        s = _bcra(base, 27, "inflacion_mensual", offline)
        s = s.resample("ME").last().dropna()
        return (np.log1p(s / 100) * 100)["1990":]
    if pais == "br":
        s, _ = comun.actualizar(SERIES_DIR / pais, "ipca_mensual", lambda d, h: _sgs_variacion(SGS_IPCA_URL),
                                "1990-01-01", solapamiento_dias=100000, offline=offline)
        return np.log1p(s / 100) * 100
    if FUENTE_IPC[pais] == "FMI":
        fetch = lambda d, h: _imf_mensual(IMF_CPI_URL.format(iso3=IMF_ISO3[pais]))  # noqa: E731
    else:
        fetch = lambda d, h: _bis_mensual(BIS_CPI_URL.format(pais=BIS_PAISES[pais]))  # noqa: E731
    lvl, _ = comun.actualizar(SERIES_DIR / pais, "ipc", fetch, "1990-01-01", solapamiento_dias=100000, offline=offline)
    return traspaso.variacion(lvl.resample("ME").last())


def tc_mensual(pais: str, offline: bool) -> pd.Series:
    """Tipo de cambio promedio del mes (moneda local por dólar)."""
    s, _ = comun.actualizar(SERIES_DIR / pais, "tc_mensual", lambda d, h: _bis_mensual(BIS_XRU_URL.format(pais=BIS_PAISES[pais])),
                            "1990-01-01", solapamiento_dias=100000, offline=offline)
    if pais == "bo":
        # El BIS llega con atraso para Bolivia: se encadena el tipo de cambio
        # implícito en la estadística semanal del BCB (Bs por USD de los depósitos).
        path = SERIES_DIR / "bo" / "bcb_semanal.csv"
        if path.exists() and not s.empty:
            d = pd.read_csv(path, parse_dates=["fecha"]).set_index("fecha")
            bcb = traspaso.mensual_promedio((d["dep_mn_bs"] / d["dep_mn_usd"]).dropna())
            s = encadenar(s, bcb)
    return s


def encadenar(base: pd.Series, nueva: pd.Series) -> pd.Series:
    """Extiende `base` con las variaciones de `nueva` después de su último dato."""
    base = base.dropna()
    nueva = nueva.dropna()
    ult = base.index.max()
    if nueva.empty or ult not in nueva.index or nueva.index.max() <= ult:
        return base
    ext = nueva[nueva.index > ult] / nueva[ult] * base[ult]
    return pd.concat([base, ext]).sort_index()


def tc_paralelo_ar() -> pd.Series:
    """Dólar libre de Argentina: blue (2011-2012) y CCL (2013 en adelante),
    promedio del mes."""
    blue = traspaso.mensual_promedio(_tc_cache(config.SERIES_DIR / "usd_blue.csv"))
    ccl = traspaso.mensual_promedio(_tc_cache(config.SERIES_DIR / "usd_ccl.csv"))
    return ccl.combine_first(blue)


def commodities(offline: bool) -> pd.Series:
    """Inflación de las materias primas en dólares (índice de precios del FMI), %."""
    s, _ = comun.actualizar(SERIES_DIR, "commodities", lambda d, h: _imf_mensual(COMMODITIES_URL), "1990-01-01",
                            solapamiento_dias=100000, offline=offline)
    return traspaso.variacion(s) if not s.empty else s


def _traspaso_pairs(r: pd.DataFrame) -> list:
    out = []
    for d, x in r.iterrows():
        if x.sin_dato or pd.isna(x.suma):
            out.append([d.strftime("%Y-%m-%d"), None, None, None])
        else:
            out.append([d.strftime("%Y-%m-%d"), round(x.suma * 100, 1), round((x.suma - 1.96 * x.se) * 100, 1),
                        round((x.suma + 1.96 * x.se) * 100, 1)])
    return out


def traspaso_pais(pais: str, offline: bool, ext: pd.Series | None) -> tuple[dict | None, pd.Series | None]:
    """Regresiones móviles por país. Devuelve el bloque para el JSON y la serie
    principal (en %) para el tablero y la comparación."""
    pi = ipc_mensual(pais, offline)
    tc = tc_mensual(pais, offline)
    if pi.empty or tc.empty:
        return None, None
    pi = traspaso.desestacionalizar(pi)
    variantes = [("oficial", "Tipo de cambio oficial", tc)]
    if pais == "ar":
        par = tc_paralelo_ar()
        # Antes del blue, el paralelo es el oficial.
        par = par.combine_first(tc[tc.index < par.index.min()]) if not par.empty else tc
        variantes = [("paralelo", "Con el dólar paralelo (blue / CCL)", par), ("oficial", "Con el tipo de cambio oficial", tc)]
    bloques = []
    principal = None
    for clave, label, e in variantes:
        dep = traspaso.variacion(e)
        r = traspaso.movil(pi, dep, ext)
        if r.empty:
            continue
        jorda = traspaso.lp_movil(pi, dep)
        bloques.append({"clave": clave, "label": label, "data": _traspaso_pairs(r),
                        "largo_plazo": [[d.strftime("%Y-%m-%d"), round(x.lp * 100, 1)] for d, x in r.iterrows() if pd.notna(x.lp)],
                        "jorda": [[d.strftime("%Y-%m-%d"), round(v * 100, 1)] for d, v in jorda.items()]})
        if principal is None:
            principal = (r.suma * 100).where(~r.sin_dato.astype(bool))
    if not bloques:
        return None, None
    quiebres = [[f, t, (pd.Timestamp(f) + pd.DateOffset(months=traspaso.VENTANA) + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")]
                for f, t in QUIEBRES.get(pais, [])]
    return {
        "ventana": traspaso.VENTANA, "rezagos": traspaso.REZAGOS, "principal": bloques[0]["clave"],
        "variantes": bloques, "quiebres": quiebres, "nota": NOTAS_TRASPASO.get(pais),
        "control_externo": "inflación de materias primas (FMI)" if ext is not None and not ext.empty else None,
    }, principal


def _mensual(ind: dict, claves: list[str]) -> dict:
    """Serie mensual del primer indicador disponible (y cuál se usó)."""
    for k in claves:
        if k in ind and ind[k]["data"]:
            s = pd.Series({pd.Timestamp(d): v for d, v in ind[k]["data"]}).resample("ME").last()
            return {"fuente": k, "data": _pairs(s)}
    return {"fuente": None, "data": []}


def run(offline: bool = False) -> dict:
    builders = {"ar": argentina, "pe": peru, "uy": uruguay, "bo": bolivia}
    resumen = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "paises": {}}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        materias = commodities(offline)
    except Exception as exc:  # noqa: BLE001
        log.warning("materias primas: %s", exc)
        materias = None
    for k, nombre in NOMBRES.items():
        try:
            out = builders[k](offline) if k in builders else {"frecuencia": "trimestral", "indicadores": {}, "descomposicion": {}}
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: %s", nombre, exc)
            out = {"frecuencia": None, "indicadores": {}, "descomposicion": {}}
        # Donde no hay serie local, los indicadores de solidez financiera del FMI.
        if k in ("cr", "br", "cl", "co"):
            try:
                for key, s in imf(k, offline).items():
                    out["indicadores"][key] = indicador(s, IMF_FSI[key][1], "% en moneda extranjera", "mensual" if (s.index[-1] - s.index[-2]).days < 40 else "trimestral",
                                                        "FMI, indicadores de solidez financiera (bancos)")
                if out["indicadores"]:
                    out["frecuencia"] = out["indicadores"][next(iter(out["indicadores"]))]["frecuencia"]
            except Exception as exc:  # noqa: BLE001
                log.warning("%s FMI: %s", nombre, exc)
        try:
            ext = bis(k, offline)
            if not ext.empty:
                out["indicadores"]["exterior"] = indicador(
                    ext, "Depósitos de residentes no bancarios en bancos del exterior", "miles de millones de USD",
                    "trimestral", "BIS, estadísticas bancarias territoriales", 1)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s BIS: %s", nombre, exc)
        principal = None
        try:
            tr, principal = traspaso_pais(k, offline, materias)
            if tr:
                out["traspaso"] = tr
                ultimo = principal.dropna()
                if not ultimo.empty:
                    out["indicadores"]["traspaso"] = indicador(
                        principal, "Traspaso del tipo de cambio a precios (7 meses)", "% de la depreciación", "mensual",
                        f"Cálculo propio con el IPC (" + FUENTE_IPC[k] + ") y el tipo de cambio " + ("paralelo" if k == "ar" else "del BIS"), 1)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s traspaso: %s", nombre, exc)
        out.update({"codigo": k, "nombre": nombre, "nota": NOTAS.get(k),
                    "generated_at": resumen["generated_at"]})
        (DATA_DIR / f"{k}.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        resumen["paises"][k] = {
            "nombre": nombre, "frecuencia": out["frecuencia"], "nota": NOTAS.get(k),
            "ultimos": {i: {f: v[f] for f in ["label", "unidad", "frecuencia", "last", "last_date", "cambio_1m", "cambio_12m"]}
                        for i, v in out["indicadores"].items()},
            # Serie mensual de dolarización de depósitos, para comparar entre países.
            "depositos_mensual": _mensual(out["indicadores"], ["depositos", "pasivos_fmi"]),
            "credito_mensual": _mensual(out["indicadores"], ["credito", "credito_fmi"]),
            "exterior": out["indicadores"].get("exterior", {}).get("data", []),
            "traspaso_mensual": [] if principal is None else [[d.strftime("%Y-%m-%d"), None if pd.isna(v) else round(float(v), 1)]
                                                              for d, v in principal.items()],
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
