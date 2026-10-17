# Monitor de Dolarización (Argentina)

Tablero diario para seguir la presión cambiaria y la dolarización de
portafolios en Argentina, pensado para hacer incidencia en el ciclo electoral
2027. Su eje es el **Índice de Dolarización (ID)**, una adaptación
del *Exchange Market Pressure Index* a la economía bimonetaria argentina.
El tablero y el reporte cubren sólo Argentina. Los módulos de Perú,
Uruguay, Brasil, Chile, Colombia y el núcleo comparable siguen en el código
(`monitor/peru.py`, etc.; el monitor financiero usa algunas de sus piezas),
pero ya no se corren en el workflow diario ni se muestran.

```
.
├── index.html              ← tablero (estático, lee data/monitor.json)
├── monitor/
│   ├── config.py           ← fuentes, componentes, pesos, umbrales, eventos
│   ├── sources.py          ← descarga (BCRA, ArgentinaDatos, A3 Mercados)
│   ├── indicators.py       ← series derivadas e ID
│   ├── build.py            ← orquestador de Argentina: python -m monitor.build
│   ├── peru.py … colombia.py, comparado.py ← otros países (sin uso en el tablero)
│   ├── comun.py            ← piezas comunes a los países
│   └── report.py           ← reporte semanal: python -m monitor.report
├── data/
│   ├── monitor.json        ← lo que consume el tablero (generado)
│   ├── panel_diario.csv    ← panel diario completo, para Excel/R/Stata (generado)
│   ├── bcra_catalogo.csv   ← catálogo de variables del BCRA (generado)
│   ├── series/*.csv        ← historia cruda de cada serie (generado)
│   ├── pe/ uy/ br/ cl/ co/ ← datos históricos de otros países (ya no se actualizan)
│   └── comparado.json      ← núcleo comparable (ya no se actualiza)
└── tests/
```

## Cómo se actualiza

El workflow `.github/workflows/actualizar.yml` corre los días hábiles a
las 19:17 y 22:47 (hora argentina). En cada corrida:

1. Descarga las series.
2. Recalcula el ID.
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

**Historia.** El ID se publica desde 2003 (`IPD_PUBLICAR_DESDE`). Las series
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

## Metodología del ID

Se parte del EMP de Girton y Roper (1977) y Eichengreen, Rose y Wyplosz (1996):
*EMP = Δe/σₑ − Δr/σᵣ + Δi/σᵢ*. La versión argentina tiene tres subíndices,
ponderados por componentes principales (hoy 38%, 30% y 32%):

| Subíndice | Componente | Transformación | Signo |
|---|---|---|---|
| Presión cambiaria | Tipo de cambio A3500 | Δlog 5 días | + |
| | Volatilidad del oficial | desvío de variaciones diarias, 20 días, anualizado | + |
| | Reservas brutas | Δlog 5 días | − |
| | Tasa BADLAR | Δ 5 días | + |
| | Brecha MEP / oficial | nivel (antes de 2018, brecha CCL; antes de 2013, blue) | + |
| | Futuros de dólar vendidos por el BCRA (neto) | Δ 21 días de la posición vendida neta (una posición comprada cuenta como 0); entra 35 días después de cada fin de mes | + |
| Dolarización de portafolios | Devaluación implícita en futuros | nivel (TNA a 90 días) | + |
| | Posición abierta en futuros de dólar | nivel, promedio de 21 días | + |
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
2. **Promedio ponderado.** Los subíndices se ponderan por componentes principales
   (primer componente principal de los subíndices mensuales, con el mismo piso
   de 10%; con dos subíndices el método da 50/50). Dentro de cada
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
3. **Índice 0–100.** El ID se promedia en 20 días hábiles y se lleva a una
   escala de 0 a 100 con la normal acumulada: Índice = 100 × Φ(ID / σ), con σ el
   desvío histórico del ID promediado. 50 es neutral; debajo, presión
   apreciatoria (alivio); arriba, presión depreciatoria. Tramos:
   - 0–10: fuerte presión apreciatoria;
   - 10–35: presión apreciatoria;
   - 35–65: neutral;
   - 65–90: presión depreciatoria;
   - 90–100: fuerte presión depreciatoria.

   También se publica el percentil del ID en los últimos 2 años y el aporte de
   cada componente en puntos del índice (los aportes suman la distancia a 50).
   Los aportes se agrupan por subíndice y se publica también su cambio en 7 y
   30 días: los cambios suman exactamente lo que se movió el índice, así que se
   puede decir qué subíndice y qué componente lo movieron. Cada subíndice tiene
   además su propia escala 0–100, calculada igual que el índice.

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

## Monitor de Dolarización Financiera

Proyecto aparte, en `financiera/` (tablero) y `monitor/financiera.py`
(datos, `python -m monitor.financiera`). No mide estrés cambiario sino la
dolarización como la define la literatura (Ize y Levy Yeyati, 2003): qué parte
de los depósitos, el crédito y la liquidez está en moneda extranjera.

