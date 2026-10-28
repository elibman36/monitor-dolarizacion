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
import re
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
# Racconto de la semana, escrito a mano: reportes/textos/AAAA-MM-DD.md, con la
# fecha del viernes de la semana informada.
TEXTOS_DIR = REPORTS_DIR / "textos"
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


def chart_indice_anual(indice: pd.Series, semana: Semana) -> str:
    s = indice[semana.viernes - pd.DateOffset(months=18): semana.viernes]
    fig, ax = plt.subplots(figsize=(7.2, 2.0))
    _bandas(ax)
    ax.axvspan(semana.lunes, semana.viernes + pd.Timedelta(days=1), color=INK, alpha=0.08, lw=0, zorder=2)
    _linea_tramos(ax, s)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%y"))
    return _svg(fig)


def chart_subindices(indice: pd.Series, subs: list[tuple[str, pd.Series, str]], semana: Semana) -> str:
    """Índice y subíndices (cada uno en su escala 0-100), últimos 18 meses."""
    desde = semana.viernes - pd.DateOffset(months=18)
    fig, ax = plt.subplots(figsize=(7.2, 2.4))
    _bandas(ax)
    for nombre, s, color in subs:
        s = s[(s.index >= desde) & (s.index <= semana.viernes)].dropna()
        ax.plot(s.index, s.values, color=color, lw=1.3, label=nombre)
    ax.axhline(50, color=AXIS, lw=0.8)
    ax.axvspan(semana.lunes, semana.viernes, color=GRID, alpha=0.6, lw=0)
    ax.set_ylim(0, 100); ax.set_yticks([0, 25, 50, 75, 100])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%y"))
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, fontsize=7.5, frameon=False, handlelength=1.6, borderaxespad=0.3)
    return _svg(fig)


def _celda_delta(d: float, marca: str = "") -> str:
    if d is None or not np.isfinite(d):
        return "<td class='num muted'>–</td>"
    if abs(d) < 0.05:
        return "<td class='num muted'>0</td>"
    color = "#c4302b" if d > 0 else S1
    return f"<td class='num' style='color:{color}'>{'▲' if d > 0 else '▼'} {fmt(d, 1, signo=True)}{marca}</td>"


def _barra(v: float, escala: float) -> str:
    if v is None or not np.isfinite(v) or escala <= 0:
        return "<td></td>"
    w = min(50, abs(v) / escala * 50)
    lado = f"left:50%;width:{w:.1f}%" if v >= 0 else f"right:50%;width:{w:.1f}%"
    color = "#e34948" if v >= 0 else S1
    return f"<td class='bar'><div><i style='{lado};background:{color}'></i></div></td>"


def _var_comp(perfil: dict, comp: str) -> str:
    """Columna de la variable que mide cada componente."""
    return perfil.get("alias", {}).get(comp, comp)


def _unidad_corta(v: dict) -> str:
    """Unidad del nivel (la de la variación la pone _txt_var)."""
    return v["unidad"].split(",")[0].strip()


def _celda_aporte(v: float, negrita: bool = False) -> str:
    if v is None or not np.isfinite(v):
        return "<td class='num muted'>–</td>"
    if abs(v) < 0.05:
        return "<td class='num muted'>0</td>"
    color = "#c4302b" if v > 0 else S1
    b = "font-weight:700;" if negrita else ""
    return f"<td class='num' style='color:{color};{b}'>{'▲' if v > 0 else '▼'} {fmt(v, 1, signo=True)}</td>"


def _txt_variacion(v: dict | None) -> str:
    """Variación de la variable en la semana, en su unidad: millones de USD,
    pp, pb, % (precios) o % mensualizado (tipo de cambio real). Las series
    mensuales sin dato nuevo en la semana lo dicen."""
    if not v:
        return ""
    nueva, a, d = v["nueva"], v["a"], v["d"]
    if not nueva or ("mes" in v["unidad"] and a == 0):
        return "<span class='muted'>sin dato nuevo</span>"
    if a is None or not np.isfinite(a):
        return "–"
    if v["tipo"] == "abs":
        return f"{fmt(a, 0, signo=True)} {_unidad_corta(v).replace(' por mes', '')}"
    return _txt_var(d if v["tipo"] in ("pct", "pct_mens") else a, v["tipo"], v["dec"])


def _txt_dato(v: dict | None, previo: bool = False) -> str:
    """Valor de la variable al cierre de la semana (o de la anterior)."""
    if not v:
        return ""
    x = v["v_prev"] if previo else v["v"]
    if x is None or not np.isfinite(x):
        return "–"
    u = _unidad_corta(v).replace(" por mes", "")
    if u in ("%", "% anual", "% n.a.", "% TNA"):
        return f"{fmt(x, 1)}{'%' if u == '%' else ' ' + u}"
    return f"{fmt(x, v['dec'] if u.startswith('$') else 0)} {u}"


