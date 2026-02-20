"""
Vectores de asignación: 0 = sin posición, 0.2 = 20% long, -0.2 = 20% short.
Un valor por cada moneda. Suma |a| <= 1 (100% exposición).
"""

from ai.allocation.types import AllocationVector
from ai.allocation.strategies import score_to_allocation, compute_allocations
from ai.allocation.constraints import normalize_exposure

__all__ = [
    "AllocationVector",
    "score_to_allocation",
    "compute_allocations",
    "normalize_exposure",
]
