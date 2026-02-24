"""
Capa explícita de risk management.
Entrada: AllocationVector (propuesta de la estrategia).
Salida: AllocationVector que cumple invariantes y límites de riesgo.
Siempre se aplica después de la estrategia y antes de ejecución/backtest.
"""

from __future__ import annotations

from typing import Callable

from ai.allocation.constraints import normalize_exposure
from ai.allocation.types import AllocationVector


def apply_risk_overlay(
    alloc: AllocationVector,
    max_exposure: float = 1.0,
    max_per_symbol: float = 0.4,
    max_net_exposure: float | None = None,
    zero_on_drawdown_above: float | None = None,
    current_equity: float | None = None,
    peak_equity: float | None = None,
) -> AllocationVector:
    """
    Aplica límites de riesgo al vector de asignación.
    Orden: clamp por símbolo → cap net (opcional) → normalizar exposición → kill switch (opcional).
    """
    out: AllocationVector = {s: max(-1.0, min(1.0, float(a))) for s, a in alloc.items()}

    # Límite por símbolo: |a| <= max_per_symbol
    if max_per_symbol < 1.0:
        out = {
            s: max(-max_per_symbol, min(max_per_symbol, a))
            for s, a in out.items()
        }

    # Límite exposición neta (long - short); si se excede, escala hacia 0
    if max_net_exposure is not None and max_net_exposure >= 0:
        net = sum(out.values())
        if abs(net) > max_net_exposure:
            scale = max_net_exposure / abs(net) if net != 0 else 0.0
            out = {s: a * scale for s, a in out.items()}

    # Normalización exposición total: sum(|a|) <= max_exposure
    out = normalize_exposure(out, max_exposure=max_exposure)

    # Kill switch: si drawdown supera umbral, cerrar todo
    if (
        zero_on_drawdown_above is not None
        and current_equity is not None
        and peak_equity is not None
        and peak_equity > 0
    ):
        dd = (peak_equity - current_equity) / peak_equity
        if dd >= zero_on_drawdown_above:
            out = {s: 0.0 for s in out}

    return out


def risk_overlay_from_config(config: dict) -> Callable[[AllocationVector], AllocationVector]:
    """
    Devuelve una función (alloc -> alloc) con los parámetros del config.
    Útil para pipelines: strategy -> risk_overlay_from_config(cfg)(alloc) -> ejecución.
    """
    def _apply(alloc: AllocationVector) -> AllocationVector:
        return apply_risk_overlay(
            alloc,
            max_exposure=config.get("max_exposure", 1.0),
            max_per_symbol=config.get("max_per_symbol", 0.4),
            max_net_exposure=config.get("max_net_exposure"),
            zero_on_drawdown_above=config.get("zero_on_drawdown_above"),
            current_equity=config.get("current_equity"),
            peak_equity=config.get("peak_equity"),
        )
    return _apply