def tabla_aportes(blocks_cfg: dict, meta: dict, dpts: dict, sub1: dict, i1: float, i0: float,
                  datos: dict, perfil: dict) -> str:
    """Una fila por subíndice y componente: dato de la semana anterior, dato
    de esta semana, variación y aporte a la suba o a la baja del índice frente
    a la semana anterior (la columna suma el cambio del índice). Al final, el
    índice."""
    def suma(cols):
        vals = [dpts[c] for c in cols if c in dpts and np.isfinite(dpts[c])]
        return sum(vals) if vals else np.nan
    filas = []
    for bkey, b in blocks_cfg.items():
        cols = [c for c in b["components"] if c in dpts]
        if not cols:
            continue
        filas.append(f"<tr class='sub'><td>{html.escape(b['label'])}</td><td></td>"
                     f"<td class='num'>{fmt(sub1.get(bkey, np.nan), 0)}/100</td><td></td>"
                     f"{_celda_aporte(suma(cols), True)}</tr>")
        for c in sorted(cols, key=lambda c: -(meta.get(c, {}).get("weight") or 0)):
            vk = _var_comp(perfil, c)
            v = datos.get(vk)
            # El tipo de cambio real se muestra con el oficial en pesos y su
            # variación real, mensualizada.
            nivel = datos.get("tc_oficial_ref") if vk == "tcr" else v
            var = _txt_variacion(v)
            if vk == "tcr" and var.endswith("% mensual"):
                var = var.replace("% mensual", "% real mensual")
            filas.append(f"<tr><td class='comp'>{html.escape(b['components'][c]['label'])}</td>"
                         f"<td class='num muted'>{_txt_dato(nivel, previo=True)}</td><td class='num'>{_txt_dato(nivel)}</td>"
                         f"<td class='num'>{var}</td>{_celda_aporte(dpts[c])}</tr>")
    filas.append(f"<tr class='tot'><td>Índice</td><td class='num muted'>{fmt(i0, 0)}/100</td>"
                 f"<td class='num'>{fmt(i1, 0)}/100</td><td class='num'>{fmt(i1 - i0, 1, signo=True)} pts</td>"
                 f"{_celda_aporte(i1 - i0, True)}</tr>")
    cab = ("<thead><tr><th>Subíndice y componente</th>"
           "<th class='num'>Dato semana anterior</th><th class='num'>Dato esta semana</th><th class='num'>Variación</th>"
           "<th class='num'>Aporte a la suba o a la baja del índice (pts)</th></tr></thead>")
    return f"<table class='vars aportes'>{cab}<tbody>{''.join(filas)}</tbody></table>"


def chart_mini(series: list[tuple], titulo: str, unidad: str, semana: Semana) -> str:
    """Gráfico chico de los últimos seis meses. Una serie con un cuarto
    elemento "der" va en un eje propio a la derecha (p. ej. reservas netas,
    de otra magnitud que las brutas)."""
    fig, ax = plt.subplots(figsize=(1.85, 1.2))
    desde = semana.viernes - pd.DateOffset(months=6)
    der = None
    for nombre, s, color, *eje in series:
        if s is None:
            continue
        s = s[desde: semana.viernes].dropna()
        if s.empty:
            continue
        destino = ax
        if eje == ["der"]:
            if der is None:
                der = ax.twinx()
                der.tick_params(labelsize=6, colors=MUTED)
                der.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt(v / 1000, 0) + " mil"))
                der.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(3))
                ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(3))
                for lado in ("top", "left", "bottom"):
                    der.spines[lado].set_visible(False)
            destino = der
        destino.plot(s.index, s.values, color=color, lw=1.4, label=nombre, zorder=3)
    ax.axvspan(semana.lunes, semana.viernes + pd.Timedelta(days=1), color=INK, alpha=0.07, lw=0)
    ax.set_title(titulo, loc="left", fontsize=8, color=INK, fontweight="bold", pad=10)
    ax.text(0, 1.02, unidad, transform=ax.transAxes, fontsize=6.5, color=MUTED)
    # Un rótulo por mes, desde el primer mes del período (abr, may, jun...).
    ax.set_xlim(desde.replace(day=1), semana.viernes + pd.Timedelta(days=3))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: MESES[mdates.num2date(x).month - 1]))
    ax.tick_params(labelsize=6)
    if len(series) > 1:
        h, l = ax.get_legend_handles_labels()
        if der is not None:
            h2, l2 = der.get_legend_handles_labels()
            h, l = h + h2, l + l2
        ax.legend(h, l, fontsize=5.8, frameon=False, loc="upper left", ncol=len(series), handlelength=1.0,
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
    # Tipo de cambio real: el oficial deflactado por el CER; su variación,
    # mensualizada.
    ("tcr", "Tipo de cambio real (oficial / CER)", "índice", 2, "pct_mens"),
    ("usd_mep", "Dólar MEP", "$ por USD", 1, "pct"),
    ("usd_ccl", "Dólar CCL", "$ por USD", 1, "pct"),
    ("brecha_mep", "Brecha MEP / oficial", "%", 1, "pp"),
    ("canje", "Canje (CCL / MEP)", "%", 1, "pp"),
    ("vol_oficial", "Volatilidad del oficial (20 días)", "% anual", 1, "pp"),
    ("riesgo_pais", "Riesgo país", "pb", 0, "pb"),
    ("reservas", "Reservas internacionales brutas", "M USD", 0, "abs"),
    ("tasa", "Tasa BADLAR privados", "% n.a.", 2, "pp"),
    ("deval_implicita", "Devaluación implícita en futuros (90 días)", "% TNA", 1, "pp"),
    ("futuros_oi_musd", "Posición abierta en futuros de dólar (promedio de 21 días)", "M USD", 0, "abs"),
    ("posicion_bcra", "Futuros vendidos por el BCRA (neto)", "M USD, último fin de mes publicado", 0, "abs"),
    ("depositos_usd", "Depósitos en USD del sector privado", "M USD", 0, "abs"),
    ("compras_ph", "Compras netas de USD de personas humanas (FAE)", "M USD por mes, último mes publicado", 0, "abs"),
    ("vol_ccl", "Volatilidad del CCL (20 días)", "% anual", 1, "pp"),
]


