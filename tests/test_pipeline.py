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
    monkeypatch.setattr(sources, "bcra_anexo_cambios", lambda: pd.DataFrame())
    monkeypatch.setattr(sources, "bcra_compras_personas_humanas", lambda datos=None: pd.DataFrame({
        "fecha": ["2025-01", "2025-02"], "compras_usd_millones": [1500.0, 1800.0],
        "ventas_usd_millones": [300.0, 250.0], "fuente": ["test", "test"]}))
    def fake_planilla(mes):
        if mes < "2025-01" or mes == "2025-06":  # 2025-06: mes sin PDF
            return None
        return {"fecha": mes, "cortas_usd_millones": -1000.0, "largas_usd_millones": 0.0,
                "vendida_neta_usd_millones": 1000.0}
    monkeypatch.setattr(sources, "bcra_planilla_reservas", fake_planilla)
    monkeypatch.setattr(config, "BCRA_PLANILLA_DESDE", "2024-06")
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
    pos = payload["series"]["posicion_bcra"]
    assert pos["data"][0] == ["2025-01-31", 1000.0]
    assert "2025-06-30" not in dict(pos["data"])
    meta = json.loads((tmp / "series" / "_descargas.json").read_text())
    assert "2024-06" in meta["posicion_futuros_bcra_no_disponibles"]
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


def test_reporte_semanal_html(fake_api):
    from datetime import date
    from monitor import report
    syn, tmp = fake_api
    build.run()
    semana = report.semana_anterior(date(2026, 6, 8))  # lunes
    assert (semana.lunes.date(), semana.viernes.date()) == (date(2026, 6, 1), date(2026, 6, 5))
    p = pd.read_csv(tmp / "panel_diario.csv", index_col=0, parse_dates=True)
    payload = json.loads((tmp / "monitor.json").read_text())
    html_txt = report.construir_html(semana, p, payload)
    assert "Reporte semanal" in html_txt and "/100" in html_txt
    assert "Qué explica el índice" in html_txt and "Var. semana" in html_txt and "<svg" in html_txt


def test_pca_weights():
    rng = np.random.default_rng(2)
    idx = pd.bdate_range("2003-01-01", periods=2500)
    f = np.repeat(rng.standard_normal(120), 21)[:2500]  # factor común mensual
    zs = pd.DataFrame({
        "a": f + 0.3 * rng.standard_normal(2500),
        "b": f + 0.3 * rng.standard_normal(2500),
        "c": -f + 0.3 * rng.standard_normal(2500),   # se mueve al revés
    }, index=idx)
    w, var = indicators.pca_weights(zs)
    # "c" tiene carga negativa: queda en el peso mínimo y el resto se reparte.
    assert w["c"] == pytest.approx(config.IPD_PCA_PESO_MINIMO)
    assert w["a"] == pytest.approx((1 - config.IPD_PCA_PESO_MINIMO) / 2, abs=0.05)
    assert sum(w.values()) == pytest.approx(1.0) and 0 < var <= 1


def test_apply_min_weight():
    w = pd.Series({"a": 0.5, "b": 0.45, "c": 0.05, "d": 0.0})
    out = indicators.apply_min_weight(w, 0.10)
    assert out.sum() == pytest.approx(1.0)
    assert out["c"] == pytest.approx(0.10) and out["d"] == pytest.approx(0.10)
    assert out["a"] / out["b"] == pytest.approx(0.5 / 0.45)


