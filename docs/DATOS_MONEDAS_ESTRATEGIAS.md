# Datos, monedas, estrategias y qué se entrena

Respuestas directas: **qué datos usa**, **con qué monedas opera**, **de dónde salen las estrategias** y **cómo se decide qué entrenar**. Luego: **evaluación por etapas** (alpha solo, risk solo, mean reversion solo, sensores, combinaciones).

---

## 1. Qué datos está usando

| Dónde | Qué es |
|-------|--------|
| **Origen** | DuckDB: tabla **`main.decision_features`** (construida por dbt a partir de bronze/silver). |
| **Código** | `ai.data.loader.load_decision_features(db_path, horizon, start, end, symbols=None)`. Si no pasas `symbols`, carga **todos los símbolos** que haya en la tabla. |
| **Contenido** | Por fila: `event_time`, `symbol`, features (momentum_3, momentum_12, basis_bps, funding_rate_8h, alpha_signal, fwd_return_1h/4h/24h, quote_volume_24h, etc.). La tabla la rellena el pipeline dbt desde `slv_decision_features` y modelos gold (fct_decision_features.sql). |

No hay otro dataset “oficial” para la suite/explorer: todo viene de **decision_features** en DuckDB.

---

## 2. Con qué monedas opera

| Dónde se define | Cómo |
|-----------------|------|
| **En la tabla** | Los símbolos que existen en `decision_features` son los que cargó el **backfill** (bronze) y que dbt dejó en la gold layer. |
| **Backfill** | `data_platform.backfill_bronze_historical` (y similares) usa **`cfg.symbols`**: viene de env **`DP_SYMBOLS`** o de la config del data platform (ej. lista fija o “top” por volumen). Si hiciste backfill con `DP_SYMBOLS=BTCUSDT,ETHUSDT,...` o con un set “top”, esas son las monedas que tienes. |
| **Suite / optimizer** | Si no filtras, usa **todos los símbolos** de la tabla. Si usas `symbol_sets` (top20, top50, all), el optimizer usa `get_top_symbols_by_volume(rows, top_n)` para restringir a los N más líquidos por volumen USD en esos mismos datos. |

Resumen: **opera con las monedas que están en `decision_features`**; esa lista la define el backfill (DP_SYMBOLS / config), y la suite puede restringir por top20/top50 o usar “all”.

---

## 3. De dónde saca las estrategias

| Dónde | Qué es |
|-------|--------|
| **Registro** | `ai.explorer.registry`: un diccionario en memoria donde se registran **StrategyDef** (id, name, default_params, param_ranges, build_compute_fn). |
| **Registro automático** | En `registry.py`, `_register_builtins()` importa y registra tres estrategias: **alpha_score**, **heuristic**, **mean_reversion** (de `ai.explorer.strategies`). No se leen de DB ni de config: son las que están **hardcodeadas** en el código. |
| **Otras** | Para añadir una estrategia nueva: creas una `StrategyDef` en `ai/explorer/strategies/`, la registras con `register_strategy(...)` y ya participa en explorer/optimizer/suite. |

No hay “lista de estrategias en un archivo de config”: vienen **solo del registro en código** (hoy: alpha_score, heuristic, mean_reversion).

---

## 4. Cómo decide qué “entrenar”

Hoy **no hay una decisión explícita de “qué entrenar”** en la suite:

- **Suite / optimizer:** Hacen **grid o sample** sobre estrategias × parámetros × horizontes × symbol_sets. No eligen “hoy entreno solo mean reversion”; prueban **combinaciones** y se quedan con las que mejor retorno neto den. El “champion” es la mejor config encontrada, no un modelo que “se decidió entrenar” por etapas.
- **Modelo ML (LightGBM):** Se entrena en **otro pipeline** (`auto_train_eval.py`, Optuna, Dagster `quant_model_train`). La suite **no** decide cuándo ni qué entrenar; solo elige estrategias y params. Para que el alpha “se entrene” y se use, hay que tener un flujo que corra ese training aparte y, si quieres, rellenar `alpha_score` antes de evaluar la estrategia alpha_score.

Por eso tiene sentido lo que pides: **evaluación por etapas** (alpha solo, risk solo, mean reversion solo, sensores, luego combinaciones) y que la “decisión” de qué usar se base en esas evaluaciones.

---

## 5. Evaluación por etapas (diseño)

La idea: **evaluar cada bloque solo**, guardar los mejores, y luego **evaluar combinaciones** de los mejores.

| Etapa | Qué se evalúa solo | Salida |
|-------|--------------------|--------|
| **1 – Alpha solo** | Solo la señal alpha → asignación. Una estrategia (p. ej. alpha_score), sin variar risk. Parámetros: prob_threshold, min/max_allocation. Métrica: retorno neto (o hit rate del score si quieres aislar calidad del alpha). | Top N configs de alpha. |
| **2 – Risk management solo** | Misma estrategia base (p. ej. la mejor alpha o una fija), **solo** se varían parámetros de risk: max_per_symbol, max_exposure, max_net_exposure, kill switch por drawdown. Métrica: retorno ajustado por riesgo, drawdown, Sharpe-like. | Top N configs de risk. |
| **3 – Mean reversion solo** | Solo estrategia mean_reversion: oversold, overbought, top_volatile, vol_metric. Sin mezclar con alpha ni risk variable. Métrica: retorno neto. | Top N configs mean reversion. |
| **4 – Sensores de movimiento inminente** | Señales que indican “movimiento inminente”: p. ej. heuristic (alpha_signal LONG/SHORT de DBT), o reglas sobre momentum_3/momentum_12 extremos, volatility spike, liquidity_event. Se evalúan **solos** (una estrategia o detector por vez). Métrica: retorno neto, o precisión si definimos “evento” explícito. | Top N sensores/configs. |
| **5 – Combinaciones** | Se toman los **mejores de cada etapa** (ej. top 2 alpha, top 2 risk, top 2 mean reversion, top 2 sensores) y se evalúan **combinaciones**: alpha + risk overlay, mean_reversion + risk, alpha + mean_reversion (blend o secuencia), sensores como filtro de entrada, etc. Métrica: retorno neto (y opcionalmente riesgo). | Mejores combinaciones y un “champion” global. |

Así tienes: **datos y monedas** claros, **origen de estrategias** claro, **qué “entrenar”/elegir** basado en evaluación por etapas y luego en combinaciones.

---

## 6. Implementación: evaluador por etapas

- **Módulo:** `ai.explorer.staged_eval.py`
  - `run_stage_alpha_only(rows, ...)` → mejores configs solo alpha.
  - `run_stage_risk_only(rows, base_strategy_id, risk_grid)` → mejores configs solo risk overlay.
  - `run_stage_mean_reversion_only(rows, ...)` → mejores configs solo mean reversion.
  - `run_stage_sensors(rows, ...)` → mejores configs sensores (heuristic / alpha_signal).
  - `run_stage_combinations(rows, best_alpha, best_risk, best_mr, best_sensors, top_per_stage)` → mejores combinaciones (alpha+risk, mean_reversion+risk).
  - `run_all_stages(rows, ...)` → ejecuta las 5 y devuelve `stage_alpha`, `stage_risk`, `stage_mean_reversion`, `stage_sensors`, `stage_combinations`, `best_overall`.

- **Script:** `python scripts/run_staged_eval.py [--lookback-days 45] [--out artifacts/quant_model/staged_report.json]`  
  Escribe un informe JSON con los top por etapa y el mejor global.
