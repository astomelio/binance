# Qué hacen los “modelos” en este proyecto

Hay **dos cosas distintas** que se pueden llamar “modelo”. Es fácil liarse; aquí va el desglose.

---

## 1. Modelo ML (LightGBM) — el que predice “sube o baja”

| Qué es | Un clasificador (LightGBM) que entrena con tus features y predice probabilidad de que el precio suba en el horizonte (1h, 4h, etc.). |
| Dónde se entrena | `scripts/auto_train_eval.py`, `examples/quant_optuna_tuning.py` |
| Input | Vector de features por fila (momentum, funding, basis, fear_greed, etc.) |
| Output | Un **score por fila** (o probabilidad). Ese score se guarda en la columna **`alpha_score`** de cada fila. |
| Quién lo usa | La **estrategia alpha_score** y `compute_allocations()`: leen `alpha_score` y deciden cuánto long/short por símbolo. |

**Importante:**  
Si **nunca** pasas las filas por `enrich_rows_with_model(rows, model)`, la columna `alpha_score` en DuckDB está vacía o a 0. Entonces la estrategia que usa `alpha_score` **no abre posiciones** (todo queda en 0) → 0 trades.  
La suite **no entrena** este modelo. Solo elige qué estrategia y qué parámetros usar. El entrenamiento del LightGBM es otro pipeline (cron, Dagster `quant_model_train`, etc.).

---

## 2. “Estrategias” en la suite — no son redes, son reglas

La suite (y el explorer) no entrenan redes ni LightGBM. Lo que hacen es **probar reglas** que convierten **columnas que ya tienes en la tabla** en un **vector de asignación** (cuánto long/short por símbolo).

| Estrategia | Qué columna(s) usa | Qué hace |
|------------|--------------------|----------|
| **alpha_score** | `alpha_score` | Si `alpha_score` > umbral → long; si < (1-umbral) → short. Si la columna está vacía o 0 → no cruza umbral → **0 trades**. |
| **heuristic** | `alpha_signal` | Si `alpha_signal == "LONG"` → long; si `"SHORT"` → short. Si la columna no existe o es `NO_TRADE` → **0 trades**. |
| **mean_reversion** | `momentum_3` (u otra) | Si momentum ≤ oversold → long; si ≥ overbought → short. Usa datos que suelen estar en la tabla. |

Todas devuelven un **AllocationVector**: `{ "BTCUSDT": 0.2, "ETHUSDT": -0.1, ... }`.  
El **backtest** toma ese vector barra a barra, aplica retornos y fees, y te da net return % y número de trades.

---

## 3. Cómo se conectan (o no)

```
Datos (DuckDB)
  → decision_features: event_time, symbol, momentum_3, alpha_signal, fwd_return_*, ...
  → Opcional: alpha_score (solo si antes pasaste por enrich_rows_with_model)

Estrategia (alpha_score / heuristic / mean_reversion)
  → Lee las columnas que toquen (alpha_score, alpha_signal, momentum_3, ...)
  → Devuelve AllocationVector

Backtest
  → Aplica ese vector en cada barra
  → Calcula retorno neto, trades, fees
```

- Si **no** rellenas `alpha_score` con el LightGBM, las estrategias **alpha_score** y (según cómo esté DBT) **heuristic** pueden dar **0 trades**.
- **Mean reversion** sí usa columnas que suelen existir (momentum, etc.), por eso puede dar trades aunque no uses el modelo ML.

La **suite** lo que hace es: probar muchas **combinaciones** de (estrategia, parámetros, horizonte, conjunto de activos) y quedarse con la que mejor retorno neto dé. **No** entrena el LightGBM; solo elige “qué regla y qué params usar” y puede promover un **champion** (esa config).

---

## 4. Leakage temporal en el backtest

En cada barra **t** el backtest hace:

1. Pasa a la estrategia **solo** `features` de esa barra (por símbolo): `compute_fn(features_by_time[t], ts)`.
2. La estrategia devuelve el **AllocationVector** para **t** (qué asignar en **t**).
3. El motor usa **fwd_return** de la fila (retorno de t → t+1) **solo para calcular el PnL**: `ret = alloc[s] * fwd_return[s]`. No pasa `fwd_return` a la estrategia.

Las estrategias actuales (`compute_allocations`, mean_reversion, heuristic) **no leen** `fwd_return_*`; solo leen `alpha_score`, `fed_window`, `momentum_3`, `alpha_signal`, etc. Por tanto **no hay leakage**: la decisión en **t** se toma con información hasta **t**; el retorno que se atribuye es el de t→t+1, que es el correcto.

**Regla de diseño:** las funciones que implementan estrategias (`compute_fn`) **no deben usar** las columnas `fwd_return_*` para decidir asignación; esas columnas son solo para que el backtest calcule el resultado.

---

## 5. Evitar “optimizar el vacío”: checks y conexión con el champion

Para no confundir “el modelo no aporta señal” con “el modelo funciona mal” cuando en realidad `alpha_score` estaba vacío:

- **Comprobación de cobertura:** `ai.allocation.checks.check_alpha_score_coverage(rows, ...)` cuenta qué fracción de filas tienen `alpha_score` no null y no cero. Si está por debajo de un mínimo, puedes **avisar** o **fallar**.
- **Warning por defecto:** Si ejecutas la suite **sin** rellenar `alpha_score`, se llama `warn_alpha_score_if_low(rows)`: si hay pocas filas con score no cero, se emite un **UserWarning** indicando que quizá estás evaluando una columna vacía y que uses `--use-champion` o `enrich_rows_with_model()`.
- **Modo estricto:** `--strict-alpha` en `run_suite_cycle.py` hace que el script **falle** si la cobertura es baja (útil en CI o para no promover resultados basados en vacío).
- **Integración con el champion:** `--use-champion` carga el modelo **models:/quant_alpha_entry_lgbm@champion** desde MLflow, rellena `alpha_score` en las filas con `enrich_rows_with_champion()`, y luego ejecuta la suite. Así la suite evalúa el modelo real. Ver `ai.inference.champion_loader`.

Uso recomendado cuando quieras que alpha_score tenga sentido:

```bash
python scripts/run_suite_cycle.py --use-champion
python scripts/run_suite_cycle.py --optimize --use-champion --strict-alpha
```

---

## 6. Resumen en una frase

- **Modelo ML (LightGBM):** predice score por barra/símbolo; ese score se escribe en `alpha_score` y lo usa la estrategia alpha_score. Si no rellenas `alpha_score`, esa estrategia no hace trades.
- **Suite:** optimiza estrategias + parámetros; no entrena el LightGBM. Con `--use-champion` rellenas `alpha_score` antes de evaluar, así la suite y el modelo trabajan juntos. Los checks evitan optimizar una columna vacía sin darte cuenta.
