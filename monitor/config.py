"""Configuración del Monitor de Dolarización de Portafolios.

Todo lo que un analista podría querer ajustar (fuentes, componentes del índice,
pesos, ventanas, umbrales y eventos a marcar) vive en este archivo.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SERIES_DIR = DATA_DIR / "series"
OUTPUT_JSON = DATA_DIR / "monitor.json"

# Primer día que se descarga y se publica. Cada serie arranca cuando su fuente
# tiene datos (reservas: 1996; BADLAR: 1999; A3500: 2002; CCL, MEP y futuros,
# más tarde). Si faltan componentes, el IPD se calcula con los disponibles.
START_DATE = "1996-01-01"

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
# Futuros de dólar (A3 Mercados) y anexo cambiario del BCRA
# ---------------------------------------------------------------------------
# Primer día que se pide a la API de A3 (antes de 2020 no devuelve datos).
FUTUROS_START_DATE = "2020-01-01"

# Anexo estadístico del Informe de Evolución del Mercado de Cambios (BCRA):
# hoja larga con operaciones mensuales por sector y concepto desde 2003.
BCRA_ANEXO_CAMBIOS_URL = ("https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/"
                          "informes/anexo-estadistico-mercado-cambios-balance-cambiario.xlsx")
BCRA_ANEXO_HOJA = "Datos Mercado de Cambios"
BCRA_ANEXO_SECTOR = "Personas Humanas"
BCRA_ANEXO_DIAS_ENTRE_DESCARGAS = 7  # el anexo se actualiza una vez por mes

# Devaluación implícita: TNA de los futuros interpolada a un plazo constante.
# Se descartan contratos con menos de FUTUROS_PLAZO_MINIMO_DIAS (muy ruidosos).
FUTUROS_PLAZO_CONSTANTE_DIAS = 90
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
# Primer día que se publica el IPD. Antes de 2003 la serie no es confiable:
# con la convertibilidad el tipo de cambio no se movía (faltan dos
# componentes), la BADLAR oscilaba 20-45 pp por semana y el corralito la
# desplomó, y hay huecos en los datos de dic-01 a feb-02. Esos años se usan
# sólo como ventana de referencia para estandarizar.
IPD_PUBLICAR_DESDE = "2003-01-01"
IPD_HORIZON = 5            # días hábiles para variaciones (≈ 1 semana)
IPD_ZSCORE_WINDOW = 504    # ventana móvil para estandarizar (≈ 2 años)
IPD_ZSCORE_MIN_OBS = 120   # mínimo de observaciones para calcular el z-score
IPD_Z_CLIP = 4.0           # recorte de outliers
# Estandarización: "robusto" usa mediana y MAD (desvío absoluto mediano x 1,4826)
# de la ventana; "clasico", media y desvío estándar. La robusta evita que un
# episodio extremo (p. ej. la devaluación de dic-23) infle la escala durante
# dos años y haga parecer chicos los movimientos siguientes.
IPD_ZSCORE_METODO = "robusto"
# Volatilidad cambiaria: desvío de las variaciones diarias en esta ventana
# (días hábiles), anualizado.
IPD_VOL_VENTANA = 20
IPD_MIN_WEIGHT_SHARE = 0.4 # peso mínimo disponible para publicar el índice

# Ponderación de los componentes dentro de cada bloque:
#   "pca"  -> cargas del primer componente principal de los promedios mensuales
#             de los z-scores del bloque (cargas negativas = 0). Se recalculan en
#             cada corrida con toda la historia publicada.
#   "fija" -> los `weight` de abajo.
# Los bloques pesan siempre según su propio `weight` (50% / 50%).
IPD_PONDERACION = "pca"
IPD_PCA_FRECUENCIA = "ME"
IPD_PCA_MIN_OBS = 24        # meses mínimos en común entre dos componentes
# Peso mínimo de cada componente dentro de su bloque: ninguno queda afuera
# aunque la PCA le asigne carga nula o negativa (p. ej. riesgo país).
IPD_PCA_PESO_MINIMO = 0.10

IPD_BLOCKS = {
    "emp": {
        "label": "Presión cambiaria (EMP)",
        "weight": 0.5,
        "components": {
            "tc_a3500":  {"transform": "dlog",  "sign": +1, "weight": 1.0,
                          "label": "Depreciación del oficial"},
            "vol_oficial": {"transform": "level", "sign": +1, "weight": 1.0,
                            "label": "Volatilidad del oficial"},
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
            "vol_ccl":     {"transform": "level", "sign": +1, "weight": 1.0,
                            "label": "Volatilidad del CCL"},
            "riesgo_pais": {"transform": "diff",  "sign": +1, "weight": 1.0,
                            "label": "Suba del riesgo país"},
            "deval_implicita": {"transform": "level", "sign": +1, "weight": 1.0,
                                "label": "Devaluación implícita en futuros"},
            "depositos_usd": {"transform": "dlog", "sign": +1, "weight": 0.5,
                              "label": "Suba de depósitos en USD"},
        },
    },
}

# Percentil del IPD dentro de su propia historia reciente (dato complementario).
IPD_PERCENTILE_WINDOW = 504

# Índice 0-100: 100 * Φ(IPD suavizado / σ), con Φ la normal acumulada y σ el
# desvío histórico del IPD suavizado. 50 = neutral; < 50 presión apreciatoria
# (alivio); > 50 presión depreciatoria. Se suaviza con un promedio de
# INDICE_SUAVIZADO días hábiles para que el titular no salte día a día.
INDICE_SUAVIZADO = 10
INDICE_SIGMA = None  # None = desvío histórico calculado en cada corrida
INDICE_TRAMOS = [
    # (desde, hasta, clave, etiqueta) - escala divergente, de azul a rojo
    (0, 10, "aprec_fuerte", "Fuerte presión apreciatoria"),
    (10, 35, "aprec", "Presión apreciatoria"),
    (35, 65, "neutral", "Neutral"),
    (65, 90, "deprec", "Presión depreciatoria"),
    (90, 100.0001, "deprec_fuerte", "Fuerte presión depreciatoria"),
]

# ---------------------------------------------------------------------------
# Eventos a marcar en los gráficos
# ---------------------------------------------------------------------------
# tipo "cambiario" se rotula siempre; "electoral", sólo en rangos de hasta 6 años.
EVENTS = [
    {"date": "1999-10-24", "label": "Generales 1999", "tipo": "electoral"},
    {"date": "2001-10-14", "label": "Legislativas 2001", "tipo": "electoral"},
    {"date": "2001-12-03", "label": "Corralito", "tipo": "cambiario"},
    {"date": "2002-01-06", "label": "Fin de la convertibilidad", "tipo": "cambiario"},
    {"date": "2003-04-27", "label": "Generales 2003", "tipo": "electoral"},
    {"date": "2005-10-23", "label": "Legislativas 2005", "tipo": "electoral"},
    {"date": "2007-10-28", "label": "Generales 2007", "tipo": "electoral"},
    {"date": "2008-09-15", "label": "Quiebra de Lehman", "tipo": "cambiario"},
    {"date": "2009-06-28", "label": "Legislativas 2009", "tipo": "electoral"},
    {"date": "2011-10-23", "label": "Generales 2011", "tipo": "electoral"},
    {"date": "2011-10-31", "label": "Cepo 2011", "tipo": "cambiario"},
    {"date": "2013-10-27", "label": "Legislativas 2013", "tipo": "electoral"},
    {"date": "2014-01-23", "label": "Devaluación ene-14", "tipo": "cambiario"},
    {"date": "2015-10-25", "label": "Generales 2015", "tipo": "electoral"},
    {"date": "2015-12-17", "label": "Salida del cepo", "tipo": "cambiario"},
    {"date": "2017-10-22", "label": "Legislativas 2017", "tipo": "electoral"},
    {"date": "2018-05-03", "label": "Corrida 2018", "tipo": "cambiario"},
    {"date": "2019-08-11", "label": "PASO 2019", "tipo": "electoral"},
    {"date": "2019-09-01", "label": "Cepo 2019", "tipo": "cambiario"},
    {"date": "2019-10-27", "label": "Generales 2019", "tipo": "electoral"},
    {"date": "2021-09-12", "label": "PASO 2021", "tipo": "electoral"},
    {"date": "2021-11-14", "label": "Legislativas 2021", "tipo": "electoral"},
    {"date": "2023-08-13", "label": "PASO 2023", "tipo": "electoral"},
    {"date": "2023-10-22", "label": "Generales 2023", "tipo": "electoral"},
    {"date": "2023-11-19", "label": "Balotaje 2023", "tipo": "electoral"},
    {"date": "2023-12-13", "label": "Devaluación dic-23", "tipo": "cambiario"},
    {"date": "2025-04-14", "label": "Bandas cambiarias / fin cepo PH", "tipo": "cambiario"},
    {"date": "2025-09-07", "label": "Elecciones PBA 2025", "tipo": "electoral"},
    {"date": "2025-10-26", "label": "Legislativas 2025", "tipo": "electoral"},
    # Calendario 2027 a confirmar por la Cámara Nacional Electoral.
    {"date": "2027-10-24", "label": "Generales 2027 (a confirmar)", "tipo": "electoral"},
]
