# Flujo: tus datos → tablas de features → entrenar → backtest

Guía corta para usar **tus datos**, construir las **tablas de features**, **entrenar** y comprobar si el **backtest** es fiable comparándolo con la **simulación en paper** (la misma que ya has usado).

---

## 1. En qué orden va todo

```
TUS DATOS (raw)  →  WAREHOUSE (DuckDB)  →  TABLAS DE FEATURES (dbt)  →  ENTRENAR  →  BACKTEST
                                                                              ↓
                                                    Validar: comparar con SIMULACIÓN PAPER
```

| Paso | Qué es | Comando / Dónde |
|------|--------|------------------|
| **1. Datos** | Precios, volumen, funding, etc. en el warehouse | `make warehouse-load` (carga bronze → DuckDB) |
| **2. Tablas de features** | Tablas gold con señales y retornos futuros (decision_features) | `make dbt-run` (o dentro de warehouse-load) |
| **3. Entrenar** | Entrenar el modelo con esas features | `make ai-train` o `make quant-optuna` |
| **4. Backtest** | Simular operar con el modelo/estrategia sobre datos históricos | `make ai-backtest` |
| **5. Validar** | Comprobar si el backtest es realista | Comparar backtest con la simulación en paper (ver abajo) |

---

## 2. Tus datos y las tablas de features

- **Datos:** Se cargan a DuckDB con `make warehouse-load` (o el flujo que uses para backfill/vision). Todo queda en `artifacts/warehouse/crypto.duckdb`.
- **Tablas de features:** Las construye **dbt** (modelos gold). La importante para entrenar y backtest es **`decision_features`**: una fila por `(event_time, symbol)` con cosas como:
  - `alpha_score`, `fwd_return_1h`, `fwd_return_4h`, `fwd_return_24h`
  - `futures_last_price`, `quote_volume_24h`, `fed_window`, etc.

Sin `decision_features` no hay entrenamiento ni backtest. Si falta, hay que tener datos en el warehouse y ejecutar dbt (p. ej. `make warehouse-load` que ya corre dbt).

---

## 3. Entrenar

- **Desde DuckDB:**  
  `make ai-train` usa `decision_features` en DuckDB y entrena/calibra el modelo. Los artefactos suelen quedar en `artifacts/quant_model/` (o donde tengas configurado).
- **Optuna (walk-forward):**  
  `make quant-optuna` entrena con ventanas en el tiempo para no hacer overfitting.

---

## 4. Backtest (¿funciona?)

- **Qué hace:** Lee `decision_features` de DuckDB, aplica la lógica de asignación (umbrales, exposición, etc.) en cada `event_time` y simula retornos con fees (y opcionalmente slippage/liquidez).
- **Comando:**  
  `make ai-backtest`  
  (o `venv\Scripts\python examples/ai_backtest.py` con `DBT_DUCKDB_PATH` apuntando a tu `crypto.duckdb`).

Ahí te sale un **retorno neto %** (y trades, fees, etc.). Ese número es el que quieres validar contra la simulación en paper.

---

## 5. Cómo validar: comparar backtest con la simulación en paper

La “herramienta de simulaciones” que ya usaste es el **modo paper** de ejecución de órdenes:

- **Generar órdenes OOS:** Con el mismo modelo y el mismo período de datos, se generan las órdenes que “habría hecho” la estrategia (archivo `oos_orders.jsonl`). Eso lo hace por ejemplo `quant_inference_oos.py` (hoy espera datos en JSONL; si solo tienes DuckDB, hay que exportar decision_features a JSONL o adaptar el script para leer de DuckDB).
- **Simulación en paper:** Se “ejecutan” esas órdenes **sin dinero real** y se guarda cada operación en `execution_log.jsonl` (símbolo, precio usado, notional, etc.). Comando típico:
  ```bash
  python examples/quant_execute_orders.py --mode paper --paper-fill-source file
  ```
  Con `--paper-fill-source file` se usa el precio del dato (mismo que en el backtest), así la comparación es justa.

**Comparación:**

