# AI: Backtest, vectores de asignación y frames temporales

## Vectores de asignación

**Formato:** `allocation[symbol]` = fracción de capital en [-1, 1]:
- `0` = sin posición
- `0.2` = 20% long
- `-0.2` = 20% short

**Restricción:** `sum(|a|) <= 1` (100% exposición máxima).

El algoritmo convierte `alpha_score` (o prob) en allocation usando umbral y normalización.

## Cómo probar las herramientas

```bash
# 1. Cargar warehouse (requisito previo)
make warehouse-load

# 2. Ver vector de asignación actual (0, 0.2, -0.2 por moneda)
make ai-alloc
python examples/ai_alloc.py --horizon 4h --prob-threshold 0.52

# 3. Backtest con vectores de asignación
make ai-backtest
python examples/ai_backtest.py --horizon 4h --prob-threshold 0.52 --fee-percent 0.04

# 4. Entrenar modelo + calibration
make ai-train

# 5. Inferencia (último event_time por símbolo)
make ai-infer

# 6. Ver corridas registradas
make ai-registry-list

# 7. Explorar estrategias (librería ai.explorer para agentes)
make ai-explorer-agent
python examples/ai_explorer_agent.py quick   # todas con defaults
python examples/ai_explorer_agent.py grid --strategy mean_reversion --max-combos 50
python examples/ai_explorer_agent.py full   # exploración completa

# Uso programático
from ai.explorer import ExplorationAgent
agent = ExplorationAgent(horizon="4h")
report = agent.run_quick()   # o run_grid("mean_reversion"), run_full()
```

---

## Frames temporales: cuándo se puede operar

**Regla:** Solo puedes comprar/vender en los instantes donde tienes datos.

| Intervalo de datos | event_time cada | Operaciones posibles |
|--------------------|-----------------|----------------------|
| 1h (actual)        | 1 hora          | Cada hora en punto  |
| 4h                 | 4 horas         | Cada 4 horas        |
| 15m                | 15 min          | Cada 15 min         |

El backtest recorre las filas de `decision_features` en orden de `event_time`. En cada fila:
- `event_time` = instante del snapshot
- `alpha_signal` = LONG | SHORT | NO_TRADE
- `futures_last_price` = precio de entrada/salida en ese instante

**No hay operaciones entre filas.** Si los datos son cada 1h, no puedes simular una operación a las 10:30.

### Dónde se define el intervalo

| Componente | Parámetro | Default |
|------------|-----------|---------|
| Backfill histórico | `--interval` en `backfill_bronze_historical` | 1h |
| Backfill vision | `make warehouse-backfill-vision` | 1h |
| Collectors live (API) | Config del collector | 1h |
| dbt (momentum, fwd_returns) | lag 3 = 3h, lag 12 = 12h | 1h |

Para 1h (principales ~20 símbolos, funding + OI):
```bash
make warehouse-backfill-vision   # ~15-20 min
make warehouse-load
```

---

## Parametrización del algoritmo de asignación

### 1. compute_allocations (ai/allocation/strategies.py)

Convierte features por symbol en vector de asignación:

```python
alloc = compute_allocations(
    features_by_symbol,
    score_key="alpha_score",
    prob_threshold=0.55,   # prob > 0.55 -> long, prob < 0.45 -> short
    min_allocation=0.1,   # mínimo 10% si hay señal
    max_allocation=0.4,   # máximo 40% por symbol
    max_exposure=1.0,     # sum(|a|) <= 1
    fed_window_key="fed_window",
    no_trade_windows=("PRE_EVENT", "POST_EVENT", "UNKNOWN"),
)
```

### 2. score_to_allocation

`alpha_score` (o prob) → allocation:
- `score >= prob_threshold` → long (0.1 a 0.4 según confianza)
- `score <= 1 - prob_threshold` → short (-0.1 a -0.4)
- else → 0

### 3. Backtest (ai/allocation/backtest.py)

- En cada `event_time`: `alloc = compute_allocations(features)`
- Retorno: `sum(alloc[s] * fwd_return[s])`
- Fees: `sum(|delta|) * fee_percent` sobre cambios de posición
- Slippage (opcional): `slippage_percent` por cambio de posición (p. ej. 0.02 para realismo)
- Liquidez: `min_quote_volume_24h` excluye símbolos con volumen 24h (USD) por debajo del umbral

### 4. Mean reversion (pares volátiles)

- **Señal:** momentum_3 (o momentum_12, price_change_percent_24h) < oversold → LONG, > overbought → SHORT
- **Volatilidad:** símbolos ordenados por mean(|momentum|). Top N = más volátiles.
- **Umbrales:** más conservadores (-3, +3) = menos trades, menos fees. Más agresivos (-1, +1) = más trades.
- **Grid:** `--grid-mr --top-volatile 10` para buscar mejor oversold/overbought.

---

## Símbolos (monedas)

Por defecto: `BTCUSDT,ETHUSDT,BNBUSDT` (DP_SYMBOLS).

Opciones:
- `DP_SYMBOLS=all` → ~500 USDT perpetual (fetch de Binance)
- `DP_SYMBOLS=top` → ~20 más líquidos (BTC, ETH, SOL, XRP, etc.)
- `DP_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT` → lista explícita

```bash
# Opción RÁPIDA: data.binance.vision (descargas directas, ~1-2h para todas)
make warehouse-backfill-vision
make warehouse-load

# Opción lenta: API Binance (5-6h para todas)
export DP_SYMBOLS=all
make warehouse-backfill
make warehouse-load
```

Listar símbolos:
```bash
make symbols-list        # los configurados
make symbols-list-all    # todos de Binance
```

## Realismo del backtest

Para que los resultados se acerquen a la ejecución real se aplican:

| Medida | Dónde | Descripción |
|--------|--------|-------------|
| **Lag macro (no lookahead)** | `br_macro_context.sql` | SP500 y oil se unen por **día anterior** al `event_time`. El cierre del S&P es ~21:00 UTC; usar el mismo día causaría leakage. |
| **Slippage** | `run_allocation_backtest(slippage_percent=0.02)` | **0.02** = 0,02% del notional por cada “lado” del trade (entrada o salida). Ej.: pasar de 0→30% long cobra 0,006%; ida y vuelta 0,012%. Simula que no ejecutas exactamente al precio de cierre. Por defecto 0. |
| **Filtro de liquidez** | `run_allocation_backtest(min_quote_volume_24h=1e6)` | **1e6** = 1 M USD de volumen en 24h. Solo se incluyen pares con al menos ese volumen; por debajo el spread/slippage real suele ser alto y el backtest sería engañoso. 1M es permisivo; 10M–50M más realista. Por defecto sin filtro. |

Runner y explorer exponen estos parámetros: `run_backtest(slippage_percent=..., min_quote_volume_24h=...)`, `run_single(..., slippage_percent=..., min_quote_volume_24h=...)`.

---

## Resumen

| Qué parametrizar | Dónde |
|------------------|-------|
| Frecuencia de trading | Intervalo del backfill/collectors (1h, 15m, etc.) |
| Señales heurísticas | dbt `fct_decision_features.sql` (alpha_signal) |
| Umbrales ML | `ai/training/pipeline.py`, calibration |
| Riesgo FED | dbt `fed_window`, alpha_backtest cierra en PRE/POST |
| Slippage / liquidez | `run_backtest`, `run_allocation_backtest`, `run_single` |
