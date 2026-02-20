"""Estrategia alpha_score: composite ML (basis + funding + momentum)."""

from ai.allocation.strategies import compute_allocations

from ai.explorer.types import StrategyDef


def _build_compute_fn(rows: list, params: dict):
    pt = params.get("prob_threshold", 0.55)
    min_a = params.get("min_allocation", 0.1)
    max_a = params.get("max_allocation", 0.4)

    def fn(features_by_symbol: dict, event_time: str):
        return compute_allocations(
            features_by_symbol,
            prob_threshold=pt,
            min_allocation=min_a,
            max_allocation=max_a,
            max_exposure=1.0,
        )
    return fn


alpha_score_strategy = StrategyDef(
    id="alpha_score",
    name="Alpha Score (composite)",
    description="Basis + funding + momentum + microstructure. Umbral prob para LONG/SHORT.",
    default_params={"prob_threshold": 0.55, "min_allocation": 0.1, "max_allocation": 0.4},
    param_ranges={
        "prob_threshold": [0.50, 0.52, 0.55, 0.58],
        "min_allocation": [0.1],
        "max_allocation": [0.4],
    },
    build_compute_fn=_build_compute_fn,
)
