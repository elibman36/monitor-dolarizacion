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
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SERIES_DIR", tmp_path / "series")
    monkeypatch.setattr(config, "OUTPUT_JSON", tmp_path / "monitor.json")
    monkeypatch.setattr(config, "MANUAL_DIR", tmp_path / "manual")
    monkeypatch.setattr(config, "START_DATE", "2023-01-01")
    (tmp_path / "manual").mkdir()
    return syn, tmp_path


def test_run_end_to_end(fake_api):
    syn, tmp = fake_api
    payload = build.run()
    assert (tmp / "monitor.json").exists()
    assert (tmp / "panel_diario.csv").exists()
    assert set(payload["series"]) >= {"tc_oficial_ref", "brecha_ccl", "riesgo_pais", "reservas", "tasa"}
    h = payload["headline"]
    assert h["ipd"] is not None
    # El shock simulado debe verse como presión alta al inicio del episodio.
    ipd = dict(payload["ipd"]["data"])
    fecha_shock = syn["fechas"][715].strftime("%Y-%m-%d")
    fecha_calma = syn["fechas"][600].strftime("%Y-%m-%d")
    assert ipd[fecha_shock] > ipd[fecha_calma] + 1
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
        "fecha": ["2026-01-05", "2026-01-05"],
        "contrato": ["DLR/ENE26", "DLR/FEB26"],
        "vencimiento": ["2026-01-30", "2026-02-27"],
        "precio_ajuste": [1050.0, 1080.0],
        "interes_abierto": [100, 200],
    })
    spot = pd.Series([1000.0], index=pd.to_datetime(["2026-01-05"]))
    out = indicators.implied_devaluation(fut, spot)
    # ENE26 vence en 25 días (>= 20): ese es el contrato elegido.
    expected = ((1050 / 1000) ** (365 / 25) - 1) * 100
    assert out["deval_implicita"].iloc[0] == pytest.approx(expected)
    assert out["futuros_interes_abierto"].iloc[0] == 300


def test_weighted_mean_requires_min_weight():
    frame = pd.DataFrame({"a": [1.0, np.nan], "b": [3.0, np.nan], "c": [np.nan, 2.0]})
    out = indicators._weighted_mean(frame, {"a": 1, "b": 1, "c": 1})
    assert out.iloc[0] == pytest.approx(2.0)
    assert np.isnan(out.iloc[1])  # sólo 1/3 del peso disponible


def test_auction_share():
    df = pd.DataFrame({
        "fecha": ["2026-03-10"] * 3,
        "instrumento": ["S30A6", "D30J6", "TZX27"],
        "tipo": ["LECAP", "DL", "CER"],
        "monto_vn_millones_ars": [600, 300, 100],
    })
    out = indicators.auction_dollar_share(df)
    assert out["share_cobertura"].iloc[0] == pytest.approx(30.0)
