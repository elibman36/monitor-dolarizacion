"""Descarga de series desde las fuentes públicas.

Cada función devuelve una `pd.Series` indexada por fecha (DatetimeIndex,
nombre "fecha") o lanza una excepción; el orquestador decide qué hacer si una
fuente falla (usar la última copia guardada).
"""

from __future__ import annotations

import io
import logging
import os
import re
import time
from datetime import date

import pandas as pd
import requests

from . import config

log = logging.getLogger(__name__)

BCRA_BASES = [
    "https://api.bcra.gob.ar/estadisticas/v4.0/monetarias",
    "https://api.bcra.gob.ar/estadisticas/v3.0/monetarias",
]
ARGENTINADATOS_BASE = "https://api.argentinadatos.com/v1"
A3_CLOSING_PRICES = "https://apicem.matbarofex.com.ar/api/v2/closing-prices"
USER_AGENT = "monitor-dolarizacion/1.0 (+https://github.com/elibman36/monitor-dolarizacion)"

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})


def _bcra_verify() -> bool:
    # El certificado de api.bcra.gob.ar tuvo históricamente la cadena
    # incompleta. Sólo si falla en CI, se puede desactivar explícitamente con
    # BCRA_SSL_VERIFY=0 (afecta únicamente a las llamadas al BCRA).
    return os.environ.get("BCRA_SSL_VERIFY", "1") != "0"


def get_json(url: str, params: dict | None = None, verify: bool = True, retries: int = 4):
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, timeout=60, verify=verify)
            # Errores del cliente (salvo rate limit) no se reintentan.
            if 400 <= r.status_code < 500 and r.status_code != 429:
                r.raise_for_status()
            if r.status_code >= 400:
                raise requests.ConnectionError(f"HTTP {r.status_code} en {url}")
            return r.json()
        except (requests.ConnectionError, requests.Timeout, ValueError) as exc:
            last_exc = exc
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"No se pudo descargar {url}: {last_exc}")


def _to_series(records, date_key: str, value_key: str, name: str) -> pd.Series:
    df = pd.DataFrame(records)
    if df.empty:
        return pd.Series(dtype=float, name=name)
    s = pd.Series(
        pd.to_numeric(df[value_key], errors="coerce").values,
        index=pd.to_datetime(df[date_key]).dt.tz_localize(None).dt.normalize(),
        name=name,
    )
    s.index.name = "fecha"
    s = s.dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


# ---------------------------------------------------------------------------
# BCRA
# ---------------------------------------------------------------------------

def bcra_catalog() -> tuple[str, pd.DataFrame]:
    """Devuelve (base_url, catálogo de variables) de la primera versión que responda."""
    errors = []
    for base in BCRA_BASES:
        try:
            payload = get_json(base, params={"limit": 3000}, verify=_bcra_verify())
            df = pd.DataFrame(payload.get("results", []))
            if not df.empty and "idVariable" in df.columns:
                return base, df
        except Exception as exc:  # noqa: BLE001 - se prueba la siguiente versión
            errors.append(f"{base}: {exc}")
    raise RuntimeError("Catálogo BCRA no disponible. " + " | ".join(errors))


def resolve_bcra_ids(catalog: pd.DataFrame) -> dict[str, int]:
    desc_col = "descripcion" if "descripcion" in catalog.columns else catalog.columns[1]
    ids: dict[str, int] = {}
    for key, spec in config.BCRA_VARIABLES.items():
        if spec.get("id"):
            ids[key] = int(spec["id"])
            continue
        pattern = re.compile(spec["regex"], re.IGNORECASE)
        matches = catalog[catalog[desc_col].astype(str).str.contains(pattern)]
        if matches.empty:
            level = logging.INFO if spec.get("optional") else logging.WARNING
            log.log(level, "BCRA: no se encontró variable para %s (%s)", key, spec["regex"])
            continue
        # Ante varias coincidencias, la de ID más bajo suele ser la serie principal.
        row = matches.sort_values("idVariable").iloc[0]
        ids[key] = int(row["idVariable"])
        log.info("BCRA: %s -> id %s (%s)", key, ids[key], row[desc_col])
    return ids


