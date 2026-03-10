# Distribución lógica: RAM y paralelismo

## 1. Qué consume más RAM (orden aproximado)

| Componente | RAM estimada | Motivo |
|-----------|--------------|--------|
| **quant_model_train** | 2–4 GB | LightGBM, Optuna, backtest, DataFrames grandes (lookback 1000 días) |
| **quant_suite_cycle** | 2–4 GB | Optuna (500 trials), múltiples ciclos, eval sobre decision_features |
| **warehouse_dbt_build** | 1–2 GB | dbt + DuckDB, muchas tablas en memoria |
| **warehouse_raw_load** | 0.5–1.5 GB | Carga JSONL → DuckDB, muchas tablas raw |
| **quant_risk_optimize** | 0.5–1 GB | Backtest con decision_features |
| **bronze_high/medium/low** | 0.3–0.8 GB c/u | dlt + APIs (Binance, CoinGecko, FRED…) |
| **stock_market_ingest** | 0.2–0.5 GB | yfinance + dlt |
| **news_sentiment_analysis** | 0.1–0.3 GB | OpenAI API (poco local) |
| **x_account_tracking** | 0.1–0.3 GB | Grok API (poco local) |
| **quant_risk_evaluation** | <0.2 GB | Risk engine, consultas DuckDB |
| **execute_pending_orders** | <0.1 GB | Solo llamadas Binance API |
| **ml_metadata_sync** | <0.1 GB | Lee SQLite MLflow/Optuna |

---

## 2. Dependencias entre assets (qué va antes de qué)

```
bronze_high ──┐
bronze_medium ─┼──► warehouse_raw_load ──► x_account_tracking ──► ml_metadata_sync ──► warehouse_dbt_build
bronze_low ───┤                                                                              │
stock_market_ingest ──► news_sentiment_analysis ──────────────────────────────────────────────┤
                                                                                              │
                                                                                              ▼
                                                                                    quant_model_train
                                                                                              │
                                                                                              ▼
                                                                                    quant_suite_cycle
                                                                                              │
                                                                                              ▼
                                                                                    quant_risk_evaluation
                                                                                              │
                                                                                              ▼
                                                                                    execute_pending_orders
```

---

## 3. Qué puede correr en paralelo y qué no

### Dentro de un mismo job (Dagster decide por dependencias)

| Nivel | Assets que pueden correr a la vez | ¿Pesados? |
|-------|-----------------------------------|-----------|
| 1 | bronze_high, bronze_medium, bronze_low, stock_market_ingest | Sí, 4 procesos |
| 2 | news_sentiment_analysis (solo tras stock_market_ingest) | No |
| 3 | warehouse_raw_load (tras bronzes + sentiment) | Sí |
| 4 | x_account_tracking | No |
| 5 | ml_metadata_sync | No |
| 6 | warehouse_dbt_build | Sí |
| 7 | quant_model_train | Muy pesado |
| 8 | quant_suite_cycle | Muy pesado |
| 9 | quant_risk_evaluation | No |
| 10 | execute_pending_orders | No |

### Entre jobs (runs distintos)

- Con `max_concurrent_runs: 1` solo hay **un run activo** a la vez.
- Si `trading_execution_job` está corriendo, `bronze_medium_job` espera en cola.
- Eso evita que varios jobs pesados se solapen.

---

## 4. Problema: paralelismo dentro del mismo run

En `data_pipeline_job` o `trading_execution_job`, Dagster puede lanzar en paralelo:

- bronze_high
- bronze_medium  
- bronze_low
- stock_market_ingest

Son 4 subprocesos a la vez. Si además `warehouse_raw_load` y `warehouse_dbt_build` se solapan con otros assets, el pico de RAM sube mucho.

---

## 5. Recomendaciones

### A. Mantener (ya aplicado)

- `max_concurrent_runs: 1` en Dagster → solo un job a la vez.
- API con 1 worker (uvicorn).

### B. Limitar paralelismo dentro de un run

En `definitions.py` se puede configurar el executor:

```python
from dagster import Definitions, multiprocess_executor

defs = Definitions(
    executor=multiprocess_executor.configured({"max_concurrent": 2}),
    # ...
)
```

Con `max_concurrent: 2` solo 2 assets corren a la vez (ej. bronze_high + bronze_medium), en vez de 4. Reduce pico de RAM.

### C. Separar jobs pesados en el tiempo

| Job | Cuándo | Motivo |
|-----|--------|--------|
| bronze_high/medium/low | Cada 15 min / 1 h / 6 h | Ligeros, pueden solaparse con otros |
| data_pipeline (bronze → dbt) | Cada 15 min o 1 h | Evitar solaparlo con ML |
| ml_train_suite | Cada 6 h o semanal | Muy pesado, mejor en horarios de baja carga |
| trading_execution | Cada 15 min | Datos + risk + ejecución, no incluye entrenar |

### D. Schedules que conviene tener STOPPED si hay poca RAM

- `04_pipeline_completo_cada_15m` (data_pipeline_job) – pesado.
- `05_pipeline_full_semanal` (full_pipeline_job) – muy pesado.
- `06_entrenar_modelos_cada_6h` (ml_train_suite_job) – muy pesado.

Dejar RUNNING solo:

- `02_datos_medio_cada_hora` (bronze_medium)
- `03_datos_macro_cada_6h` (bronze_low)
- `08_operacion_testnet_cada_15m` (trading_execution) – si quieres operar en vivo.

---

## 6. Resumen visual

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                    DOCKER CONTAINERS                      │
                    ├─────────────────────────────────────────────────────────┤
                    │  binance-connector   │  dagster-postgres  │    dagster    │
                    │  (API, 1 worker)    │  (Postgres)        │  daemon+web   │
                    │  ~200 MB            │  ~100 MB           │  ~300 MB base  │
                    └─────────────────────────────────────────────────────────┘
                                                              │
                    ┌─────────────────────────────────────────┴─────────────────┐
                    │              DAGSTER RUN (1 a la vez)                     │
                    │  Pico RAM = suma de assets en paralelo dentro del run      │
                    │  Peor caso: bronze×4 + warehouse_load + dbt ≈ 3–4 GB      │
                    │  Peor caso ML: train + suite ≈ 4–8 GB                      │
                    └───────────────────────────────────────────────────────────┘
```

**Total estimado en peor caso:** ~6–10 GB (API + Postgres + Dagster + run activo con ML).
