"""
Criterios de cierre de posición: cuándo cerrar (poner asignación a 0).
La ejecución "cierra" implícitamente cuando el vector en la siguiente barra
asigna 0 a ese símbolo; las reglas aquí permiten forzar cierre antes.
"""

from __future__ import annotations

from typing import Any, Callable

from ai.allocation.types import AllocationVector

# Contexto opcional para reglas: puede incluir bars_held, unrealized_pnl_pct, score, etc.
ExitContext = dict[str, Any]


def close_when_alloc_zero(
    alloc: AllocationVector,
    _context: ExitContext | None = None,
) -> AllocationVector:
    """
    No fuerza cierre; el vector ya dice 0 donde no hay posición.
    Cierre = cuando la estrategia devuelve 0 para ese símbolo (siguiente barra).
    """
    return alloc


def close_after_n_bars(
    alloc: AllocationVector,
    context: ExitContext | None,
    max_bars_held: int,
    bars_held_by_symbol: dict[str, int],
) -> AllocationVector:
    """
    Fuerza cierre (alloc[s]=0) si el símbolo lleva más de max_bars_held barras abierto.
    context puede traer bars_held_by_symbol; si no, se usa el dict pasado.
    """
    if context:
        held = context.get("bars_held_by_symbol") or bars_held_by_symbol
    else:
        held = bars_held_by_symbol
    out = dict(alloc)
    for s, n in held.items():
        if n >= max_bars_held and s in out and out[s] != 0:
            out[s] = 0.0
    return out


def close_on_stop_or_target(
    alloc: AllocationVector,
    context: ExitContext | None,
    target_pct: float = 1.0,
    stop_pct: float = -0.5,
    unrealized_pnl_by_symbol: dict[str, float] | None = None,
) -> AllocationVector:
    """
    Fuerza cierre si PnL no realizado del símbolo >= target_pct (tomar beneficio)
    o <= stop_pct (cortar pérdida).
    context puede traer unrealized_pnl_by_symbol.
    """
    pnls = (context or {}).get("unrealized_pnl_by_symbol") or unrealized_pnl_by_symbol or {}
    out = dict(alloc)
    for s, pnl in pnls.items():
        if s not in out:
            continue
        if out[s] == 0:
            continue
        if pnl >= target_pct or pnl <= stop_pct:
            out[s] = 0.0
    return out


def build_exit_rule(
    max_bars_held: int | None = None,
    target_pct: float | None = None,
    stop_pct: float | None = None,
) -> Callable[[AllocationVector, ExitContext | None], AllocationVector]:
    """
    Construye una regla de salida que aplica (opcionalmente) tope de barras y/o target/stop.
    Uso: en cada barra, pasar el alloc propuesto y el contexto; devuelve el alloc
    posiblemente con algunos símbolos forzados a 0.
    """
    def _rule(alloc: AllocationVector, context: ExitContext | None) -> AllocationVector:
        out = alloc
        if max_bars_held is not None and context:
            held = context.get("bars_held_by_symbol") or {}
            out = close_after_n_bars(out, context, max_bars_held, held)
        if target_pct is not None and stop_pct is not None and context:
            pnls = context.get("unrealized_pnl_by_symbol") or {}
            out = close_on_stop_or_target(out, context, target_pct, stop_pct, pnls)
        return out
    return _rule
