"""
Librería de exploración de estrategias para uso automático (agentes).
Registro de estrategias, variación de parámetros, backtest comparativo.
"""

from ai.explorer.registry import get_registry, register_strategy, list_strategies
from ai.explorer.experiment import run_single, run_grid, run_all_strategies
from ai.explorer.agent import ExplorationAgent
from ai.explorer.types import ExperimentResult, ExplorationReport, StrategyDef

__all__ = [
    "get_registry",
    "register_strategy",
    "list_strategies",
    "run_single",
    "run_grid",
    "run_all_strategies",
    "ExplorationAgent",
    "ExperimentResult",
    "ExplorationReport",
    "StrategyDef",
]
