# Monitor de Dolarización de Portafolios (Argentina)

Tablero diario para seguir la presión cambiaria y la dolarización de
portafolios en Argentina, pensado para hacer incidencia en el ciclo electoral
2027. Su eje es el **Índice de Presión de Dolarización (IPD)**, una adaptación
del *Exchange Market Pressure Index* a la economía bimonetaria argentina.

```
.
├── index.html              ← tablero (estático, lee data/monitor.json)
├── monitor/
│   ├── config.py           ← fuentes, componentes, pesos, umbrales, eventos
│   ├── sources.py          ← descarga (BCRA, ArgentinaDatos, CSV manuales)
│   ├── indicators.py       ← series derivadas e IPD
│   └── build.py            ← orquestador: python -m monitor.build
├── data/
│   ├── monitor.json        ← lo que consume el tablero (generado)
│   ├── panel_diario.csv    ← panel diario completo, para Excel/R/Stata (generado)
│   ├── bcra_catalogo.csv   ← catálogo de variables del BCRA (generado)
│   ├── series/*.csv        ← historia cruda de cada serie (generado)
│   └── manual/*.csv        ← fuentes que se cargan a mano o desde una Google Sheet
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
| Futuros de dólar: devaluación implícita e interés abierto | 2020 | diaria | A3 Mercados (API pública de precios de cierre) | automática; `data/manual/futuros_dolar.csv` para correcciones |
| Compras de USD de personas humanas | 2003 | mensual | BCRA, anexo del Informe de Evolución del Mercado de Cambios | automática (semanal); `data/manual/compras_personas_humanas.csv` para correcciones |
| Licitaciones del Tesoro (share dollar linked / USD) | — | por licitación | Secretaría de Finanzas | `data/manual/licitaciones_tesoro.csv` |

**Historia.** El IPD arranca en 1999. En los primeros años se calcula con los
componentes que ya existían (reservas, BADLAR y riesgo país; desde 2002 también el
A3500 y los depósitos en dólares). El panel diario incluye la columna
`ipd_n_componentes` y el tooltip del gráfico indica cuántos había cada día.

**Fuentes manuales.** Cada CSV trae en su encabezado el formato y de dónde
sacar el dato. En equipo, lo más práctico suele ser llevarlas en una Google
Sheet: publicala como CSV y poné el link en `MANUAL_SOURCES[...]["url"]` dentro
de `monitor/config.py`. El pipeline la descarga en cada corrida y, si la descarga
falla, conserva la copia local.

**IDs del BCRA.** Las variables se buscan con una expresión regular sobre su
descripción. Después de la primera corrida conviene revisar
`data/bcra_catalogo.csv` y fijar los IDs en `BCRA_VARIABLES` para que no cambien
de forma silenciosa. Si el certificado del BCRA falla en CI, existe la opción
`BCRA_SSL_VERIFY=0`. Esa variable sólo afecta a las llamadas al BCRA.

## Metodología del IPD

Se parte del EMP de Girton y Roper (1977) y Eichengreen, Rose y Wyplosz (1996):
*EMP = Δe/σₑ − Δr/σᵣ + Δi/σᵢ*. La versión argentina tiene dos bloques, con 50%
de peso cada uno:

| Bloque | Componente | Transformación | Signo |
|---|---|---|---|
| Presión cambiaria (EMP) | Tipo de cambio A3500 | Δlog 5 días | + |
| | Volatilidad del oficial | desvío de variaciones diarias, 20 días, anualizado | + |
| | Reservas brutas | Δlog 5 días | − |
| | Tasa BADLAR | Δ 5 días | + |
| Dolarización de portafolios | Brecha CCL / oficial | nivel | + |
| | Volatilidad del CCL | desvío de variaciones diarias, 20 días, anualizado | + |
| | Riesgo país | Δ 5 días | + |
| | Devaluación implícita en futuros | nivel | + |
| | Depósitos en USD (peso ½) | Δlog 5 días | + |

El cálculo sigue estos pasos:

1. **Estandarización.** Cada componente se estandariza contra los últimos 504
   días hábiles (unos 2 años) con mediana y MAD (desvío absoluto mediano ×
   1,4826), recortado a ±4. Equivale a ponderar por la inversa de la
   dispersión, como en el EMP clásico, pero sin que un episodio extremo (la
   devaluación de dic-23) infle la escala durante dos años. La versión con
   media y desvío estándar sigue disponible (`IPD_ZSCORE_METODO = "clasico"`).
2. **Promedio ponderado.** Se promedia dentro de cada bloque y después entre
   bloques. Si falta un componente, su peso se reparte entre los demás. El
   índice sólo se publica si está disponible al menos el 40% del peso.
3. **Índice 0–100.** El IPD se promedia en 10 días hábiles y se lleva a una
   escala de 0 a 100 con la normal acumulada: Índice = 100 × Φ(IPD / σ), con σ el
   desvío histórico del IPD promediado. 50 es neutral; debajo, presión
   apreciatoria (alivio); arriba, presión depreciatoria. Tramos:
   - 0–10: fuerte presión apreciatoria;
   - 10–35: presión apreciatoria;
   - 35–65: neutral;
   - 65–90: presión depreciatoria;
   - 90–100: fuerte presión depreciatoria.

   También se publica el percentil del IPD en los últimos 2 años.

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
