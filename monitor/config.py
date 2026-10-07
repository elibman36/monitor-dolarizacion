"""Configuración del Monitor de Dolarización de Portafolios.

Todo lo que un analista podría querer ajustar (fuentes, componentes del índice,
pesos, ventanas, umbrales y eventos a marcar) vive en este archivo.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SERIES_DIR = DATA_DIR / "series"
MANUAL_DIR = DATA_DIR / "manual"
OUTPUT_JSON = DATA_DIR / "monitor.json"

# Primer día que se descarga y se publica.
START_DATE = "2019-01-01"

# ---------------------------------------------------------------------------
# Fuentes diarias automáticas
# ---------------------------------------------------------------------------
# BCRA - API de Estadísticas Monetarias (v4, con fallback a v3).
# IDs verificados contra el catálogo de la API v4 (oct-2026). Si `id` es None,
# la variable se busca con la regex sobre su descripción. El catálogo completo
# queda en data/bcra_catalogo.csv después de cada corrida.
BCRA_VARIABLES = {
    "reservas": {
        "id": 1,
        "regex": r"reservas internacionales",
        "label": "Reservas internacionales brutas",
        "unit": "millones de USD",
    },
    "tc_a3500": {
        "id": 5,
        "regex": r"tipo de cambio mayorista de referencia",
        "label": "Tipo de cambio mayorista (Com. A3500)",
        "unit": "$ por USD",
    },
    "badlar": {
        "id": 7,
        "regex": r"badlar.*privados",
        "label": "Tasa BADLAR bancos privados (n.a.)",
        "unit": "% n.a.",
    },
    "tamar": {
        "id": 44,
        "regex": r"tamar.*privados",
        "label": "Tasa TAMAR bancos privados",
        "unit": "% n.a.",
        "optional": True,
    },
    "depositos_usd": {
        "id": 108,
        "regex": r"dep[oó]sitos.*(?:d[oó]lares|moneda extranjera)",
        "label": "Depósitos en dólares del sector privado",
        "unit": "millones de USD",
        "optional": True,
    },
}

# ArgentinaDatos (https://argentinadatos.com) - cotizaciones y riesgo país.
ARGENTINADATOS_DOLARES = {
    "usd_oficial": {"casa": "oficial", "label": "Dólar oficial minorista"},
    "usd_mayorista": {"casa": "mayorista", "label": "Dólar mayorista"},
    "usd_mep": {"casa": "bolsa", "label": "Dólar MEP"},
    "usd_ccl": {"casa": "contadoconliqui", "label": "Dólar CCL"},
    "usd_blue": {"casa": "blue", "label": "Dólar blue"},
}
ARGENTINADATOS_RIESGO_PAIS = {"label": "Riesgo país (EMBI Argentina)", "unit": "pb"}

# ---------------------------------------------------------------------------
# Fuentes manuales / semiautomáticas
# ---------------------------------------------------------------------------
# Cada fuente es un CSV en data/manual/. Si se define `url` (por ejemplo, una
# Google Sheet publicada como CSV), el pipeline la descarga primero y
# sobreescribe el archivo local; si falla, usa la última copia local.
MANUAL_SOURCES = {
    "futuros_dolar": {
        "file": "futuros_dolar.csv",
        "url": None,
        "freq": "diaria",
        "fuente": "A3 Mercados - precios de ajuste e interés abierto de futuros DLR",
    },
    "compras_personas_humanas": {
        "file": "compras_personas_humanas.csv",
        "url": None,
        "freq": "mensual",
        "fuente": "BCRA - Informe de Evolución del Mercado de Cambios y Balance Cambiario",
    },
    "licitaciones_tesoro": {
        "file": "licitaciones_tesoro.csv",
        "url": None,
        "freq": "por licitación",
        "fuente": "Secretaría de Finanzas - resultados de licitaciones",
    },
}

# Plazo mínimo (días corridos) del contrato de futuros usado para la
# devaluación implícita: se toma el primer vencimiento con al menos este plazo.
FUTUROS_PLAZO_MINIMO_DIAS = 20

# ---------------------------------------------------------------------------
# Índice de Presión de Dolarización (IPD)
# ---------------------------------------------------------------------------
# Inspirado en el Exchange Market Pressure Index (Girton-Roper 1977;
# Eichengreen-Rose-Wyplosz 1996): cada componente se transforma de forma que
# un valor más alto = más presión, se estandariza (z-score móvil) y se
# promedia. Los z-scores son la versión "precision-weighted" del EMP clásico.
#
# transform:
#   dlog  -> variación logarítmica en `horizon` días hábiles (x100)
#   diff  -> diferencia simple en `horizon` días hábiles
#   level -> nivel de la serie
# sign: +1 si un aumento implica más presión, -1 si implica menos.
IPD_HORIZON = 5            # días hábiles para variaciones (≈ 1 semana)
IPD_ZSCORE_WINDOW = 504    # ventana móvil para estandarizar (≈ 2 años)
IPD_ZSCORE_MIN_OBS = 120   # mínimo de observaciones para calcular el z-score
IPD_Z_CLIP = 4.0           # recorte de outliers
IPD_MIN_WEIGHT_SHARE = 0.5 # peso mínimo disponible para publicar el índice

IPD_BLOCKS = {
    "emp": {
        "label": "Presión cambiaria (EMP)",
        "weight": 0.5,
        "components": {
            "tc_a3500":  {"transform": "dlog",  "sign": +1, "weight": 1.0,
                          "label": "Depreciación del oficial"},
            "reservas":  {"transform": "dlog",  "sign": -1, "weight": 1.0,
                          "label": "Pérdida de reservas"},
            "tasa":      {"transform": "diff",  "sign": +1, "weight": 1.0,
                          "label": "Suba de tasas (defensa del peso)"},
        },
    },
    "portafolio": {
        "label": "Dolarización de portafolios y expectativas",
        "weight": 0.5,
        "components": {
            "brecha_ccl":  {"transform": "level", "sign": +1, "weight": 1.0,
                            "label": "Brecha CCL / oficial"},
            "riesgo_pais": {"transform": "diff",  "sign": +1, "weight": 1.0,
                            "label": "Suba del riesgo país"},
            "deval_implicita": {"transform": "level", "sign": +1, "weight": 1.0,
                                "label": "Devaluación implícita en futuros"},
            "depositos_usd": {"transform": "dlog", "sign": +1, "weight": 0.5,
                              "label": "Suba de depósitos en USD"},
        },
    },
}

# Semáforo: percentil del IPD dentro de su propia historia (ventana móvil).
IPD_PERCENTILE_WINDOW = 504
IPD_STATUS = [
    # (percentil mínimo, clave, etiqueta)
    (97.5, "critical", "Presión crítica"),
    (90.0, "serious", "Presión elevada"),
    (75.0, "warning", "Presión moderada"),
    (0.0, "good", "Presión baja"),
]

# ---------------------------------------------------------------------------
# Eventos a marcar en los gráficos
# ---------------------------------------------------------------------------
EVENTS = [
    {"date": "2019-08-11", "label": "PASO 2019"},
    {"date": "2019-10-27", "label": "Generales 2019"},
    {"date": "2021-09-12", "label": "PASO 2021"},
    {"date": "2021-11-14", "label": "Legislativas 2021"},
    {"date": "2023-08-13", "label": "PASO 2023"},
    {"date": "2023-10-22", "label": "Generales 2023"},
    {"date": "2023-11-19", "label": "Balotaje 2023"},
    {"date": "2023-12-13", "label": "Devaluación dic-23"},
    {"date": "2025-04-14", "label": "Bandas cambiarias / fin cepo PH"},
    {"date": "2025-09-07", "label": "Elecciones PBA 2025"},
    {"date": "2025-10-26", "label": "Legislativas 2025"},
    # Calendario 2027 a confirmar por la Cámara Nacional Electoral.
    {"date": "2027-10-24", "label": "Generales 2027 (a confirmar)"},
]
