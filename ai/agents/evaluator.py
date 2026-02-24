"""
Walk-forward evaluator for strategy genomes.

Evaluates a genome on historical data using walk-forward splits with embargo
to prevent look-ahead bias. Returns a fitness score combining return, risk,
and stability across folds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ai.agents.genome import StrategyGenome
from ai.allocation.backtest import run_allocation_backtest
from ai.allocation.constraints import normalize_exposure
from ai.allocation.exit_rules import build_exit_rule
from ai.allocation.risk import apply_risk_overlay
from ai.allocation.types import AllocationVector
from trading_lib.timeseries import build_walk_forward_splits


@dataclass
class FoldMetric:
    fold: int
    test_start: str
    test_end: str
    net_return_percent: float
    max_drawdown_percent: float
    sharpe_ratio: float
    win_rate_percent: float
    trades: int
    periods: int


@dataclass
class EvalResult:
    """Full evaluation result for a genome."""

    genome_id: str
    genome: dict[str, Any]
    folds: list[FoldMetric]

    # Aggregated metrics across folds
    mean_return: float = 0.0
    std_return: float = 0.0
    mean_sharpe: float = 0.0
    mean_drawdown: float = 0.0
    mean_win_rate: float = 0.0
    total_trades: int = 0
    stability: float = 0.0  # fraction of folds with positive return
    fitness: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "genome_id": self.genome_id,
            "genome": self.genome,
            "n_folds": len(self.folds),
            "mean_return": self.mean_return,
            "std_return": self.std_return,
            "mean_sharpe": self.mean_sharpe,
            "mean_drawdown": self.mean_drawdown,
            "mean_win_rate": self.mean_win_rate,
            "total_trades": self.total_trades,
            "stability": self.stability,
            "fitness": self.fitness,
        }


def _build_compute_fn_from_genome(genome: StrategyGenome, rows: list[dict]):
    """Build a compute_fn that scores each symbol using genome's feature weights."""
    weights = genome.feature_weights
    lt = genome.long_threshold
    st = genome.short_threshold
    min_a = genome.min_allocation
    max_a = genome.max_allocation
    max_exp = genome.max_exposure
    max_sym = genome.max_per_symbol
    dd_kill = genome.max_drawdown_kill

    exit_rule = build_exit_rule(
        max_bars_held=genome.max_bars_held,
        target_pct=genome.take_profit_pct,
        stop_pct=genome.stop_loss_pct,
    )

    bars_held: dict[str, int] = {}
    unrealized_pnl: dict[str, float] = {}
    prev_alloc: AllocationVector = {}

    def compute_fn(features_by_symbol: dict[str, dict], event_time: str) -> AllocationVector:
        alloc: AllocationVector = {}
        for symbol, feats in features_by_symbol.items():
            window = feats.get("fed_window", "NORMAL")
            if window in ("PRE_EVENT", "POST_EVENT", "UNKNOWN"):
                alloc[symbol] = 0.0
                continue

            # Weighted score from genome's feature weights
            score = 0.0
            for feat_name, weight in weights.items():
                val = feats.get(feat_name)
                if val is None:
                    continue
                try:
                    score += weight * float(val)
                except (TypeError, ValueError):
                    continue

            if score >= lt:
                strength = min((score - lt) / max(1.0 - lt, 0.01), 1.0)
                alloc[symbol] = min_a + strength * (max_a - min_a)
            elif score <= st:
                strength = min((st - score) / max(1.0 + st, 0.01), 1.0)
                alloc[symbol] = -(min_a + strength * (max_a - min_a))
            else:
                alloc[symbol] = 0.0

        alloc = apply_risk_overlay(
            alloc,
            max_exposure=max_exp,
            max_per_symbol=max_sym,
        )

        # Track bars held and apply exit rules
        for s in alloc:
            if abs(alloc.get(s, 0)) > 1e-6:
                bars_held[s] = bars_held.get(s, 0) + 1
            else:
                bars_held[s] = 0

        if genome.max_bars_held or genome.stop_loss_pct or genome.take_profit_pct:
            context = {
                "bars_held_by_symbol": dict(bars_held),
                "unrealized_pnl_by_symbol": dict(unrealized_pnl),
            }
            alloc = exit_rule(alloc, context)

        return alloc

    return compute_fn


