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

| Variable | Frecuencia | Fuente | Carga |
|---|---|---|---|
| Tipo de cambio mayorista A3500 | diaria | BCRA, API de Estadísticas v4 | automática |
| Reservas internacionales brutas | diaria | BCRA | automática |
| Tasas TAMAR / BADLAR privados | diaria | BCRA | automática |
| Depósitos en dólares | diaria | BCRA (si la variable está en el catálogo) | automática |
| Dólar oficial, mayorista, MEP, CCL y blue | diaria | [ArgentinaDatos](https://argentinadatos.com) | automática |
| Riesgo país (EMBI) | diaria | ArgentinaDatos | automática |
| Brechas CCL, MEP y blue | diaria | cálculo propio | derivada |
| Futuros de dólar: devaluación implícita e interés abierto | diaria | A3 Mercados | `data/manual/futuros_dolar.csv` |
| Compras de USD de personas humanas | mensual | BCRA, Informe del Mercado de Cambios y Balance Cambiario | `data/manual/compras_personas_humanas.csv` |
| Licitaciones del Tesoro (share dollar linked / USD) | por licitación | Secretaría de Finanzas | `data/manual/licitaciones_tesoro.csv` |

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
| | Reservas brutas | Δlog 5 días | − |
| | Tasa TAMAR / BADLAR | Δ 5 días | + |
| Dolarización de portafolios | Brecha CCL / oficial | nivel | + |
| | Riesgo país | Δ 5 días | + |
| | Devaluación implícita en futuros | nivel | + |
| | Depósitos en USD (peso ½) | Δlog 5 días | + |

El cálculo sigue estos pasos:

1. **Estandarización.** Cada componente pasa a z-score móvil sobre 504 días
   hábiles (unos 2 años), recortado a ±4. Esto equivale a ponderar por la
   inversa del desvío, como en el EMP clásico.
2. **Promedio ponderado.** Se promedia dentro de cada bloque y después entre
   bloques. Si falta un componente, su peso se reparte entre los demás. El
   índice sólo se publica si está disponible al menos el 50% del peso.
3. **Semáforo.** Se ubica el IPD en su percentil de los últimos 2 años:
   - menos de 75: presión baja;
   - desde 75: moderada;
   - desde 90: elevada;
   - desde 97,5: crítica.

Todo es configurable en `monitor/config.py`: horizonte, ventanas, pesos,
componentes, umbrales y eventos electorales.

**Cuidados al leerlo.**

- Las reservas brutas también se mueven por pagos de deuda, desembolsos y
  valuación.
- Los cambios de régimen (cepo, desdoblamiento, bandas de abril de 2025) alteran
  la comparabilidad histórica. Un z-score móvil se adapta, pero puede
  "normalizar" un período largo de tensión.
- El índice mide presión relativa a la historia reciente, no niveles de
  equilibrio.

## Próximos pasos posibles

- Automatizar los futuros de A3 Mercados (requiere acceso a su API de market
  data) y sumar la posición del BCRA en futuros.
- Agregar el breakeven de devaluación implícito entre LECAPs y bonos dollar
  linked a partir de precios de mercado.
- Agregar flujos diarios de FCI de dólares y de money market (CAFCI).
- Agregar las expectativas de tipo de cambio del REM (mensual).
- Descargar automáticamente el anexo del balance cambiario.