def test_parse_planilla_reservas():
    vieja = ("Datos Corrientes en millones de USD (final del período) 31/01/19\n"
             "(b) Instrumentos financieros denominados en moneda extranjera y liquidados por otros medios\n"
             "(por ejemplo, en moneda nacional)13 159.85\n"
             "—derivados financieros (forwards, futuros y opciones) 159.85\n"
             "—Posiciones cortas -1,190.27\n—Posiciones largas 350.12\n—otros instrumentos\n")
    nueva = ("Datos Corrientes en millones de USD (final del período) 31/08/26\n"
             "(b) Instrumentos financieros denominados en moneda extranjera y liquidados por otros medios (por\n"
             "ejemplo, en moneda nacional)13 -6.278,46\n"
             "—derivados financieros (forwards, futuros y opciones) -6.278,46\n"
             "—Posiciones cortas -6.278,46\n—Posiciones largas 0,00\n—otros instrumentos 0,00\n")
    vacia = ("(final del período) 30/06/17\n(b) ... liquidados por otros medios (por\n"
             "ejemplo, en moneda nacional)13\n—derivados financieros\n—Posiciones cortas\n"
             "—Posiciones largas\n—otros instrumentos\n(c) Activos dados en prendas14 0.00\n")
    a = sources.parse_planilla_reservas(vieja)
    assert a["fecha"] == "2019-01"
    assert a["cortas_usd_millones"] == pytest.approx(-1190.27)
    assert a["vendida_neta_usd_millones"] == pytest.approx(840.15)
    b = sources.parse_planilla_reservas(nueva)
    assert b["fecha"] == "2026-08" and b["vendida_neta_usd_millones"] == pytest.approx(6278.46)
    # En blanco = no informado (no es cero); "0.00" sí es cero.
    assert sources.parse_planilla_reservas(vacia)["vendida_neta_usd_millones"] is None
    cero = vacia.replace("Posiciones cortas\n", "Posiciones cortas 0.00\n")
    assert sources.parse_planilla_reservas(cero)["vendida_neta_usd_millones"] == 0.0
    assert sources.parse_planilla_reservas("sin datos") is None


def test_posicion_bcra_rezago():
    pos = pd.DataFrame({"fecha": ["2025-01", "2025-02"], "vendida_neta_usd_millones": [100.0, 200.0]})
    idx = pd.bdate_range("2025-01-01", "2025-04-30")
    d = indicators.posicion_bcra_daily(pos, idx)
    # El dato de enero (31/1) recién se conoce 35 días después.
    assert d[:"2025-03-06"].isna().all()
    assert d["2025-03-07"] == 100.0
    assert d["2025-04-30"] == 200.0


def test_peru_parse_bcrp():
    from monitor import peru
    j = {"config": {"series": [{"name": "TC"}]}, "periods": [
        {"name": "02.Ene.97", "values": ["2.6"]}, {"name": "30.Set.26", "values": ["3.4"]},
        {"name": "01.Oct.26", "values": ["n.d."]}]}
    s = peru.parse_bcrp(j, "tc")
    assert list(s.index) == [pd.Timestamp("1997-01-02"), pd.Timestamp("2026-09-30")]
    m = peru.parse_bcrp({"periods": [{"name": "Ago.2026", "values": ["26.0"]}]}, "x")
    assert m.index[0] == pd.Timestamp("2026-08-31")


