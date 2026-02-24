"""
Vectores de asignación: 0 = sin posición, 0.2 = 20% long, -0.2 = 20% short.
Un valor por cada moneda. Suma |a| <= 1 (100% exposición).
"""

from ai.allocation.types import AllocationVector
from ai.allocation.strategies import score_to_allocation, compute_allocations
from ai.allocation.constraints import normalize_exposure
from ai.allocation.invariants import check_invariants, clamp_vector
from ai.allocation.risk import apply_risk_overlay, risk_overlay_from_config
from ai.allocation.exit_rules import build_exit_rule
from ai.allocation.checks import check_alpha_score_coverage, warn_alpha_score_if_low
from ai.allocation.backtest import (
    run_allocation_backtest,
    run_backtest_from_orders,
    AllocationBacktestResult,
    AllocationsByTime,
)

__all__ = [
    "AllocationVector",
    "AllocationsByTime",
    "AllocationBacktestResult",
    "score_to_allocation",
    "compute_allocations",
    "normalize_exposure",
    "check_invariants",
    "clamp_vector",
    "apply_risk_overlay",
    "risk_overlay_from_config",
    "build_exit_rule",
    "check_alpha_score_coverage",
    "warn_alpha_score_if_low",
    "run_allocation_backtest",
    "run_backtest_from_orders",
]