- **Backtest:** te da un **retorno neto %** sobre el período (ej. “+2.3%”).
- **Paper:** con el mismo período y las mismas señales, el `execution_log.jsonl` tiene todas las entradas/salidas. Se puede calcular un **retorno realizado %** (ganancia/pérdida por trades cerrados sobre el capital usado).

Si **backtest** y **paper** dan retornos parecidos (mismo período, mismas señales), el backtest está bien planteado. Si el paper da mucho menos, puede ser por límites de riesgo que rechazan órdenes, por slippage real si usas precio vivo, o por diferencias en la lógica (redondeos, filtros, etc.).

En el repo hay un script que lee `execution_log.jsonl` y calcula ese retorno realizado para que lo compares a mano con la salida de `ai_backtest`: ver **Comparar backtest vs paper** más abajo.

---

## 6. Comandos rápidos (resumen)

```bash
# 1. Cargar datos y construir features (DuckDB + dbt)
make warehouse-load

# 2. Entrenar (usa decision_features de DuckDB)
make ai-train

# 3. Backtest (usa decision_features de DuckDB)
make ai-backtest

# 4. (Opcional) Generar órdenes OOS y simular en paper
#    - Requiere datos en JSONL para quant_inference_oos, o adaptar a DuckDB
python examples/quant_inference_oos.py --dataset ... --model-artifact artifacts/quant_model/...
python examples/quant_execute_orders.py --mode paper --paper-fill-source file

# 5. Simulación en paper (órdenes sin dinero real)
make quant-exec-paper
# o: python examples/quant_execute_orders.py --mode paper --paper-fill-source file

# 6. Revisar ejecución y comparar con backtest
python examples/quant_execution_review.py
python examples/compare_backtest_vs_paper.py --execution-log artifacts/quant_model/execution_log.jsonl
```

---

## 7. Comparar backtest vs paper (script)

El script `examples/compare_backtest_vs_paper.py`:

- Lee `execution_log.jsonl` (salida de `quant_execute_orders.py --mode paper`).
- Empareja OPEN/CLOSE por símbolo y calcula el **retorno realizado %** en ese período.
- Puedes comparar ese % con el **retorno neto %** que te da `make ai-backtest` para el mismo período.
- Opciones: `--scenarios` (tabla de trades), `--out-scenarios FILE`, `--backtest-scenarios FILE` (comparar con `examples/backtest_scenarios.py`).

Así compruebas si el backtest se parece a lo que “habría pasado” en la simulación con operaciones concretas (las del log).

---

## 8. Comparar por escenarios (entradas y salidas)

Para validar que las entradas/salidas coinciden entre backtest y paper:

1. **Escenarios paper:** `python examples/compare_backtest_vs_paper.py --scenarios --out-scenarios artifacts/quant_model/paper_scenarios.jsonl`
2. **Escenarios backtest:** `python examples/backtest_scenarios.py` (genera `artifacts/quant_model/backtest_scenarios.jsonl`)
3. **Lado a lado:** `python examples/compare_backtest_vs_paper.py --scenarios --backtest-scenarios artifacts/quant_model/backtest_scenarios.jsonl`

Cuando los escenarios cuadran (mismos símbolos, fechas, retornos del mismo orden), puedes correr la suite completa y dejar los agentes en el tiempo.

---

## 9. Suite completa y agentes en el tiempo

- **Suite completa:** `make agent-flow-full` (datos + train + eval).
- **Programar:** Diario `make agent-flow-data`; semanal `make agent-flow-train`; explorador `make ai-explorer-agent` o `ai-explorer-agent-full`.
- **Ver resultados:** `make ai-backtest`, `make ai-registry-list`; `artifacts/quant_model/` (execution_log, reports); MLflow. Ver [AGENTS_AUTOMATION.md](AGENTS_AUTOMATION.md) sección Cron/scheduling.

---

## 10. Testnet (Binance)

Para probar con órdenes reales pero sin dinero real, se usa **Binance Testnet** (`BINANCE_TESTNET=true`). Eso ya lo tenías; el flujo de “datos → features → entrenar → backtest” es el mismo. La diferencia es que en testnet las órdenes se envían a Binance (simulado), no solo se escriben en un log como en el modo paper local.
