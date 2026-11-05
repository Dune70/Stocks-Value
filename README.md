# Valuador — Fases 1 a 3: datos, motor DCF y valuación

Baja y normaliza los datos de una acción de EE.UU. en `data/fundamentals/<TICKER>.json`, listo para el motor DCF (fase 2).

## Instalación

```bash
pip install -r requirements.txt
```

## Variables de entorno

| Variable | Obligatoria | Qué es |
| --- | --- | --- |
| `SEC_USER_AGENT` | Sí | `"Nombre Apellido email@dominio.com"`. La SEC rechaza pedidos sin esto. |
| `VALUADOR_ERP` | No | Prima de riesgo de mercado (default `0.045`). Actualizala cada mes con el ERP implícito de Damodaran. |
| `FMP_API_KEY` | No | Clave gratis de Financial Modeling Prep para el consenso de ingresos. |

## Uso

```bash
python -m valuador fetch TEM AAPL MSFT          # usa caché
python -m valuador fetch TEM --refresh --print  # ignora caché y muestra el JSON
python -m valuador valuar TEM ORCL              # 5 escenarios, intrínseco, rango, DCF inverso, escalera
python -m valuador value TEM --g1 0.25 --margin 0.20 --sc 1.5 --detail   # DCF con supuestos a mano
python -m valuador industrias bank              # busca nombres de industria de Damodaran
python diag.py XOM                              # diagnóstico de etiquetas XBRL
pytest -q                                       # tests offline
```

### Parámetros de `value`

| Parámetro | Qué es |
| --- | --- |
| `--g1` | crecimiento de ingresos del año 1 |
| `--margin` | margen EBIT objetivo |
| `--sc` | ventas / capital invertido (cuántos US$ de ventas nuevas genera cada US$ reinvertido) |
| `--years-to-target` | años hasta llegar al margen objetivo (default 7) |
| `--high-growth-years` | años con crecimiento g1 antes de empezar a bajar (default 1) |
| `--gT` | crecimiento terminal (default tasa libre de riesgo − 0,5 pp) |

## Fuentes

| Bloque del JSON | Fuente |
| --- | --- |
| `financials` (5 años + TTM + balance + acciones) | SEC EDGAR companyfacts (XBRL) |
| `profile`, `market` | yfinance (nombre, sector, web, precio, beta) + EDGAR como respaldo |
| `rates.risk_free` | FRED DGS10 (bono 10 años) |
| `industry` | Damodaran `margin.xls` y `betas.xls` |
| `estimates` | FMP plan gratis (opcional) |

Si una fuente falla, el resto sigue y el problema queda en `warnings`.

## Archivos editables en `data/`

- `industry_map.json`: fuerza la industria de Damodaran cuando el match automático es malo. Ej: `{"Health Information Services": "Heathcare Information and Technology"}` (el nombre tiene que ser exacto al de la planilla).
- `summaries.json`: resúmenes en castellano por ticker, `{"TEM": "Medicina de precisión con IA: ..."}`.

## A verificar en la primera corrida real

- Los nombres de campo de FMP (`revenueAvg`, `revenueLow`, `revenueHigh`, `numAnalystsRevenue`) y si el plan gratis incluye ese endpoint.
- Los nombres de columna de las planillas de Damodaran (se buscan por palabras clave).

## Valuación (`valuar`)

Escribe `data/valuations/<TICKER>.json` y muestra un resumen.

- **Escenarios:** todo mal, conservador, base, optimista, todo bien. El base sale de datos (consenso o crecimiento histórico, margen de la industria o el actual si es mayor, ventas/capital histórica). Los otros son desvíos fijos (ver `RULES` en `assumptions.py`).
- **Intrínseco:** conservador / base / optimista ponderados 25/50/25. El base queda fijo en 50%; el reparto de los otros dos se edita por ticker (15%–35% cada uno) y queda marcado como modificado.
- **Rango:** sensibilidad a WACC ±0,5 pp y g terminal ±0,5 pp.
- **DCF inverso:** qué margen objetivo o qué crecimiento del año 1 hace que el valor iguale al precio.
- **Escalera:** todo mal · conservador · (conservador + base)/2 · base × 0,95 · (base + optimista)/2 · optimista · todo bien. Banda de tolerancia ±8%.
- **¿Alcanzable en el año?:** la zona se cruza con precio × e^(±volatilidad anual).

### `data/overrides.json`

```json
{
  "TEM": {
    "all":         {"nol": 1500000000},
    "base":        {"g1": 0.25, "margin_target": 0.20},
    "conservador": {"margin_target": 0.12},
    "weights":     {"conservador": 0.30, "optimista": 0.20}
  }
}
```

`all` aplica a los cinco escenarios; cada escenario acepta cualquier campo de `DCFInputs` (`g1`, `margin_target`, `sales_to_capital`, `years_to_target`, `high_growth_years`, `g_terminal`, `nol`, `p_failure`, `wacc_shift`, etc.).

## Publicación (GitHub Pages + Action)

- `docs/index.html`: la página. Lee `docs/data/index.json` y `docs/data/<TICKER>.json`, toma el precio en vivo de data912 y recalcula zona, potencial y "alcanzable" con ese precio. Se elige empresa con el selector o con `#TICKER` en la dirección.
- `.github/workflows/valuacion.yml`: corre de lunes a viernes 19:17 (Buenos Aires) y a mano desde la pestaña Actions, con un campo opcional para agregar un ticker.
- `data/watchlist.json`: lista de seguimiento (`python -m valuador watch add MSFT`).

Secretos del repositorio (Settings → Secrets and variables → Actions):

| Nombre | Tipo | Valor |
| --- | --- | --- |
| `SEC_USER_AGENT` | Secret | `Nombre Apellido email@dominio.com` |
| `FMP_API_KEY` | Secret | opcional |
| `VALUADOR_ERP` | Variable | opcional, ej. `0.045` |