def test_peru_intervencion_y_ipd():
    from monitor import peru
    idx = pd.bdate_range("2001-01-01", "2006-12-29")
    rng = np.random.default_rng(1)
    n = len(idx)
    tc = pd.Series(3.4 * np.exp(np.cumsum(rng.normal(0, 0.003, n))), index=idx)
    raw = {
        "tc": tc, "rin": pd.Series(10000.0, index=idx), "posicion_cambio": pd.Series(np.linspace(5000, 8000, n), index=idx),
        "mesa_compras_netas": pd.Series(rng.normal(0, 20, n), index=idx),
        "sc_venta_pactado": pd.Series(0.0, index=idx), "sc_venta_vencido": pd.Series(0.0, index=idx),
        "tasa_interbancaria": pd.Series(4 + rng.normal(0, 0.05, n).cumsum() * 0.01, index=idx),
        "embig": pd.Series(200 + rng.normal(0, 3, n).cumsum(), index=idx),
        "bono_10a": pd.Series(6 + rng.normal(0, 0.02, n).cumsum(), index=idx),
        "dolarizacion_liquidez": pd.Series(np.linspace(70, 50, 72), index=pd.date_range("2001-01-31", periods=72, freq="ME")),
    }
    # Un día de ventas fuertes del BCRP (compras netas negativas) y un swap venta.
    raw["mesa_compras_netas"].iloc[1000] = -500
    raw["sc_venta_pactado"].iloc[1000] = 300
    df = peru.derived_series(raw)
    d = idx[1000]
    assert df.loc[d, "intervencion_usd"] - df.loc[idx[999], "intervencion_usd"] == pytest.approx(
        800 - (-raw["mesa_compras_netas"].iloc[1000 - peru.INTERVENCION_VENTANA]), abs=1e-6)
    out = indicators.compute_ipd(df, peru.IPD_BLOCKS, "2003-01-01")
    assert out["indice"].dropna().between(0, 100).all()
    assert out["indice"][:"2002-12-31"].isna().all()
    assert set(out["pesos"]) == {"cambiaria", "dolarizacion"}


def test_comparado_unidades_comunes():
    from monitor import comparado
    idx = pd.date_range("2003-01-31", periods=120, freq="ME")
    rng = np.random.default_rng(3)
    a = pd.DataFrame({"depreciacion": rng.normal(2, 3, 120), "intervencion": rng.normal(0, 2, 120)}, index=idx)
    b = pd.DataFrame({"depreciacion": rng.normal(0, 1, 120), "intervencion": rng.normal(0, 1, 120)}, index=idx)
    res, rho = comparado.calcular({"ar": a, "pe": b})
    assert rho > 0
    # La presión es depreciación + ρ × intervención, con el mismo ρ para todos.
    for v, src in [(res["ar"], a), (res["pe"], b)]:
        assert np.allclose(v["presion"], src["depreciacion"] + rho * src["intervencion"])
    assert res["ar"]["presion_3m"].iloc[:2].isna().all()


def test_uruguay_lectores():
    from monitor import uruguay
    xml = ("<datoscotizaciones.dato><Fecha>2026-09-01</Fecha><TCV>40.236000</TCV></datoscotizaciones.dato>"
           "<datoscotizaciones.dato><Fecha>2026-09-02</Fecha><TCV>40.233000</TCV></datoscotizaciones.dato>")
    tc = uruguay.parse_cotizaciones(xml)
    assert tc.iloc[-1] == pytest.approx(40.233) and len(tc) == 2
    res = pd.DataFrame([[None, None, None, None, None, None],
                        [None, "Fecha", "ACTIVOS DE RESERVA", "OTROS", "ACTIVOS DE RESERVA SIN CONTRAPARTIDAS", "POSICION EN MONEDA EXTRANJERA DEL B.C.U."],
                        [None, None, "(a)", "(b)", "(e)", None],
                        [None, pd.Timestamp("2002-06-26"), 1098.7, "n/d", "n/d", "n/d"],
                        [None, pd.Timestamp("2026-10-08"), 18741.6, 0, 9133.4, 9564.5],
                        [None, pd.Timestamp("2026-10-08"), 18741.6, 0, 9133.4, 9564.5],
                        [None, "NOTAS:", None, None, None, None]])
    r = uruguay.parse_reservas(res)
    assert list(r.index) == [pd.Timestamp("2002-06-26"), pd.Timestamp("2026-10-08")]
    assert r.loc["2026-10-08", "posicion_me"] == pytest.approx(9564.5)
    assert np.isnan(r.loc["2002-06-26", "posicion_me"])
    dep = pd.DataFrame([["Mes", "SECTOR PRIVADO", None, None], [None, "MN", "ME", "Total"],
                        [pd.Timestamp("2026-08-01"), 600.0, 1400.0, 2000.0], ["Notas", None, None, None]])
    d = uruguay.parse_depositos(dep)
    assert d.index[0] == pd.Timestamp("2026-08-31")
    assert d["dolarizacion_depositos"].iloc[0] == pytest.approx(70.0)


