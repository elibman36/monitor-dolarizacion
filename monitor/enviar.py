"""Envío del reporte semanal por email (SMTP).

    python -m monitor.enviar                  # último reporte, a REPORTE_PARA
    python -m monitor.enviar --para a@x.com   # prueba a otra lista
    python -m monitor.enviar --dry-run        # arma el mail y lo guarda, sin enviar

Variables de entorno (en GitHub, secretos del repositorio):
  SMTP_USER       cuenta que envía (p. ej. elibman@fund.ar)
  SMTP_PASSWORD   contraseña de aplicación de esa cuenta
  REPORTE_PARA    destinatarios separados por coma
  SMTP_HOST       por defecto smtp.gmail.com (Google Workspace)
  SMTP_PORT       por defecto 587 (STARTTLS)

El mail lleva el PDF adjunto y, en el cuerpo, el índice al cierre y el racconto
de la semana si lo hay (reportes/textos/AAAA-MM-DD.md). Los destinatarios van
en copia oculta para no exponer la lista.
"""
from __future__ import annotations

import argparse
import html
import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

import pandas as pd

from . import config, indicators, report

log = logging.getLogger(__name__)


def ultimo_pdf(dir_: Path | None = None) -> Path:
    pdfs = sorted((dir_ or report.REPORTS_DIR).glob("reporte-semanal-*.pdf"))
    if not pdfs:
        raise SystemExit("No hay reportes en reportes/.")
    return pdfs[-1]


def armar_mensaje(pdf: Path, remitente: str, para: list[str], panel: Path | None = None,
                  textos: Path | None = None) -> EmailMessage:
    viernes = pd.Timestamp(pdf.stem.removeprefix("reporte-semanal-"))
    lunes = viernes - pd.Timedelta(days=4)
    semana = f"{lunes.day} al {report.fecha_larga(viernes)}"
    indice_txt = ""
    try:
        p = pd.read_csv(panel or report.PANEL_CSV, index_col=0, parse_dates=True)
        _, i1 = report._hasta(p["indice_0_100"], viernes)
        _, i0 = report._hasta(p["indice_0_100"], viernes - pd.Timedelta(days=7))
        if pd.notna(i1):
            tramo = indicators.status_for(i1)[1].lower()
            indice_txt = f"El Índice de Dolarización cerró la semana en {i1:.0f}/100 ({tramo})"
            if pd.notna(i0):
                indice_txt += f"; el viernes anterior estaba en {i0:.0f}"
            indice_txt += "."
    except Exception as e:  # el mail sale igual, sin la línea del índice
        log.warning("Sin el índice para el cuerpo del mail: %s", e)
    racconto = report.racconto(viernes, textos)

    m = EmailMessage()
    m["Subject"] = f"Monitor de Dolarización · Reporte semanal · semana del {semana}"
    m["From"] = remitente
    m["To"] = remitente
    m["Bcc"] = ", ".join(para)
    texto_plano = "\n\n".join(x for x in [
        f"Reporte semanal del Monitor de Dolarización, semana del {semana}.",
        indice_txt,
        html.unescape(re.sub(r"<[^>]+>", " ", racconto.replace("</p>", "\n\n"))).strip() if racconto else "",
        "Va adjunto el reporte en PDF.",
    ] if x)
    m.set_content(texto_plano)
    cuerpo = (f"<p>Reporte semanal del Monitor de Dolarización, semana del {html.escape(semana)}.</p>"
              + (f"<p><b>{html.escape(indice_txt)}</b></p>" if indice_txt else "")
              + (f"<h3 style='margin:16px 0 4px'>La semana</h3>{racconto}" if racconto else "")
              + "<p style='color:#52514e'>Va adjunto el reporte en PDF.</p>")
    m.add_alternative(f"<div style='font-family:Arial,sans-serif;font-size:14px;line-height:1.5;color:#0b0b0b'>{cuerpo}</div>",
                      subtype="html")
    m.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf", filename=pdf.name)
    return m


def enviar(m: EmailMessage, usuario: str, clave: str, host: str = "smtp.gmail.com", puerto: int = 587) -> None:
    with smtplib.SMTP(host, puerto, timeout=60) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(usuario, clave)
        s.send_message(m)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", type=Path, help="reporte a enviar (por defecto, el último)")
    ap.add_argument("--para", help="destinatarios separados por coma (por defecto, REPORTE_PARA)")
    ap.add_argument("--dry-run", action="store_true", help="no envía: guarda el mail en reportes/ultimo.eml")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    usuario = os.environ.get("SMTP_USER", "")
    para = [x.strip() for x in (a.para or os.environ.get("REPORTE_PARA", "")).split(",") if x.strip()]
    if not para:
        raise SystemExit("Faltan destinatarios (--para o REPORTE_PARA).")
    pdf = a.pdf or ultimo_pdf()
    m = armar_mensaje(pdf, usuario or "monitor@localhost", para)
    if a.dry_run:
        destino = config.ROOT / "reportes" / "ultimo.eml"
        destino.write_bytes(bytes(m))
        log.info("Mail armado (sin enviar): %s", destino)
        return
    clave = os.environ.get("SMTP_PASSWORD", "")
    if not usuario or not clave:
        raise SystemExit("Faltan SMTP_USER o SMTP_PASSWORD.")
    enviar(m, usuario, clave, os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", "587")))
    log.info("Reporte %s enviado a %d destinatarios.", pdf.name, len(para))


if __name__ == "__main__":
    main()