def _compute_fitness(folds: list[FoldMetric]) -> float:
    """Risk-adjusted fitness that penalizes drawdown and instability.

    fitness = mean_sharpe * stability_bonus - drawdown_penalty - instability_penalty

    A strategy that makes money consistently with low drawdown scores highest.
    """
    if not folds:
        return -999.0

    returns = [f.net_return_percent for f in folds]
    sharpes = [f.sharpe_ratio for f in folds]
    drawdowns = [f.max_drawdown_percent for f in folds]

    mean_ret = sum(returns) / len(returns)
    mean_sharpe = sum(sharpes) / len(sharpes)
    mean_dd = sum(drawdowns) / len(drawdowns)

    positive_folds = sum(1 for r in returns if r > 0)
    stability = positive_folds / len(returns)

    std_ret = math.sqrt(sum((r - mean_ret) ** 2 for r in returns) / len(returns)) if len(returns) > 1 else 0.0
    instability = (std_ret / abs(mean_ret)) if abs(mean_ret) > 0.01 else 1.0

    fitness = (
        mean_sharpe * (0.5 + 0.5 * stability)
        - 0.15 * mean_dd
        - 0.10 * min(instability, 3.0)
        + 0.10 * mean_ret
    )
    return round(fitness, 6)


def evaluate_genome(
    genome: StrategyGenome,
    rows: list[dict],
    train_days: int = 30,
    test_days: int = 7,
    step_days: int = 7,
    embargo_hours: int = 12,
    fee_percent: float = 0.04,
    slippage_percent: float = 0.02,
    min_folds: int = 2,
) -> EvalResult | None:
    """Evaluate a genome using walk-forward cross-validation.

    Returns None if insufficient data for the requested splits.
    """
    horizon = genome.horizon
    splits = build_walk_forward_splits(
        rows=rows,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        embargo_hours=embargo_hours,
    )

    if len(splits) < min_folds:
        # Fall back: evaluate on all data (no walk-forward)
        compute_fn = _build_compute_fn_from_genome(genome, rows)
        r = run_allocation_backtest(
            rows,
            horizon=horizon,
            fee_percent=fee_percent,
            slippage_percent=slippage_percent,
            compute_fn=compute_fn,
        )
        fold = FoldMetric(
            fold=0,
            test_start=rows[0].get("event_time", "") if rows else "",
            test_end=rows[-1].get("event_time", "") if rows else "",
            net_return_percent=r.net_return_percent,
            max_drawdown_percent=r.max_drawdown_percent,
            sharpe_ratio=r.sharpe_ratio,
            win_rate_percent=r.win_rate_percent,
            trades=r.trades_count,
            periods=r.periods,
        )
        folds = [fold]
    else:
        from trading_lib.timeseries import _parse_event_time
        folds: list[FoldMetric] = []
        for idx, split in enumerate(splits):
            t_start = _parse_event_time(split.test_start)
            t_end = _parse_event_time(split.test_end)
            test_rows = [
                r for r in rows
                if _parse_event_time(r["event_time"]) >= t_start
                and _parse_event_time(r["event_time"]) < t_end
            ]
            if len(test_rows) < 10:
                continue

            compute_fn = _build_compute_fn_from_genome(genome, rows)
            r = run_allocation_backtest(
                test_rows,
                horizon=horizon,
                fee_percent=fee_percent,
                slippage_percent=slippage_percent,
                compute_fn=compute_fn,
            )
            folds.append(FoldMetric(
                fold=idx,
                test_start=split.test_start,
                test_end=split.test_end,
                net_return_percent=r.net_return_percent,
                max_drawdown_percent=r.max_drawdown_percent,
                sharpe_ratio=r.sharpe_ratio,
                win_rate_percent=r.win_rate_percent,
                trades=r.trades_count,
                periods=r.periods,
            ))

    if not folds:
        return None

    returns = [f.net_return_percent for f in folds]
    sharpes = [f.sharpe_ratio for f in folds]
    drawdowns = [f.max_drawdown_percent for f in folds]
    win_rates = [f.win_rate_percent for f in folds]

    mean_ret = sum(returns) / len(returns)
    std_ret = math.sqrt(sum((r - mean_ret) ** 2 for r in returns) / len(returns)) if len(returns) > 1 else 0.0
    positive = sum(1 for r in returns if r > 0) / len(returns)

    return EvalResult(
        genome_id=genome.genome_id,
        genome=genome.to_dict(),
        folds=folds,
        mean_return=round(mean_ret, 4),
        std_return=round(std_ret, 4),
        mean_sharpe=round(sum(sharpes) / len(sharpes), 4),
        mean_drawdown=round(sum(drawdowns) / len(drawdowns), 4),
        mean_win_rate=round(sum(win_rates) / len(win_rates), 2),
        total_trades=sum(f.trades for f in folds),
        stability=round(positive, 2),
        fitness=_compute_fitness(folds),
    )
