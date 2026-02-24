# Dónde está (y qué falta) el agente que trabaja solo y encuentra modelos

Resumen: **hoy no hay un solo “agente” que trabaje solo y encuentre modelos**. Hay piezas repartidas; ninguna hace el bucle completo sin que tú lo dispares.

---

## 1. Dónde está “encontrar modelos” (buscar / optimizar)

### Modelo ML (LightGBM) – quién lo entrena o busca

| Qué | Dónde en el código | Qué hace |
|-----|--------------------|----------|
| Entrenar **un** modelo fijo | `scripts/auto_train_eval.py` | Carga datos, entrena LightGBM (params fijos), registra en MLflow, opcionalmente `--set-champion`. **No busca** hiperparámetros. |
| **Buscar** mejores hiperparámetros (Optuna) | `examples/quant_optuna_tuning.py` | Hace muchos trials, elige el mejor y puede marcar `--set-champion-alias`. Aquí sí se **encuentra** un modelo (el mejor del grid de trials). |
| Champion/challenger (evaluar modelos) | `examples/quant_champion_challenger.py` | Compara modelos por horizonte, calibración, etc.; **no entrena ni busca** solo, es evaluación. |

Ninguno de estos se ejecuta solo en bucle: los tienes que lanzar tú (o un cron/Dagster).

### “Encontrar” mejor estrategia + params (suite)

| Qué | Dónde en el código | Qué hace |
|-----|--------------------|----------|
| Buscar mejores **estrategias × params** (mean reversion, alpha_score, heuristic) | `ai/explorer/optimizer.py` → `run_optimization()` | Prueba muchas combinaciones (estrategia, params, horizonte, activos). **Aquí se “encuentran” configs de estrategia**, no modelos ML. |
| Quien usa ese optimizer en la suite | `ai/suite/agents.py` → `OptimizerTuningAgent.run()` | Llama a `run_optimization()`, devuelve candidatos (mejores configs). |
| Quien “promueve” un candidato a champion (estrategia) | `ai/suite/agents.py` → `DefaultEvolutionAgent.run()` | Si el report dice “promote”, actualiza **champion_id + champion_config** (estrategia + params). **No toca el modelo ML** en MLflow. |
| Un ciclo completo: tuning → decisión → informe → evolución | `ai/suite/runner.py` → `run_cycle()` | Orquesta: TuningAgent → DecisionAgent → ReportAgent → EvolutionAgent. Un solo ciclo; no hay bucle infinito. |

Resumen: **“encontrar modelos” (ML)** está en Optuna (`quant_optuna_tuning.py`). **“Encontrar” mejor estrategia/params** está en `ai/explorer/optimizer.py` + suite (`OptimizerTuningAgent` + `DefaultEvolutionAgent`). No hay un único sitio que “encuentre modelos” en el sentido de “buscar y dejar el mejor modelo listo”.

---

## 2. Dónde está “trabajar solo” (sin que tú lo ejecutes)

| Qué | Dónde | Cómo “trabaja solo” |
|-----|--------|----------------------|
| Schedule que dispara datos + entrenamiento + suite | `data_platform/orchestration/dagster/schedules.py` | `quant_suite_daily` (cada día 04:00) y `crypto_lake_full_plus_train_weekly` (domingo 23:00). **Solo si Dagster está levantado** (p. ej. `docker compose -f docker-compose.server.yml --profile full up -d`). |
| Asset que ejecuta la suite | `data_platform/orchestration/dagster/assets.py` → `quant_suite_cycle` (línea ~177) | Llama a `run_suite_cycle.py` **sin** `--optimize` ni `--use-champion` por defecto (solo `--horizon 4h --lookback-days 90`). Es decir, la suite en Dagster no usa el optimizer ni el modelo. |
| Asset que entrena el modelo | `data_platform/orchestration/dagster/assets.py` → `quant_model_train` (línea ~138) | Llama a `auto_train_eval.py --set-champion`. Entrena **un** modelo, no busca muchos. |

Conclusión: **“trabajar solo”** existe solo vía **Dagster**: si el daemon está corriendo, los schedules disparan jobs. Pero (1) el job de la suite no usa `--optimize` ni `--use-champion`, y (2) no hay un bucle que “entrene → busque estrategias → promueva modelo” todo junto.

---

## 3. Qué falta para un agente que “trabaje solo y encuentre modelos”

- **Un solo proceso o job** que, en bucle o cada X tiempo:
  1. Actualice datos (o use los ya cargados).
  2. **Encuentre modelos**: por ejemplo ejecute Optuna (o `auto_train_eval` con más variación) y marque champion.
  3. **Encuentre mejor estrategia/params**: ejecute la suite con `--optimize` y `--use-champion`, y persista el champion de la suite (y opcionalmente actualice algo en MLflow).
  4. No requiera que tú ejecutes un script a mano.

- **Conectar la suite en Dagster** con “encontrar modelos”: que el asset `quant_suite_cycle` (o un job nuevo) llame a `run_suite_cycle.py` con `--optimize` y `--use-champion`, y que el training (Optuna o auto_train_eval) esté en el mismo grafo (mismo job o job que se ejecute antes).

- Opcional: **un script “agent”** que en un bucle (o con schedule interno) haga: datos → train/optuna → suite con champion → sleep X horas/días, y que se pueda dejar corriendo en el PC o en el contenedor.

---

## 4. Resumen en una tabla

| Pregunta | Dónde está | ¿Trabaja solo? |
|----------|------------|-----------------|
| ¿Quién entrena el modelo ML? | `scripts/auto_train_eval.py` | No; lo ejecutas tú o Dagster. |
| ¿Quién busca mejores hiperparams del modelo? | `examples/quant_optuna_tuning.py` | No; lo ejecutas tú. |
| ¿Quién busca mejores estrategias/params? | `ai/explorer/optimizer.py` + `OptimizerTuningAgent` | No; se usa cuando ejecutas la suite con `--optimize`. |
| ¿Quién “promueve” champion (estrategia)? | `DefaultEvolutionAgent` en `ai/suite/agents.py` | Sí, dentro del ciclo de la suite; pero el ciclo lo disparas tú o Dagster. |
| ¿Algo corre solo sin que hagas nada? | Dagster schedules (`quant_suite_daily`, `crypto_lake_full_plus_train_weekly`) | Solo si Dagster está levantado; y la suite en Dagster no usa `--optimize` ni `--use-champion`. |

**En una frase:** el código que “encuentra” cosas está en **`ai/explorer/optimizer.py`** (estrategias/params) y en **`examples/quant_optuna_tuning.py`** (modelo ML). El que “trabaja solo” es **Dagster** (schedules), pero no está conectado a ese flujo completo de “encontrar modelos”. Para tener un agente que trabaje solo y encuentre modelos hace falta unificar eso en un solo flujo y dispararlo (script en bucle o job Dagster que sí use optimize + champion).