def _parse_bcra_records(payload: dict) -> list[dict]:
    """Normaliza las respuestas v3 ({fecha, valor}) y v4 ({detalle: [...]})."""
    out: list[dict] = []
    for item in payload.get("results", []) or []:
        if isinstance(item, dict) and "detalle" in item:
            out.extend(item["detalle"] or [])
        else:
            out.append(item)
    return out


def bcra_series(base: str, var_id: int, name: str, start: str = config.START_DATE) -> pd.Series:
    limit = 3000
    records: list[dict] = []
    # Se pide por tramos anuales para no depender de la paginación.
    start_year = int(start[:4])
    for year in range(start_year, date.today().year + 1):
        desde = max(f"{year}-01-01", start)
        hasta = f"{year}-12-31"
        offset = 0
        while True:
            payload = get_json(
                f"{base}/{var_id}",
                params={"desde": desde, "hasta": hasta, "limit": limit, "offset": offset},
                verify=_bcra_verify(),
            )
            chunk = _parse_bcra_records(payload)
            records.extend(chunk)
            if len(chunk) < limit:
                break
            offset += limit
    return _to_series(records, "fecha", "valor", name)


# ---------------------------------------------------------------------------
# ArgentinaDatos
# ---------------------------------------------------------------------------

def argentinadatos_dolar(casa: str, name: str) -> pd.Series:
    payload = get_json(f"{ARGENTINADATOS_BASE}/cotizaciones/dolares/{casa}")
    # Se usa el precio de venta; si falta, el de compra.
    df = pd.DataFrame(payload)
    if df.empty:
        return pd.Series(dtype=float, name=name)
    df["valor"] = pd.to_numeric(df.get("venta"), errors="coerce")
    if "compra" in df.columns:
        df["valor"] = df["valor"].fillna(pd.to_numeric(df["compra"], errors="coerce"))
    s = _to_series(df.to_dict("records"), "fecha", "valor", name)
    return s[s.index >= config.START_DATE]


def argentinadatos_riesgo_pais(name: str = "riesgo_pais") -> pd.Series:
    payload = get_json(f"{ARGENTINADATOS_BASE}/finanzas/indices/riesgo-pais")
    s = _to_series(payload, "fecha", "valor", name)
    return s[s.index >= config.START_DATE]


# ---------------------------------------------------------------------------
# A3 Mercados (ex Matba-Rofex) - futuros de dólar
# ---------------------------------------------------------------------------

def _a3_expiry(symbol: str) -> pd.Timestamp | None:
    """DLR102026 -> último día hábil de octubre de 2026 (vencimiento de A3)."""
    m = re.fullmatch(r"DLR(\d{2})(\d{4})", symbol)
    if not m:
        return None
    month_start = pd.Timestamp(year=int(m.group(2)), month=int(m.group(1)), day=1)
    return month_start + pd.offsets.BMonthEnd(0)


def a3_futuros_dolar(desde: str, hasta: str | None = None) -> pd.DataFrame:
    """Precios de ajuste e interés abierto de los futuros mensuales de dólar.

    Devuelve una fila por fecha y contrato con las columnas que usa
    indicators.implied_devaluation(). La API pagina de a `pageSize` filas.
    """
    hasta = hasta or date.today().isoformat()
    rows: list[dict] = []
    for year in range(int(desde[:4]), int(hasta[:4]) + 1):
        a, b = max(desde, f"{year}-01-01"), min(hasta, f"{year}-12-31")
        if a > b:
            continue
        page = 1
        while True:
            payload = get_json(A3_CLOSING_PRICES, params={
                "product": "DLR", "segment": "Monedas", "type": "FUT",
                "excludeEmptyVol": "false", "from": a, "to": b,
                "page": page, "pageSize": 1000, "_ds": 1,
            })
            data = payload.get("data", []) or []
            for x in data:
                venc = _a3_expiry(str(x.get("symbol", "")))
                if venc is None:
                    continue
                rows.append({
                    "fecha": str(x["dateTime"])[:10],
                    "contrato": x["symbol"],
                    "vencimiento": venc.strftime("%Y-%m-%d"),
                    "precio_ajuste": x.get("settlement"),
                    "interes_abierto": x.get("openInterest"),
                    "volumen": x.get("volume"),
                    "tasa_implicita_a3": x.get("impliedRate"),
                })
            size = int(payload.get("pageSize") or len(data) or 1)
            total = int(payload.get("totalEntries") or 0)
            if not data or page * size >= total:
                break
            page += 1
            time.sleep(0.3)
    return pd.DataFrame(rows, columns=["fecha", "contrato", "vencimiento", "precio_ajuste",
                                       "interes_abierto", "volumen", "tasa_implicita_a3"])


