"""
Backtest con vectores de asignación.
En cada event_time: allocation[symbol] = 0 (nada), 0.2 (20% long), -0.2 (20% short).
Retorno = sum(alloc[s] * fwd_return[s]). Fees sobre notional de cambio de posición.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from ai.allocation.strategies import compute_allocations
from ai.allocation.types import AllocationVector


AllocationsByTime = dict[str, dict[str, float]]


@dataclass
class AllocationBacktestResult:
    total_return_percent: float
    net_return_percent: float
    total_fees_percent: float
    total_slippage_percent: float
    trades_count: int
    max_drawdown_percent: float
    sharpe_ratio: float
    win_rate_percent: float
    periods: int
    by_symbol: dict[str, float]
    alloc_history: list[tuple[str, AllocationVector]]
    equity_curve: list[float] = field(default_factory=list)


def _compute_sharpe(period_returns: list[float]) -> float:
    """Sharpe-like ratio from per-period returns (no annualization)."""
    if len(period_returns) < 2:
        return 0.0
    avg = sum(period_returns) / len(period_returns)
    var = sum((r - avg) ** 2 for r in period_returns) / len(period_returns)
    std = math.sqrt(var)
    if std < 1e-9:
        return 0.0
    return avg / std


def run_allocation_backtest(
    rows: list[dict],
    horizon: str = "4h",
    fee_percent: float = 0.04,
    slippage_percent: float = 0.02,
    min_quote_volume_24h: float | None = None,
    compute_fn: Callable[[dict[str, dict], str], AllocationVector] | None = None,
    symbols: list[str] | None = None,
) -> AllocationBacktestResult:
    """
    rows: decision_features, cada fila = (event_time, symbol, alpha_score, fwd_return_*, ...)
    horizon: 1h, 4h, 24h -> usa fwd_return_1h, fwd_return_4h, fwd_return_24h
    fee_percent: fee por lado sobre notional (ej 0.04 = 4bps)
    slippage_percent: coste estimado por lado sobre notional, ej 0.02
    min_quote_volume_24h: excluir símbolos con quote_volume_24h < este valor (USD)
    compute_fn: si None, usa compute_allocations por defecto
    """
    label_col = {"1h": "fwd_return_1h", "4h": "fwd_return_4h", "24h": "fwd_return_24h"}.get(
        horizon, "fwd_return_4h"
    )
    compute_fn = compute_fn or (lambda f, _: compute_allocations(f))

    by_time: dict[str, dict[str, dict]] = {}
    for r in rows:
        ts = r.get("event_time", "")
        sym = r.get("symbol", "")
        if not ts or not sym:
            continue
        if symbols and sym not in symbols:
            continue
        if min_quote_volume_24h is not None:
            qv = r.get("quote_volume_24h")
            if qv is None:
                continue
            try:
                if float(qv) < min_quote_volume_24h:
                    continue
            except (TypeError, ValueError):
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
            total_slippage_percent=0.0,
            trades_count=0,
            max_drawdown_percent=0.0,
            sharpe_ratio=0.0,
            win_rate_percent=0.0,
            periods=0,
            by_symbol={},
            alloc_history=[],
        )

    prev_alloc: AllocationVector = {}
    total_return = 0.0
    total_fees = 0.0
    total_slippage = 0.0
    trades_count = 0
    by_symbol: dict[str, float] = {}
    alloc_history: list[tuple[str, AllocationVector]] = []

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    period_returns: list[float] = []
    winning_periods = 0
    equity_curve: list[float] = [1.0]

    for ts in event_times:
        features = by_time[ts]
        alloc = compute_fn(features, ts)
        alloc_history.append((ts, dict(alloc)))

        # Fees on notional change: round-trip fee * |delta| for each symbol.
        # In real trading, fee applies to the notional of each leg.
        period_fee = 0.0
        period_slip = 0.0
        for s in set(prev_alloc) | set(alloc):
            prev_a = prev_alloc.get(s, 0.0)
            curr_a = alloc.get(s, 0.0)
            delta = abs(curr_a - prev_a)
            if delta > 1e-6:
                trades_count += 1
                # Each allocation change requires closing old + opening new.
                # Fee on close: |prev_a| * fee_percent (if closing/reducing)
                # Fee on open: |curr_a| * fee_percent (if opening/increasing)
                # Net: fee on the larger of the two legs (round-trip on overlap)
                close_leg = abs(prev_a) if abs(curr_a) < abs(prev_a) or (prev_a * curr_a < 0) else delta
                open_leg = abs(curr_a) if abs(prev_a) < abs(curr_a) or (prev_a * curr_a < 0) else delta
                if prev_a * curr_a < 0:
                    # Signal flip: close full old + open full new
                    period_fee += (abs(prev_a) + abs(curr_a)) * fee_percent
                    period_slip += (abs(prev_a) + abs(curr_a)) * slippage_percent
                else:
                    # Same direction: fee only on the delta
                    period_fee += delta * fee_percent
                    period_slip += delta * slippage_percent

        total_fees += period_fee
        total_slippage += period_slip

        period_ret = 0.0
        for s, feats in features.items():
            if s not in alloc or abs(alloc[s]) < 1e-9:
                continue
            fwd_val = feats.get(label_col)
            if fwd_val is None:
                continue
            fwd = float(fwd_val)
            ret = alloc[s] * (fwd / 100.0)
            period_ret += ret
            total_return += ret
            by_symbol[s] = by_symbol.get(s, 0.0) + ret

        net_period = period_ret - period_fee - period_slip
        period_returns.append(net_period)
        if net_period > 0:
            winning_periods += 1

        equity *= 1 + net_period
        if equity > peak:
            peak = equity
        dd = ((peak - equity) / peak) * 100 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
        equity_curve.append(equity)

        prev_alloc = alloc

    n_periods = len(period_returns)
    win_rate = (winning_periods / n_periods * 100) if n_periods > 0 else 0.0

    return AllocationBacktestResult(
        total_return_percent=total_return,
        net_return_percent=total_return - total_fees - total_slippage,
        total_fees_percent=total_fees,
        total_slippage_percent=total_slippage,
        trades_count=trades_count,
        max_drawdown_percent=max_dd,
        sharpe_ratio=_compute_sharpe(period_returns),
        win_rate_percent=win_rate,
        periods=n_periods,
        by_symbol=by_symbol,
        alloc_history=alloc_history,
        equity_curve=equity_curve,
    )


def run_backtest_from_orders(
    rows: list[dict],
    allocations_by_ts: AllocationsByTime,
    horizon: str = "1h",
    fee_percent: float = 0.04,
    slippage_percent: float = 0.02,
    symbols: list[str] | None = None,
) -> AllocationBacktestResult:
    """
    Simula la realidad: ejecuta entradas/salidas con TUS órdenes.
    Tú pasas: vector de monedas (vía rows/symbols) y por cada barra el vector de
    asignaciones normalizadas. El backtest aplica esas asignaciones, cobra fees
    por cambio de posición y devuelve retorno neto y trades.
    """
    label_col = {"1h": "fwd_return_1h", "4h": "fwd_return_4h", "24h": "fwd_return_24h"}.get(
        horizon, "fwd_return_1h"
    )
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
            total_slippage_percent=0.0,
            trades_count=0,
            max_drawdown_percent=0.0,
            sharpe_ratio=0.0,
            win_rate_percent=0.0,
            periods=0,
            by_symbol={},
            alloc_history=[],
        )

    prev_alloc: AllocationVector = {}
    total_return = 0.0
    total_fees = 0.0
    total_slippage = 0.0
    trades_count = 0
    by_symbol: dict[str, float] = {}
    alloc_history: list[tuple[str, AllocationVector]] = []

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    period_returns: list[float] = []
    winning_periods = 0

    for ts in event_times:
        features = by_time[ts]
        raw = allocations_by_ts.get(ts, {})
        alloc = {s: float(raw.get(s, 0.0) or 0.0) for s in features}
        alloc_history.append((ts, dict(alloc)))

        period_fee = 0.0
        period_slip = 0.0
        for s in set(prev_alloc) | set(alloc):
            prev_a = prev_alloc.get(s, 0.0)
            curr_a = alloc.get(s, 0.0)
            delta = abs(curr_a - prev_a)
            if delta > 1e-6:
                trades_count += 1
                if prev_a * curr_a < 0:
                    period_fee += (abs(prev_a) + abs(curr_a)) * fee_percent
                    period_slip += (abs(prev_a) + abs(curr_a)) * slippage_percent
                else:
                    period_fee += delta * fee_percent
                    period_slip += delta * slippage_percent

        total_fees += period_fee
        total_slippage += period_slip

        period_ret = 0.0
        for s, feats in features.items():
            if s not in alloc or abs(alloc[s]) < 1e-9:
                continue
            fwd_val = feats.get(label_col)
            if fwd_val is None:
                continue
            fwd = float(fwd_val)
            ret = alloc[s] * (fwd / 100.0)
            period_ret += ret
            total_return += ret
            by_symbol[s] = by_symbol.get(s, 0.0) + ret

        net_period = period_ret - period_fee - period_slip
        period_returns.append(net_period)
        if net_period > 0:
            winning_periods += 1

        equity *= 1 + net_period
        if equity > peak:
            peak = equity
        dd = ((peak - equity) / peak) * 100 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

        prev_alloc = alloc

    n_periods = len(period_returns)
    win_rate = (winning_periods / n_periods * 100) if n_periods > 0 else 0.0

    return AllocationBacktestResult(
        total_return_percent=total_return,
        net_return_percent=total_return - total_fees - total_slippage,
        total_fees_percent=total_fees,
        total_slippage_percent=total_slippage,
        trades_count=trades_count,
        max_drawdown_percent=max_dd,
        sharpe_ratio=_compute_sharpe(period_returns),
        win_rate_percent=win_rate,
        periods=n_periods,
        by_symbol=by_symbol,
        alloc_history=alloc_history,
    )
