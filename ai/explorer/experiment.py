"""Ejecutor de experimentos: backtest con distintas estrategias y parámetros."""

from __future__ import annotations

import itertools
from typing import Any

from ai.allocation.backtest import run_allocation_backtest

from ai.explorer.registry import get_strategy
from ai.explorer.types import ExperimentResult, StrategyDef


def _grid_params(strategy: StrategyDef, param_overrides: dict[str, list] | None = None) -> list[dict]:
    """Genera combinaciones de params para grid search."""
    ranges = dict(strategy.param_ranges)
    if param_overrides:
        ranges.update(param_overrides)
    keys = list(ranges.keys())
    values = [ranges[k] for k in keys]
    combos = []
    for combo in itertools.product(*values):
        params = dict(zip(keys, combo))
        for k, v in strategy.default_params.items():
            if k not in params:
                params[k] = v
        combos.append(params)
    return combos


def run_single(
    rows: list[dict],
    strategy_id: str,
    params: dict[str, Any],
    horizon: str = "4h",
    fee_percent: float = 0.04,
    slippage_percent: float = 0.02,
    min_quote_volume_24h: float | None = None,
    symbols: list[str] | None = None,
) -> ExperimentResult | None:
    """Ejecuta un backtest con una estrategia y params."""
    strategy = get_strategy(strategy_id)
    if not strategy:
        return None
    compute_fn = strategy.build_compute_fn(rows, params)
    r = run_allocation_backtest(
        rows,
        horizon=horizon,
        fee_percent=fee_percent,
        slippage_percent=slippage_percent,
        min_quote_volume_24h=min_quote_volume_24h,
        compute_fn=compute_fn,
        symbols=symbols,
    )
    return ExperimentResult(
        strategy_id=strategy_id,
        params=params,
        horizon=horizon,
        net_return_percent=r.net_return_percent,
        total_return_percent=r.total_return_percent,
        fees_percent=r.total_fees_percent,
        slippage_percent=r.total_slippage_percent,
        trades_count=r.trades_count,
        max_drawdown_percent=r.max_drawdown_percent,
        sharpe_ratio=r.sharpe_ratio,
        win_rate_percent=r.win_rate_percent,
        periods=r.periods,
        by_symbol=r.by_symbol,
    )


def run_grid(
    rows: list[dict],
    strategy_id: str,
    horizon: str = "4h",
    fee_percent: float = 0.04,
    slippage_percent: float = 0.02,
    min_quote_volume_24h: float | None = None,
    symbols: list[str] | None = None,
    param_overrides: dict[str, list] | None = None,
    max_combos: int = 100,
) -> list[ExperimentResult]:
    """Grid search sobre param_ranges de la estrategia."""
    strategy = get_strategy(strategy_id)
    if not strategy:
        return []
    combos = _grid_params(strategy, param_overrides)
    if len(combos) > max_combos:
        step = len(combos) // max_combos
        combos = [combos[i] for i in range(0, len(combos), max(1, step))][:max_combos]
    results = []
    for params in combos:
        res = run_single(
            rows, strategy_id, params,
            horizon=horizon, fee_percent=fee_percent,
            slippage_percent=slippage_percent, min_quote_volume_24h=min_quote_volume_24h,
            symbols=symbols,
        )
        if res:
            results.append(res)
    return results


def run_all_strategies(
    rows: list[dict],
    strategy_ids: list[str] | None = None,
    horizon: str = "4h",
    fee_percent: float = 0.04,
    slippage_percent: float = 0.02,
    min_quote_volume_24h: float | None = None,
    symbols: list[str] | None = None,
    use_default_params: bool = True,
) -> list[ExperimentResult]:
    """Ejecuta todas las estrategias (o las indicadas) con params por defecto."""
    from ai.explorer.registry import get_registry
    registry = get_registry()
    ids = strategy_ids or list(registry.keys())
    results = []
    for sid in ids:
        strategy = registry.get(sid)
        if not strategy:
            continue
        params = strategy.default_params if use_default_params else {}
        res = run_single(rows, sid, params, horizon, fee_percent, slippage_percent, min_quote_volume_24h, symbols)
        if res:
            results.append(res)
    return results
