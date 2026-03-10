# Fuentes de datos → Tablas → Herramientas

Mapa claro de dónde entra cada dato, en qué tabla termina y qué herramienta lo trae.

---

## Cómo tener los Dockers con la última versión

Hay dos niveles: **solo código** (cambiaste Python/scripts/config) y **imagen** (cambiaste dependencias o Dockerfile).

### Solo cambiaste código (data_platform, scripts, ai, trading_lib, apps)

Los compose montan el repo (o esas carpetas) como volumen, así que el contenedor ya ve tu código actual. Para que los procesos carguen los cambios:

- **Reiniciar el servicio** (suficiente en la mayoría de los casos):
  ```bash
  # Con docker-compose.yml (local)
  docker compose restart dagster
  docker compose restart binance-connector

  # Con docker-compose.server.yml (servidor)
  docker compose -f docker-compose.server.yml restart dagster
  docker compose -f docker-compose.server.yml restart api
  ```

Si Dagster no ve un asset nuevo o da “no software definition”, suele ser por import fallando: revisa logs y corrige el código; luego reinicia de nuevo.

### Cambiaste dependencias (requirements*.txt) o Dockerfile

Ahí hace falta **reconstruir la imagen** y volver a levantar los contenedores:

```bash
# Local (docker-compose.yml)
docker compose build --no-cache
docker compose up -d --force-recreate

# Servidor (docker-compose.server.yml)
docker compose -f docker-compose.server.yml build --no-cache
docker compose -f docker-compose.server.yml up -d --force-recreate
```

- `build --no-cache` evita usar capas viejas y asegura que pip instale lo que hay en `requirements.txt` (y en `requirements-dagster.txt` si aplica).
- `up -d --force-recreate` tira los contenedores actuales y crea otros con la imagen nueva.

### Resumen rápido

| Cambio | Qué hacer |
|--------|-----------|
| Código en `data_platform/`, `scripts/`, `ai/`, `trading_lib/`, `apps/` | `docker compose restart <servicio>` (o el que uses). |
| `requirements.txt`, `requirements-dagster.txt`, Dockerfile | `docker compose build --no-cache` y `docker compose up -d --force-recreate`. |
| Quieres asegurarte de que todo sea “última versión” | Rebuild + recreate como arriba. |

---

## Si ves "This asset doesn't have a software definition"

Significa que Dagster no pudo cargar el código (p. ej. por un error de importación). Solución:

1. **Reinicia Dagster** para que tome el código actualizado:
   ```bash
   docker restart binance_dagster_1
   ```
2. El código está montado como volumen; los cambios en `data_platform/`, `scripts/`, `ai/` se aplican al reiniciar.
3. Si sigue fallando, revisa los logs: `docker logs binance_dagster_1` y busca errores de Python.

---

## Cómo ver qué corre en Dagster

### Schedules (lo que corre solo)
1. Abre **http://localhost:3000**
2. Menú izquierdo → **"Schedules"**
3. Verás 7 schedules con nombres tipo `01_datos_cripto_cada_15min`, `04_pipeline_completo_cada_2h`, etc.
4. **Actívalos** con el toggle (verde = ON) para que corran automáticamente

### Jobs (lo que puedes lanzar a mano)
- Menú izquierdo → **"Jobs"** → verás `01_datos_cripto`, `04_pipeline_datos_completo`, etc.
- Cada job tiene el mismo nombre que su schedule asociado (sin el cron)

### Runs (qué se ejecutó)
- Menú izquierdo → **"Runs"**
- Cada run muestra: **Job name** (ej. `04_pipeline_datos_completo`), **Status**, **Tags** (`origen: schedule`, `que_hace: ...`)
- Si dice "Schedule" en el run, fue disparado por un schedule; si no, fue manual

### Assets (el grafo de datos)
- Menú izquierdo → **"Assets"** → grafo de dependencias
- Clic en un asset → pestaña "Metadata" → verás `herramienta`, `tablas`, `fuente`

---

## 1. Datos Cripto (Binance, Bybit, OKX, Aster, DEX)

| Asset Dagster | Frecuencia | Herramienta | Fuente | Tablas destino |
|---------------|------------|-------------|--------|----------------|
| **bronze_high** | Cada 15 min | `data_platform.pipeline.run_bronze` | Binance API (spot, futures, flow), Bybit, OKX, **Aster** (asterdex.com), Hyperliquid | `market_snapshot_raw`, `derivatives_*`, `cross_exchange_*`, `aster_dex_raw` |
| **bronze_medium** | Cada hora | `data_platform.pipeline.run_bronze` | CoinGecko, Fear & Greed, DexScreener | `global_market_raw`, `fear_greed_raw`, `dex_snapshot_raw` |
| **bronze_low** | Cada 6 h | `data_platform.pipeline.run_bronze` | FRED, FED calendar, on-chain | `macro_rates_raw`, `macro_assets_raw`, `fed_calendar_raw` |

