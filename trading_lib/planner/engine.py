from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Tuple

from ..fees import FeeModel
from ..timeseries import build_walk_forward_splits
from .allocation import compute_model_allocations
from .specs import StrategySpec


@dataclass
class PlannerTrade:
    symbol: str
    entry_time: str
    exit_time: str
    side: str
    entry_price: float
    exit_price: float
    allocation_pct: float
    net_pnl_percent: float
    weighted_net_pnl_percent: float
    reason: str


@dataclass
class PlannerResult:
    strategy_name: str
    trades: int
    win_rate: float
    net_return_percent: float
    max_drawdown_percent: float
    turnover_percent: float


@dataclass
class PlannerFoldResult:
    strategy_name: str
    split_index: int
    test_start: str
    test_end: str
    trades: int
    net_return_percent: float
    win_rate: float


def _parse_iso(value: str):
    from datetime import datetime, timezone

    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _run_rows(rows: List[Dict], spec: StrategySpec, fee_model: FeeModel) -> Tuple[PlannerResult, List[PlannerTrade]]:
    open_positions: Dict[str, Dict] = {}
    trades: List[PlannerTrade] = []
    rt_fee = fee_model.round_trip_fee_percent("futures", is_maker=True)

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    turnover = 0.0
    prev_target_alloc: Dict[str, float] = {}

    # Group rows by event_time to compute portfolio allocations jointly across symbols.
    rows_by_time: Dict[str, List[Dict]] = {}
    for row in rows:
        ts = row.get("event_time", "")
        if not ts:
            continue
        rows_by_time.setdefault(ts, []).append(row)

    for ts in sorted(rows_by_time.keys()):
        snapshot = rows_by_time[ts]
        row_by_symbol = {r.get("symbol"): r for r in snapshot if r.get("symbol")}
        target_allocs = compute_model_allocations(
            snapshot_rows=snapshot,
            spec=spec,
            max_gross_exposure_pct=spec.max_gross_exposure_pct,
            max_symbol_pct=spec.max_symbol_pct,
        )
        target_by_symbol = {a.symbol: a for a in target_allocs}
        target_alloc_pct = {a.symbol: a.allocation_pct for a in target_allocs}

        # Portfolio turnover: sum absolute allocation changes at each rebalance.
        all_symbols = set(prev_target_alloc.keys()) | set(target_alloc_pct.keys())
        turnover += sum(abs(target_alloc_pct.get(s, 0.0) - prev_target_alloc.get(s, 0.0)) for s in all_symbols)
        prev_target_alloc = target_alloc_pct

        weighted_return_this_ts = 0.0
        symbols_considered = set(open_positions.keys()) | set(target_by_symbol.keys())
        for symbol in symbols_considered:
            row = row_by_symbol.get(symbol)
            if not row:
                continue
            price = float(row.get("futures_last_price", 0) or 0)
            if price <= 0:
                continue

            pos = open_positions.get(symbol)
            target = target_by_symbol.get(symbol)

            if pos is None and target is not None:
                open_positions[symbol] = {
                    "side": target.side,
                    "entry_price": price,
                    "entry_time": ts,
                    "allocation_pct": target.allocation_pct,
                }
                continue

            if pos is not None:
                close_reason = None
                if target is None:
                    close_reason = "no_signal"
                elif target.side != pos["side"]:
                    close_reason = "signal_flip"

                if close_reason:
                    gross = ((price - pos["entry_price"]) / pos["entry_price"]) * 100
                    if pos["side"] == "SHORT":
                        gross = -gross
                    net = gross - rt_fee
                    weighted_net = net * pos["allocation_pct"]
                    weighted_return_this_ts += weighted_net

                    trades.append(
                        PlannerTrade(
                            symbol=symbol,
                            entry_time=pos["entry_time"],
                            exit_time=ts,
                            side=pos["side"],
                            entry_price=pos["entry_price"],
                            exit_price=price,
                            allocation_pct=pos["allocation_pct"],
                            net_pnl_percent=net,
                            weighted_net_pnl_percent=weighted_net,
                            reason=close_reason,
                        )
                    )
                    open_positions.pop(symbol, None)

                    if target is not None and close_reason == "signal_flip":
                        open_positions[symbol] = {
                            "side": target.side,
                            "entry_price": price,
                            "entry_time": ts,
                            "allocation_pct": target.allocation_pct,
                        }

        if weighted_return_this_ts != 0.0:
            equity *= 1 + (weighted_return_this_ts / 100.0)
            peak = max(peak, equity)
            dd = ((peak - equity) / peak) * 100
            max_dd = max(max_dd, dd)

    # force close at end of sample
    if rows:
        last_by_symbol: Dict[str, Dict] = {}
        for row in rows:
            sym = row.get("symbol")
            if sym:
                last_by_symbol[sym] = row
        for symbol, pos in list(open_positions.items()):
            last = last_by_symbol.get(symbol)
            if not last:
                continue
            price = float(last.get("futures_last_price", 0) or 0)
            if price <= 0:
                continue
            gross = ((price - pos["entry_price"]) / pos["entry_price"]) * 100
            if pos["side"] == "SHORT":
                gross = -gross
            net = gross - rt_fee
            weighted_net = net * pos["allocation_pct"]
            equity *= 1 + (weighted_net / 100.0)
            peak = max(peak, equity)
            dd = ((peak - equity) / peak) * 100
            max_dd = max(max_dd, dd)
            trades.append(
                PlannerTrade(
                    symbol=symbol,
                    entry_time=pos["entry_time"],
                    exit_time=last.get("event_time", ""),
                    side=pos["side"],
                    entry_price=pos["entry_price"],
                    exit_price=price,
                    allocation_pct=pos["allocation_pct"],
                    net_pnl_percent=net,
                    weighted_net_pnl_percent=weighted_net,
                    reason="sample_end",
                )
            )

    wins = len([t for t in trades if t.weighted_net_pnl_percent > 0])
    result = PlannerResult(
        strategy_name=spec.name,
        trades=len(trades),
        win_rate=(wins / len(trades) * 100) if trades else 0.0,
        net_return_percent=sum(t.weighted_net_pnl_percent for t in trades),
        max_drawdown_percent=max_dd,
        turnover_percent=turnover * 100,
    )
    return result, trades


