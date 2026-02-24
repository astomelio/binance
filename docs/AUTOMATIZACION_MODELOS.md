# Automatizar: sacar modelos y probarlos por <10 €/semana

Pipeline 100% automatizado para entrenar, registrar y evaluar modelos **en local**, sin APIs de pago. Si no usas cloud ni servicios externos en el bucle, el coste es **0 €**. Los 10 €/semana son margen por si usas algo opcional (Cursor, un VPS, etc.); el propio pipeline no gasta.

**Para que el training use datos al día:** primero tienen que correr los **pipelines de datos** (bronze + carga DuckDB + dbt). Un solo cron puede hacer ambas cosas: actualizar datos y luego entrenar.

---

## 1. Todo en uno: datos + training (recomendado para cron)

Para que sea automático **con datos en tiempo (casi) real**:

1. **Pipelines datos:** traer datos recientes de APIs (Binance, Bybit, OKX, FearGreed, etc.) → bronze → cargar a DuckDB → dbt (actualiza `decision_features`).
2. **Training:** entrenar modelo, registrar en MLflow, backtest y escribir reporte.

Un solo comando hace los dos pasos en orden:

```bash
# Datos (bronze + warehouse + dbt) y luego training
python scripts/auto_data_then_train.py --set-champion
```

O con Make (desde la raíz del repo):

```bash
make auto-data-then-train
```

Opciones:

- `--skip-data`: solo training (si ya actualizaste datos antes).
- `--data-only`: solo pipelines datos; no entrena.
- `--set-champion`: marcar el modelo nuevo como champion.

---

## 2. Prender todo: datos (temporales + gold) + modelo + suite

Un solo comando que usa **todos los datos de la base de datos** (tablas cargadas desde bronze + gold `decision_features`):

1. **Pipeline datos:** bronze → warehouse → dbt (actualiza DuckDB con temporales y gold).
2. **Entrenar modelo:** LightGBM con hasta 365 días de `decision_features` (configurable) y marcar champion.
3. **Suite de agentes:** un ciclo con `--use-champion` y `--optimize` sobre los datos (p. ej. últimos 180 días para la suite, para evitar OOM).

```bash
python scripts/run_prender_full.py
# o
make prender-full
```

Opciones útiles:

- `--skip-data`: no ejecutar datos; solo entrenar + suite (si la DB ya está actualizada).
- `--data-only`: solo pipeline datos (bronze + dbt).
- `--train-days 365`: días de datos para entrenar (default 365).
- `--suite-days 180`: días para la suite (default 180; cargar todo en RAM puede dar MemoryError).
- `--no-champion`: no marcar el modelo como champion.
- `--no-use-champion`: suite sin rellenar alpha_score con el modelo (solo estrategias que no dependen de alpha).
- `--no-optimize`: suite más rápida, sin búsqueda amplia de parámetros.
- `--dry`: suite sin guardar estado ni informe.

Los datos "temporales" y "gold" son: lo que el pipeline deja en DuckDB (raw desde bronze, tablas construidas por dbt, y la gold `decision_features`). El script usa esa misma base para entrenar y para la suite.

---

## 3. Solo training (si los datos ya están actualizados)

```bash
# Desde la raíz del repo (Windows PowerShell)
$env:DBT_DUCKDB_PATH = "C:\ruta\al\repo\artifacts\warehouse\crypto.duckdb"
$env:PYTHONPATH = "C:\ruta\al\repo"
.\venv\Scripts\python.exe scripts\auto_train_eval.py --set-champion
```

Qué hace:

1. Carga `decision_features` de DuckDB (últimos 90 días por defecto).
2. Entrena un LightGBM con parámetros fijos (rápido, sin Optuna).
3. Registra el modelo en MLflow (sqlite local) y opcionalmente lo marca como **champion** (`--set-champion`).
4. Ejecuta backtest en los últimos 14 días y escribe `artifacts/quant_model/auto_report.json`.

Todo en tu máquina: **0 € en APIs**.

---

## 4. Programar para que corra solo (sin abrir Cursor)

Para que **los datos se actualicen y luego entrene** con un solo cron/tarea:

### Windows (Programador de tareas)

1. Abre **Programador de tareas**.
2. Crear tarea básica → nombre "Quant auto data + train" → desencadenador **Semanal** (ej. domingo 23:00) o **Diario** si quieres datos cada día.
3. Acción: **Iniciar un programa**.
   - Programa: `C:\ruta\al\repo\venv\Scripts\python.exe`
   - Argumentos: `scripts\auto_data_then_train.py --set-champion`
   - Iniciar en: `C:\ruta\al\repo`
