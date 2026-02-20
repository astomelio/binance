"""Estrategia mean reversion: oversold -> LONG, overbought -> SHORT."""

from collections import defaultdict

from ai.allocation.constraints import normalize_exposure
from ai.allocation.types import AllocationVector

from ai.explorer.types import StrategyDef


def _rank_volatile_symbols(rows: list[dict], top_n: int, vol_metric: str) -> list[str]:
    by_sym: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        v = r.get(vol_metric)
        if v is not None:
            try:
                by_sym[r["symbol"]].append(abs(float(v)))
            except (TypeError, ValueError):
                pass
    ranked = sorted(
        by_sym.items(),
        key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 0,
        reverse=True,
    )
    return [s for s, _ in ranked[:top_n]]


def _build_compute_fn(rows: list, params: dict):
    oversold = params.get("oversold", -2.0)
    overbought = params.get("overbought", 2.0)
    size = params.get("allocation_size", 0.2)
    max_exp = params.get("max_exposure", 1.0)
    top_vol = params.get("top_volatile", 0)
    vol_metric = params.get("vol_metric", "momentum_3")

    volatile = _rank_volatile_symbols(rows, top_n=top_vol or 999, vol_metric=vol_metric) if top_vol else None
    if top_vol and volatile:
        volatile = volatile[:top_vol]

    def fn(features_by_symbol: dict, event_time: str) -> AllocationVector:
        alloc: AllocationVector = {}
        for symbol, feats in features_by_symbol.items():
            if volatile and symbol not in volatile:
                alloc[symbol] = 0.0
                continue
            m = float(feats.get(vol_metric) or 0)
            if m <= oversold:
                strength = min(1.0, abs(m - oversold) / abs(oversold))
                alloc[symbol] = size * (0.5 + 0.5 * strength)
            elif m >= overbought:
                strength = min(1.0, abs(m - overbought) / overbought)
                alloc[symbol] = -size * (0.5 + 0.5 * strength)
            else:
                alloc[symbol] = 0.0
        return normalize_exposure(alloc, max_exp)
    return fn


mean_reversion_strategy = StrategyDef(
    id="mean_reversion",
    name="Mean Reversion",
    description="Oversold (momentum < umbral) -> LONG, overbought -> SHORT. Opcional: solo pares volátiles.",
    default_params={
        "oversold": -2.0,
        "overbought": 2.0,
        "allocation_size": 0.2,
        "max_exposure": 1.0,
        "top_volatile": 0,
        "vol_metric": "momentum_3",
    },
    param_ranges={
        "oversold": [-3.0, -2.5, -2.0, -1.5, -1.0],
        "overbought": [1.0, 1.5, 2.0, 2.5, 3.0],
        "top_volatile": [0, 5, 10],
        "vol_metric": ["momentum_3", "momentum_12", "price_change_percent_24h"],
    },
    build_compute_fn=_build_compute_fn,
)
