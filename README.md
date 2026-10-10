# Monitor de Dolarización (Argentina)

Tablero diario para seguir la presión cambiaria y la dolarización de
portafolios en Argentina, pensado para hacer incidencia en el ciclo electoral
2027. Su eje es el **Índice de Presión de Dolarización (IPD)**, una adaptación
del *Exchange Market Pressure Index* a la economía bimonetaria argentina.

```
.
├── index.html              ← tablero (estático, lee data/monitor.json)
├── monitor/
│   ├── config.py           ← fuentes, componentes, pesos, umbrales, eventos
│   ├── sources.py          ← descarga (BCRA, ArgentinaDatos, A3 Mercados)
│   ├── indicators.py       ← series derivadas e IPD
│   └── build.py            ← orquestador: python -m monitor.build
├── data/
│   ├── monitor.json        ← lo que consume el tablero (generado)
│   ├── panel_diario.csv    ← panel diario completo, para Excel/R/Stata (generado)
│   ├── bcra_catalogo.csv   ← catálogo de variables del BCRA (generado)
│   └── series/*.csv        ← historia cruda de cada serie (generado)
└── tests/
```

## Cómo se actualiza

El workflow `.github/workflows/actualizar.yml` corre los días hábiles a
las 19:17 y 22:47 (hora argentina). En cada corrida:

1. Descarga las series.
2. Recalcula el IPD.
3. Commitea `data/`.

Si una fuente falla, se usa la última copia guardada y el tablero marca la
fuente con ✕. También se puede correr a mano desde *Actions → Run workflow*.

El tablero se publica con **GitHub Pages** (Settings → Pages → Deploy from
branch `main`, carpeta `/`) en
<https://elibman36.github.io/monitor-dolarizacion/>.