def test_lectores_brasil_chile_colombia():
    from monitor import brasil, chile, colombia
    s = brasil.parse_sgs([{"data": "03/08/2026", "valor": "5.0723"}, {"data": "04/08/2026", "valor": "5.10"}], "tc")
    assert s.index[0] == pd.Timestamp("2026-08-03") and s.iloc[1] == pytest.approx(5.10)
    csv = ("﻿Comunicação,Data Hora Comunicação,Comunicado,Data Hora Comunicado,Data Hora Anúncio,Procedimento Operacional,Data,Instrumento,Modalidade,Tipo Composto,Data de Liquidação,Data de Vencimento,Volume USD Ofertado,Volume USD Aceito,Taxa de Corte\n"
           ',,,,,Operação Direta,1999-01-22 00:00:00,Venda a Vista,Mercado,,1999-01-26 00:00:00,,,"675510000,00",\n'
           ',,,,,Operação Direta,1999-01-22 00:00:00,Compra a Vista,Mercado,,1999-01-26 00:00:00,,,"75510000,00",\n'
           ',,45808,,,Leilão Eletrônico,2026-08-25 00:00:00,Swap Cambial,Tradicional,,2026-09-01 00:00:00,2026-12-01 00:00:00,"2500000000,00","2000000000,00","5,029000"\n')
    v = brasil.parse_atuacoes(csv)
    assert v[pd.Timestamp("1999-01-22")] == pytest.approx(600.0)
    assert v[pd.Timestamp("2026-08-25")] == 0.0  # los swaps van por el stock, no por acá
    m = chile.parse_mindicador({"serie": [{"fecha": "2026-10-13T03:00:00.000Z", "valor": 978.61},
                                           {"fecha": "2026-10-10T03:00:00.000Z", "valor": 975.0}]}, "tc")
    assert list(m.index) == [pd.Timestamp("2026-10-10"), pd.Timestamp("2026-10-13")]
    t = colombia.parse_trm([{"valor": "3194.44", "vigenciadesde": "2026-10-10T00:00:00.000", "vigenciahasta": "2026-10-13T00:00:00.000"}])
    assert t.index[0] == pd.Timestamp("2026-10-10") and t.iloc[0] == pytest.approx(3194.44)


def test_colombia_suameca():
    from monitor import colombia
    s = colombia.parse_suameca([{"id": 59, "data": [[1760331600000, 12.25], [1760418000000, 12.0]]}], "tpm")
    assert s.index[0] == pd.Timestamp("2025-10-13") and s.iloc[-1] == 12.0


def test_tipo_de_cambio_a_fecha_de_operacion():
    from monitor import comun
    # Publicado viernes 9 (operaciones del jueves) y martes 13 tras feriado (operaciones del viernes).
    s = pd.Series([979.85, 981.61, 978.61], index=pd.to_datetime(["2026-10-08", "2026-10-09", "2026-10-13"]))
    out = comun.a_fecha_de_operacion(s)
    assert list(out.index.strftime("%Y-%m-%d")) == ["2026-10-08", "2026-10-09"]
    assert out.iloc[-1] == 978.61


def test_comparado_incluye_indices_0_100(tmp_path, monkeypatch):
    import json
    from monitor import comparado
    f = tmp_path / "monitor.json"
    f.write_text(json.dumps({"headline": {"date": "2026-10-09", "indice": 49.8, "status": "neutral"},
                             "ipd": {"indice": [["2026-10-08", 51.23], ["2026-10-09", None], ["2026-10-10", 49.8]]}}))
    monkeypatch.setattr(comparado, "INDICES", {"ar": ("Argentina", f), "pe": ("Perú", tmp_path / "no.json")})
    out = comparado.indices_0_100()
    assert list(out) == ["ar"]
    assert out["ar"]["data"] == [["2026-10-08", 51.2], ["2026-10-10", 49.8]]
    assert out["ar"]["headline"]["indice"] == 49.8