def _variacion(v1, v0, tipo, dias: float = 7):
    if not (np.isfinite(v1) and np.isfinite(v0)):
        return np.nan
    if tipo == "pct_mens":  # variación de `dias` corridos llevada a 30 días
        return ((v1 / v0) ** (30 / dias) - 1) * 100
    return (v1 / v0 - 1) * 100 if tipo == "pct" else v1 - v0


def _txt_var(d, tipo, dec):
    suf = {"pct": "%", "pct_mens": "% mensual", "pp": " pp", "pb": " pb", "abs": ""}[tipo]
    return fmt(d, 1 if tipo in ("pct", "pct_mens", "pp") else dec, signo=True, sufijo=suf)


def tabla_variables(p: pd.DataFrame, semana: Semana, variables: list | None = None) -> tuple[str, dict]:
    filas, datos = [], {}
    cierre_prev = semana.viernes - pd.Timedelta(days=7)
    hace4 = semana.viernes - pd.Timedelta(days=28)
    for col, label, unidad, dec, tipo in (variables or VARIABLES):
        if col not in p:
            continue
        f1, v1 = _hasta(p[col], semana.viernes)
        _, v0 = _hasta(p[col], cierre_prev)
        _, v4 = _hasta(p[col], hace4)
        d1, d4 = _variacion(v1, v0, tipo), _variacion(v1, v4, tipo, 28)
        a1, a4 = _variacion(v1, v0, "abs"), _variacion(v1, v4, "abs")
        # "nueva": hubo dato en la semana (una serie que la fuente dejó de
        # actualizar no se comenta en el resumen).
        datos[col] = {"v": v1, "d": d1, "d4": d4, "a": a1, "a4": a4, "fecha": f1, "nueva": f1 is not None and f1 >= semana.lunes,
                      "v_prev": v0,
                      "label": label, "unidad": unidad, "dec": dec, "tipo": tipo}
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


def _frase(comp: str, pts: float, frases: dict | None = None) -> str:
    sube, baja = (frases or FRASES).get(comp, (comp, comp))
    return f"{sube if pts > 0 else baja} ({fmt(pts, 0, signo=True)} pts)"


def _pts(x: float) -> str:
    """Puntos redondeados con signo; un cambio que redondea a cero se escribe 0."""
    return "0" if round(x) == 0 else fmt(x, 0, signo=True)


def _pts1(x: float) -> str:
    return "0" if abs(x) < 0.05 else fmt(x, 1, signo=True)


def _md_inline(t: str) -> str:
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<i>\1</i>", t)
    return t


def racconto(viernes: pd.Timestamp, dir_: Path | None = None) -> str:
    """El texto de la semana (Markdown simple: párrafos, **negrita**, *cursiva*
    y listas con «- »), en HTML. Vacío si no hay archivo para ese viernes. Los
    comentarios <!-- ... --> no se publican."""
    f = (dir_ or TEXTOS_DIR) / f"{viernes:%Y-%m-%d}.md"
    if not f.exists():
        return ""
    txt = re.sub(r"<!--.*?-->", "", f.read_text(encoding="utf-8"), flags=re.S).strip()
    bloques = []
    for b in re.split(r"\n\s*\n", txt):
        lineas = [l.strip() for l in b.strip().splitlines() if l.strip()]
        if lineas and lineas[0].startswith("#"):
            bloques.append(f"<h3>{_md_inline(lineas[0].lstrip('#').strip())}</h3>")
            lineas = lineas[1:]
        if not lineas:
            continue
        if all(l.startswith(("- ", "* ")) for l in lineas):
            bloques.append("<ul>" + "".join(f"<li>{_md_inline(l[2:])}</li>" for l in lineas) + "</ul>")
        else:
            bloques.append(f"<p>{_md_inline(' '.join(lineas))}</p>")
    return "".join(bloques)


def _movimiento(label: str, pts: float) -> str:
    """"canje (+0,8 pts)": cuántos puntos movió la variable al índice."""
    return f"{_corto(label)} ({_pts1(pts)} pts)"


def _corto(label: str) -> str:
    return _minus(label.split(" (")[0])


