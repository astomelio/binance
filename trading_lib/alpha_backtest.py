from __future__ import annotations

import glob
import json
from dataclasses import dataclass
from typing import Dict, List

from .fees import FeeModel
from .trade_logger import TradingLogger


@dataclass
class AlphaTrade:
    symbol: str
    entry_time: str
    exit_time: str
    side: str
    entry_price: float
    exit_price: float
    pnl_percent: float
    net_pnl_percent: float
    reason: str


@dataclass
class AlphaBacktestResult:
    trades: int
    win_rate: float
    gross_return_percent: float
    net_return_percent: float
    by_symbol: Dict[str, float]
    trade_log: List[AlphaTrade]


def _read_jsonl(path_pattern: str) -> List[Dict]:
    rows: List[Dict] = []
    for file in glob.glob(path_pattern, recursive=True):
        with open(file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    rows.sort(key=lambda x: x.get("event_time", ""))
    return rows


def run_alpha_backtest(
    decision_features_glob: str,
    fee_model: FeeModel,
    logger: TradingLogger | None = None,
) -> AlphaBacktestResult:
    rows = _read_jsonl(decision_features_glob)
    if not rows:
        raise ValueError(f"No decision features found at: {decision_features_glob}")

    open_positions: Dict[str, Dict] = {}
    trades: List[AlphaTrade] = []
    by_symbol: Dict[str, float] = {}
    rt_fee = fee_model.round_trip_fee_percent("futures", is_maker=True)

    for row in rows:
        symbol = row.get("symbol", "")
        signal = row.get("alpha_signal", "NO_TRADE")
        price = float(row.get("futures_last_price", 0) or 0)
        ts = row.get("event_time", "")
        window = row.get("fed_window", "UNKNOWN")
        if not symbol or price <= 0:
            continue

        if window != "NORMAL":
            if symbol in open_positions:
                pos = open_positions.pop(symbol)
                gross = ((price - pos["entry_price"]) / pos["entry_price"]) * 100
                if pos["side"] == "SHORT":
                    gross = -gross
                net = gross - rt_fee
                trade = AlphaTrade(
                    symbol=symbol,
                    entry_time=pos["entry_time"],
                    exit_time=ts,
                    side=pos["side"],
                    entry_price=pos["entry_price"],
                    exit_price=price,
                    pnl_percent=gross,
                    net_pnl_percent=net,
                    reason="Exit by FED window risk control",
                )
                trades.append(trade)
                by_symbol[symbol] = by_symbol.get(symbol, 0.0) + net
                if logger:
                    logger.event("ALPHA_EXIT", {"trade": trade})
            continue

        if symbol not in open_positions and signal in {"LONG", "SHORT"}:
            open_positions[symbol] = {
                "side": signal,
                "entry_price": price,
                "entry_time": ts,
            }
            if logger:
                logger.event(
                    "ALPHA_ENTRY",
                    {"symbol": symbol, "side": signal, "entry_price": price, "entry_time": ts},
                )
            continue

        if symbol in open_positions:
            pos = open_positions[symbol]
            if (pos["side"] == "LONG" and signal == "SHORT") or (pos["side"] == "SHORT" and signal == "LONG"):
                open_positions.pop(symbol)
                gross = ((price - pos["entry_price"]) / pos["entry_price"]) * 100
                if pos["side"] == "SHORT":
                    gross = -gross
                net = gross - rt_fee
                trade = AlphaTrade(
                    symbol=symbol,
                    entry_time=pos["entry_time"],
                    exit_time=ts,
                    side=pos["side"],
                    entry_price=pos["entry_price"],
                    exit_price=price,
                    pnl_percent=gross,
                    net_pnl_percent=net,
                    reason="Signal flip",
                )
                trades.append(trade)
                by_symbol[symbol] = by_symbol.get(symbol, 0.0) + net
                if logger:
                    logger.event("ALPHA_EXIT", {"trade": trade})

                open_positions[symbol] = {
                    "side": signal,
                    "entry_price": price,
                    "entry_time": ts,
                }
                if logger:
                    logger.event(
                        "ALPHA_ENTRY",
                        {"symbol": symbol, "side": signal, "entry_price": price, "entry_time": ts},
                    )

    # Close remaining positions at last known price to get measurable backtest output.
    if rows:
        last_by_symbol = {}
        for row in rows:
            symbol = row.get("symbol", "")
            if symbol:
                last_by_symbol[symbol] = row

        for symbol, pos in list(open_positions.items()):
            last_row = last_by_symbol.get(symbol)
            if not last_row:
                continue
            price = float(last_row.get("futures_last_price", 0) or 0)
            if price <= 0:
                continue
            gross = ((price - pos["entry_price"]) / pos["entry_price"]) * 100
            if pos["side"] == "SHORT":
                gross = -gross
            net = gross - rt_fee
            trade = AlphaTrade(
                symbol=symbol,
                entry_time=pos["entry_time"],
                exit_time=last_row.get("event_time", ""),
                side=pos["side"],
                entry_price=pos["entry_price"],
                exit_price=price,
                pnl_percent=gross,
                net_pnl_percent=net,
                reason="Forced close at end of sample",
            )
            trades.append(trade)
            by_symbol[symbol] = by_symbol.get(symbol, 0.0) + net
            if logger:
                logger.event("ALPHA_EXIT", {"trade": trade})

    wins = len([t for t in trades if t.net_pnl_percent > 0])
    trades_count = len(trades)
    result = AlphaBacktestResult(
        trades=trades_count,
        win_rate=(wins / trades_count * 100) if trades_count else 0.0,
        gross_return_percent=sum(t.pnl_percent for t in trades),
        net_return_percent=sum(t.net_pnl_percent for t in trades),
        by_symbol=by_symbol,
        trade_log=trades,
    )
    if logger:
        logger.event("ALPHA_SUMMARY", {"result": result})
    return result

