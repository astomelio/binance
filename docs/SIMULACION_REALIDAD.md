# Simular la realidad: órdenes tuyas → ejecución → resultado

Un solo flujo replicable: tú pasas **vector de monedas** y **asignaciones normalizadas por barra**; el sistema **ejecuta** entradas/salidas y devuelve retorno neto y trades. Mismo input → mismo output en cualquier experimento.

---

## Input

1. **Vector de monedas:** lista de símbolos, ej. `["BTCUSDT", "ETHUSDT", "BNBUSDT"]`.
2. **Asignaciones por barra:** por cada `event_time` (cada vela), un vector de cantidades normalizadas (ej. 0.2 = 20% long, -0.1 = 10% short, 0 = nada). Orden = mismo que el vector de monedas si usas `"vector"`, o por clave símbolo.

Los datos de mercado (precios/retornos por barra) se leen de DuckDB `decision_features`; tú solo pasas las órdenes.

---

## Cómo ejecutarlo

### Opción A: JSON de entrada (recomendado)

Crea un JSON con este formato:

```json
{
  "symbols": ["BTCUSDT", "ETHUSDT"],
  "horizon": "1h",
  "fee_percent": 0.04,
  "slippage_percent": 0.02,
  "allocations": [
    { "event_time": "2026-01-27T00:59:59.999000+00:00", "BTCUSDT": 0.2, "ETHUSDT": -0.1 },
    { "event_time": "2026-01-27T01:59:59.999000+00:00", "BTCUSDT": 0.3, "ETHUSDT": 0.0 }
  ]
}
```

O con vector en orden de `symbols`:

```json
{
  "symbols": ["BTCUSDT", "ETHUSDT"],
  "allocations": [
    { "event_time": "2026-01-27T00:59:59.999000+00:00", "vector": [0.2, -0.1] },
    { "event_time": "2026-01-27T01:59:59.999000+00:00", "vector": [0.3, 0.0] }
  ]
}
```

Luego:

```bash
set DBT_DUCKDB_PATH=artifacts\warehouse\crypto.duckdb
set PYTHONPATH=%CD%
python scripts/run_sim_from_orders.py --input artifacts/quant_model/orders_to_simulate_example.json --out artifacts/quant_model/sim_result.json
```

### Opción B: API en Python (replicable en notebooks/experimentos)

```python
from ai.data.loader import load_decision_features
from ai.allocation.backtest import run_backtest_from_orders

# 1. Datos de barras (DuckDB)
rows = load_decision_features(
    horizon="1h",
    symbols=["BTCUSDT", "ETHUSDT"],
    start="2026-01-27",
    end="2026-01-28",
    label_not_null=True,
    db_path="artifacts/warehouse/crypto.duckdb",
)

# 2. Tus órdenes: por cada event_time, asignación por símbolo (normalizada)
allocations_by_ts = {
    "2026-01-27T00:59:59.999000+00:00": {"BTCUSDT": 0.2, "ETHUSDT": -0.1},
    "2026-01-27T01:59:59.999000+00:00": {"BTCUSDT": 0.3, "ETHUSDT": 0.0},
    # ...
}

# 3. Ejecutar simulación
result = run_backtest_from_orders(
    rows,
    allocations_by_ts,
    horizon="1h",
    fee_percent=0.04,
    slippage_percent=0.02,
    symbols=["BTCUSDT", "ETHUSDT"],
)

print("Retorno neto %:", result.net_return_percent)
print("Trades:", result.trades_count)
```

---

## Output

- **Retorno neto %:** retorno bruto menos fees y slippage.
- **Trades:** número de cambios de posición (entradas/salidas).
- **Por símbolo:** contribución al retorno por moneda.
- Opcional: `--out fichero.json` escribe todo en JSON.

---

## Resumen

| Qué | Dónde |
|-----|--------|
| Definición de “ejecutar órdenes” | `ai/allocation/backtest.py` → `run_backtest_from_orders()` |
| Script CLI (JSON → resultado) | `scripts/run_sim_from_orders.py` |
| Ejemplo de JSON | `artifacts/quant_model/orders_to_simulate_example.json` |

Mismo vector de monedas y mismas asignaciones por barra → mismo resultado en cualquier máquina o experimento.