def resumen(indice, semana, dpts: dict, perfil: dict | None = None) -> list[str]:
    """Resumen en palabras: dónde quedó el índice respecto de 50, cuánto cambió
    frente al viernes anterior, sus principales aportes a la suba y a la baja
    y el aporte de cada subíndice (los aportes suman el cambio del índice)."""
    perfil = perfil or PERFIL_AR
    blocks_cfg = perfil["blocks"]
    _, i1 = _hasta(indice, semana.viernes)
    _, i0 = _hasta(indice, semana.viernes - pd.Timedelta(days=7))
    tramo = indicators.status_for(i1)[1].lower()
    labels = {c: spec["label"] for b in blocks_cfg.values() for c, spec in b["components"].items()}
    puntos = []
    if not np.isfinite(i1):
        return puntos
    dist = i1 - 50
    if abs(dist) < 0.5:
        donde = "en 50, el punto neutral"
    else:
        donde = f"{fmt(abs(dist), 0)} {'punto' if round(abs(dist)) == 1 else 'puntos'} {'por encima' if dist > 0 else 'por debajo'} de 50"
    puntos.append(f"El índice cerró la semana en <b>{fmt(i1, 0)}/100</b> ({tramo}): {donde}.")
    if not np.isfinite(i0):
        return puntos
    d = i1 - i0
    cambio = "sin cambios" if abs(d) < 0.05 else f"{'subió' if d > 0 else 'bajó'} {fmt(abs(d), 1)} puntos"
    puntos.append(f"<b>Frente al viernes anterior</b> ({fmt(i0, 1)}), {cambio}.")
    pc = {k: v for k, v in dpts.items() if np.isfinite(v)}
    for signo, titulo in ((1, "Principales aportes a la suba"), (-1, "Principales aportes a la baja")):
        comps = sorted((k for k in pc if signo * pc[k] >= 0.1), key=lambda k: -abs(pc[k]))[:5]
        if comps:
            puntos.append(f"<b>{titulo}</b>: " + "; ".join(_movimiento(labels[k], pc[k]) for k in comps) + ".")
    por_bloque = [f"{_minus(b['label'])} ({_pts1(sum(pc[c] for c in b['components'] if c in pc))} pts)"
                  for b in blocks_cfg.values() if any(c in pc for c in b["components"])]
    if por_bloque:
        puntos.append("<b>Por subíndice</b>: " + "; ".join(por_bloque) + ".")
    return puntos


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
.racconto p { margin: 4pt 0 0; font-size: 9.5pt; line-height: 1.5; }
.racconto ul { margin: 4pt 0 0; padding-left: 14pt; } .racconto li { margin: 2pt 0; }
.racconto h3 { font-size: 9.5pt; margin: 8pt 0 0; }
table.vars { width: 100%; border-collapse: collapse; font-size: 8.3pt; }
table.vars th { text-align: left; color: #52514e; font-weight: 600; border-bottom: 1px solid #c3c2b7; padding: 4pt 4pt; }
table.vars td { border-bottom: 1px solid #eeede8; padding: 2.1pt 4pt; vertical-align: top; }
table.vars .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10pt; }
.g-sub { grid-template-columns: 1.6fr 1fr; }
.subs-t { margin-top: 8pt; font-size: 7.5pt; color: #898781; }
.kv.subs { margin-top: 3pt; }
.kv.subs span { display: flex; align-items: center; gap: 4pt; }
.kv.subs i { display: inline-block; width: 8pt; height: 2.5pt; border-radius: 1pt; }
.kv.subs small { font-weight: 400; color: #52514e; }
table.aportes td.comp { padding-left: 12pt; color: #52514e; }
table.aportes tr.sub td { font-weight: 700; color: #0b0b0b; border-top: 1px solid #c3c2b7; }
table.aportes tr.tot td { font-weight: 700; border-top: 1.5px solid #0b0b0b; }
table.aportes tr.otras td { font-weight: 700; color: #52514e; padding-top: 8pt; border-bottom: 1px solid #c3c2b7; }
table.aportes { font-size: 7.8pt; }
.card.partible { break-inside: auto; }
table.aportes tr { break-inside: avoid; }
table.aportes thead { display: table-header-group; }
table.aportes .muted { color: #898781; font-weight: 400; }
table.aportes th.bar, table.aportes td.bar { width: 12%; }
table.aportes th.c { text-align: center; border-bottom: 1px solid #c3c2b7; padding-bottom: 2pt; }
table.aportes tr.grupo th { border-bottom-width: 0; }
table.aportes tr.grupo th.c { border-bottom: 1px solid #c3c2b7; }
table.aportes th[rowspan] { vertical-align: bottom; border-bottom: 1px solid #c3c2b7; }
table.aportes td:first-child, table.aportes th:first-child { width: 25%; }
table.aportes td.bar div { position: relative; height: 8pt; }
table.aportes td.bar div::after { content: ""; position: absolute; left: 50%; top: -2pt; bottom: -2pt; border-left: 1px solid #c3c2b7; }
table.aportes td.bar i { position: absolute; top: 0; bottom: 0; border-radius: 1.5pt; }
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
.apendice td { vertical-align: top; font-size: 7.4pt; line-height: 1.3; padding: 2.5pt 4pt; }
.apendice tr.sub td { background: #f6f5f1; padding-top: 4pt; }
.apendice ul { margin: 0 0 6pt; padding-left: 13pt; color: #333; } .apendice li { margin-bottom: 3pt; }
a { color: #2a78d6; text-decoration: none; }
"""


def _serie_payload(payload: dict | None, key: str) -> pd.Series | None:
    datos = ((payload or {}).get("series", {}).get(key) or {}).get("data")
    if not datos:
        return None
    return pd.Series([v for _, v in datos], index=pd.to_datetime([f for f, _ in datos]), dtype=float)


def _minis_ar(p: pd.DataFrame, semana: Semana, payload: dict | None = None) -> list[str]:
    return [
        chart_mini([("Oficial", p["tc_oficial_ref"], S1), ("MEP", p.get("usd_mep"), S2), ("CCL", p.get("usd_ccl"), S3)],
                   "Tipo de cambio", "$ por USD", semana),
        chart_mini([("Brecha MEP", p.get("brecha_mep"), S1), ("Canje", p.get("canje"), S2)],
                   "Brecha MEP / oficial y canje", "%", semana),
        chart_mini([("Riesgo país", p["riesgo_pais"], S1)], "Riesgo país", "pb", semana),
        # Netas: dato de fin de mes de la planilla de reservas (formato FMI).
        chart_mini([("Brutas", p["reservas"], S1), ("Netas", _serie_payload(payload, "reservas_netas"), S2, "der"),
                    ("Sin FMI", _serie_payload(payload, "reservas_netas_sin_fmi"), S3, "der")],
                   "Reservas", "M USD; netas, eje derecho", semana),
        chart_mini([("Futuros", p.get("deval_implicita"), S1)], "Devaluación implícita", "% TNA a 90 días", semana),
        # Cada contrato es de USD 1.000: miles de contratos = millones de USD.
        chart_mini([("Posición abierta", p.get("futuros_interes_abierto") / 1000 if "futuros_interes_abierto" in p else None, S1),
                    ("Vendida por el BCRA", p.get("posicion_bcra"), S2)],
                   "Futuros de dólar", "millones de USD", semana),
        chart_mini([("Depósitos", p.get("depositos_usd"), S1)], "Depósitos en USD", "millones de USD", semana),
        chart_mini([("Oficial", p.get("vol_oficial"), S1), ("CCL", p.get("vol_ccl"), S2)],
                   "Volatilidad cambiaria", "% anualizada, 20 días", semana),
    ]



# Clave de lo que deja de contar de la semana anterior (no se muestra: los
# aportes de la semana no suman el cambio del índice).
APENDICE_FLUJOS = '<b>Por su movimiento de la semana</b> (tipo de cambio real, reservas, BADLAR, depósitos en dólares y riesgo país). Se miden por cuánto se movieron en los últimos 5 días, centrado en cero: unas reservas que suben restan y un riesgo país que sube suma. Su aporte al cambio del índice compara el movimiento de esta semana con el de la anterior: si las reservas suben menos que la semana pasada, el índice sube; si el riesgo país sube lo mismo dos semanas seguidas, no lo mueve.'


def construir_html(semana: Semana, p: pd.DataFrame, payload: dict, perfil: dict | None = None) -> str:
    perfil = perfil or PERFIL_AR
    blocks_cfg = perfil["blocks"]
    indice = p["indice_0_100"]
    f_cierre, i1 = _hasta(indice, semana.viernes)
    if f_cierre is None:
        raise SystemExit("No hay datos del índice para la semana pedida.")
    _, i0 = _hasta(indice, semana.viernes - pd.Timedelta(days=7))
    _, i4 = _hasta(indice, semana.viernes - pd.Timedelta(days=28))
    tramo_key, tramo_label = indicators.status_for(i1)

    labels = {c: spec["label"] for b in blocks_cfg.values() for c, spec in b["components"].items()}
    meta = {c["key"]: c for c in payload["ipd"]["components"]}
    pts_cierre = {c: _hasta(p[f"pts_{c}"], semana.viernes)[1] for c in labels if f"pts_{c}" in p}
    sub1 = {b: _hasta(p[f"indice_bloque_{b}"], semana.viernes)[1] for b in blocks_cfg if f"indice_bloque_{b}" in p}
    colores_sub = dict(zip(blocks_cfg, [S1, S2, S3]))
    dpts = indicators.cambio_por_componente(p, semana.viernes, list(pts_cierre))
    sub_pts = {b: sum(pts_cierre[c] for c in blocks_cfg[b]["components"] if c in pts_cierre and np.isfinite(pts_cierre[c]))
                for b in blocks_cfg}
    subs_hero = "".join(
        f"<span><i style='background:{colores_sub[b]}'></i>{html.escape(blocks_cfg[b]['label'])}</span>"
        f"<b>{fmt(sub1[b], 0)}/100 <small>({_pts1(sub_pts.get(b, np.nan))} pts)</small></b>"
        for b in blocks_cfg if b in sub1 and np.isfinite(sub1[b]))
    sub_svg = chart_subindices(indice, [(blocks_cfg[b]["label"], p[f"indice_bloque_{b}"], colores_sub[b]) for b in sub1], semana) if sub1 else ""

    if "futuros_oi" in p:
        # Cada contrato es de USD 1.000: miles de contratos = millones de USD. Es
        # el promedio de 21 días que usa el índice, no el dato del día.
        p = p.assign(futuros_oi_musd=p["futuros_oi"] / 1000)
    if "cer" in p and "tc_oficial_ref" in p:
        p = p.assign(tcr=p["tc_oficial_ref"] / p["cer"].ffill() * 100)
    tabla, datos = tabla_variables(p, semana, perfil["variables"])
    for b in blocks_cfg.values():
        for c, spec in b["components"].items():
            vk = _var_comp(perfil, c)
            if spec.get("transform") in ("level", "desvio_12m") and vk in datos and vk in p:
                x = p[vk][p.index <= semana.viernes].dropna()
                datos[vk]["habitual"] = (x.tail(config.IPD_ZSCORE_WINDOW).median() if spec["transform"] == "level"
                                         else x.tail(252).mean())
    pesos_b = {b: (payload["ipd"]["blocks"].get(b, {}).get("weight") or blocks_cfg[b]["weight"]) for b in blocks_cfg}
    tabla_html = tabla_aportes(blocks_cfg, meta, dpts, sub1, i1, i0, datos, perfil)
    puntos = resumen(indice, semana, dpts, perfil)
    texto_semana = racconto(semana.viernes)

    gauge = "".join(f"<span style='flex:{min(hi, 100) - lo};background:{TRAMO_COLOR[k]}'></span>"
                    for lo, hi, k, _ in config.INDICE_TRAMOS)
    gauge += f"<i style='left:{max(0, min(100, i1)):.1f}%'></i>"
    leyenda = "".join(f"<span style='--c:{TRAMO_COLOR[k]}'>{html.escape(l)} ({lo}–{int(min(hi, 100))})</span>"
                      for lo, hi, k, l in config.INDICE_TRAMOS)

    minis = perfil["minis"](p, semana, payload)
    compras = payload.get("monthly", {}).get("compras_personas_humanas", []) if perfil.get("fae") else []
    ph_svg = chart_compras_ph(compras)
    ph_ult = compras[-1] if compras else None

    comp_rows = "".join(
        f"<tr><td>{html.escape(b['label'])}</td><td>{html.escape(spec['label'])}</td>"
        f"<td class='num'>{fmt((meta.get(c, {}).get('weight') or 0) * 100, 0)}%</td>"
        f"<td class='num'>{fmt((meta.get(c, {}).get('weight_ipd') or 0) * 100, 1)}%</td></tr>"
        for b in blocks_cfg.values() for c, spec in b["components"].items())
    pca_cfg = payload.get("config", {}).get("pca", {})
    pca_txt = "; ".join(f"{blocks_cfg[k]['label'] if k in blocks_cfg else 'entre subíndices'}, {fmt(v['varianza_explicada'] * 100, 0)}%"
                        for k, v in pca_cfg.items())
    generado = pd.Timestamp.now(tz="America/Argentina/Buenos_Aires")

    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<header class="top">
  <div><h1>Monitor de Dolarización{perfil["titulo"]}</h1>
  <p class="sub">Reporte semanal · semana del {semana.etiqueta}</p></div>
  <div class="meta">Datos al {fecha_larga(f_cierre)}<br><a href="{DASHBOARD_URL}{perfil["query"]}">Tablero diario</a></div>
</header>

{perfil.get("aviso", "")}
<section class="hero">
  <div class="card">
    <h2>Índice de Dolarización</h2>
    <div class="muted">0 a 100 · 50 = neutral</div>
    <div class="num-big">{fmt(i1, 0)}<small>/100</small></div>
    <span class="pill" style="background:{TRAMO_COLOR.get(tramo_key, MUTED)}">{html.escape(tramo_label)}</span>
    <div class="gauge">{gauge}</div>
    <div class="scale"><span>0 apreciación</span><span>50</span><span>depreciación 100</span></div>
    <div class="kv">
      <span>Semana anterior</span><b>{fmt(i0, 0)} ({fmt(i1 - i0, 0, signo=True)} pts)</b>
      <span>Hace 4 semanas</span><b>{fmt(i4, 0)} ({fmt(i1 - i4, 0, signo=True)} pts)</b>
    </div>
    {f"<div class='subs-t'>Subíndices (0–100). Entre paréntesis, cuánto aporta cada uno a la distancia del índice a 50</div><div class='kv subs'>{subs_hero}</div>" if subs_hero else ""}
  </div>
  <div class="card">
    <h2>Resumen de la semana</h2>
    <ul class="res">{"".join(f"<li>{x}</li>" for x in puntos)}</ul>
  </div>
</section>

{f'''<section class="section card racconto">
  <h2>La semana</h2>
  {texto_semana}
</section>''' if texto_semana else ""}

<section class="section card partible">
  <h2>Qué explica el índice</h2>
  <p class="note">El dato de cada variable el viernes anterior y este, su variación y su aporte a la suba (rojo) o a la baja (azul) del índice frente a la semana anterior, en puntos: suman el cambio del índice. {perfil["nota_variables"]}</p>
  {tabla_html}
</section>

<section class="section card">
  <h2>Índice en los últimos 18 meses</h2>
  <p class="note"><a href="{DASHBOARD_URL}{perfil["query"]}">Versión interactiva</a></p>
  <div class="chart">{chart_indice_anual(indice, semana)}</div>
  <div class="legend">{leyenda}</div>
</section>

{f'''<section class="section card">
    <h2>Subíndices</h2>
    <div class="chart">{sub_svg}</div>
</section>''' if sub_svg else ""}

<section class="page">
  <div>
    <h2>Últimos seis meses</h2>
    <div class="grid3">{"".join(f"<div class='card chart'>{m}</div>" for m in minis)}</div>
  </div>
  {"" if not ph_svg else f'''<div class="section card">
    <h2>Compras netas de USD de personas humanas (FAE)</h2>
    <p class="note">Millones de USD por mes y promedio de 12 meses. BCRA.</p>    <div class="chart">{ph_svg}</div>
  </div>'''}
</section>

<section class="page method">
  <h2>Metodología</h2>
  {perfil["metodo"](pca_txt, pesos_b) if perfil["codigo"] == "ar" else perfil["metodo"](pca_txt)}
  <table><thead><tr><th>Subíndice</th><th>Componente</th><th class="num">Peso en el subíndice</th><th class="num">Peso en el índice</th></tr></thead><tbody>{comp_rows}</tbody></table>
  <p>El promedio ponderado de cada día se lleva a una escala de 0 a 100 con la normal acumulada, sin promediar días: el índice reacciona enseguida a los giros, aunque puede moverse bastante de un día a otro. 50 es neutral; debajo hay presión apreciatoria (alivio) y arriba, presión depreciatoria. Un valor de 90 indica una presión tan alta como la del 10% de los días más tensos desde 2003. Los aportes en puntos reparten la distancia del índice a 50 entre los componentes, así que suman exactamente esa distancia. Si falta un componente, su peso se reparte entre los demás de su subíndice. Cada subíndice también se lleva a su propia escala de 0 a 100 con el mismo método, para leerlo solo; en puntos del índice, los tres subíndices suman la distancia del índice a 50.{perfil["metodo_extra"]}</p>
  <p><b>Fuentes:</b> {perfil["fuentes"]}</p>
  <p class="muted">Generado el {generado.day}/{generado.month}/{generado.year} a las {generado:%H:%M} (hora argentina). Tablero diario y datos: <a href="{DASHBOARD_URL}">{DASHBOARD_URL}</a></p>
</section>
{apendice(perfil, meta)}
</body></html>"""


# ---------------------------------------------------------------------------
# Perfiles por país
# ---------------------------------------------------------------------------

def _metodo_ar(pca_txt: str, pesos_b: dict | None = None) -> str:
    pesos_sub_txt = (": " + ", ".join(f"{_minus(config.IPD_BLOCKS[b]['label'])} {fmt(w * 100, 0)}%" for b, w in pesos_b.items())
                     if pesos_b else "")
    return f"""<p>El Índice de Dolarización adapta el <i>Exchange Market Pressure Index</i> (Girton y Roper, 1977; Eichengreen, Rose y Wyplosz, 1996) a la economía bimonetaria argentina. Cada componente se transforma para que un valor más alto signifique más presión y se compara con los últimos dos años (mediana y desvío absoluto mediano, para que un episodio extremo no infle la escala). Para el oficial, las reservas, la BADLAR, los depósitos en dólares y el riesgo país, que se miden por su cambio en 5 días hábiles, el centro es cero y no la mediana: así una semana en que las reservas suben siempre resta presión, y una en que caen siempre suma (con la escala de sus dos años anteriores). Los componentes se agrupan en tres subíndices: <b>presión cambiaria</b> (tipo de cambio real (oficial deflactado por el CER), su volatilidad, reservas, tasa en pesos, brecha MEP / oficial y futuros de dólar vendidos por el BCRA, que son intervención como la venta de reservas), <b>dolarización de portafolios</b> (devaluación implícita y posición abierta en futuros de dólar, depósitos en dólares y compras de dólares de personas humanas: la demanda de cobertura) y <b>extranjerización de portafolios</b> (canje CCL / MEP, volatilidad del CCL y riesgo país). Dentro de cada subíndice, los pesos salen de componentes principales: cada componente pesa según cuánto se mueve junto con el resto (cargas del primer componente principal de los promedios mensuales desde 2003). Los tres subíndices se ponderan con el mismo método{pesos_sub_txt}. Las cargas negativas valen cero y ningún componente pesa menos del 10% de su subíndice. Varianza explicada por el primer componente: {pca_txt}.</p>"""


# Apéndice metodológico: para cada componente, cómo se mide, qué lo hace
# subir o bajar en la semana.
APENDICE_AR = {
    "tc_a3500": ("Variación del tipo de cambio real (oficial A3500 / CER) en 5 días hábiles.",
                 "Subió el tipo de cambio real: el peso se deprecia en términos reales.",
                 "Bajó el tipo de cambio real: apreciación real."),
    "vol_oficial": ("Volatilidad del oficial en los últimos 20 días hábiles, comparada con la de los dos años anteriores.",
                    "Subió la volatilidad del oficial: más incertidumbre sobre el precio del dólar.",
                    "Bajó la volatilidad del oficial: más calma en el mercado oficial."),
    "reservas": ("Variación de las reservas brutas del BCRA en 5 días hábiles.",
                 "Las reservas cayeron: el BCRA pierde poder de fuego para defender el peso.",
                 "Las reservas subieron: el BCRA acumula respaldo."),
    "tasa": ("Variación de la tasa BADLAR de bancos privados en 5 días hábiles (puntos porcentuales).",
             "Subió la tasa en pesos: hace falta pagar más para que no se pasen al dólar (defensa del peso).",
             "Bajó la tasa en pesos: no hace falta convalidar tasas altas para sostener el peso."),
    "brecha_mep": ("Brecha entre el dólar MEP y el oficial, comparada con los dos años anteriores.",
                   "Subió la brecha: el mercado paga más por el dólar libre que por el oficial.",
                   "Bajó la brecha: el oficial y el MEP se acercan."),
    "posicion_bcra": ("Cambio en un mes de la posición vendida en futuros de dólar del BCRA (planilla de reservas). Una posición comprada cuenta como cero.",
                      "El BCRA vendió más futuros que el mes anterior: interviene ofreciendo cobertura para contener la devaluación esperada.",
                      "El BCRA vendió menos futuros que el mes anterior, o redujo su posición."),
    "deval_implicita": ("Devaluación anual implícita en los futuros de dólar a 90 días (A3 Mercados), comparada con los dos años anteriores.",
                        "Los futuros anticipan más devaluación que la semana anterior.",
                        "Los futuros anticipan menos devaluación que la semana anterior."),
    "futuros_oi": ("Posición abierta en futuros de dólar, en millones de USD (promedio de 21 días hábiles), comparada con los dos años anteriores.",
                   "Subió la posición abierta: más gente busca cubrirse contra una devaluación.",
                   "Bajó la posición abierta: menos demanda de cobertura."),
    "depositos_usd": ("Variación de los depósitos en dólares del sector privado en 5 días hábiles.",
                      "Cayeron los depósitos en dólares: retiran dólares de los bancos, señal de desconfianza.",
                      "Crecieron los depósitos en dólares: más confianza en el sistema."),
    "compras_ph": ("Compras netas de dólares de personas humanas en el mes (FAE, balance cambiario del BCRA), comparadas con su promedio de 12 meses. Entra un mes después, cuando el BCRA la publica.",
                   "Las personas compraron más dólares que el mes anterior.",
                   "Las personas compraron menos dólares que el mes anterior."),
    "canje": ("Diferencia entre el dólar CCL y el MEP, comparada con los dos años anteriores.",
              "Subió el canje: se paga más por tener los dólares afuera que adentro.",
              "Bajó el canje: tener dólares afuera tiene menos premio."),
    "vol_ccl": ("Volatilidad del CCL en los últimos 20 días hábiles, comparada con la de los dos años anteriores.",
                "Subió la volatilidad del CCL: más incertidumbre en el dólar financiero.",
                "Bajó la volatilidad del CCL."),
    "riesgo_pais": ("Variación del riesgo país (EMBI Argentina) en 5 días hábiles, en puntos básicos.",
                    "Subió el riesgo país: más riesgo en la deuda argentina y más incentivo a salir de activos locales.",
                    "Bajó el riesgo país: mejora la confianza en los activos argentinos."),
}


def apendice(perfil: dict, meta: dict) -> str:
    """Apéndice metodológico: una fila por componente con cómo se mide y qué
    significa que haga subir o bajar el índice."""
    textos = perfil.get("apendice") or {}
    filas = []
    for b in perfil["blocks"].values():
        filas.append(f"<tr class='sub'><td colspan='4'><b>{html.escape(b['label'])}</b></td></tr>")
        for c, spec in b["components"].items():
            if c not in textos:
                continue
            como, sube, baja = textos[c]
            peso = meta.get(c, {}).get("weight_ipd")
            peso_txt = f"<br><span class='muted'>{fmt(peso * 100, 1)}% del índice</span>" if peso else ""
            filas.append(f"<tr><td><b>{html.escape(spec['label'])}</b>{peso_txt}</td><td>{html.escape(como)}</td>"
                         f"<td>{html.escape(sube)}</td><td>{html.escape(baja)}</td></tr>")
    if not filas:
        return ""
    return f"""<section class="page method apendice">
  <h2>Apéndice metodológico: qué mueve el índice</h2>
  <p>El índice mide cuánta presión hay sobre el peso: arriba de 50, presión hacia la depreciación; abajo, alivio. El reporte muestra primero cuántos puntos empuja cada variable el índice por encima o por debajo de 50 (suman la distancia del índice a 50) y después cuánto lo movió frente a la semana anterior. Lo que mueve el índice depende de cómo entra cada variable:</p>
  <ul>
    <li><b>Por su nivel</b> (volatilidades del oficial y del CCL, brecha, canje, devaluación implícita y posición abierta en futuros). Si la variable sube en la semana, el índice sube; si baja, baja. Que esté por encima o por debajo de lo habitual de los dos años anteriores define si, en el nivel, cuenta como presión o como calma: una volatilidad baja que sube empuja el índice hacia arriba, aunque todavía cuente como calma.</li>
    <li>{perfil.get("apendice_flujos", APENDICE_FLUJOS)}</li>
    <li><b>Contra una referencia</b>. Las compras de dólares de personas humanas se miden contra su promedio de 12 meses.</li>
  </ul>
  <p>Cuánto mueve el índice cada variable depende de qué tan grande es su cambio frente a lo que suele moverse en los dos años anteriores, y de su peso.</p>
  <table><thead><tr><th style="width:17%">Componente</th><th style="width:27%">Cómo se mide</th><th style="width:28%">Sube el índice en la semana si…</th><th style="width:28%">Baja el índice en la semana si…</th></tr></thead><tbody>{"".join(filas)}</tbody></table>
</section>"""


PERFIL_AR = {
    "codigo": "ar", "titulo": "", "query": "", "blocks": config.IPD_BLOCKS, "variables": VARIABLES,
    # Componente -> variable que lo mide, cuando no tienen el mismo nombre.
    "alias": {"tc_a3500": "tcr", "futuros_oi": "futuros_oi_musd"},
    "minis": _minis_ar, "fae": True, "metodo": _metodo_ar, "apendice": APENDICE_AR,
    "metodo_extra": " Las compras de dólares de personas humanas son mensuales, entran al índice un mes después del cierre de cada mes (cuando el BCRA las publica) y se miden contra su promedio de 12 meses, para no confundir la salida del cepo con presión.",
    "nota_variables": "Las reservas y los depósitos se publican con dos o tres días de rezago.",
    "fuentes": """BCRA (reservas, tipo de cambio A3500, BADLAR, depósitos en dólares, anexo del balance cambiario y planilla de reservas y liquidez en moneda extranjera), ArgentinaDatos (dólar MEP, CCL y blue; riesgo país) y A3 Mercados (futuros de dólar). Todas las series se descargan automáticamente.""",
    "panel": config.DATA_DIR / "panel_diario.csv", "json": config.OUTPUT_JSON, "salida": REPORTS_DIR,
}


PERFILES = {"ar": lambda: PERFIL_AR}


def html_a_pdf(html_txt: str, destino: Path, titulo: str = "Monitor de Dolarización") -> None:
    from playwright.sync_api import sync_playwright

    footer = ("<div style='font-family:Inter,DejaVu Sans,sans-serif;font-size:7px;color:#898781;width:100%;"
              "padding:0 14mm;display:flex;justify-content:space-between'><span>" + titulo + " · "
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


def generar(ref: date, pais: str = "ar") -> Path:
    perfil = PERFILES[pais]()
    semana = semana_anterior(ref)
    p = pd.read_csv(perfil["panel"], index_col=0, parse_dates=True)
    payload = json.loads(perfil["json"].read_text(encoding="utf-8"))
    html_txt = construir_html(semana, p, payload, perfil)
    salida = perfil["salida"]
    salida.mkdir(parents=True, exist_ok=True)
    destino = salida / f"reporte-semanal-{semana.viernes:%Y-%m-%d}.pdf"
    (salida / "ultimo.html").write_text(html_txt, encoding="utf-8")
    html_a_pdf(html_txt, destino, "Monitor de Dolarización" + perfil["titulo"])
    shutil.copyfile(destino, salida / "ultimo.pdf")
    log.info("Reporte de la semana del %s: %s", semana.etiqueta, destino)
    return destino


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fecha", help="fecha de referencia AAAA-MM-DD (se informa la semana anterior)")
    parser.add_argument("--pais", default="ar", choices=sorted(PERFILES), help="país (ar por defecto)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ref = date.fromisoformat(args.fecha) if args.fecha else date.today()
    generar(ref, args.pais)


if __name__ == "__main__":
    main()