# ---------------------------------------------------------------------------
# BCRA - Anexo del Informe de Evolución del Mercado de Cambios
# ---------------------------------------------------------------------------

def parse_compras_personas_humanas(datos: pd.DataFrame) -> pd.DataFrame:
    """Compras y ventas mensuales de billetes y divisas de personas humanas.

    `datos` es la hoja larga del anexo (Anexo, Mes, Sector, Monto, A, B, C, D),
    con montos en dólares: las compras de los clientes figuran con signo
    negativo (egresos del mercado) y las ventas con signo positivo. Se toma el
    rubro "Compra-venta de billetes y divisas sin fines específicos"
    (formación de activos externos) del sector personas humanas.
    """
    d = datos.copy()
    d.columns = [str(c).strip() for c in d.columns]
    d = d[d["Sector"].astype(str).str.strip().str.casefold() == config.BCRA_ANEXO_SECTOR.casefold()]
    d = d[d["B"].astype(str).str.contains(r"compra-venta de billetes y divisas", case=False, regex=True)]
    d["Monto"] = pd.to_numeric(d["Monto"], errors="coerce")
    d["fecha"] = pd.to_datetime(d["Mes"]).dt.strftime("%Y-%m")
    compras = d[d["C"].astype(str).str.contains(r"^\s*02- compra", case=False, regex=True)]
    ventas = d[d["C"].astype(str).str.contains(r"^\s*01- venta", case=False, regex=True)]
    out = pd.DataFrame({
        "compras_usd_millones": -compras.groupby("fecha")["Monto"].sum() / 1e6,
        "ventas_usd_millones": ventas.groupby("fecha")["Monto"].sum() / 1e6,
    }).fillna(0.0).round(2)
    out.index.name = "fecha"
    out["fuente"] = "BCRA, anexo del Informe de Evolución del Mercado de Cambios"
    return out.reset_index().sort_values("fecha")


def bcra_compras_personas_humanas() -> pd.DataFrame:
    r = _session.get(config.BCRA_ANEXO_CAMBIOS_URL, timeout=180, verify=_bcra_verify(),
                     headers={"Accept": "*/*"})
    r.raise_for_status()
    datos = pd.read_excel(io.BytesIO(r.content), sheet_name=config.BCRA_ANEXO_HOJA, engine="openpyxl")
    out = parse_compras_personas_humanas(datos)
    if out.empty:
        raise RuntimeError("el anexo no trae operaciones de personas humanas")
    return out


# ---------------------------------------------------------------------------
# Fuentes manuales (CSV local o URL publicada)
# ---------------------------------------------------------------------------

def manual_source(key: str) -> pd.DataFrame:
    spec = config.MANUAL_SOURCES[key]
    path = config.MANUAL_DIR / spec["file"]
    if spec.get("url"):
        try:
            r = _session.get(spec["url"], timeout=60)
            r.raise_for_status()
            pd.read_csv(io.StringIO(r.text))  # valida antes de sobreescribir
            path.write_text(r.text, encoding="utf-8")
            log.info("Fuente manual %s actualizada desde URL", key)
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudo actualizar %s desde URL (%s); uso copia local", key, exc)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, comment="#")
    return df.dropna(how="all")
