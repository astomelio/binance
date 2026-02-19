from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from trading_lib import BinanceConnectorClient


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_orders(path: str) -> List[Dict]:
    out: List[Dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    out.sort(key=lambda x: (x.get("event_time", ""), x.get("symbol", "")))
    return out


def _side_and_position(order: Dict) -> tuple[str, str, bool]:
    action = str(order.get("action", "")).upper()
    side = str(order.get("side", "")).upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError(f"Unsupported side: {side}")

    # Hedge-mode semantics:
    # - LONG opens with BUY/LONG and closes with SELL/LONG (reduceOnly)
    # - SHORT opens with SELL/SHORT and closes with BUY/SHORT (reduceOnly)
    if action == "CLOSE":
        if side == "LONG":
            return "SELL", "LONG", True
        return "BUY", "SHORT", True

    if action in {"OPEN", "REBALANCE", "FLIP"}:
        if side == "LONG":
            return "BUY", "LONG", False
        return "SELL", "SHORT", False

    raise ValueError(f"Unsupported action: {action}")


def _safe_float(order: Dict, key: str) -> float:
    return float(order.get(key, 0) or 0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute quant OOS orders in paper or live mode")
    parser.add_argument("--orders-file", default="artifacts/quant_model/oos_orders.jsonl")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    parser.add_argument("--api-base-url", default="http://localhost:8000")
    parser.add_argument("--capital-usd", type=float, default=500.0)
    parser.add_argument("--max-notional-per-order-usd", type=float, default=75.0)
    parser.add_argument("--max-daily-notional-usd", type=float, default=300.0)
    parser.add_argument("--min-allocation-change-pct", type=float, default=0.02)
    parser.add_argument("--min-seconds-between-orders", type=float, default=0.25)
    parser.add_argument("--max-orders", type=int, default=200)
    parser.add_argument("--max-price-diff-bps", type=float, default=20.0)
    parser.add_argument(
        "--paper-fill-source",
        choices=["file", "live"],
        default="file",
        help="In paper mode use historical file price (replay) or current live price.",
    )
    args = parser.parse_args()

    orders = _load_orders(args.orders_file)
    if not orders:
        raise ValueError(f"No orders in file: {args.orders_file}")

    client = BinanceConnectorClient(base_url=args.api_base_url)
    out_dir = Path("artifacts/quant_model")
    out_dir.mkdir(parents=True, exist_ok=True)
    exec_log = out_dir / "execution_log.jsonl"
    report_file = out_dir / "execution_report.json"

    daily_notional = defaultdict(float)
    executed = 0
    skipped = 0
    failed = 0
    total_notional = 0.0

    with exec_log.open("w", encoding="utf-8") as log:
        for idx, order in enumerate(orders, start=1):
            if executed >= args.max_orders:
                skipped += 1
                log.write(json.dumps({"status": "SKIP", "reason": "max_orders", "order": order}) + "\n")
                continue

            alloc_change = abs(_safe_float(order, "to_allocation_pct") - _safe_float(order, "from_allocation_pct"))
            if alloc_change < args.min_allocation_change_pct:
                skipped += 1
                log.write(json.dumps({"status": "SKIP", "reason": "small_allocation_change", "order": order}) + "\n")
                continue

            ts = order.get("event_time", "")
            symbol = str(order.get("symbol", "")).upper()
            if not ts or not symbol:
                skipped += 1
                log.write(json.dumps({"status": "SKIP", "reason": "invalid_order", "order": order}) + "\n")
                continue

            dt = _parse_iso(ts)
            day = dt.date().isoformat()
            from_alloc = _safe_float(order, "from_allocation_pct")
            to_alloc = _safe_float(order, "to_allocation_pct")
            action = str(order.get("action", "")).upper()
            if action == "CLOSE":
                alloc_for_notional = from_alloc
            else:
                alloc_for_notional = to_alloc

            target_notional = min(args.capital_usd * alloc_for_notional, args.max_notional_per_order_usd)
            if target_notional <= 0:
                skipped += 1
                log.write(json.dumps({"status": "SKIP", "reason": "non_positive_notional", "order": order}) + "\n")
                continue

            if daily_notional[day] + target_notional > args.max_daily_notional_usd:
                skipped += 1
                log.write(
                    json.dumps(
                        {
                            "status": "SKIP",
                            "reason": "daily_notional_limit",
                            "order": order,
                            "daily_notional": daily_notional[day],
                            "attempt_notional": target_notional,
                        }
                    )
                    + "\n"
                )
                continue

            try:
                side, position_side, reduce_only = _side_and_position(order)
                file_price = _safe_float(order, "price")
                price_used = 0.0

                if args.mode == "paper" and args.paper_fill_source == "file" and file_price > 0:
                    price_used = file_price
                else:
                    live_price = client.get_futures_ticker_price(symbol)
                    if live_price <= 0:
                        raise ValueError("live_price <= 0")
                    price_used = live_price

                    if file_price > 0:
                        diff_bps = abs((live_price - file_price) / file_price) * 10000
                        if diff_bps > args.max_price_diff_bps:
                            skipped += 1
                            log.write(
                                json.dumps(
                                    {
                                        "status": "SKIP",
                                        "reason": "price_diff_guard",
                                        "symbol": symbol,
                                        "file_price": file_price,
                                        "live_price": live_price,
                                        "diff_bps": diff_bps,
                                        "max_diff_bps": args.max_price_diff_bps,
                                        "order": order,
                                    }
                                )
                                + "\n"
                            )
                            continue

                qty = target_notional / price_used
                if qty <= 0:
                    skipped += 1
                    log.write(json.dumps({"status": "SKIP", "reason": "qty_non_positive", "order": order}) + "\n")
                    continue

                payload = {
                    "event_time": ts,
                    "symbol": symbol,
                    "action": order.get("action"),
                    "side": side,
                    "position_side": position_side,
                    "reduce_only": reduce_only,
                    "quantity": qty,
                    "price_used": price_used,
                    "notional_usd": target_notional,
                    "mode": args.mode,
                }

                if args.mode == "live":
                    resp = client.create_futures_order(
                        symbol=symbol,
                        side=side,
                        quantity=qty,
                        order_type="MARKET",
                        position_side=position_side,
                        reduce_only=reduce_only,
                    )
                    payload["exchange_response"] = resp

                payload["status"] = "EXECUTED"
                log.write(json.dumps(payload) + "\n")
                executed += 1
                daily_notional[day] += target_notional
                total_notional += target_notional

                if args.min_seconds_between_orders > 0:
                    time.sleep(args.min_seconds_between_orders)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                log.write(
                    json.dumps({"status": "FAILED", "reason": str(exc), "order": order, "mode": args.mode}) + "\n"
                )

            if idx >= args.max_orders and args.max_orders > 0:
                break

    summary = {
        "mode": args.mode,
        "orders_file": args.orders_file,
        "executed": executed,
        "skipped": skipped,
        "failed": failed,
        "total_notional_usd": round(total_notional, 4),
        "daily_notional_usd": dict(daily_notional),
        "risk_controls": {
            "capital_usd": args.capital_usd,
            "max_notional_per_order_usd": args.max_notional_per_order_usd,
            "max_daily_notional_usd": args.max_daily_notional_usd,
            "min_allocation_change_pct": args.min_allocation_change_pct,
            "max_price_diff_bps": args.max_price_diff_bps,
            "min_seconds_between_orders": args.min_seconds_between_orders,
            "max_orders": args.max_orders,
        },
        "log_file": str(exec_log),
    }
    report_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Execution report -> {report_file}")


if __name__ == "__main__":
    main()