**Aster** = [asterdex.com](https://www.asterdex.com) — DEX de perpetuals (API: `https://fapi.asterdex.com`, estilo Binance Futures). Los datos entran en `aster_dex_raw` y en `br_market_snapshot` como `aster_last_price` y en la capa DEX.

---

## 2. Datos Acciones + Noticias

| Asset Dagster | Frecuencia | Herramienta | Fuente | Tablas destino |
|---------------|------------|-------------|--------|----------------|
| **stock_market_ingest** | Con data_pipeline (cada 2h) | `yfinance` + `dlt` | Yahoo Finance | `stock_prices`, `market_news` (DuckDB directo) |

---

## 3. Análisis de sentimiento (IA)

| Asset Dagster | Frecuencia | Herramienta | Fuente | Tablas destino |
|---------------|------------|-------------|--------|----------------|
| **news_sentiment_analysis** | Con data_pipeline | `ai/agents/sentiment_agent.py` (OpenAI/LangChain) | Titulares de `market_news` | `news_sentiment` |
| **x_account_tracking** | Con data_pipeline | `ai/agents/x_tracker_agent.py` (Grok/xAI) | Cuentas X: @elonmusk, @VitalikButerin, etc. | `x_account_sentiment` |

---

## 4. Carga al warehouse

| Asset Dagster | Herramienta | Qué hace |
|---------------|-------------|----------|
| **warehouse_raw_load** | `bronze_to_duckdb.py` | Lee JSONL del data lake y carga en tablas raw de DuckDB |
| **warehouse_dbt_build** | `dbt build` | Transforma raw → bronze → silver → gold (`decision_features`, etc.) |

---

## 5. Modelos ML

| Asset Dagster | Herramienta | Qué hace |
|---------------|-------------|----------|
| **quant_model_train** | `scripts/auto_train_eval.py` | Walk-forward benchmark, entrena LightGBM/RF/LogReg, promueve champion |
| **quant_suite_cycle** | `scripts/run_suite_cycle.py` | Loop de optimización Optuna, explora estrategias |
| **quant_risk_evaluation** | `scripts/run_risk_engine.py` | Aplica position sizing y límites de riesgo a señales crudas → órdenes aprobadas |

---

## 6. Listado de modelos y salidas

### Modelos que entrena el pipeline

| Modelo | Descripción | Target (label) | Salida principal |
|--------|-------------|----------------|------------------|
| **LightGBM** | Clasificador por gradiente (árboles). | Dirección del retorno a 4h (`fwd_return_4h` > 0 → 1, si no 0). Con `--neutral`: `alpha_return_4h_btc`. | Probabilidad de subida; se usa para LONG/SHORT según umbral (ej. 0.55). |
| **Random Forest** | Ensemble de árboles. | Mismo que arriba. | Probabilidad de subida. |
| **Logistic Regression** | Regresión logística con StandardScaler. | Mismo que arriba. | Probabilidad de subida. |

Cada uno se prueba con **4 conjuntos de features**:

- **core_micro**: basis, funding, sentiment, grok_x.
- **core_plus_flow**: lo anterior + long_short_ratio, buy_sell_ratio.
- **full_quant**: + momentum, fear_greed, btc_dominance, fed_funds, session, liquidity_event.
- **cross_dex_quant**: full_quant + cross-exchange, DEX (bybit/okx/aster, dex_cex_basis, dex_alpha).

Se hace **walk-forward** (train 180 días, test 30, step 15), con fees 0.04% y límite de drawdown 15%. El mejor por *objective* (Sharpe-like) se registra en MLflow como **champion** (`quant_alpha_entry@champion`).

### Salidas esperadas (archivos / tablas)

| Salida | Ruta / origen | Contenido |
|--------|----------------|-----------|
| **auto_report.json** | `artifacts/quant_model/auto_report.json` | Mejor modelo, feature set, objective, net return %, win rate %, si es “profitable”, si se registró y si quedó como champion. |
| **MLflow (champion)** | `artifacts/quant_model/mlflow_v2.db` + alias `quant_alpha_entry@champion` | Modelo serializado (sklearn) para inferencia. |
| **suite_state.json** | `artifacts/quant_model/suite_state.json` | Champion actual de la suite (id, versión, métricas: net_return, sharpe). |
| **research_state.json** | `artifacts/quant_model/research_state.json` | Modo (exploit/explore), ciclos sin mejora, ronda de exploración. |
| **suite_report_*.json** | `artifacts/quant_model/suite_report_YYYYMMDD_HHMM.json` | Informes por ciclo de la suite (qué estrategias se probaron, promociones). |
| **fct_raw_signals / fct_approved_orders** | DuckDB (vía `run_risk_engine.py`) | Señales crudas y órdenes después del risk engine (position sizing, límites). |

---

## 7. Cómo dejar al agente corriendo y qué esperar de noche

### Qué está haciendo el “agente” hasta ahora

1. **Datos**: Bronze (Binance, Bybit, OKX, Aster, Hyperliquid, stocks, noticias) → warehouse → dbt → `decision_features`.
2. **Entrenamiento**: `quant_model_train` ejecuta `auto_train_eval.py` → benchmark walk-forward de muchos modelos/configs → el mejor se guarda como **champion** en MLflow.
3. **Suite**: `quant_suite_cycle` ejecuta `run_suite_cycle.py` → usa el champion para enriquecer `alpha_score`, luego Optuna + agentes (tuning, backtest, report, evolution) para explorar horizontes (1h, 4h), símbolos (top20, top50, all) y estrategias; escribe `suite_state`, `research_state` y reportes.
4. **Riesgo**: `quant_risk_evaluation` ejecuta `run_risk_engine.py` → lee las últimas `decision_features`, genera señales (usando `alpha_score` como proxy si no hay champion cargado), las pasa por el risk engine y escribe señales/órdenes aprobadas en DuckDB.

### Cómo dejarlo corriendo (Dagster)

- **Opción A – Solo schedules (recomendado para “dejarlo de noche”)**  
  En la UI de Dagster (http://localhost:3000) activa los schedules que quieras. Por la noche tendrás algo como:
  - Cada **15 min**: `01_datos_cripto` (bronze_high).
  - Cada **hora**: `02_datos_medio` (bronze_medium).
  - Cada **6 h**: `03_datos_macro` (bronze_low) y **`06_entrenar_modelos`** (quant_model_train → quant_suite_cycle → quant_risk_evaluation).
  - Cada **2 h**: `04_pipeline_completo` (datos + warehouse + dbt + sentimiento + X).
  - Cada **3 h** (en horas 1,4,7,10,13,16,19,22): `07_optimizar_suite` (solo quant_suite_cycle, sin re-entrenar).
  - **Domingos 23:00**: `05_pipeline_full_semanal` (todo el grafo, incluido ML).

- **Opción B – Un solo run “full”**  
  Lanzar a mano el job **`05_pipeline_full_con_ml`**: hace todo (datos → dbt → train → suite → risk) en un solo run. Útil para una pasada completa antes de irte.

### Qué puedes esperar si lo dejas corriendo de noche

- **Cada 6 h** (00:00, 06:00, 12:00, 18:00 si no cambias el cron): se re-entrena el modelo y se corre la suite. Al despertar deberías tener:
  - **auto_report.json** actualizado (mejor modelo y métricas del último benchmark).
  - **Champion** en MLflow posiblemente nuevo si hubo mejora.
  - **suite_state.json** y **research_state.json** con el estado actual de la investigación (champion de la suite, ciclos sin mejora, modo exploit/explore).
  - Posiblemente varios **suite_report_*.json** con los ciclos de la suite.
- **Cada 3 h** (solo suite): más iteraciones de optimización sin re-entrenar; más pruebas de estrategias/horizontes/símbolos.
- **Risk engine**: se ejecuta después de cada `quant_suite_cycle` dentro de `06_entrenar_modelos` o del pipeline full; las tablas `fct_raw_signals` y `fct_approved_orders` en DuckDB se rellenan con la última hora de `decision_features`.

Si un run falla (API, disco, memoria), Dagster marcará el run en rojo; los schedules siguientes se ejecutarán en su hora según el cron. Revisa **Runs** en la UI y los logs del asset que falló para depurar.

---

## Schedules (cuándo corre cada cosa)

| Schedule | Cron | Job |
|----------|------|-----|
| bronze_high_every_15_min | `*/15 * * * *` | bronze_high_job |
| bronze_medium_every_hour | `5 * * * *` | bronze_medium_job |
| bronze_low_every_6_hours | `0 */6 * * *` | bronze_low_job |
| data_pipeline_every_2h | `30 */2 * * *` | data_pipeline_job (datos frescos + dbt + sentimiento + X) |
| ml_train_suite_every_6h | `0 */6 * * *` | ml_train_suite_job (entrena modelos) |
| quant_suite_every_3h | `30 1,4,7,10,13,16,19,22 * * *` | quant_suite_job (solo optimización) |
| full_pipeline_weekly | `0 23 * * 0` (domingos 23:00) | full_pipeline_job (todo de punta a punta) |

---

## Flujo resumido

```
bronze_high, bronze_medium, bronze_low, stock_market_ingest
    ↓
warehouse_raw_load (carga JSONL → DuckDB)
    ↓
news_sentiment_analysis + x_account_tracking (en paralelo)
    ↓
warehouse_dbt_build (dbt → decision_features)
    ↓
quant_model_train → quant_suite_cycle
```
