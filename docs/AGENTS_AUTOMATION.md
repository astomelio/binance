# Automatización de flujos de agentes AI

Guía para orquestar y automatizar los flujos de agentes de modelos de AI (exploración, entrenamiento, evaluación).

**Flujo claro (datos → features → entrenar → backtest) y cómo validar el backtest con la simulación en paper:** ver [FLUJO_DATOS_ENTRENAMIENTO_BACKTEST.md](FLUJO_DATOS_ENTRENAMIENTO_BACKTEST.md).  
**Usar GPU (tarjeta de video) en entrenamiento:** ver [GPU_CUDA_SETUP.md](GPU_CUDA_SETUP.md).

---

## 1. Componentes del sistema

| Componente | Descripción | Entrypoint |
|------------|-------------|------------|
| **ExplorationAgent** | Explora estrategias (alpha_score, heuristic, mean_reversion). Grid search, backtest. | `ai.explorer.ExplorationAgent` |
| **Quant Optuna** | Entrenamiento LightGBM con walk-forward, MLflow. | `examples/quant_optuna_tuning.py` |
| **Model Evaluation** | Compara LightGBM, XGBoost, mean reversion. 1 vs N monedas. | `examples/quant_model_evaluation.py` |
| **Data Pipeline** | Bronze → Silver → Gold → Warehouse (DuckDB + dbt). | `data_platform.pipeline` |
| **Backfill External** | Fear & Greed, FRED (FED, SP500, oil), CoinGecko, FED Calendar, Glassnode. | `data_platform.backfill_external_sources` |

---

## 2. Flujos recomendados

### Flujo A: Pipeline de datos (diario/semanal)

```
backfill_external_sources → warehouse-load (bronze→DuckDB) → dbt run
```

- **Cuándo**: Diario (fuentes externas) o tras backfill histórico.
- **Comandos**:
  ```bash
  python -m data_platform.backfill_external_sources
  make warehouse-load
  ```

### Flujo B: Entrenamiento + evaluación (semanal)

```
warehouse (con datos frescos) → quant_optuna_tuning → quant_model_evaluation
```

- **Cuándo**: Semanal o tras actualizar datos.
- **Comandos**:
  ```bash
  make quant-optuna          # Entrena LightGBM, registra en MLflow
  make quant-model-eval     # Evalúa LightGBM vs XGBoost vs mean reversion
  ```

### Flujo C: Agente explorador (búsqueda de estrategias)

```
warehouse → ExplorationAgent.run_quick | run_grid | run_full
```

- **Cuándo**: Exploración ad-hoc o programada (ej. cada lunes).
- **Comandos**:
  ```bash
  make ai-explorer-agent                    # quick
  python examples/ai_explorer_agent.py grid --strategy mean_reversion --max-combos 50
  python examples/ai_explorer_agent.py full
  ```

### Flujo D: Flujo completo (end-to-end)

```
backfill_external → warehouse-load → dbt → explorer quick → quant-optuna → model-eval
```

- **Comandos**:
  ```bash
  make agent-flow-full
  # o
  python scripts/run_agent_flow.py --steps all
  ```

- **Prerrequisito**: Para `model-eval` se necesita `decision_features_backfill` (JSONL). Si no existe, ejecutar antes:
  ```bash
  make warehouse-backfill-vision
  ```

---

## 3. API endpoints para automatización

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/actions/backfill` | Backfill Binance Vision |
| POST | `/actions/warehouse-load` | Cargar bronze → DuckDB |
| POST | `/actions/train` | Entrenar modelo (Optuna) |
| POST | `/actions/explorer-agent` | Ejecutar ExplorationAgent (quick/grid/full) |
| POST | `/actions/model-evaluation` | Evaluar modelos (LightGBM, XGBoost, mean reversion) |
| POST | `/actions/backfill-external` | Backfill fuentes externas (FRED, Fear&Greed, etc.) |
| GET | `/actions/status` | Listar jobs en background |
| GET | `/actions/status/{job_id}` | Estado de un job |

---

## 4. Orquestación con Dagster

Dagster ya orquesta los assets de datos:

- `bronze_*` → `silver_*` → `gold_*` → `warehouse_raw_load` → `warehouse_dbt_build`

Los jobs de agentes (training, explorer, evaluation) se pueden:

1. **Ejecutar vía API** desde un cron externo o scheduler.
2. **Añadir como assets opcionales** en Dagster (si se instala `dagster`).
3. **Ejecutar con `make`** desde un script de cron.

---

## 5. Cron / scheduling

Ejemplo crontab para Linux/macOS:

```cron
# Diario 00:30 - Backfill fuentes externas + warehouse
30 0 * * * cd /path/to/binance && make agent-flow-data

# Lunes 02:00 - Entrenamiento + evaluación
0 2 * * 1 cd /path/to/binance && make agent-flow-train

# Semanal - Explorador completo
0 3 * * 0 cd /path/to/binance && make ai-explorer-agent-full
```

---

## 6. Variables de entorno

| Variable | Uso |
|----------|-----|
| `DBT_DUCKDB_PATH` | Ruta al DuckDB (ej. `artifacts/warehouse/crypto.duckdb`) |
| `LAKE_ROOT` | Raíz del data lake |
| `FRED_API_KEY` | FRED (SP500, oil, fed funds) |
| `GLASSNODE_API_KEY` | Opcional para on-chain |
| `DP_SYMBOLS` | Símbolos para backfill (top, all, o lista) |

---

## 7. Resumen de comandos Make

| Target | Descripción |
|--------|-------------|
| `make agent-flow-data` | Backfill externo + warehouse-load |
| `make agent-flow-train` | Optuna + model evaluation |
| `make agent-flow-full` | Flujo completo (data + train + eval) |
| `make ai-explorer-agent` | Explorer quick |
| `make ai-explorer-agent-full` | Explorer full |
| `make quant-model-eval` | Evaluación de modelos |
