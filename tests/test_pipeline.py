"""Pruebas del pipeline con respuestas HTTP simuladas (sin red).

Los datos que generan estas pruebas son SINTÉTICOS: sirven para verificar la
mecánica (parseo, alineación, IPD, JSON), no para análisis.
"""

import json

import numpy as np
import pandas as pd
import pytest

from monitor import build, config, indicators, sources


def _dates(n=900):
    return pd.bdate_range("2023-01-02", periods=n)


def _synthetic():
    rng = np.random.default_rng(0)
    d = _dates()
    n = len(d)
    shock = np.zeros(n)
    shock[700:720] = np.linspace(0, 1, 20)  # episodio de presión simulado
    shock[720:] = 1
    tc = 800 * np.exp(np.cumsum(0.0008 + 0.004 * rng.standard_normal(n) + 0.01 * (np.arange(n) >= 700) * (np.arange(n) < 720)))
    return {
        "fechas": d,
        "tc": tc,
        "ccl": tc * (1.1 + 0.25 * shock + 0.01 * rng.standard_normal(n)),
        "reservas": 30000 - np.cumsum(5 * rng.standard_normal(n)) - 2000 * shock,
        "badlar": 40 + np.cumsum(0.1 * rng.standard_normal(n)) + 10 * shock,
        "riesgo": 1500 + np.cumsum(5 * rng.standard_normal(n)) + 600 * shock,
    }


@pytest.fixture
def fake_api(monkeypatch, tmp_path):
    syn = _synthetic()
    fechas = [x.strftime("%Y-%m-%d") for x in syn["fechas"]]

    catalog = [
        {"idVariable": 1, "descripcion": "Reservas Internacionales del BCRA (en millones de dólares)"},
        {"idVariable": 5, "descripcion": "Tipo de cambio mayorista de referencia"},
        {"idVariable": 7, "descripcion": "BADLAR en pesos de bancos privados (en % n.a.)"},
    ]
    by_id = {1: syn["reservas"], 5: syn["tc"], 7: syn["badlar"]}

    def fake_get_json(url, params=None, verify=True, retries=4):
        if url.endswith("/monetarias"):
            return {"status": 200, "results": catalog}
        if "/monetarias/" in url:
            var = int(url.rsplit("/", 1)[1])
            if var not in by_id:
                return {"status": 200, "results": []}
            desde, hasta = params["desde"], params["hasta"]
            det = [{"fecha": f, "valor": float(v)} for f, v in zip(fechas, by_id[var]) if desde <= f <= hasta]
            # formato v4: results -> [{idVariable, detalle}]
            return {"status": 200, "results": [{"idVariable": var, "detalle": det}]}
        if url == sources.A3_CLOSING_PRICES:
            # Un contrato por mes, vence a fin del mes siguiente; 2 páginas de 100.
            if params["from"] < "2025-01-01":
                return {"pageSize": 100, "page": 1, "totalEntries": 0, "data": []}
            rows = []
            for f, spot in zip(fechas, syn["tc"]):
                if not (params["from"] <= f <= params["to"]):
                    continue
                venc = pd.Timestamp(f) + pd.offsets.MonthEnd(2)
                rows.append({"dateTime": f + "T00:00:00.000Z",
                             "symbol": f"DLR{venc.month:02d}{venc.year}",
                             "settlement": float(spot) * 1.03, "openInterest": 1000.0,
                             "volume": 10, "impliedRate": 30.0})
            page = params["page"]
            return {"pageSize": 100, "page": page, "totalEntries": len(rows),
                    "data": rows[(page - 1) * 100: page * 100]}
        if url.endswith("/riesgo-pais"):
            return [{"fecha": f, "valor": float(v)} for f, v in zip(fechas, syn["riesgo"])]
        if "/cotizaciones/dolares/" in url:
            casa = url.rsplit("/", 1)[1]
            serie = {"contadoconliqui": syn["ccl"], "bolsa": syn["ccl"] * 0.99,
                     "blue": syn["ccl"] * 1.02, "oficial": syn["tc"] * 1.05,
                     "mayorista": syn["tc"]}[casa]
            return [{"casa": casa, "compra": float(v) * 0.98, "venta": float(v), "fecha": f}
                    for f, v in zip(fechas, serie)]
        raise AssertionError(f"URL inesperada: {url}")

    monkeypatch.setattr(sources, "get_json", fake_get_json)
    monkeypatch.setattr(sources, "bcra_compras_personas_humanas", lambda: pd.DataFrame({
        "fecha": ["2025-01", "2025-02"], "compras_usd_millones": [1500.0, 1800.0],
        "ventas_usd_millones": [300.0, 250.0], "fuente": ["test", "test"]}))
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SERIES_DIR", tmp_path / "series")
    monkeypatch.setattr(config, "OUTPUT_JSON", tmp_path / "monitor.json")
    monkeypatch.setattr(config, "START_DATE", "2023-01-01")
    return syn, tmp_path


