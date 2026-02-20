"""
Backtest con vectores de asignación.
En cada event_time: allocation[symbol] = 0 (nada), 0.2 (20% long), -0.2 (20% short).
Retorno = sum(alloc[s] * fwd_return[s]). Fees sobre cambios de posición.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ai.allocation.strategies import compute_allocations
from ai.allocation.types import AllocationVector


@dataclass
class AllocationBacktestResult:
    total_return_percent: float
    net_return_percent: float
    total_fees_percent: float
    trades_count: int
    by_symbol: dict[str, float]
    alloc_history: list[tuple[str, AllocationVector]]


def run_allocation_backtest(
    rows: list[dict],
    horizon: str = "4h",
    fee_percent: float = 0.04,
    compute_fn: Callable[[dict[str, dict], str], AllocationVector] | None = None,
    symbols: list[str] | None = None,
) -> AllocationBacktestResult:
    """
    rows: decision_features, cada fila = (event_time, symbol, alpha_score, fwd_return_*, ...)
    horizon: 1h, 4h, 24h -> usa fwd_return_1h, fwd_return_4h, fwd_return_24h
    fee_percent: round-trip fee por trade (ej 0.04)
    compute_fn: si None, usa compute_allocations por defecto
    """
    label_col = {"1h": "fwd_return_1h", "4h": "fwd_return_4h", "24h": "fwd_return_24h"}.get(
        horizon, "fwd_return_4h"
    )
    compute_fn = compute_fn or (lambda f, _: compute_allocations(f))

    # Agrupar por event_time
    by_time: dict[str, dict[str, dict]] = {}
    for r in rows:
        ts = r.get("event_time", "")
        sym = r.get("symbol", "")
        if not ts or not sym:
            continue
        if symbols and sym not in symbols:
            continue
        if ts not in by_time:
            by_time[ts] = {}
        by_time[ts][sym] = r

    event_times = sorted(by_time.keys())
    if not event_times:
        return AllocationBacktestResult(
            total_return_percent=0.0,
            net_return_percent=0.0,
            total_fees_percent=0.0,
            trades_count=0,
            by_symbol={},
            alloc_history=[],
        )

    prev_alloc: AllocationVector = {}
    total_return = 0.0
    total_fees = 0.0
    trades_count = 0
    by_symbol: dict[str, float] = {}
    alloc_history: list[tuple[str, AllocationVector]] = []

    for ts in event_times:
        features = by_time[ts]
        alloc = compute_fn(features, ts)
        alloc_history.append((ts, dict(alloc)))

        # Fee por cambio de posición
        for s in set(prev_alloc) | set(alloc):
            prev_a = prev_alloc.get(s, 0.0)
            curr_a = alloc.get(s, 0.0)
            delta = abs(curr_a - prev_a)
            if delta > 1e-6:
                trades_count += 1
                total_fees += delta * fee_percent

        # Retorno: alloc * fwd_return (del período anterior al actual)
        # En t tenemos fwd_return = retorno de t a t+1. Usamos alloc de t-1 para el retorno t-1->t.
        # Simplificación: usamos alloc de t y fwd_return de t = retorno t->t+1.
        # Así el retorno del período actual se materializa en el siguiente step.
        # Mejor: en t, tenemos alloc_t y fwd_return en la fila = ret de t a t+1.
        # Portfolio return de t a t+1 = sum(alloc_t[s] * fwd_return[s])
        for s, feats in features.items():
            if s not in alloc:
                continue
            fwd_val = feats.get(label_col)
            if fwd_val is None:
                continue
            fwd = float(fwd_val)
            ret = alloc[s] * (fwd / 100.0)
            total_return += ret
            by_symbol[s] = by_symbol.get(s, 0.0) + ret

        prev_alloc = alloc

    return AllocationBacktestResult(
        total_return_percent=total_return,
        net_return_percent=total_return - total_fees,
        total_fees_percent=total_fees,
        trades_count=trades_count,
        by_symbol=by_symbol,
        alloc_history=alloc_history,
    )
