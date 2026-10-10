"""Reporte semanal en PDF del Monitor de Dolarización.

Se genera los lunes con los datos de la semana hábil anterior (lunes a
viernes) a partir de lo que ya calculó `monitor.build`:

    python -m monitor.report                 # semana anterior a hoy
    python -m monitor.report --fecha 2026-10-12

Escribe reportes/reporte-semanal-AAAA-MM-DD.pdf (fecha del viernes de la
semana informada) y reportes/ultimo.pdf.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

from . import config, indicators  # noqa: E402

log = logging.getLogger("monitor.report")

REPORTS_DIR = config.ROOT / "reportes"
PANEL_CSV = config.DATA_DIR / "panel_diario.csv"
DASHBOARD_URL = "https://elibman36.github.io/monitor-dolarizacion/"

# Paleta (misma que el tablero, modo claro).
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"
TRAMO_COLOR = {
    "aprec_fuerte": "#1c5cab", "aprec": "#6da7ec", "neutral": "#a3a29b",
    "deprec": "#ec8a89", "deprec_fuerte": "#c0302f",
}
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

plt.rcParams.update({
    "font.family": ["Inter", "DejaVu Sans"],
    "font.size": 8.5,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "axes.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.major.size": 0, "ytick.major.size": 0,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.7,
    "svg.fonttype": "none", "figure.dpi": 150,
})


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------

@dataclass
class Semana:
    lunes: pd.Timestamp
    viernes: pd.Timestamp

    @property
    def etiqueta(self) -> str:
        a, b = self.lunes, self.viernes
        if a.month == b.month:
            return f"{a.day} al {b.day} de {MESES[b.month - 1]}. {b.year}"
        return f"{a.day} de {MESES[a.month - 1]}. al {b.day} de {MESES[b.month - 1]}. {b.year}"


def semana_anterior(ref: date) -> Semana:
    lunes_actual = pd.Timestamp(ref) - pd.Timedelta(days=ref.weekday())
    lunes = lunes_actual - pd.Timedelta(days=7)
    return Semana(lunes, lunes + pd.Timedelta(days=4))


def _hasta(s: pd.Series, fecha: pd.Timestamp):
    s = s.dropna()
    s = s[s.index <= fecha]
    return (s.index[-1], float(s.iloc[-1])) if not s.empty else (None, np.nan)


def fmt(v, dec=1, signo=False, sufijo=""):
    if v is None or not np.isfinite(v):
        return "–"
    txt = f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if signo and v > 0:
        txt = "+" + txt
    return txt + sufijo


def fecha_larga(d: pd.Timestamp) -> str:
    return f"{d.day} de {MESES[d.month - 1]}. {d.year}"


# ---------------------------------------------------------------------------
# Gráficos (SVG embebidos)
# ---------------------------------------------------------------------------

def _svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)
    svg = buf.getvalue()
    return svg[svg.index("<svg"):]


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=200, facecolor="white")
    plt.close(fig)
    return '<img alt="" src="data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode() + '">'


def _tramo_de(v: float) -> str:
    for lo, hi, key, _ in config.INDICE_TRAMOS:
        if lo <= v < hi:
            return key
    return "neutral"


def _bandas(ax):
    for lo, hi, key, _ in config.INDICE_TRAMOS:
        if key != "neutral":
            ax.axhspan(lo, min(hi, 100), color=TRAMO_COLOR[key], alpha=0.08, lw=0, zorder=0)
    ax.axhline(50, color=AXIS, lw=0.8, zorder=1)
    ax.set_ylim(0, 100)
    ax.set_yticks([0, 25, 50, 75, 100])


def _linea_tramos(ax, s: pd.Series, lw=1.8):
    s = s.dropna()
    x = mdates.date2num(s.index.to_pydatetime())
    pts = np.column_stack([x, s.values])
    segs = np.stack([pts[:-1], pts[1:]], axis=1)
    colores = [TRAMO_COLOR[_tramo_de((a + b) / 2)] for a, b in zip(s.values[:-1], s.values[1:])]
    ax.add_collection(LineCollection(segs, colors=colores, linewidths=lw, capstyle="round", zorder=3))
    ax.set_xlim(x[0], x[-1])


def chart_indice_anual(indice: pd.Series, semana: Semana, eventos: list[dict]) -> str:
    s = indice[semana.viernes - pd.DateOffset(months=18): semana.viernes]
    fig, ax = plt.subplots(figsize=(7.2, 2.0))
    _bandas(ax)
    ax.axvspan(semana.lunes, semana.viernes + pd.Timedelta(days=1), color=INK, alpha=0.08, lw=0, zorder=2)
    _linea_tramos(ax, s)
    for e in eventos:
        d = pd.Timestamp(e["date"])
        # Se omiten los eventos pegados al borde izquierdo, donde el texto se corta.
        if s.index[0] + (s.index[-1] - s.index[0]) * 0.04 <= d <= s.index[-1]:
            ax.axvline(d, color=AXIS, lw=0.8, zorder=1)
            ax.text(d, 97, " " + e["label"], rotation=90, va="top", ha="right", fontsize=6.5, color=MUTED)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%y"))
    return _svg(fig)


def chart_indice_historico(indice: pd.Series) -> str:
    m = indice.dropna().resample("ME").mean()
    m.index = m.index - pd.offsets.MonthBegin(1) + pd.Timedelta(days=14)
    fig, ax = plt.subplots(figsize=(3.6, 2.1))
    _bandas(ax)
    _linea_tramos(ax, m, lw=1.1)
    ax.xaxis.set_major_locator(mdates.YearLocator(5))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    return _svg(fig)


def chart_contribuciones(z: dict[str, float], labels: dict[str, str]) -> str:
    items = sorted(((labels[k], v) for k, v in z.items() if np.isfinite(v)), key=lambda t: t[1])
    fig, ax = plt.subplots(figsize=(3.6, 0.21 * len(items) + 0.45))
    ys = np.arange(len(items))
    vals = [v for _, v in items]
    ax.barh(ys, vals, height=0.6, color=["#e34948" if v >= 0 else S1 for v in vals], zorder=3)
    ax.set_yticks(ys, [n for n, _ in items], fontsize=7.5, color=INK2)
    ax.axvline(0, color=AXIS, lw=0.8)
    ax.grid(axis="x", color=GRID, lw=0.7)
    ax.grid(axis="y", visible=False)
    lim = max(1.0, max(abs(v) for v in vals) * 1.25)
    ax.set_xlim(-lim, lim)
    for y, v in zip(ys, vals):
        ax.text(v + (0.06 * lim if v >= 0 else -0.06 * lim), y, fmt(v, 1, signo=True), va="center",
                ha="left" if v >= 0 else "right", fontsize=7, color=INK2)
    return _svg(fig)


def chart_mini(series: list[tuple[str, pd.Series, str]], titulo: str, unidad: str, semana: Semana) -> str:
    fig, ax = plt.subplots(figsize=(1.85, 1.2))
    desde = semana.viernes - pd.DateOffset(months=6)
    for nombre, s, color in series:
        if s is None:
            continue
        s = s[desde: semana.viernes].dropna()
        if s.empty:
            continue
        ax.plot(s.index, s.values, color=color, lw=1.4, label=nombre, zorder=3)
    ax.axvspan(semana.lunes, semana.viernes + pd.Timedelta(days=1), color=INK, alpha=0.07, lw=0)
    ax.set_title(titulo, loc="left", fontsize=8, color=INK, fontweight="bold", pad=10)
    ax.text(0, 1.02, unidad, transform=ax.transAxes, fontsize=6.5, color=MUTED)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%y"))
    ax.tick_params(labelsize=6)
    if len(series) > 1:
        ax.legend(fontsize=5.8, frameon=False, loc="upper left", ncol=len(series), handlelength=1.0,
                  columnspacing=0.7, handletextpad=0.3, bbox_to_anchor=(-0.02, -0.2), borderaxespad=0)
    return _svg(fig)


def chart_compras_ph(compras: list[dict]) -> str:
    df = pd.DataFrame(compras)
    if df.empty or "netas_usd_millones" not in df:
        return ""
    df = df.tail(36)
    fig, ax = plt.subplots(figsize=(7.2, 1.3))
    ax.bar(range(len(df)), df["netas_usd_millones"], color=S1, width=0.7, zorder=3, label="Compras netas")
    if "netas_prom_12m" in df:
        ax.plot(range(len(df)), df["netas_prom_12m"], color=S2, lw=1.8, zorder=4, label="Promedio móvil 12 meses")
        ax.legend(fontsize=6.5, frameon=False, loc="upper left", ncol=2, handlelength=1.2)
    ax.set_xticks(range(0, len(df), 2), [f"{MESES[int(f[5:7]) - 1]}\n{f[2:4]}" for f in df["fecha"]][::2], fontsize=6.5)
    ax.axhline(0, color=AXIS, lw=0.8)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt(v, 0)))
    return _svg(fig)


# ---------------------------------------------------------------------------
# Contenido
# ---------------------------------------------------------------------------

VARIABLES = [
    # (columna, etiqueta, unidad, decimales, tipo de variación: "pct" | "pp" | "pb" | "abs")
    ("tc_oficial_ref", "Tipo de cambio oficial (A3500)", "$ por USD", 2, "pct"),
    ("usd_mep", "Dólar MEP", "$ por USD", 1, "pct"),
    ("usd_ccl", "Dólar CCL", "$ por USD", 1, "pct"),
    ("brecha_mep", "Brecha MEP / oficial", "%", 1, "pp"),
    ("canje", "Canje (CCL / MEP)", "%", 1, "pp"),
    ("vol_oficial", "Volatilidad del oficial (20 días)", "% anual", 1, "pp"),
    ("riesgo_pais", "Riesgo país", "pb", 0, "pb"),
    ("reservas", "Reservas internacionales brutas", "M USD", 0, "abs"),
    ("tasa", "Tasa BADLAR privados", "% n.a.", 2, "pp"),
    ("deval_implicita", "Devaluación implícita en futuros (90 días)", "% TNA", 1, "pp"),
    ("futuros_interes_abierto", "Posición abierta en futuros de dólar", "contratos de USD 1.000", 0, "pct"),
    ("posicion_bcra", "Futuros vendidos por el BCRA (neto)", "M USD, último fin de mes publicado", 0, "abs"),
    ("depositos_usd", "Depósitos en USD del sector privado", "M USD", 0, "abs"),
]


def _variacion(v1, v0, tipo):
    if not (np.isfinite(v1) and np.isfinite(v0)):
        return np.nan
    return (v1 / v0 - 1) * 100 if tipo == "pct" else v1 - v0


def _txt_var(d, tipo, dec):
    suf = {"pct": "%", "pp": " pp", "pb": " pb", "abs": ""}[tipo]
    return fmt(d, 1 if tipo in ("pct", "pp") else dec, signo=True, sufijo=suf)


def tabla_variables(p: pd.DataFrame, semana: Semana) -> tuple[str, dict]:
    filas, datos = [], {}
    cierre_prev = semana.viernes - pd.Timedelta(days=7)
    hace4 = semana.viernes - pd.Timedelta(days=28)
    for col, label, unidad, dec, tipo in VARIABLES:
        if col not in p:
            continue
        f1, v1 = _hasta(p[col], semana.viernes)
        _, v0 = _hasta(p[col], cierre_prev)
        _, v4 = _hasta(p[col], hace4)
        d1, d4 = _variacion(v1, v0, tipo), _variacion(v1, v4, tipo)
        datos[col] = {"v": v1, "d": d1, "fecha": f1}
        nota = "" if f1 is None or f1 >= semana.lunes else f' <span class="muted">(al {f1.day}/{f1.month})</span>'
        filas.append(
            f"<tr><td>{label} <span class='unit'>{unidad}</span>{nota}</td>"
            f"<td class='num'>{fmt(v1, dec)}</td><td class='num'>{_txt_var(d1, tipo, dec)}</td>"
            f"<td class='num'>{_txt_var(d4, tipo, dec)}</td></tr>")
    tabla = ("<table class='vars'><thead><tr><th>Variable</th><th class='num'>Cierre</th>"
             "<th class='num'>Var. semanal</th><th class='num'>Var. 4 semanas</th></tr></thead><tbody>"
             + "".join(filas) + "</tbody></table>")
    return tabla, datos


def _minus(txt: str) -> str:
    """Primera letra en minúscula, sin tocar siglas (USD, CCL...)."""
    return txt[:1].lower() + txt[1:]


FRASES = {c: spec["frases"] for b in config.IPD_BLOCKS.values() for c, spec in b["components"].items()}


def _frase(comp: str, pts: float) -> str:
    sube, baja = FRASES.get(comp, (comp, comp))
    return f"{sube if pts > 0 else baja} ({fmt(pts, 0, signo=True)} pts)"


def resumen(indice, semana, pts_cierre, datos) -> list[str]:
    """Resumen en palabras: cuánto se movió el índice y qué lo explica, en puntos."""
    _, i1 = _hasta(indice, semana.viernes)
    _, i0 = _hasta(indice, semana.viernes - pd.Timedelta(days=7))
    tramo = indicators.status_for(i1)[1].lower()
    puntos = []
    if np.isfinite(i1):
        txt = f"El índice cerró la semana en <b>{fmt(i1, 0)}/100</b> ({tramo})"
        if np.isfinite(i0):
            dif = i1 - i0
            if abs(dif) < 1.5:
                txt += f", sin cambios relevantes respecto del viernes anterior ({fmt(i0, 0)})"
            else:
                txt += f", {fmt(abs(dif), 0)} puntos {'por encima' if dif > 0 else 'por debajo'} del viernes anterior ({fmt(i0, 0)})"
        puntos.append(txt + ".")
    pc = {k: v for k, v in pts_cierre.items() if np.isfinite(v)}
    if pc:
        presion = [k for k, v in sorted(pc.items(), key=lambda t: -t[1]) if v >= 1][:3]
        alivio = [k for k, v in sorted(pc.items(), key=lambda t: t[1]) if v <= -1][:3]
        if presion:
            puntos.append("En el último mes sumaron presión: " + "; ".join(_frase(k, pc[k]) for k in presion) + ".")
        if alivio:
            puntos.append("En el último mes restaron presión: " + "; ".join(_frase(k, pc[k]) for k in alivio) + ".")
        puntos.append('<span class="muted">"Habitual" se refiere a los últimos dos años. Los puntos indican cuánto aporta '
                      "cada factor a la distancia del índice respecto de 50, en promedio de las últimas cuatro semanas "
                      "(el mismo período con que se calcula el índice).</span>")
    partes = []
    if "tc_oficial_ref" in datos:
        partes.append(f"el oficial {_txt_var(datos['tc_oficial_ref']['d'], 'pct', 2)}")
    if "usd_mep" in datos:
        partes.append(f"el MEP {_txt_var(datos['usd_mep']['d'], 'pct', 1)}")
    if "usd_ccl" in datos:
        partes.append(f"el CCL {_txt_var(datos['usd_ccl']['d'], 'pct', 1)}")
    if "riesgo_pais" in datos:
        partes.append(f"el riesgo país {_txt_var(datos['riesgo_pais']['d'], 'pb', 0)}")
    if "reservas" in datos and np.isfinite(datos["reservas"]["d"]):
        d = datos["reservas"]["d"]
        partes.append(f"las reservas {'subieron' if d >= 0 else 'cayeron'} USD {fmt(abs(d), 0)} M")
    if partes:
        puntos.append("Variaciones de la semana: " + ", ".join(partes) + ".")
    return puntos


# ---------------------------------------------------------------------------
# HTML -> PDF
# ---------------------------------------------------------------------------

CSS = """
@page { size: A4; margin: 14mm 14mm 16mm; }
* { box-sizing: border-box; }
body { font-family: Inter, "DejaVu Sans", sans-serif; color: #0b0b0b; font-size: 9.5pt; line-height: 1.4; margin: 0; }
h1 { font-size: 17pt; margin: 0; letter-spacing: -0.01em; }
h2 { font-size: 11pt; margin: 0 0 2pt; }
.sub { color: #52514e; margin: 2pt 0 0; }
.muted, .unit { color: #898781; font-size: 7.5pt; }
.top { display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1px solid #e1e0d9; padding-bottom: 8pt; margin-bottom: 10pt; }
.top .meta { text-align: right; color: #52514e; font-size: 8.5pt; }
.hero { display: grid; grid-template-columns: 52mm 1fr; gap: 8pt; margin-bottom: 8pt; }
.card { border: 1px solid #e1e0d9; border-radius: 8px; padding: 7pt 9pt; break-inside: avoid; }
.num-big { font-size: 36pt; font-weight: 650; line-height: 1; letter-spacing: -0.02em; margin: 6pt 0 4pt; }
.num-big small { font-size: 13pt; color: #898781; font-weight: 500; }
.pill { display: inline-block; padding: 2pt 8pt; border-radius: 999px; font-weight: 600; font-size: 8.5pt; color: #fff; }
.gauge { display: flex; gap: 1.5px; height: 7pt; margin: 9pt 0 2pt; position: relative; }
.gauge span:first-child { border-radius: 4px 0 0 4px; } .gauge span:last-child { border-radius: 0 4px 4px 0; }
.gauge i { position: absolute; top: -3pt; width: 2.5pt; height: 13pt; margin-left: -1.25pt; background: #0b0b0b; border-radius: 2px; box-shadow: 0 0 0 1.5px #fff; }
.scale { display: flex; justify-content: space-between; font-size: 6.5pt; color: #898781; }
.kv { display: grid; grid-template-columns: auto auto; gap: 2pt 8pt; margin-top: 8pt; font-size: 8pt; color: #52514e; }
.kv b { color: #0b0b0b; text-align: right; }
ul.res { margin: 4pt 0 0; padding-left: 13pt; } ul.res li { margin-bottom: 3pt; }
.chart svg, .chart img { width: 100%; height: auto; display: block; }
.note { color: #898781; font-size: 7.5pt; margin: 0 0 4pt; }
table.vars { width: 100%; border-collapse: collapse; font-size: 8.3pt; }
table.vars th { text-align: left; color: #52514e; font-weight: 600; border-bottom: 1px solid #c3c2b7; padding: 4pt 4pt; }
table.vars td { border-bottom: 1px solid #eeede8; padding: 2.1pt 4pt; vertical-align: top; }
table.vars .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10pt; }
.grid3 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 5pt; }
.grid3 .card { padding: 4pt 6pt; }
.section { margin-top: 8pt; break-inside: avoid; }
.page { break-before: page; }
.legend { display: flex; flex-wrap: wrap; gap: 4pt 10pt; font-size: 7pt; color: #52514e; margin-top: 4pt; }
.legend span::before { content: ""; display: inline-block; width: 8pt; height: 6pt; border-radius: 2px; margin-right: 3pt; background: var(--c); vertical-align: middle; }
.method p { margin: 0 0 6pt; color: #333; }
.method table { width: 100%; border-collapse: collapse; font-size: 8pt; margin: 4pt 0 8pt; }
.method td, .method th { border-bottom: 1px solid #eeede8; padding: 3pt 4pt; text-align: left; }
.method .num { text-align: right; font-variant-numeric: tabular-nums; }
a { color: #2a78d6; text-decoration: none; }
"""


def construir_html(semana: Semana, p: pd.DataFrame, payload: dict) -> str:
    indice = p["indice_0_100"]
    f_cierre, i1 = _hasta(indice, semana.viernes)
    if f_cierre is None:
        raise SystemExit("No hay datos del índice para la semana pedida.")
    _, i0 = _hasta(indice, semana.viernes - pd.Timedelta(days=7))
    _, i4 = _hasta(indice, semana.viernes - pd.Timedelta(days=28))
    tramo_key, tramo_label = indicators.status_for(i1)

    labels = {c: spec["label"] for b in config.IPD_BLOCKS.values() for c, spec in b["components"].items()}
    meta = {c["key"]: c for c in payload["ipd"]["components"]}
    labels_peso = {c: (f"{l} · {fmt(meta[c]['weight_ipd'] * 100, 0)}%" if meta.get(c, {}).get("weight_ipd") is not None else l)
                   for c, l in labels.items()}
    pts_cierre = {c: _hasta(p[f"pts_{c}"], semana.viernes)[1] for c in labels if f"pts_{c}" in p}

    tabla, datos = tabla_variables(p, semana)
    puntos = resumen(indice, semana, pts_cierre, datos)

    gauge = "".join(f"<span style='flex:{min(hi, 100) - lo};background:{TRAMO_COLOR[k]}'></span>"
                    for lo, hi, k, _ in config.INDICE_TRAMOS)
    gauge += f"<i style='left:{max(0, min(100, i1)):.1f}%'></i>"
    leyenda = "".join(f"<span style='--c:{TRAMO_COLOR[k]}'>{html.escape(l)} ({lo}–{int(min(hi, 100))})</span>"
                      for lo, hi, k, l in config.INDICE_TRAMOS)

    minis = [
        chart_mini([("Oficial", p["tc_oficial_ref"], S1), ("MEP", p.get("usd_mep"), S2), ("CCL", p.get("usd_ccl"), S3)],
                   "Tipo de cambio", "$ por USD", semana),
        chart_mini([("Brecha MEP", p.get("brecha_mep"), S1), ("Canje", p.get("canje"), S2)],
                   "Brecha MEP / oficial y canje", "%", semana),
        chart_mini([("Riesgo país", p["riesgo_pais"], S1)], "Riesgo país", "pb", semana),
        chart_mini([("Reservas", p["reservas"], S1)], "Reservas brutas", "millones de USD", semana),
        chart_mini([("Futuros", p.get("deval_implicita"), S1)], "Devaluación implícita", "% TNA a 90 días", semana),
        # Cada contrato es de USD 1.000: miles de contratos = millones de USD.
        chart_mini([("Posición abierta", p.get("futuros_interes_abierto") / 1000 if "futuros_interes_abierto" in p else None, S1),
                    ("Vendida por el BCRA", p.get("posicion_bcra"), S2)],
                   "Futuros de dólar", "millones de USD", semana),
        chart_mini([("Depósitos", p.get("depositos_usd"), S1)], "Depósitos en USD", "millones de USD", semana),
        chart_mini([("Oficial", p.get("vol_oficial"), S1), ("CCL", p.get("vol_ccl"), S2)],
                   "Volatilidad cambiaria", "% anualizada, 20 días", semana),
    ]
    compras = payload.get("monthly", {}).get("compras_personas_humanas", [])
    ph_svg = chart_compras_ph(compras)
    ph_ult = compras[-1] if compras else None

    comp_rows = "".join(
        f"<tr><td>{html.escape(b['label'])}</td><td>{html.escape(spec['label'])}</td>"
        f"<td class='num'>{fmt((meta.get(c, {}).get('weight') or 0) * 100, 0)}%</td>"
        f"<td class='num'>{fmt((meta.get(c, {}).get('weight_ipd') or 0) * 100, 1)}%</td></tr>"
        for b in config.IPD_BLOCKS.values() for c, spec in b["components"].items())
    pca_txt = "; ".join(f"{config.IPD_BLOCKS[k]['label']}, {fmt(v['varianza_explicada'] * 100, 0)}%"
                        for k, v in payload.get("config", {}).get("pca", {}).items())
    generado = pd.Timestamp.now(tz="America/Argentina/Buenos_Aires")

    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<header class="top">
  <div><h1>Monitor de Dolarización</h1>
  <p class="sub">Reporte semanal · semana del {semana.etiqueta}</p></div>
  <div class="meta">Datos al {fecha_larga(f_cierre)}<br><a href="{DASHBOARD_URL}">Tablero diario</a></div>
</header>

<section class="hero">
  <div class="card">
    <h2>Índice de Presión de Dolarización</h2>
    <div class="muted">0 a 100 · 50 = neutral</div>
    <div class="num-big">{fmt(i1, 0)}<small>/100</small></div>
    <span class="pill" style="background:{TRAMO_COLOR.get(tramo_key, MUTED)}">{html.escape(tramo_label)}</span>
    <div class="gauge">{gauge}</div>
    <div class="scale"><span>0 apreciación</span><span>50</span><span>depreciación 100</span></div>
    <div class="kv">
      <span>Semana anterior</span><b>{fmt(i0, 0)} ({fmt(i1 - i0, 0, signo=True)} pts)</b>
      <span>Hace 4 semanas</span><b>{fmt(i4, 0)} ({fmt(i1 - i4, 0, signo=True)} pts)</b>
    </div>
  </div>
  <div class="card">
    <h2>Resumen de la semana</h2>
    <ul class="res">{"".join(f"<li>{x}</li>" for x in puntos)}</ul>
  </div>
</section>

<section class="card">
  <h2>Índice en los últimos 18 meses</h2>
  <p class="note">Dato diario (promedio de 20 días hábiles). La franja gris marca la semana informada. <a href="{DASHBOARD_URL}">Ver la versión interactiva, con el período a elección</a>.</p>
  <div class="chart">{chart_indice_anual(indice, semana, payload.get("events", []))}</div>
  <div class="legend">{leyenda}</div>
</section>

<section class="section grid2">
  <div class="card">
    <h2>Qué explica el índice</h2>
    <p class="note">Aporte de cada componente al cierre, en puntos del índice (suman la distancia a 50). Rojo suma presión; azul la resta.</p>
    <div class="chart">{chart_contribuciones(pts_cierre, labels_peso)}</div>
  </div>
  <div class="card">
    <h2>Índice desde 2003</h2>
    <p class="note">Promedio mensual.</p>
    <div class="chart">{chart_indice_historico(indice)}</div>
  </div>
</section>

<section class="page">
  <div class="card">
    <h2>Variables de la semana</h2>
    <p class="note">Cierre al viernes {fecha_larga(semana.viernes)} o último dato disponible. Las reservas y los depósitos se publican con dos o tres días de rezago.</p>
    {tabla}
  </div>
  <div class="section">
    <h2>Últimos seis meses</h2>
    <div class="grid3">{"".join(f"<div class='card chart'>{m}</div>" for m in minis)}</div>
  </div>
  {"" if not ph_svg else f'''<div class="section card">
    <h2>Compras netas de USD de personas humanas (FAE)</h2>
    <p class="note">Formación de activos externos (billetes y divisas sin fines específicos), millones de USD por mes, con su promedio móvil de 12 meses. Último dato: {ph_ult["fecha"]} ({fmt(ph_ult.get("netas_usd_millones"), 0)} M USD netos; {fmt(ph_ult.get("compras_usd_millones"), 0)} M de compras brutas). BCRA, balance cambiario.</p>
    <div class="chart">{ph_svg}</div>
  </div>'''}
</section>

<section class="page method">
  <h2>Metodología</h2>
  <p>El Índice de Presión de Dolarización adapta el <i>Exchange Market Pressure Index</i> (Girton y Roper, 1977; Eichengreen, Rose y Wyplosz, 1996) a la economía bimonetaria argentina. Cada componente se transforma para que un valor más alto signifique más presión y se compara con los últimos dos años (mediana y desvío absoluto mediano, para que un episodio extremo no infle la escala). Los componentes se agrupan en tres subíndices de igual peso: <b>presión cambiaria</b> (tipo de cambio oficial, su volatilidad, reservas, tasa en pesos y brecha MEP / oficial), <b>dolarización de portafolios</b> (devaluación implícita y posición abierta en futuros de dólar, futuros vendidos por el BCRA, depósitos en dólares y compras de dólares de personas humanas) y <b>extranjerización de portafolios</b> (canje CCL / MEP, volatilidad del CCL y riesgo país). Dentro de cada subíndice, los pesos salen de componentes principales: cada componente pesa según cuánto se mueve junto con el resto (cargas del primer componente principal de los promedios mensuales desde 2003). Las cargas negativas valen cero y ningún componente pesa menos del 10% de su subíndice. Varianza explicada por el primer componente: {pca_txt}.</p>
  <table><thead><tr><th>Subíndice</th><th>Componente</th><th class="num">Peso en el subíndice</th><th class="num">Peso en el índice</th></tr></thead><tbody>{comp_rows}</tbody></table>
  <p>El promedio ponderado se promedia en 20 días hábiles (un mes, para que el índice no salte de una semana a otra) y se lleva a una escala de 0 a 100 con la normal acumulada. 50 es neutral; debajo hay presión apreciatoria (alivio) y arriba, presión depreciatoria. Un valor de 90 indica una presión tan alta como la del 10% de los días más tensos desde 2003. Los aportes en puntos reparten la distancia del índice a 50 entre los componentes, así que suman exactamente esa distancia. Si falta un componente, su peso se reparte entre los demás de su subíndice. Las compras de dólares de personas humanas son mensuales, entran al índice un mes después del cierre de cada mes (cuando el BCRA las publica) y se miden contra su promedio de 12 meses, para no confundir la salida del cepo con presión.</p>
  <p><b>Fuentes:</b> BCRA (reservas, tipo de cambio A3500, BADLAR, depósitos en dólares, anexo del balance cambiario y planilla de reservas y liquidez en moneda extranjera), ArgentinaDatos (dólar MEP, CCL y blue; riesgo país) y A3 Mercados (futuros de dólar). Todas las series se descargan automáticamente.</p>
  <p class="muted">Generado el {generado.day}/{generado.month}/{generado.year} a las {generado:%H:%M} (hora argentina). Tablero diario y datos: <a href="{DASHBOARD_URL}">{DASHBOARD_URL}</a></p>
</section>
</body></html>"""


def html_a_pdf(html_txt: str, destino: Path) -> None:
    from playwright.sync_api import sync_playwright

    footer = ("<div style='font-family:Inter,DejaVu Sans,sans-serif;font-size:7px;color:#898781;width:100%;"
              "padding:0 14mm;display:flex;justify-content:space-between'><span>Monitor de Dolarización · "
              "Reporte semanal</span><span><span class='pageNumber'></span> / "
              "<span class='totalPages'></span></span></div>")
    with sync_playwright() as pw:
        kwargs = {}
        exe = shutil.which("chromium") or shutil.which("chromium-browser")
        local = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        if local.exists():
            kwargs["executable_path"] = str(local)
        elif exe:
            kwargs["executable_path"] = exe
        browser = pw.chromium.launch(**kwargs)
        page = browser.new_page()
        page.set_content(html_txt, wait_until="load")
        page.pdf(path=str(destino), format="A4", print_background=True, display_header_footer=True,
                 header_template="<div></div>", footer_template=footer,
                 margin={"top": "14mm", "bottom": "16mm", "left": "14mm", "right": "14mm"})
        browser.close()


def generar(ref: date) -> Path:
    semana = semana_anterior(ref)
    p = pd.read_csv(PANEL_CSV, index_col=0, parse_dates=True)
    payload = json.loads(config.OUTPUT_JSON.read_text(encoding="utf-8"))
    html_txt = construir_html(semana, p, payload)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    destino = REPORTS_DIR / f"reporte-semanal-{semana.viernes:%Y-%m-%d}.pdf"
    (REPORTS_DIR / "ultimo.html").write_text(html_txt, encoding="utf-8")
    html_a_pdf(html_txt, destino)
    shutil.copyfile(destino, REPORTS_DIR / "ultimo.pdf")
    log.info("Reporte de la semana del %s: %s", semana.etiqueta, destino)
    return destino


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fecha", help="fecha de referencia AAAA-MM-DD (se informa la semana anterior)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ref = date.fromisoformat(args.fecha) if args.fecha else date.today()
    generar(ref)


if __name__ == "__main__":
    main()
