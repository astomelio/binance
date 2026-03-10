"""
Estrategia ensemble: combina múltiples modelos/estrategias.
El agente puede elegir qué modelos incluir y cómo ponderarlos.
"""

from __future__ import annotations

from ai.allocation.constraints import normalize_exposure
from ai.allocation.types import AllocationVector

from ai.explorer.registry import get_strategy
from ai.explorer.types import StrategyDef


def _build_compute_fn(rows: list, params: dict):
    """
    params:
      model_ids: list[str] - estrategias a combinar (alpha_score, mean_reversion, heuristic)
      weights: list[float] - ponderación por modelo (opcional, default: igual)
      merge_mode: "average" | "max_conviction" | "voting"
        - average: alloc = sum(w_i * alloc_i)
        - max_conviction: por symbol, toma el de mayor |alloc|
        - voting: mayoría por signo, magnitud = promedio de los que coinciden
    """
    model_ids = params.get("model_ids", ["alpha_score"])
    weights = params.get("weights")
    merge_mode = params.get("merge_mode", "average")
    max_exp = params.get("max_exposure", 1.0)

    strategies = []
    for mid in model_ids:
        strat = get_strategy(mid)
        if strat:
            strategies.append((mid, strat.build_compute_fn(rows, strat.default_params)))

    if not strategies:
        # Fallback: alpha_score
        strat = get_strategy("alpha_score")
        if strat:
            strategies = [("alpha_score", strat.build_compute_fn(rows, strat.default_params))]

    n = len(strategies)
    weights = weights if weights and len(weights) == n else [1.0 / n] * n
    w_sum = sum(weights)
    weights = [w / w_sum for w in weights]

    def fn(features_by_symbol: dict, event_time: str) -> AllocationVector:
        allocs = []
        for _, compute in strategies:
            a = compute(features_by_symbol, event_time)
            allocs.append(a)

        combined: AllocationVector = {}
        symbols = set()
        for a in allocs:
            symbols.update(a.keys())

        for sym in symbols:
            vals = [(a.get(sym, 0.0), w) for a, w in zip(allocs, weights)]
            if merge_mode == "average":
                combined[sym] = sum(v * w for v, w in vals)
            elif merge_mode == "max_conviction":
                best = max(vals, key=lambda x: abs(x[0]))
                combined[sym] = best[0]
            else:  # voting
                longs = sum(w for v, w in vals if v > 0)
                shorts = sum(w for v, w in vals if v < 0)
                if longs > shorts:
                    combined[sym] = sum(v * w for v, w in vals if v > 0) / max(longs, 0.01)
                elif shorts > longs:
                    combined[sym] = sum(v * w for v, w in vals if v < 0) / max(shorts, 0.01)
                else:
                    combined[sym] = 0.0

        return normalize_exposure(combined, max_exp)

    return fn


ensemble_strategy = StrategyDef(
    id="ensemble",
    name="Ensemble (multi-modelo)",
    description="Combina alpha_score, mean_reversion, heuristic. El agente elige modelos y ponderación.",
    default_params={
        "model_ids": ["alpha_score", "mean_reversion"],
        "merge_mode": "average",
        "max_exposure": 1.0,
    },
    param_ranges={
        "merge_mode": ["average", "max_conviction", "voting"],
    },
    build_compute_fn=_build_compute_fn,
)
