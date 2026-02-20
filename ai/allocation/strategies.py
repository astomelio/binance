"""
Estrategias que convierten features en vectores de asignación.
Input: features por symbol. Output: allocation por symbol (0 = nada, 0.2 = 20% long, -0.2 = 20% short).
"""

from __future__ import annotations

import math

from ai.allocation.constraints import normalize_exposure
from ai.allocation.types import AllocationVector


def score_to_allocation(
    score: float,
    prob_threshold: float = 0.55,
    min_allocation: float = 0.1,
    max_allocation: float = 0.4,
) -> float:
    """
    Convierte score (o prob) en allocation.
    score > prob_threshold -> long (positivo)
    score < (1 - prob_threshold) -> short (negativo)
    else -> 0
    Magnitud entre min_allocation y max_allocation según confianza.
    """
    if score >= prob_threshold:
        # Long: más confianza = más allocation
        strength = (score - prob_threshold) / (1.0 - prob_threshold)
        return min_allocation + strength * (max_allocation - min_allocation)
    if score <= 1.0 - prob_threshold:
        # Short
        strength = ((1.0 - prob_threshold) - score) / (1.0 - prob_threshold)
        return -(min_allocation + strength * (max_allocation - min_allocation))
    return 0.0


def compute_allocations(
    features_by_symbol: dict[str, dict],
    score_key: str = "alpha_score",
    prob_threshold: float = 0.55,
    min_allocation: float = 0.1,
    max_allocation: float = 0.4,
    max_exposure: float = 1.0,
    fed_window_key: str = "fed_window",
    no_trade_windows: tuple[str, ...] = ("PRE_EVENT", "POST_EVENT", "UNKNOWN"),
) -> AllocationVector:
    """
    Convierte features por symbol en vector de asignación.
    features_by_symbol[symbol] = {alpha_score, fed_window, ...}
    Retorna {symbol: allocation} con allocation ∈ [-1, 1].
    """
    alloc: AllocationVector = {}
    for symbol, feats in features_by_symbol.items():
        window = feats.get(fed_window_key, "NORMAL")
        if window in no_trade_windows:
            alloc[symbol] = 0.0
            continue
        score = float(feats.get(score_key, 0) or 0)
        # alpha_score está en [-1, 1] aprox; mapear a prob [0, 1] para umbral
        prob = 1.0 / (1.0 + math.exp(-score)) if abs(score) < 20 else (1.0 if score > 0 else 0.0)
        a = score_to_allocation(prob, prob_threshold, min_allocation, max_allocation)
        alloc[symbol] = a

    return normalize_exposure(alloc, max_exposure)