Para correrlo localmente:

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m monitor.build             # descarga y recalcula
python -m monitor.build --offline   # recalcula con lo ya guardado
python -m http.server               # y abrir http://localhost:8000
```

## Reporte semanal en PDF

Todos los lunes a las 07:47 (hora argentina) el workflow
`.github/workflows/reporte-semanal.yml` actualiza los datos y genera un PDF de
tres páginas con la semana hábil anterior (lunes a viernes):

1. el índice al cierre de la semana, un resumen automático y los gráficos del
   índice (18 meses y desde 2003) y de sus componentes;
2. la tabla de variables con variación semanal y de 4 semanas, gráficos de los
   últimos seis meses y compras de USD de personas humanas;
3. la metodología.

Queda en `reportes/reporte-semanal-AAAA-MM-DD.pdf` (fecha del viernes) y en
`reportes/ultimo.pdf`, y también como artefacto de la corrida en *Actions*.
Para regenerar una semana: *Actions → Reporte semanal (PDF) → Run workflow*
con la fecha del lunes siguiente. Localmente:

```bash
pip install -r requirements-reporte.txt && python -m playwright install chromium
python -m monitor.report --fecha 2026-10-05   # semana del 28/9 al 2/10
```

## Variables y fuentes

| Variable | Desde | Frecuencia | Fuente | Carga |
|---|---|---|---|---|
| Reservas internacionales brutas | 1996 | diaria | BCRA, API de Estadísticas v4 | automática |
| Tasa BADLAR privados (TAMAR como respaldo) | 1999 | diaria | BCRA | automática |
| Tipo de cambio mayorista A3500 | 2002 | diaria | BCRA | automática |
| Depósitos en dólares del sector privado | 2002 | diaria | BCRA | automática |
| Riesgo país (EMBI) | 1999 | diaria | [ArgentinaDatos](https://argentinadatos.com) | automática |
| Dólar oficial, mayorista y blue | 2011 | diaria | ArgentinaDatos | automática |
| Dólar CCL | 2013 | diaria | ArgentinaDatos | automática |
| Dólar MEP | 2018 | diaria | ArgentinaDatos | automática |
| Brechas CCL, MEP y blue | 2011 | diaria | cálculo propio (CCL; antes de 2013, blue) | derivada |
| Futuros de dólar: devaluación implícita e interés abierto | 2020 | diaria | A3 Mercados (API pública de precios de cierre) | automática |
| Posición del BCRA en futuros de dólar (ítem IV.1.b) | 2003 | mensual (fin de mes) | BCRA, Planilla de Reservas Internacionales y Liquidez en Moneda Extranjera (PDF, formato FMI) | automática |
| Compras de USD de personas humanas | 2003 | mensual | BCRA, anexo del Informe de Evolución del Mercado de Cambios | automática (semanal) |

**Historia.** El IPD se publica desde 2003 (`IPD_PUBLICAR_DESDE`). Las series
se descargan desde 1996, pero 1996–2002 sólo sirve como ventana de referencia:
con la convertibilidad el tipo de cambio no se movía, la BADLAR oscilaba 20–45
puntos por semana y se desplomó con el corralito, y hay huecos en los datos.
Desde 2003 hay 7 de los 9 componentes; la brecha se suma en 2011 y los futuros
en 2020. El panel diario incluye la columna `ipd_n_componentes`.

Todas las fuentes son automáticas: no hay datos que cargar a mano.

**IDs del BCRA.** Las variables se buscan con una expresión regular sobre su
descripción. Después de la primera corrida conviene revisar
`data/bcra_catalogo.csv` y fijar los IDs en `BCRA_VARIABLES` para que no cambien
de forma silenciosa. Si el certificado del BCRA falla en CI, existe la opción
`BCRA_SSL_VERIFY=0`. Esa variable sólo afecta a las llamadas al BCRA.

## Metodología del IPD

Se parte del EMP de Girton y Roper (1977) y Eichengreen, Rose y Wyplosz (1996):
*EMP = Δe/σₑ − Δr/σᵣ + Δi/σᵢ*. La versión argentina tiene tres subíndices de
igual peso:

| Subíndice (1/3 cada uno) | Componente | Transformación | Signo |
|---|---|---|---|
| Presión cambiaria | Tipo de cambio A3500 | Δlog 5 días | + |
| | Volatilidad del oficial | desvío de variaciones diarias, 20 días, anualizado | + |
| | Reservas brutas | Δlog 5 días | − |
| | Tasa BADLAR | Δ 5 días | + |
| | Brecha MEP / oficial | nivel (antes de 2018, brecha CCL; antes de 2013, blue) | + |
| Dolarización de portafolios | Devaluación implícita en futuros | nivel (TNA a 90 días) | + |
| | Posición abierta en futuros de dólar | nivel, promedio de 21 días | + |
| | Futuros de dólar vendidos por el BCRA (neto) | Δ 21 días de la posición vendida neta (una posición comprada cuenta como 0); entra 35 días después de cada fin de mes | + |
| | Depósitos en USD del sector privado | Δlog 5 días | − |
| | Compras netas de USD de personas humanas (FAE) | desvío respecto de su promedio de 12 meses; entra 30 días después del cierre de cada mes | + |
| Extranjerización de portafolios | Canje (CCL / MEP) | nivel | + |
| | Volatilidad del CCL | desvío de variaciones diarias, 20 días, anualizado | + |
| | Riesgo país | Δ 5 días | + |

El cálculo sigue estos pasos:

1. **Estandarización.** Cada componente se estandariza contra los últimos 504
   días hábiles (unos 2 años) con mediana y MAD (desvío absoluto mediano ×
   1,4826), recortado a ±4. Equivale a ponderar por la inversa de la
   dispersión, como en el EMP clásico, pero sin que un episodio extremo (la
   devaluación de dic-23) infle la escala durante dos años. La versión con
   media y desvío estándar sigue disponible (`IPD_ZSCORE_METODO = "clasico"`).
2. **Promedio ponderado.** Los subíndices pesan un tercio cada uno. Dentro de cada
   bloque, los pesos salen de **componentes principales**: se calcula la matriz
   de correlaciones de los promedios mensuales de los z-scores desde 2003 y cada
   componente pesa según su carga en el primer componente principal (cuánto se
   mueve junto con el resto). Las cargas negativas valen cero, para no invertir
   el sentido económico de ninguna variable, y ningún componente pesa menos del
   10% de su bloque (`IPD_PCA_PESO_MINIMO`). Los pesos se recalculan en cada
   corrida y se publican en `monitor.json`, el tablero y el reporte
   (`IPD_PONDERACION = "fija"` vuelve a los pesos manuales). Si falta un
   componente, su peso se reparte entre los demás; el índice sólo se publica si
   está disponible al menos el 40% del peso.
3. **Índice 0–100.** El IPD se promedia en 20 días hábiles y se lleva a una
   escala de 0 a 100 con la normal acumulada: Índice = 100 × Φ(IPD / σ), con σ el
   desvío histórico del IPD promediado. 50 es neutral; debajo, presión
   apreciatoria (alivio); arriba, presión depreciatoria. Tramos:
   - 0–10: fuerte presión apreciatoria;
   - 10–35: presión apreciatoria;
   - 35–65: neutral;
   - 65–90: presión depreciatoria;
   - 90–100: fuerte presión depreciatoria.

   También se publica el percentil del IPD en los últimos 2 años y el aporte de
   cada componente en puntos del índice (los aportes suman la distancia a 50).

Todo es configurable en `monitor/config.py`: horizonte, ventanas, pesos,
componentes, suavizado y tramos del índice, y eventos.

**Cuidados al leerlo.**

- Las reservas brutas también se mueven por pagos de deuda, desembolsos y
  valuación.
- Los cambios de régimen (cepo, desdoblamiento, bandas de abril de 2025) alteran
  la comparabilidad histórica. Un z-score móvil se adapta, pero puede
  "normalizar" un período largo de tensión.
- El índice mide presión relativa a la historia reciente, no niveles de
  equilibrio.

## Próximos pasos posibles

- Sumar la posición del BCRA en futuros (se publica con rezago).
- Agregar el breakeven de devaluación implícito entre LECAPs y bonos dollar
  linked a partir de precios de mercado.
- Agregar flujos diarios de FCI de dólares y de money market (CAFCI).
- Agregar las expectativas de tipo de cambio del REM (mensual).
