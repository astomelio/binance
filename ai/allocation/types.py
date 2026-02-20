"""Tipos para vectores de asignación."""

from __future__ import annotations

from typing import TypedDict


# dict[symbol, allocation] donde allocation ∈ [-1, 1]
# 0 = sin posición, 0.2 = 20% long, -0.2 = 20% short
AllocationVector = dict[str, float]
