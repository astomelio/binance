# ai.explorer – Librería de exploración de estrategias

Librería para explorar estrategias de forma automática (agentes, pipelines).

## Uso programático

```python
from ai.explorer import ExplorationAgent, get_registry, register_strategy

# Quick: todas las estrategias con params default
agent = ExplorationAgent(horizon="4h")
report = agent.run_quick()

# Grid: variar params de una estrategia
report = agent.run_grid("mean_reversion", max_combos=50)

# Full: exploración completa (todas las estrategias, muestreo de params)
report = agent.run_full(max_experiments_per_strategy=30)

# Resultados
print(report.best_overall.strategy_id, report.best_overall.params)
print(report.best_by_strategy)  # mejor por estrategia
```

## Estrategias incluidas

| id | Descripción |
|----|-------------|
| alpha_score | Composite (basis + funding + momentum). Umbral prob. |
| heuristic | alpha_signal dbt: LONG/SHORT según reglas. |
| mean_reversion | Oversold → LONG, overbought → SHORT. Opcional: top volátiles. |

## Registrar estrategia custom

```python
from ai.explorer import register_strategy
from ai.explorer.types import StrategyDef

def my_build_fn(rows, params):
    def compute(features_by_symbol, event_time):
        # ... retornar AllocationVector
        return {}
    return compute

my_strategy = StrategyDef(
    id="mi_estrategia",
    name="Mi estrategia",
    description="...",
    default_params={"x": 1},
    param_ranges={"x": [1, 2, 3]},
    build_compute_fn=my_build_fn,
)
register_strategy(my_strategy)
```

## Estructura

```
ai/explorer/
  __init__.py      # exports
  registry.py      # registro de estrategias
  types.py         # StrategyDef, ExperimentResult, ExplorationReport
  experiment.py    # run_single, run_grid, run_all_strategies
  agent.py         # ExplorationAgent
  strategies/
    alpha_score.py
    heuristic.py
    mean_reversion.py
```
