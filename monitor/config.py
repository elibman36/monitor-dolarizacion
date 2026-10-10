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

# Planilla mensual de Reservas Internacionales y Liquidez en Moneda Extranjera
# (formato del FMI, NEDD): de ahí sale la posición del BCRA en futuros de dólar.
# Un PDF por mes, con nombre tempMMAA.pdf (entre jul-23 y may-24, tempMMAAAA.pdf).
BCRA_PLANILLA_URLS = [
    "https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/temp{mm}{yy}.pdf",
    "https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/temp{mm}{yyyy}.pdf",
]
# Antes de 2011 el ítem de derivados figura en blanco (no se informaba).
BCRA_PLANILLA_DESDE = "2011-01"
# Los meses que no están publicados se reintentan sólo si son de este número
# de meses para acá (los huecos viejos se dan por definitivos).
BCRA_PLANILLA_REINTENTAR_MESES = 4
# El dato de fin de mes se publica unas 4-5 semanas después.
POSICION_BCRA_REZAGO_DIAS = 35

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
# Opcionales: horizonte (días hábiles, en lugar de IPD_HORIZON) y piso (valor
# mínimo de la serie antes de transformarla).
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

# Cada componente lleva dos frases para el resumen escrito del reporte: qué
# está pasando cuando suma presión y cuándo resta ("habitual" = últimos 2 años).
IPD_BLOCKS = {
    "cambiaria": {
        "label": "Presión cambiaria",
        "weight": 1 / 3,
        "components": {
            "tc_a3500":  {"transform": "dlog",  "sign": +1, "weight": 1.0,
                          "label": "Depreciación del oficial",
                          "frases": ("el oficial se depreció más que lo habitual",
                                     "el oficial se depreció menos que lo habitual")},
            "vol_oficial": {"transform": "level", "sign": +1, "weight": 1.0,
                            "label": "Volatilidad del oficial",
                            "frases": ("la volatilidad del oficial está por encima de lo habitual",
                                       "la volatilidad del oficial está por debajo de lo habitual")},
            "reservas":  {"transform": "dlog",  "sign": -1, "weight": 1.0,
                          "label": "Reservas internacionales",
                          "frases": ("las reservas cayeron más que lo habitual",
                                     "las reservas evolucionaron mejor que lo habitual")},
            "tasa":      {"transform": "diff",  "sign": +1, "weight": 1.0,
                          "label": "Tasa BADLAR (defensa del peso)",
                          "frases": ("subió la tasa en pesos", "bajó la tasa en pesos")},
            "brecha_mep":  {"transform": "level", "sign": +1, "weight": 1.0,
                            "label": "Brecha MEP / oficial",
                            "frases": ("la brecha MEP / oficial está por encima de lo habitual",
                                       "la brecha MEP / oficial está por debajo de lo habitual")},
        },
    },
    "dolarizacion": {
        "label": "Dolarización de portafolios",
        "weight": 1 / 3,
        "components": {
            "deval_implicita": {"transform": "level", "sign": +1, "weight": 1.0,
                                "label": "Devaluación implícita en futuros",
                                "frases": ("los futuros anticipan más devaluación que lo habitual",
                                           "los futuros anticipan menos devaluación que lo habitual")},
            "futuros_oi": {"transform": "level", "sign": +1, "weight": 1.0,
                           "label": "Posición abierta en futuros de dólar",
                           "frases": ("hay más posiciones abiertas en futuros de dólar (demanda de cobertura)",
                                      "hay menos posiciones abiertas en futuros de dólar")},
            # Los depósitos en USD caen cuando sube la presión (fuga de
            # depósitos) y suben con la confianza: su caída suma presión.
            "depositos_usd": {"transform": "dlog", "sign": -1, "weight": 1.0,
                              "label": "Depósitos en USD",
                              "frases": ("cayeron los depósitos en dólares",
                                         "crecieron los depósitos en dólares")},
            # Futuros vendidos por el BCRA (planilla de reservas, mensual): es
            # demanda de cobertura que el BCRA absorbe para contener la
            # devaluación implícita, es decir, presión que no se ve en el precio.
            # Cuenta la variación mensual (21 días hábiles): ampliar la posición
            # vendida suma presión y desarmarla resta, para que el remanente de
            # un episodio no se lea como presión mientras se desarma. Una posición
            # comprada neta (2019) cuenta como cero, no como alivio.
            "posicion_bcra": {"transform": "diff", "horizonte": 21, "piso": 0.0, "sign": +1, "weight": 1.0,
                              "label": "Futuros vendidos por el BCRA",
                              "frases": ("el BCRA amplió su posición vendida en futuros de dólar",
                                         "el BCRA redujo su posición vendida en futuros de dólar")},
            # Formación de activos externos de personas humanas: dato mensual,
            # que entra recién cuando el BCRA lo publica (ver FAE_REZAGO_DIAS).
            # Se mide contra su promedio de 12 meses: con el cepo las compras
            # eran casi nulas y la salida (abr-25) no es presión en sí misma.
            "compras_ph": {"transform": "desvio_12m", "sign": +1, "weight": 1.0,
                           "label": "Compras de USD de personas humanas (FAE)",
                           "frases": ("las compras de dólares de personas humanas superan su promedio de 12 meses",
                                      "las compras de dólares de personas humanas están por debajo de su promedio de 12 meses")},
        },
    },
    "extranjerizacion": {
        "label": "Extranjerización de portafolios",
        "weight": 1 / 3,
        "components": {
            "canje": {"transform": "level", "sign": +1, "weight": 1.0,
                      "label": "Canje (CCL / MEP)",
                      "frases": ("el canje está por encima de lo habitual: más preferencia por dólares afuera",
                                 "el canje está por debajo de lo habitual")},
            "vol_ccl":     {"transform": "level", "sign": +1, "weight": 1.0,
                            "label": "Volatilidad del CCL",
                            "frases": ("la volatilidad del CCL está por encima de lo habitual",
                                       "la volatilidad del CCL está por debajo de lo habitual")},
            "riesgo_pais": {"transform": "diff",  "sign": +1, "weight": 1.0,
                            "label": "Riesgo país",
                            "frases": ("subió el riesgo país", "bajó el riesgo país")},
        },
    },
}

# Rezago con que se incorpora la FAE mensual: el dato de un mes entra este
# número de días después del fin de mes (el BCRA lo publica ~4 semanas
# después) y se mantiene hasta el siguiente.
FAE_REZAGO_DIAS = 30
# La posición abierta en futuros cae cada fin de mes por el vencimiento del
# contrato más corto: se suaviza con un promedio de este número de días hábiles.
FUTUROS_OI_SUAVIZADO = 21
# Peso mínimo de un bloque para calcularlo: 0 = alcanza con un componente.
IPD_MIN_WEIGHT_SHARE_BLOQUE = 0.0

# Percentil del IPD dentro de su propia historia reciente (dato complementario).
IPD_PERCENTILE_WINDOW = 504

# Índice 0-100: 100 * Φ(IPD suavizado / σ), con Φ la normal acumulada y σ el
# desvío histórico del IPD suavizado. 50 = neutral; < 50 presión apreciatoria
# (alivio); > 50 presión depreciatoria. Se suaviza con un promedio de
# INDICE_SUAVIZADO días hábiles para que el titular no salte día a día
# (con 20 días el cambio semanal promedio es de unos 6 puntos).
INDICE_SUAVIZADO = 20  # un mes hábil
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
