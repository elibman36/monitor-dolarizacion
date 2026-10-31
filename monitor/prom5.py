"""Versión paralela del índice, para comparar: promedio de 5 días.

    python -m monitor.prom5 --fecha 2026-11-02

Igual al índice publicado, pero cada día es el promedio de los últimos 5 días
hábiles (en vez de 20): reacciona más rápido a lo de la semana. Recalcula todo
con las series guardadas (no descarga nada) y deja los resultados en
data/prom5/ y reportes/prom5/, sin tocar el índice publicado.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date

from . import build, config, report

DIAS = 5
DATA_DIR = config.DATA_DIR / "prom5"
SALIDA = config.ROOT / "reportes" / "prom5"


def perfil() -> dict:
    return {
        **report.PERFIL_AR,
        "titulo": " · promedio de 5 días",
        "panel": DATA_DIR / "panel_diario.csv", "json": DATA_DIR / "monitor.json", "salida": SALIDA,
        "aviso": ("<section class='section card' style='border-color:#e0a030;background:#fff8ea'><b>Versión paralela, "
                  "para comparar.</b> Cada día es el promedio de los últimos 5 días hábiles (el índice publicado usa 20). "
                  "No es el índice publicado.</section>"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fecha", help="fecha de referencia AAAA-MM-DD (se informa la semana anterior)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config.INDICE_SUAVIZADO = DIAS
    config.DATA_DIR = DATA_DIR
    config.OUTPUT_JSON = DATA_DIR / "monitor.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    build.run(offline=True)
    report.PERFILES["prom5"] = perfil
    report.generar(date.fromisoformat(a.fecha) if a.fecha else date.today(), "prom5")


if __name__ == "__main__":
    main()