def test_run_end_to_end(fake_api):
    syn, tmp = fake_api
    payload = build.run()
    assert (tmp / "monitor.json").exists()
    assert (tmp / "panel_diario.csv").exists()
    assert set(payload["series"]) >= {"tc_oficial_ref", "brecha_ccl", "riesgo_pais", "reservas",
                                      "tasa", "deval_implicita", "futuros_interes_abierto"}
    fut = pd.read_csv(tmp / "series" / "futuros_dolar.csv")
    # Paginación: todas las fechas hábiles de 2025 en adelante, sin duplicados.
    assert fut["fecha"].nunique() == sum(1 for x in syn["fechas"] if x.year >= 2025)
    assert not fut.duplicated(["fecha", "contrato"]).any()
    h = payload["headline"]
    assert h["ipd"] is not None
    # El shock simulado debe verse como presión alta al inicio del episodio.
    ipd = dict(payload["ipd"]["data"])
    fecha_shock = syn["fechas"][715].strftime("%Y-%m-%d")
    fecha_calma = syn["fechas"][600].strftime("%Y-%m-%d")
    assert ipd[fecha_shock] > ipd[fecha_calma] + 1
    ph = payload["monthly"]["compras_personas_humanas"]
    assert [r["fecha"] for r in ph] == ["2025-01", "2025-02"]
    assert ph[1]["netas_usd_millones"] == pytest.approx(1550.0)
    assert payload["ipd"]["n_components"]
    json.loads((tmp / "monitor.json").read_text())


def test_failed_source_keeps_cache(fake_api, monkeypatch):
    _, tmp = fake_api
    build.run()
    before = build.load_cached("riesgo_pais")

    def broken(*a, **k):
        raise RuntimeError("caído")

    monkeypatch.setattr(sources, "argentinadatos_riesgo_pais", broken)
    payload = build.run()
    assert payload["sources_status"]["riesgo_pais"].startswith("error")
    pd.testing.assert_series_equal(build.load_cached("riesgo_pais"), before)


def test_implied_devaluation():
    fut = pd.DataFrame({
        "fecha": ["2026-01-05"] * 3,
        "contrato": ["DLR012026", "DLR022026", "DLR042026"],
        "vencimiento": ["2026-01-15", "2026-02-27", "2026-04-30"],
        "precio_ajuste": [1010.0, 1030.0, 1060.0],
        "interes_abierto": [100, 200, 50],
        "tasa_implicita_a3": [np.nan, 20.0, 26.0],
    })
    spot = pd.Series([1000.0], index=pd.to_datetime(["2026-01-05"]))
    out = indicators.implied_devaluation(fut, spot)
    # ENE26 (10 días) se descarta; 90 días cae entre FEB26 (53 d) y ABR26 (115 d).
    expected = 20.0 + (90 - 53) / (115 - 53) * 6.0
    assert out["deval_implicita"].iloc[0] == pytest.approx(expected)
    assert out["deval_implicita_mensual"].iloc[0] == pytest.approx(expected * 30 / 365)
    assert out["futuros_interes_abierto"].iloc[0] == 350