El tablero (`financiera/index.html`) muestra **sólo Argentina**: el selector
de país y la vista comparada están ocultos. El pipeline sigue calculando y
guardando los demás países en `data/financiera/`, por si se quieren volver a
mostrar (quitar el `hidden` del selector `#pais` y la lectura de `?pais=`).

| País | Depósitos | Crédito | Liquidez | Frecuencia | Fuente |
|---|---|---|---|---|---|
| Argentina | sí | sí | sí (con circulante); M3 desde 1940 | diaria | BCRA |
| Perú | sí | sí | sí (coeficiente del BCRP) | mensual | BCRP |
| Uruguay | sí | sí | – | mensual | BCU (SSF) |
| Bolivia | sí | sí | sí (M'3) | diaria las últimas semanas, mensual hacia atrás | BCB, información estadística semanal |
| Costa Rica | pasivos en ME de los bancos (aproximación) | sí | – | mensual, con rezago | FMI, indicadores de solidez financiera |
| Colombia | pasivos en ME de los bancos | sí | – | mensual, con rezago | FMI |
| Brasil, Chile | – | sí | – | trimestral / mensual, con rezago | FMI |

En Argentina se suman las compras netas de dólares de personas (FAE): por
mes, en 12 meses, acumuladas, y qué parte de lo comprado en 12 meses quedó en
depósitos (el resto va al colchón, al exterior o a otros activos).

Cada cambio se separa en **efecto valuación** (sólo el tipo de cambio) y
**efecto portafolio** (con el tipo de cambio del mes anterior); suman el
cambio total. Para los seis países se agregan los depósitos de residentes no
bancarios en bancos del exterior (BIS, estadísticas bancarias territoriales,
trimestral). Datos en `data/financiera/`.

### Traspaso del tipo de cambio a precios (unidad de cuenta)

`monitor/traspaso.py`. Proxy de cuánto se "piensa en dólares": qué parte de
una depreciación pasa al IPC. Por país y por mes, regresión móvil de 36 meses
(mínimo 30 observaciones) de la inflación mensual desestacionalizada sobre la
depreciación del tipo de cambio promedio del mes con rezagos 0–6, la inflación
rezagada y la inflación de materias primas en dólares (FMI, vía FRED). El
indicador es Σβ (traspaso acumulado a 7 meses), con banda del 95% por
Newey-West; se guarda también el de largo plazo Σβ/(1−ρ) y, como chequeo, el
cociente de proyecciones locales a 6 meses.

- Sin dato cuando el tipo de cambio casi no se mueve en la ventana (menos de
  8 meses con |depreciación| ≥ 0,5% o desvío < 0,5 pp): Bolivia hasta 2026.
- Argentina: variante principal con el dólar paralelo (blue 2011–2012, CCL
  desde 2013) y variante con el oficial. Inflación de la API del BCRA
  (variable 27, INDEC; subestimada 2007–2015).
- Los demás países: IPC (WS_LONG_CPI) y tipo de cambio promedio (WS_XRU) del
  BIS.
- Los cambios de régimen (`QUIEBRES` en `financiera.py`) se sombrean en el
  gráfico durante los 36 meses siguientes.

En el JSON de cada país, `traspaso.variantes[].data` = `[fecha, Σβ, límite
inferior, superior]` en %; `indicadores.traspaso` es la serie principal.

### Índice de las tres funciones del dinero (Argentina)

`monitor/funciones.py`. Cuánto cumple el dólar cada función del dinero, de 0
a 1 en la escala natural de cada pata:

- **Medio de pago**: dólares en los depósitos a la vista del sector privado
  (cuentas corrientes, otras a la vista y cajas de ahorro; BCRA, variables
  1528/1530/1532 en pesos y 1565/1567/1569 en dólares, diarias desde 1999).
  Variante con el circulante en pesos en el denominador (`vista_circulante`).
- **Unidad de cuenta**: traspaso acumulado a 7 meses con el dólar paralelo,
  acotado a [0, 1].
- **Reserva de valor**: promedio de la dolarización de depósitos y crédito.
  Alternativa: plazos fijos (`plazo_fijo`, variables 1534/1571).

Índice = promedio simple (meses con las tres patas). Chequeo: ponderación por
el primer componente principal (`indicators.pca_weights`, como el Índice de
Dolarización). El tablero muestra un triángulo estilo Aizenman–Chinn–Ito con
los promedios de 2007, 2015, 2019, 2023 y los últimos 12 meses. En `ar.json`,
bloque `funciones`.

## Próximos pasos posibles

- Agregar el breakeven de devaluación implícito entre LECAPs y bonos dollar
  linked a partir de precios de mercado.
- Agregar flujos diarios de FCI de dólares y de money market (CAFCI).
- Agregar las expectativas de tipo de cambio del REM (mensual).
