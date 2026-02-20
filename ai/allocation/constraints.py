"""Restricciones sobre vectores de asignación."""

from __future__ import annotations

from ai.allocation.types import AllocationVector


def normalize_exposure(
    alloc: AllocationVector,
    max_exposure: float = 1.0,
) -> AllocationVector:
    """
    Escala el vector para que sum(|a|) <= max_exposure.
    Mantiene signos y proporciones relativas.
    """
    total = sum(abs(a) for a in alloc.values())
    if total <= 0 or total <= max_exposure:
        return dict(alloc)
    scale = max_exposure / total
    return {s: a * scale for s, a in alloc.items()}
