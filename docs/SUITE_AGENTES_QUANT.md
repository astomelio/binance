# Suite de agentes quant: decisiones, parámetros, informes y evolución

Objetivo: **una suite de agentes** que (1) cambie parámetros, (2) tome decisiones de quants con los algoritmos, (3) genere informes y (4) **evolucione el algoritmo en el tiempo**, no solo “entrenar cada semana”.

---

## 1. Roles de la suite

| Agente | Responsabilidad | Input | Output |
|--------|------------------|--------|--------|
| **Tuning** | Proponer o explorar hiperparámetros y configuraciones (Optuna, grid, estrategias). | Datos, estado actual (champion). | Candidatos: modelos o configs (params + métricas de validación). |
| **Decision** | Aplicar el algoritmo (champion o candidatos) a datos recientes; producir vectores de asignación y/o backtest. | Datos, modelo/config. | Asignaciones por barra, resultado de backtest, comparación con paper si aplica. |
| **Report** | Construir informes estructurados (métricas, backtest vs paper, recomendaciones). | Resultados de Decision + Tuning. | Informe (JSON/Markdown) para humanos o para el agente de evolución. |
| **Evolution** | Decidir si promover un candidato a champion, cambiar config en vivo o disparar retrain. | Informes, métricas, umbrales. | Nuevo estado: champion version, config, “qué algoritmo usamos desde ya”. |

El **algoritmo evoluciona** porque el agente Evolution actualiza el estado (champion/config) según los informes; el siguiente ciclo usa ese estado (Decision usa el nuevo champion, Tuning puede proponer challengers).

---

## 2. Flujo de un ciclo

```
[Datos actualizados]
        │
        ▼
┌───────────────┐     candidatos      ┌───────────────┐
│ TuningAgent   │ ──────────────────► │ DecisionAgent │
│ (params,      │                     │ (backtest,    │
│  estrategias) │                     │  vs paper)    │
└───────────────┘                     └───────┬───────┘
        │                                     │
        │ report_input                        │ resultados
        ▼                                     ▼
┌───────────────┐     informe        ┌───────────────┐
│ ReportAgent   │ ◄──────────────────│                │
│ (métricas,    │                    │                │
│  recomend.)   │                    │                │
└───────┬───────┘                    │                │
        │                            │                │
        │ informe                    │                │
        ▼                            │                │
┌───────────────┐                    │                │
│ EvolutionAgent│ ──────────────────►│ actualiza      │
│ (promover     │   nuevo champion   │ champion /    │
│  champion?)   │   o config         │ config        │
└───────────────┘                    └────────────────┘
```

- **Tuning** y **Decision** pueden ser el mismo proceso (ej. ExplorationAgent + backtest) o separados (Optuna → modelo; luego Decision solo evalúa).
- **Report** centraliza todo lo que “sabemos” en un formato útil.
- **Evolution** es el que **cambia el algoritmo en el tiempo**: decide si el challenger pasa a ser champion o si se ajustan parámetros en producción.

---

## 3. Contratos (interfaces)

Cada agente expone una interfaz mínima para que la suite pueda orquestarlos:

- **TuningAgent.run(state, data) → candidates**
  - `state`: estado actual (champion_id, config, última fecha de evolución).
  - `data`: filas o rango de datos.
  - `candidates`: lista de { model_or_config, metrics }.

- **DecisionAgent.run(state, data, candidates?) → decisions_result**
  - Evalúa el champion (y opcionalmente candidatos) sobre `data`.
  - Devuelve backtest, comparación con paper si hay, vectores de asignación por barra (resumen o rutas).

- **ReportAgent.run(tuning_result, decision_result, state) → report**
  - `report`: dict o documento (métricas, backtest vs paper, recomendación: promover X / no promover).

- **EvolutionAgent.run(report, state) → new_state**
  - Lee umbrales (ej. “promover si net_return > champion y trades >= N”).
  - Devuelve el nuevo estado (champion actualizado, config, o “sin cambios”).

La **suite** ejecuta en bucle (o por trigger): Tuning → Decision → Report → Evolution y persiste `state` entre ciclos.

---

## 4. Dónde encaja lo que ya tienes

| Pieza actual | Rol en la suite |
|--------------|------------------|
| **ExplorationAgent** (ai.explorer) | Puede ser la base del **Tuning**: explora estrategias y params, devuelve candidatos (mejores configs por estrategia). |
| **Optuna / auto_train_eval** | Otro **Tuning**: entrena modelos, registra en MLflow; los candidatos son versiones de modelo. |
| **run_backtest_from_orders / backtest** | Parte del **Decision**: evalúa un config/modelo sobre datos y produce backtest (y opcionalmente comparación con paper). |
| **compare_backtest_vs_paper**, **CONCLUSIONES** | Input para **Report**: ya tienes comparación backtest vs paper; el ReportAgent puede estructurarla y añadir recomendación. |
| **MLflow champion alias** | Estado que **Evolution** puede actualizar: “promover versión X a champion”. |

Nada se tira; se **conecta** detrás de los contratos de la suite.

---

## 5. Evolución del algoritmo en el tiempo

- **Estado persistido:** por ejemplo `artifacts/quant_model/suite_state.json`: `{ "champion_version": "3", "champion_config": {...}, "last_evolution_at": "..." }`.
- **Evolution** lee el informe (backtest, paper, Sharpe, trades) y sus reglas (ej. “promover si net_return del candidato > champion en ventana reciente y no empeora drawdown”).
- Si decide promover: escribe nuevo `champion_version` (o alias en MLflow) y/o actualiza `champion_config`. El siguiente **Decision** ya usará ese champion.
- Opcional: **Tuning** en cada ciclo puede proponer solo “challengers” (variaciones del champion actual) para que la evolución sea incremental.

