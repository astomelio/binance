"""Estrategia alpha_score: composite ML (basis + funding + momentum)."""

from ai.allocation.strategies import compute_allocations

from ai.explorer.types import StrategyDef


def _build_compute_fn(rows: list, params: dict):
    lt = params.get("long_threshold", 0.10)
    st = params.get("short_threshold", -0.10)
    min_a = params.get("min_allocation", 0.1)
    max_a = params.get("max_allocation", 0.4)

    def fn(features_by_symbol: dict, event_time: str):
        return compute_allocations(
            features_by_symbol,
            long_threshold=lt,
            short_threshold=st,
            min_allocation=min_a,
            max_allocation=max_a,
            max_exposure=1.0,
        )
    return fn


alpha_score_strategy = StrategyDef(
    id="alpha_score",
    name="Alpha Score (composite)",
    description="Basis + funding + momentum + microstructure. Direct threshold on score.",
    default_params={
        "long_threshold": 0.10,
        "short_threshold": -0.10,
        "min_allocation": 0.1,
        "max_allocation": 0.4,
    },
    param_ranges={
        "long_threshold": [0.05, 0.08, 0.10, 0.15, 0.20],
        "short_threshold": [-0.20, -0.15, -0.10, -0.08, -0.05],
        "min_allocation": [0.1],
        "max_allocation": [0.3, 0.4],
    },
    build_compute_fn=_build_compute_fn,
)
