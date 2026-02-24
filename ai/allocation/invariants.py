"""
Invariantes formales del AllocationVector.
Cualquier vector que salga de estrategia o pase a ejecución debe cumplirlos.
"""

from __future__ import annotations

from ai.allocation.types import AllocationVector

# --- Invariantes formales (contrato) ------------------------------------------
#
# I1 (rango por símbolo):  ∀s,  a[s] ∈ [-1, 1]
# I2 (exposición total):   Σ_s |a[s]| ≤ max_exposure   (típicamente 1.0)
# I3 (clave):             claves = símbolos (str), valores = float
#
# La normalización de exposición (constraints.normalize_exposure) garantiza I2
# manteniendo proporciones relativas. El clamp por símbolo garantiza I1.


def check_invariants(
    alloc: AllocationVector,
    max_exposure: float = 1.0,
    tol: float = 1e-9,
) -> tuple[bool, list[str]]:
    """
    Verifica que el vector cumpla I1 e I2.
    Devuelve (ok, lista de mensajes de violación).
    """
    violations: list[str] = []
    for s, a in alloc.items():
        if not isinstance(a, (int, float)):
            violations.append(f"I1: {s} allocation no es float")
        elif a < -1.0 - tol or a > 1.0 + tol:
            violations.append(f"I1: {s} = {a} fuera de [-1, 1]")
    total = sum(abs(a) for a in alloc.values())
    if total > max_exposure + tol:
        violations.append(f"I2: exposición total {total:.4f} > max_exposure {max_exposure}")
    return (len(violations) == 0, violations)


def clamp_vector(alloc: AllocationVector) -> AllocationVector:
    """Fuerza I1: cada componente en [-1, 1]. No modifica I2."""
    return {s: max(-1.0, min(1.0, float(a))) for s, a in alloc.items()}
