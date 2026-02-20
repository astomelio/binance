"""Registro de estrategias explorables."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai.explorer.types import StrategyDef

_REGISTRY: dict[str, "StrategyDef"] = {}


def register_strategy(strategy: "StrategyDef") -> None:
    _REGISTRY[strategy.id] = strategy


def get_registry() -> dict[str, "StrategyDef"]:
    return dict(_REGISTRY)


def get_strategy(strategy_id: str) -> "StrategyDef | None":
    return _REGISTRY.get(strategy_id)


def list_strategies() -> list[str]:
    return list(_REGISTRY.keys())


# Auto-register built-in strategies
def _register_builtins():
    from ai.explorer.strategies import alpha_score_strategy, heuristic_strategy, mean_reversion_strategy
    register_strategy(alpha_score_strategy)
    register_strategy(heuristic_strategy)
    register_strategy(mean_reversion_strategy)


_register_builtins()