def evaluate_strategy_walk_forward(
    rows: List[Dict],
    spec: StrategySpec,
    fee_model: FeeModel,
    train_days: int = 30,
    test_days: int = 7,
    step_days: int = 7,
    embargo_hours: int = 12,
) -> Tuple[PlannerResult, List[PlannerFoldResult]]:
    splits = build_walk_forward_splits(
        rows=rows,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        embargo_hours=embargo_hours,
    )
    if not splits:
        # fallback: evaluate on all rows if history is still small.
        result, _ = _run_rows(rows, spec, fee_model)
        return result, []

    fold_results: List[PlannerFoldResult] = []
    all_test_rows: List[Dict] = []
    for idx, split in enumerate(splits, start=1):
        test_start = _parse_iso(split.test_start)
        test_end = _parse_iso(split.test_end)
        test_rows = [r for r in rows if test_start <= _parse_iso(r["event_time"]) < test_end]
        all_test_rows.extend(test_rows)
        fold_result, _ = _run_rows(test_rows, spec, fee_model)
        fold_results.append(
            PlannerFoldResult(
                strategy_name=spec.name,
                split_index=idx,
                test_start=split.test_start,
                test_end=split.test_end,
                trades=fold_result.trades,
                net_return_percent=fold_result.net_return_percent,
                win_rate=fold_result.win_rate,
            )
        )

    global_result, _ = _run_rows(all_test_rows, spec, fee_model)
    global_result.strategy_name = spec.name
    return global_result, fold_results


def rank_results(results: List[PlannerResult]) -> List[PlannerResult]:
    return sorted(
        results,
        key=lambda r: (r.net_return_percent, -r.max_drawdown_percent, -r.turnover_percent, r.win_rate),
        reverse=True,
    )


def to_dict(item):
    return asdict(item)