4. En "Configuración" de la tarea, asegúrate de que se ejecute aunque no haya sesión.
5. Opcional: en "Condiciones", desmarca "Iniciar solo con energía de red" si quieres que corra también con batería.

Variables de entorno para esa tarea (opcional, si no están en el sistema):

- `DBT_DUCKDB_PATH` = `C:\ruta\al\repo\artifacts\warehouse\crypto.duckdb`
- `PYTHONPATH` = `C:\ruta\al\repo`

(Puedes ponerlas en un `.bat` que haga `set DBT_DUCKDB_PATH=...` y luego `python scripts\auto_data_then_train.py --set-champion` y programar ese `.bat`.)

### Linux / Mac (cron)

```bash
# Datos + training cada domingo a las 23:00
0 23 * * 0 cd /ruta/al/repo && DBT_DUCKDB_PATH=/ruta/al/repo/artifacts/warehouse/crypto.duckdb PYTHONPATH=/ruta/al/repo ./venv/bin/python scripts/auto_data_then_train.py --set-champion >> artifacts/quant_model/auto_data_then_train.log 2>&1
```

Si quieres **solo refresco de datos cada día** y **training solo una vez a la semana**, puedes usar dos crons: uno diario con `--data-only` y otro semanal con el comando completo.

---

## 5. Opciones del script (auto_train_eval.py)

| Argumento | Default | Descripción |
|-----------|--------|-------------|
| `--db` | DuckDB por env | Ruta a `crypto.duckdb`. |
| `--horizon` | 1h | Horizonte (1h, 4h, 24h). |
| `--lookback-days` | 90 | Días de datos para entrenar. |
| `--test-days` | 14 | Días para el backtest final. |
| `--trials` | 0 | 0 = un solo modelo fijo (rápido). Futuro: 5–20 = Optuna ligero. |
| `--register-name` | quant_alpha_entry_lgbm | Nombre del modelo en MLflow. |
| `--set-champion` | false | Si se pone, marca esta versión como champion. |
| `--mlflow-uri` | sqlite en repo | URI de MLflow. |
| `--out-report` | artifacts/quant_model/auto_report.json | Dónde se escribe el reporte. |

---

## 6. Cómo mantenerte por debajo de 10 €/semana

- **Pipeline de modelos (este script):** todo local (DuckDB, LightGBM, MLflow sqlite, backtest). **Coste = 0 €**.
- **Cursor / IDE / APIs:** lo que gastes es independiente; puedes limitar uso para no pasarte de 10 €/semana.
- **Opcional cloud (ej. una VM para que corra el cron):** si usas un VPS barato, cuenta ese coste aparte; el script no llama a ningún servicio de pago.

Regla práctica: no incluyas en el bucle automático llamadas a APIs de pago (OpenAI, etc.). El entrenamiento y la evaluación que hace `auto_train_eval.py` son 100% locales.

---

## 7. Qué revisar después de cada ejecución

- **Reporte:** `artifacts/quant_model/auto_report.json`  
  - `backtest.net_return_percent`, `backtest.trades_count`  
  - `registered_version`, `champion`
- **MLflow (opcional):** `mlflow ui --backend-store-uri sqlite:///artifacts/quant_model/mlflow.db` y revisar el run y el modelo registrado.

---

## 8. Resumen

| Objetivo | Cómo |
|----------|------|
| Datos al día + sacar modelos sin tocar nada | Programar `scripts/auto_data_then_train.py --set-champion` (Task Scheduler o cron). |
| Solo datos (pipelines en tiempo real) | `scripts/auto_data_then_train.py --data-only` (ej. cron diario). |
| Solo training (datos ya actualizados) | `scripts/auto_train_eval.py --set-champion` o `--skip-data` en auto_data_then_train. |
| Que los pruebe | El training hace backtest y escribe `auto_report.json`. |
| Gastar &lt;10 €/semana | Pipeline local = 0 €; controla solo lo que gastes en Cursor/cloud/APIs. |

**Alternativa con contenedor:** Si quieres dejar **un contenedor corriendo en tu PC como servidor** con los DAGs y procesos ya integrados (datos por schedule + training semanal), usa Docker Compose + Dagster. Ver **`docs/SERVIDOR_LOCAL_CONTENEDOR.md`**.