def test_subindices_suman_el_indice():
    """Los puntos de los subíndices suman la distancia del índice a 50, hoy y
    hace 7 días, y cada subíndice tiene su escala 0-100."""
    import numpy as np
    from monitor import build, indicators
    idx = pd.bdate_range("2018-01-01", "2023-12-29")
    rng = np.random.default_rng(3)
    df = pd.DataFrame({k: rng.normal(size=len(idx)).cumsum() for k in ["a", "b", "c", "d"]}, index=idx)
    blocks = {"x": {"label": "X", "weight": 0.5, "components": {"a": {"transform": "level", "sign": 1, "weight": 1, "label": "A"},
                                                                 "b": {"transform": "level", "sign": 1, "weight": 1, "label": "B"}}},
              "y": {"label": "Y", "weight": 0.5, "components": {"c": {"transform": "level", "sign": 1, "weight": 1, "label": "C"},
                                                                 "d": {"transform": "level", "sign": -1, "weight": 1, "label": "D"}}}}
    ipd = indicators.compute_ipd(df, blocks, "2019-06-01")
    metas = {b: build._bloque_meta(b, blocks, ipd) for b in blocks}
    ind = ipd["indice"].dropna()
    assert abs(sum(m["puntos"] for m in metas.values()) - (ind.iloc[-1] - 50)) < 1e-3
    assert abs(sum(m["puntos_7d"] for m in metas.values()) - (build._last(ind, 7)[1] - 50)) < 1e-3
    assert all(0 <= m["indice_last"] <= 100 for m in metas.values())


def test_flujos_financieros_del_anexo():
    from monitor import sources
    fila = lambda mes, b, c, d, monto: {"Anexo": 49, "Mes": mes, "Sector": "Petróleo", "Monto": monto, "A": "03- Cuenta Financiera", "B": b, "C": c, "D": d}
    nr = "01- Inversión directa y de portafolio de no residentes"
    deuda = "02- Préstamos financieros, títulos de deuda y líneas de crédito"
    datos = pd.DataFrame([
        fila("2026-07-01", nr, "01-... - Ingresos", "Inversión de portafolio - Ingresos", 3_000e6),
        fila("2026-07-01", nr, "02-... - Egresos", "Inversión de portafolio - Egresos", -100e6),
        fila("2026-07-01", nr, "01-... - Ingresos", "Inversión directa - Ingresos", 90e6),
        fila("2026-07-01", nr, "02-... - Egresos", "Inversión directa - Egresos", -70e6),
        fila("2026-07-01", nr, "01-... - Ingresos", "Inversiones aplicadas a la compra de inmuebles - Ingresos", 10e6),
        fila("2026-07-01", deuda, "01-... - Ingresos", "Otros préstamos del exterior y títulos de deuda - Ingresos", 3_600e6),
        fila("2026-07-01", deuda, "02-... - Egresos", "Otros préstamos del exterior y títulos de deuda - Egresos", -2_500e6),
        fila("2026-08-01", nr, "02-... - Egresos", "Inversión de portafolio - Egresos", -190e6),
    ])
    out = sources.parse_flujos_financieros(datos).set_index("fecha")
    assert out.loc["2026-07", "portafolio_neto"] == 2900.0
    assert out.loc["2026-07", "directa_neto"] == 30.0
    assert out.loc["2026-07", "deuda_neto"] == 1100.0
    assert out.loc["2026-08", "portafolio_neto"] == -190.0 and out.loc["2026-08", "deuda_neto"] == 0.0


