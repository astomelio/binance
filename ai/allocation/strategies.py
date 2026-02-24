"""
Estrategias que convierten features en vectores de asignación.
Input: features por symbol. Output: allocation por symbol (0 = nada, 0.2 = 20% long, -0.2 = 20% short).
"""

from __future__ import annotations

from ai.allocation.constraints import normalize_exposure
from ai.allocation.types import AllocationVector


def score_to_allocation(
    score: float,
    long_threshold: float = 0.10,
    short_threshold: float = -0.10,
    min_allocation: float = 0.1,
    max_allocation: float = 0.4,
) -> float:
    """
    Direct threshold on alpha_score (no sigmoid transformation).
    score > long_threshold -> long (positive allocation)
    score < short_threshold -> short (negative allocation)
    else -> 0
    Magnitude scales linearly with distance from threshold up to max_allocation.
    """
    if score >= long_threshold:
        strength = min((score - long_threshold) / max(1.0 - long_threshold, 0.01), 1.0)
        return min_allocation + strength * (max_allocation - min_allocation)
    if score <= short_threshold:
        strength = min((short_threshold - score) / max(1.0 + short_threshold, 0.01), 1.0)
        return -(min_allocation + strength * (max_allocation - min_allocation))
    return 0.0


def compute_allocations(
    features_by_symbol: dict[str, dict],
    score_key: str = "alpha_score",
    long_threshold: float = 0.10,
    short_threshold: float = -0.10,
    min_allocation: float = 0.1,
    max_allocation: float = 0.4,
    max_exposure: float = 1.0,
    fed_window_key: str = "fed_window",
    no_trade_windows: tuple[str, ...] = ("PRE_EVENT", "POST_EVENT", "UNKNOWN"),
) -> AllocationVector:
    """
    Convierte features por symbol en vector de asignación.
    features_by_symbol[symbol] = {alpha_score, fed_window, ...}
    Uses direct thresholds on alpha_score [-1, 1] instead of sigmoid mapping.
    """
    alloc: AllocationVector = {}
    for symbol, feats in features_by_symbol.items():
        window = feats.get(fed_window_key, "NORMAL")
        if window in no_trade_windows:
            alloc[symbol] = 0.0
            continue
        score = float(feats.get(score_key, 0) or 0)
        a = score_to_allocation(score, long_threshold, short_threshold, min_allocation, max_allocation)
        alloc[symbol] = a

    return normalize_exposure(alloc, max_exposure)
