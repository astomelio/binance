"""Estrategia heurística: alpha_signal = LONG | SHORT | NO_TRADE."""

from ai.allocation.constraints import normalize_exposure
from ai.allocation.types import AllocationVector

from ai.explorer.types import StrategyDef


def _build_compute_fn(rows: list, params: dict):
    size = params.get("allocation_size", 0.2)
    max_exp = params.get("max_exposure", 1.0)

    def fn(features_by_symbol: dict, event_time: str) -> AllocationVector:
        alloc: AllocationVector = {}
        for symbol, feats in features_by_symbol.items():
            signal = (feats.get("alpha_signal") or "NO_TRADE").strip().upper()
            if signal == "LONG":
                alloc[symbol] = size
            elif signal == "SHORT":
                alloc[symbol] = -size
            else:
                alloc[symbol] = 0.0
        return normalize_exposure(alloc, max_exp)
    return fn


heuristic_strategy = StrategyDef(
    id="heuristic",
    name="Alpha Signal (heurística)",
    description="LONG/SHORT según reglas dbt (basis + funding + price_change).",
    default_params={"allocation_size": 0.2, "max_exposure": 1.0},
    param_ranges={
        "allocation_size": [0.15, 0.2, 0.25],
        "max_exposure": [1.0],
    },
    build_compute_fn=_build_compute_fn,
)
