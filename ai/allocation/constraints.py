"""Restricciones sobre vectores de asignación."""

from __future__ import annotations

from ai.allocation.types import AllocationVector


def normalize_exposure(
    alloc: AllocationVector,
    max_exposure: float = 1.0,
) -> AllocationVector:
    """
    Normalización de exposición total (garantiza invariante I2).
    Regla: si total := Σ_s |a_s| > max_exposure, devuelve a_s' = a_s * (max_exposure / total).
    Si total <= max_exposure, devuelve el vector sin cambios.
    Mantiene signos y proporciones relativas entre símbolos.
    """
    total = sum(abs(a) for a in alloc.values())
    if total <= 0 or total <= max_exposure:
        return dict(alloc)
    scale = max_exposure / total
    return {s: a * scale for s, a in alloc.items()}