Así el algoritmo **cambia en el tiempo** sin que tengas que decidir a mano: la suite propone candidatos, los evalúa, genera informes y el agente de evolución actualiza qué algoritmo está “en producción” (champion).

---

## 6. Implementación

- **Módulo `ai/suite`**: contratos en `types.py`; implementaciones en `agents.py` (ExplorationTuningAgent, BacktestDecisionAgent, DefaultReportAgent, DefaultEvolutionAgent); orquestador en `runner.py` (load_state, save_state, run_cycle, QuantAgentSuite).
- **Estado:** `artifacts/quant_model/suite_state.json` (champion_id, champion_config, version).
- **Script:** `python scripts/run_suite_cycle.py [--horizon 4h] [--no-persist]` — carga datos de DuckDB, ejecuta un ciclo y escribe informe en `artifacts/quant_model/suite_report_*.json`.

### Optimización: encontrar modelos probando estrategias y datos

En modo **optimización** la suite no solo ejecuta estrategias con params por defecto, sino que **busca** mejores combinaciones sobre **todo tu dataset** (o un lookback grande):

- **Estrategias:** mean reversion, alpha_score, heuristic (todas las registradas).
- **Parámetros:** grid muestreado sobre `param_ranges` de cada estrategia (umbrales, tamaño de asignación, vol_metric, etc.).
- **Horizontes:** 1h y 4h (configurable).
- **Tipos de activos:** top20, top50 y all (por volumen USD).
- **Horas de entrada/sesión:** opcional `--session 8 16` para solo operar barras entre 08:00 y 16:59 UTC.

Comando para usar **todo el dataset** y explorar cientos de combinaciones:

```bash
python scripts/run_suite_cycle.py --optimize --lookback-days 0
```

Con sesión (solo ciertas horas) y tope de pruebas:

```bash
python scripts/run_suite_cycle.py --optimize --lookback-days 180 --session 8 16 --max-trials 500
```

El agente **OptimizerTuningAgent** llama a `run_optimization()` en `ai/explorer/optimizer.py`, que hace grid/sample sobre estrategias × params × horizontes × symbol_sets y opcionalmente filtra por sesión (`ai/explorer/data_filters.filter_rows_by_session`). Los mejores candidatos pasan al Report y Evolution; el champion puede ser, por ejemplo, mean_reversion con oversold=-2, overbought=2, horizon=4h, symbol_set=top50.

### Cómo correr (prender todo)

1. **Entorno:** `pip install -r requirements.txt` (y opcionalmente `venv` activado).
2. **Datos:** Si ya tienes DuckDB con `decision_features` poblado (p. ej. tras `make warehouse-load` o `make auto-data-then-train`), puedes lanzar la suite directamente.
3. **Un ciclo de la suite:**
   - **Con Make:** `make suite-cycle` (o `make suite-cycle-dry` para no guardar estado/informe).
   - **Prender todo (recomendado):** `python scripts/run_suite_prender_todo.py` — comprueba imports y que haya suficientes filas; si faltan datos, te dice qué comando ejecutar. Con `--ensure-data` intenta generar datos antes (bronze + warehouse + dbt) y luego corre la suite.
   - **Directo:** `python scripts/run_suite_cycle.py`.

Salida típica: recomendación (promote / no_promote), champion actual, backtest en consola; estado e informe en `artifacts/quant_model/`.

## 7. El agente que sigue corriendo (Docker + Dagster)

La suite **no se queda corriendo sola** si solo ejecutas el script a mano: el script hace un ciclo y termina. Para que **siga ejecutándose automáticamente** (en Docker o en el servidor):

- **Dagster en Docker:** el contenedor con Dagster tiene un **schedule** que dispara la suite sin que tú hagas nada.
  - **Schedule:** `quant_suite_daily` — cada día a las **04:00** ejecuta el job **quant_suite_job** (un ciclo de la suite).
  - **Job:** `quant_suite_job` → materializa el asset `quant_suite_cycle` (que llama a `scripts/run_suite_cycle.py`).
- Cómo levantar el contenedor (Dagster + API + MLflow, etc.): ver **docs/SERVIDOR_LOCAL_CONTENEDOR.md**. Comando:
  ```bash
  docker compose -f docker-compose.server.yml --profile full up -d
  ```
- En la UI de Dagster (http://localhost:3000) puedes activar/desactivar el schedule **quant_suite_daily** y lanzar **quant_suite_job** a mano cuando quieras.

Así, el “agente” que hace que la suite siga corriendo es **el daemon de Dagster dentro del contenedor**, que respeta los schedules (p. ej. todos los días a las 4:00).

### Bucle de investigación: correr hasta algo bueno o explorar

Si quieres que la suite **siga corriendo** hasta que (1) encuentre algo bueno (promote) o (2) detecte que **no está avanzando** y entonces **pruebe nuevas maneras** de mejorar (más trials, otros horizontes, sesiones), usa el bucle de investigación:

- **Script:** `python scripts/run_suite_research.py [--optimize]`
- Si pasan **N ciclos sin mejora** (`--cycles-before-explore`, p. ej. 3) se activa **exploración**: tuning más agresivo (más trials, 24h, sesión 8–16 UTC). Estado en `artifacts/quant_model/research_state.json`.

```bash
python scripts/run_suite_research.py --optimize --max-cycles 20 --cycles-before-explore 3
```

## 8. Próximos pasos opcionales

- **Tuning con MLflow:** agente de tuning que use `auto_train_eval` y proponga candidatos como versiones de modelo; Evolution actualice el alias champion en MLflow.
- **Backtest vs paper** dentro de DecisionAgent y en el informe.
