"""Versión alternativa del índice, sólo para comparar: flujos acumulados.

    python -m monitor.alternativo --fecha 2026-10-26

En el índice publicado, el oficial (contra la inflación), las reservas, la
BADLAR, los depósitos en dólares y el riesgo país entran por su movimiento de
los últimos 5 días. Cuando una semana termina, lo que pasó sale de golpe: si
el BCRA venía acumulando 1.000 M y una semana acumula 10 M, el índice sube,
porque deja de contar el alivio de los 1.000 M.

En esta versión cada movimiento diario se suma a un acumulado que se va
borrando de a poco (vida media de un mes): las reservas que suben siempre
bajan el índice, y lo acumulado antes pierde peso gradualmente. Recalcula todo
con las series guardadas (no descarga nada) y deja los resultados en
data/alternativo/ y reportes/alternativo/, sin tocar el índice publicado.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date

from . import build, config, report

VIDA_MEDIA = 21  # días hábiles: lo acumulado pierde la mitad de su peso en un mes
DATA_DIR = config.DATA_DIR / "alternativo"
SALIDA = config.ROOT / "reportes" / "alternativo"

NOMBRES = "el oficial (contra la inflación), las reservas, la BADLAR, los depósitos y el riesgo país"


def perfil() -> dict:
    textos = dict(report.APENDICE_AR)
    for c, como in {
        "tc_a3500": "Movimientos diarios del dólar oficial mayorista (A3500) descontada la inflación (CER), acumulados: lo de cada día se suma y se va borrando (la mitad en un mes).",
        "reservas": "Movimientos diarios de las reservas brutas del BCRA, acumulados: lo de cada día se suma y se va borrando (la mitad en un mes).",
        "tasa": "Movimientos diarios de la tasa BADLAR de bancos privados, acumulados: lo de cada día se suma y se va borrando (la mitad en un mes).",
        "depositos_usd": "Movimientos diarios de los depósitos en dólares del sector privado, acumulados: lo de cada día se suma y se va borrando (la mitad en un mes).",
        "riesgo_pais": "Movimientos diarios del riesgo país (EMBI Argentina), acumulados: lo de cada día se suma y se va borrando (la mitad en un mes).",
    }.items():
        _, sube, baja, ojo = textos[c]
        ojo = ojo.replace("Entra por su movimiento de los últimos 5 días, centrado en cero", "Su movimiento de la semana siempre empuja el índice con su signo")
        textos[c] = (como, sube, baja, ojo)
    return {
        **report.PERFIL_AR,
        "titulo": " · versión alternativa",
        "panel": DATA_DIR / "panel_diario.csv", "json": DATA_DIR / "monitor.json", "salida": SALIDA,
        "apendice": textos,
        "nota_flujos": (f"En esta versión, {NOMBRES} entran acumulados: cada movimiento diario se suma a la presión y se va "
                        "borrando de a poco (la mitad en un mes); unas reservas que suben siempre restan."),
        "apendice_flujos": (f"<b>Acumulados</b> ({NOMBRES}). Cada movimiento diario se suma a la presión acumulada, que se va "
                            "borrando de a poco: pierde la mitad de su peso en un mes. Por eso el movimiento de la semana siempre "
                            "empuja el índice con su signo: si las reservas suben, el índice baja, aunque suban menos que la "
                            "semana anterior. Lo acumulado antes pierde peso de a poco (y no de golpe a los 5 días): si el BCRA "
                            "venía comprando mucho y una semana compra 10 M, esos 10 M restan y el índice sube sólo un poco, "
                            "porque lo acumulado se va borrando."),
        "aviso": ("<section class='section card' style='border-color:#e0a030;background:#fff8ea'><b>Versión alternativa, "
                  "para comparar.</b> El oficial, las reservas, la BADLAR, los depósitos y el riesgo país entran acumulados "
                  "(cada movimiento suma y se va borrando en un mes) en lugar de por su movimiento de los últimos 5 días. "
                  "No es el índice publicado.</section>"),
        "metodo_extra": report.PERFIL_AR["metodo_extra"] + (
            f" En esta versión alternativa, {NOMBRES} no entran por su movimiento de 5 días sino acumulados: cada "
            "movimiento diario, estandarizado contra cero, se suma a un acumulado que pierde la mitad de su peso en "
            "un mes, y el acumulado se compara con su desvío histórico."),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fecha", help="fecha de referencia AAAA-MM-DD (se informa la semana anterior)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config.IPD_FLUJOS_VIDA_MEDIA = VIDA_MEDIA
    config.DATA_DIR = DATA_DIR
    config.OUTPUT_JSON = DATA_DIR / "monitor.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    build.run(offline=True)
    report.PERFILES["alternativo"] = perfil
    report.generar(date.fromisoformat(a.fecha) if a.fecha else date.today(), "alternativo")


if __name__ == "__main__":
    main()