def test_implied_devaluation_sin_tasa_a3():
    fut = pd.DataFrame({"fecha": ["2026-01-05"], "contrato": ["DLR042026"],
                        "vencimiento": ["2026-04-05"], "precio_ajuste": [1050.0]})
    spot = pd.Series([1000.0], index=pd.to_datetime(["2026-01-05"]))
    out = indicators.implied_devaluation(fut, spot)
    assert out["deval_implicita"].iloc[0] == pytest.approx(5.0 * 365 / 90)


def test_weighted_mean_requires_min_weight():
    frame = pd.DataFrame({"a": [1.0, np.nan], "b": [3.0, np.nan], "c": [np.nan, 2.0]})
    out = indicators._weighted_mean(frame, {"a": 1, "b": 1, "c": 1})
    assert out.iloc[0] == pytest.approx(2.0)
    assert np.isnan(out.iloc[1])  # sólo 1/3 del peso disponible


def test_a3_expiry():
    assert sources._a3_expiry("DLR102026") == pd.Timestamp("2026-10-30")
    assert sources._a3_expiry("DLR052026") == pd.Timestamp("2026-05-29")  # 31/5 es domingo
    assert sources._a3_expiry("DLR/SPOT") is None


def test_parse_compras_personas_humanas():
    datos = pd.DataFrame({
        "Anexo": [65, 66, 63, 65, 23],
        "Mes": pd.to_datetime(["2025-05-01"] * 4 + ["2025-05-01"]),
        "Sector": ["Personas Humanas", "Personas Humanas", "Personas Humanas", "Comercio", "Personas Humanas"],
        "Monto": [-2_000_000_000, -500_000_000, 400_000_000, -9e9, -1e8],
        "A": ["03- Cuenta Financiera"] * 4 + ["01- Cuenta Corriente"],
        "B": ["03- Compra-venta de billetes y divisas sin fines específicos"] * 4 + ["02- Servicios"],
        "C": ["02- Compra de billetes y divisas sin fines específicos",
              "02- Compra de billetes y divisas sin fines específicos",
              "01- Venta de billetes y divisas sin fines específicos",
              "02- Compra de billetes y divisas sin fines específicos",
              "02- Servicios - Egresos"],
        "D": ["Billetes - Egresos", "Otras inversiones", "Billetes - Ingresos", "Billetes - Egresos", "x"],
    })
    out = sources.parse_compras_personas_humanas(datos)
    assert list(out["fecha"]) == ["2025-05"]
    assert out["compras_usd_millones"].iloc[0] == pytest.approx(2500.0)
    assert out["ventas_usd_millones"].iloc[0] == pytest.approx(400.0)


def test_pressure_index_scale():
    ipd = pd.Series([0.0] * 20 + [1.0] * 20 + [-1.0] * 20)
    indice, sigma = indicators.pressure_index(ipd)
    assert indice.iloc[19] == pytest.approx(50.0)
    assert indice.iloc[-1] < 50 < indice.iloc[39]
    assert indice.dropna().between(0, 100).all()
    assert indicators.status_for(50.0)[0] == "neutral"
    assert indicators.status_for(95.0)[0] == "deprec_fuerte"
    assert indicators.status_for(100.0)[0] == "deprec_fuerte"
    assert indicators.status_for(3.0)[0] == "aprec_fuerte"


def test_robust_z_ignora_outliers():
    rng = np.random.default_rng(1)
    x = pd.Series(np.r_[rng.standard_normal(200), [80.0], rng.standard_normal(40), [3.0]])
    z = indicators.rolling_z(x, window=300, min_obs=50, clip=4.0)
    # Con media/desvío, el 80 inflaría la escala y el 3 quedaría cerca de 0,5.
    assert z.iloc[-1] > 2.5


def test_realized_vol():
    s = pd.Series(np.exp(np.cumsum([0.01, -0.01] * 30)))
    v = indicators.realized_vol(s, 20)
    assert v.iloc[-1] == pytest.approx(0.01 * np.sqrt(20 / 19) * np.sqrt(252) * 100, rel=1e-6)