def test_financiera_ratio_y_descomposicion():
    from monitor import financiera as f
    idx = pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31"])
    mn = pd.Series([800.0, 800.0, 800.0], index=idx)       # pesos
    me = pd.Series([100.0, 100.0, 110.0], index=idx)       # dólares
    tc = pd.Series([2.0, 3.0, 3.0], index=idx)
    r = f.ratio(me * tc, mn)
    assert round(r.iloc[0], 2) == 20.0
    d = f.descomponer(mn, me, tc)
    # Febrero: sólo cambió el tipo de cambio -> todo es valuación.
    assert abs(d.loc["2026-02-28", "portafolio"]) < 1e-9 and d.loc["2026-02-28", "valuacion"] > 0
    # Marzo: sólo cambiaron los saldos -> todo es portafolio.
    assert abs(d.loc["2026-03-31", "valuacion"]) < 1e-9 and d.loc["2026-03-31", "portafolio"] > 0
    assert (abs(d["total"] - d["valuacion"] - d["portafolio"]) < 1e-9).all()


def test_financiera_parse_bis():
    from monitor import financiera as f
    txt = "FREQ,UNIT_MULT,TIME_PERIOD,OBS_VALUE\nQ,6,2025-Q4,120500\nQ,6,2026-Q1,121000\n"
    s = f.parse_bis(txt)
    assert list(s.index.strftime("%Y-%m-%d")) == ["2025-12-31", "2026-03-31"]
    assert s.iloc[-1] == 121.0  # miles de millones de USD


def test_financiera_creditos_bcu():
    from monitor import financiera as f
    filas = [[None] * 39 for _ in range(12)]
    filas[5][1] = "TOTAL (MN + ME) en millones de pesos"
    filas[5][19] = "MONEDA NACIONAL en millones de pesos"
    filas[5][29] = "MONEDA EXTRANJERA en millones de dólares"
    filas[7][0] = "Mes"
    fila = [None] * 39
    fila[0] = pd.Timestamp("2026-08-01"); fila[3] = 1130517.8; fila[21] = 601758.5; fila[31] = 13138.8
    filas.append(fila)
    d = f.parse_creditos_bcu(pd.DataFrame(filas))
    r = d.iloc[-1]
    assert d.index[-1] == pd.Timestamp("2026-08-31")
    assert round(r["me"] / r["total"] * 100, 1) == 46.8 and r["me_usd"] == 13138.8


def test_financiera_parse_imf():
    from monitor import financiera as f
    txt = ("DATAFLOW,COUNTRY,SECTOR,INDICATOR,FREQUENCY,TIME_PERIOD,OBS_VALUE\n"
           "x,CRI,S12CFSI,FSI131_AFSI_PT,M,2025-M11,31.0\n"
           "x,CRI,S12CFSI,FSI131_AFSI_PT,M,2025-M12,31.4\n"
           "x,CRI,S12CFSI,FSI131_AFSI_PT,Q,2025-Q4,31.4\n"
           "x,BRA,S12CFSI,FSI680_AFSI_PT,Q,2026-Q2,11.3\n")
    s = f.parse_imf_fsi(txt, "FSI131_AFSI_PT")
    assert list(s.index.strftime("%Y-%m-%d")) == ["2025-11-30", "2025-12-31"] and s.iloc[-1] == 31.4
    q = f.parse_imf_fsi(txt, "FSI680_AFSI_PT")
    assert q.index[-1] == pd.Timestamp("2026-06-30")


