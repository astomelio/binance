"""Tipos para el explorer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Any

from ai.allocation.types import AllocationVector


@dataclass
class StrategyDef:
    """Definición de una estrategia explorable."""

    id: str
    name: str
    description: str
    default_params: dict[str, Any]
    param_ranges: dict[str, list[Any]]  # valores para grid search
    build_compute_fn: Callable[[list[dict], dict[str, Any]], Callable[[dict, str], AllocationVector]]


@dataclass
class ExperimentResult:
    """Resultado de un experimento (backtest)."""

    strategy_id: str
    params: dict[str, Any]
    horizon: str
    net_return_percent: float
    total_return_percent: float
    fees_percent: float
    slippage_percent: float = 0.0
    trades_count: int = 0
    by_symbol: dict[str, float] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)  # symbol_set, session_hours, etc.

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "params": self.params,
            "horizon": self.horizon,
            "net_return_percent": self.net_return_percent,
            "total_return_percent": self.total_return_percent,
            "fees_percent": self.fees_percent,
            "slippage_percent": self.slippage_percent,
            "trades_count": self.trades_count,
        }


@dataclass
class ExplorationReport:
    """Reporte de exploración: mejores configs por estrategia."""

    results: list[ExperimentResult]
    best_overall: ExperimentResult | None
    best_by_strategy: dict[str, ExperimentResult]
    data_summary: dict[str, Any]