def test_financiera_parse_bcb():
    from monitor import financiera as f
    n = 8
    filas = [[None] * n for _ in range(20)]
    filas[2][4] = pd.Timestamp("2026-09-30"); filas[2][5] = "Semana 1"; filas[3][5] = pd.Timestamp("2026-10-02")
    filas[3][6] = pd.Timestamp("2026-10-09")
    def bloque(i, titulo, mn_usd, mn_bs, me_usd):
        filas[i][3] = titulo
        for j, v in enumerate([mn_usd, mn_bs, me_usd]):
            filas[i + 1 + j][3] = ["Moneda nacional", "Pro Memoria: Moneda nacional (en millones de Bs)", "Moneda extranjera"][j]
            for c in (4, 5, 6):
                filas[i + 1 + j][c] = v
    filas[5][3] = "  M’3   "
    for c in (4, 5, 6):
        filas[6][c] = 328574.0; filas[7][c] = 30716.0
    filas[6][3] = "Moneda nacional"; filas[7][3] = "Moneda extranjera"
    bloque(9, "Depósitos en entidades de intermediación financiera", 19953.6, 236450.5, 2592.1)
    bloque(14, "Crédito del sistema financiero al sector privado7 (en millones de USD)", 19353.3, 229336.2, 94.9)
    d = f.parse_bcb_semanal(pd.DataFrame(filas))
    assert list(d.index.strftime("%Y-%m-%d")) == ["2026-09-30", "2026-10-02", "2026-10-09"]
    r = d.iloc[-1]
    assert round(r["dep_me_usd"] / (r["dep_me_usd"] + r["dep_mn_usd"]) * 100, 1) == 11.5
    assert round(r["dep_mn_bs"] / r["dep_mn_usd"], 2) == 11.85


def _simular_traspaso(betas, n=240, rho=0.3, semilla=0):
    rng = np.random.default_rng(semilla)
    idx = pd.date_range("2005-01-31", periods=n, freq="ME")
    d = pd.Series(rng.normal(1, 3, n), idx)
    pi = np.zeros(n)
    for i in range(n):
        pi[i] = 0.5 + (rho * pi[i - 1] if i else 0) + sum(b * d.iloc[i - k] for k, b in enumerate(betas) if i >= k) + rng.normal(0, 0.3)
    return pd.Series(pi, idx), d


def test_traspaso_recupera_la_suma_de_coeficientes():
    from monitor import traspaso as t
    pi, d = _simular_traspaso([0.2, 0.1, 0.05, 0.05])
    # Muestra completa: Σβ = 0,4 y largo plazo 0,4 / 0,7.
    r = t.estimar(t.armar(pi, d))
    assert abs(r["suma"] - 0.4) < 0.05 and abs(r["lp"] - 0.4 / 0.7) < 0.08 and r["se"] > 0
    m = t.movil(pi, d)
    assert len(m) > 150 and not m.sin_dato.any()
    # En ventanas de 36 meses la estimación es ruidosa pero centrada.
    assert abs(m.suma.median() - 0.4) < 0.08
    assert abs(t.proyeccion_local(pi, d) - 0.4 / 0.7) < 0.15


def test_traspaso_sin_dato_con_tipo_de_cambio_fijo():
    from monitor import traspaso as t
    pi, d = _simular_traspaso([0.2])
    fijo = pd.Series(0.0, d.index)
    fijo.iloc[-3] = 40.0   # una devaluación aislada no alcanza para identificar
    m = t.movil(pi, fijo)
    assert m.sin_dato.all() and m.suma.isna().all()
    assert t.lp_movil(pi, fijo).empty


def test_traspaso_desestacionaliza():
    from monitor import traspaso as t
    idx = pd.date_range("2010-01-31", periods=144, freq="ME")
    pi = pd.Series(2.0 + np.where(idx.month == 1, 1.2, -0.1), idx)
    sa = t.desestacionalizar(pi)
    assert sa.std() < 1e-9 and abs(sa.mean() - pi.mean()) < 1e-9


def test_traspaso_json(monkeypatch):
    from monitor import financiera as f
    pi, d = _simular_traspaso([0.3, 0.1])
    e = np.exp(d.cumsum() / 100) * 10
    monkeypatch.setattr(f, "ipc_mensual", lambda pais, offline: pi)
    monkeypatch.setattr(f, "tc_mensual", lambda pais, offline: e)
    monkeypatch.setattr(f, "tc_paralelo_ar", lambda: e[e.index >= "2011-01-31"] * 1.5)
    tr, principal = f.traspaso_pais("ar", True, None)
    assert [v["clave"] for v in tr["variantes"]] == ["paralelo", "oficial"]
    fecha, suma, lo, hi = tr["variantes"][0]["data"][-1]
    assert lo < suma < hi and 20 < suma < 60
    assert tr["quiebres"][0][:2] == ["2002-01-31", "Fin de la convertibilidad"] and tr["quiebres"][0][2] == "2005-01-31"
    assert principal.dropna().iloc[-1] == pytest.approx(suma, abs=0.06)


def test_parse_imf_mensual_y_encadenar():
    from monitor import financiera as f
    txt = "COUNTRY,TIME_PERIOD,OBS_VALUE\nG001,2026-M07,193.9\nG001,2026-M08,205.6\n"
    s = f.parse_imf_mensual(txt)
    assert list(s.index.strftime("%Y-%m-%d")) == ["2026-07-31", "2026-08-31"] and s.iloc[-1] == 205.6
    idx = pd.date_range("2026-03-31", periods=5, freq="ME")
    base = pd.Series([6.91, 6.91, 6.91], idx[:3])
    bcb = pd.Series([6.86, 6.86, 6.86, 9.76, 12.15], idx)
    e = f.encadenar(base, bcb)
    assert len(e) == 5 and e.iloc[-1] == pytest.approx(6.91 * 12.15 / 6.86)


def test_funciones_del_dinero():
    from monitor import funciones as fn
    idx = pd.date_range("2005-01-31", periods=48, freq="ME")
    rng = np.random.default_rng(1)
    base = np.linspace(10, 40, 48)
    vista = pd.Series(base + rng.normal(0, 1, 48), idx)                  # %
    dep = pd.Series(base + 5 + rng.normal(0, 1, 48), idx)
    cred = pd.Series(base - 5 + rng.normal(0, 1, 48), idx)
    tr = pd.Series(np.linspace(-0.1, 1.3, 48), idx)                      # fracción, se acota a [0, 1]
    p = fn.patas(vista, tr, dep, cred)
    assert p["unidad_cuenta"].min() == 0 and p["unidad_cuenta"].max() == 1
    assert p["reserva_valor"].iloc[0] == pytest.approx((dep.iloc[0] + cred.iloc[0]) / 200)
    b = fn.bloque(vista, tr, dep, cred)
    u = b["ultimo"]
    assert u["indice"] == pytest.approx((u["medio_pago"] + u["unidad_cuenta"] + u["reserva_valor"]) / 3, abs=2e-3)
    assert set(b["pca"]["pesos"]) == set(fn.PATAS) and sum(b["pca"]["pesos"].values()) == pytest.approx(1, abs=3e-3)
    assert min(b["pca"]["pesos"].values()) >= 0.0999
    etiquetas = [t["etiqueta"] for t in b["triangulo"]]
    assert etiquetas[0] == "2007" and etiquetas[-1].startswith("Últimos 12 meses")
    # Sin traspaso (tipo de cambio fijo) el índice es parcial: promedio de las otras dos patas.
    sin = fn.bloque(vista, pd.Series(np.nan, idx), dep, cred)
    assert sin["faltan"] == ["unidad_cuenta"] and sin["triangulo"][-1]["unidad_cuenta"] is None
    assert sin["ultimo"]["indice"] == pytest.approx((sin["ultimo"]["medio_pago"] + sin["ultimo"]["reserva_valor"]) / 2, abs=2e-3)
    # Sin depósitos, la reserva de valor usa sólo el crédito; las series trimestrales se extienden dos meses.
    q = cred.resample("QE").last()
    p2 = fn.patas(None, tr, None, q)
    assert p2["reserva_valor"].notna().sum() >= len(q) * 3 - 2
