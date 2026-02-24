#!/usr/bin/env python3
"""
Simular la realidad: tú pasas vector de monedas y asignaciones normalizadas por barra;
el script ejecuta entradas/salidas y devuelve retorno neto y trades.
Replicable: mismo JSON/input -> mismo resultado.

Uso:
  python scripts/run_sim_from_orders.py --input artifacts/quant_model/orders_to_simulate.json
  python scripts/run_sim_from_orders.py --symbols BTCUSDT,ETHUSDT --alloc-json '[{"event_time":"2026-01-27T12:00:00","BTCUSDT":0.2,"ETHUSDT":-0.1}]'

Formato del JSON de entrada (--input):
  {
    "symbols": ["BTCUSDT", "ETHUSDT", ...],
    "horizon": "1h",
    "allocations": [
      { "event_time": "2026-01-27T11:59:59.999000+00:00", "BTCUSDT": 0.2, "ETHUSDT": -0.1 },
      ...
    ]
  }
  O con vector en orden de symbols: "allocations": [ {"event_time": "...", "vector": [0.2, -0.1]} ]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simula realidad: vector de monedas + asignaciones por barra -> ejecuta y devuelve resultado."
    )
    parser.add_argument("--input", "-i", help="JSON con symbols y allocations (ver doc arriba)")
    parser.add_argument("--symbols", help="Comma-separated si no usas --input")
    parser.add_argument("--alloc-json", help="JSON array de {event_time, symbol: allocation} o {event_time, vector: [...]}")
    parser.add_argument("--start", help="Inicio periodo (si no se infiere del input)")
    parser.add_argument("--end", help="Fin periodo (si no se infiere del input)")
    parser.add_argument("--horizon", default="1h", choices=("1h", "4h", "24h"))
    parser.add_argument("--fee", type=float, default=0.04)
    parser.add_argument("--slippage", type=float, default=0.02)
    parser.add_argument("--out", "-o", help="Escribir resultado JSON aquí")
    parser.add_argument("--db", default=None, help="DuckDB path (default DBT_DUCKDB_PATH o artifacts/warehouse/crypto.duckdb)")
    args = parser.parse_args()

    symbols: list[str]
    allocations_by_ts: dict[str, dict[str, float]]
    start_str: str | None = args.start
    end_str: str | None = args.end

    if args.input:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        symbols = data.get("symbols") or []
        horizon = data.get("horizon", args.horizon)
        fee = data.get("fee_percent", args.fee)
        slippage = data.get("slippage_percent", args.slippage)
        raw_alloc = data.get("allocations") or []
    else:
        horizon = args.horizon
        fee = args.fee
        slippage = args.slippage
        if not args.symbols or not args.alloc_json:
            print("Falta --input o (--symbols y --alloc-json)", file=sys.stderr)
            return 1
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        raw_alloc = json.loads(args.alloc_json)

    if not symbols:
        print("symbols vacío", file=sys.stderr)
        return 1

    # Construir allocations_by_ts: event_time -> { symbol: allocation }
    allocations_by_ts = {}
    for item in raw_alloc:
        if not isinstance(item, dict):
            continue
        ts = item.get("event_time")
        if not ts:
            continue
        if "vector" in item:
            allocations_by_ts[ts] = dict(zip(symbols, (float(x) for x in item["vector"])))
        else:
            allocations_by_ts[ts] = {k: float(v) for k, v in item.items() if k != "event_time"}

    if not allocations_by_ts:
        print("allocations vacío o formato incorrecto", file=sys.stderr)
        return 1

    if not start_str or not end_str:
        times = sorted(allocations_by_ts.keys())
        start_str = start_str or (times[0].replace("Z", "").replace("+00:00", "").strip() if times else None)
        end_str = end_str or (times[-1].replace("Z", "").replace("+00:00", "").strip() if times else None)
    if not start_str or not end_str:
        print("Falta start/end o event_time en allocations", file=sys.stderr)
        return 1

    db_path = args.db or os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    if not Path(db_path).exists():
        print(f"DuckDB no encontrado: {db_path}", file=sys.stderr)
        return 1

    from ai.data.loader import load_decision_features
    from ai.allocation.backtest import run_backtest_from_orders

    rows = load_decision_features(
        horizon=horizon,
        label_not_null=True,
        db_path=db_path,
        symbols=symbols,
        start=start_str,
        end=end_str,
    )
    if not rows:
        print("No hay filas en decision_features para ese periodo/símbolos.", file=sys.stderr)
        return 1

    result = run_backtest_from_orders(
        rows,
        allocations_by_ts,
        horizon=horizon,
        fee_percent=fee,
        slippage_percent=slippage,
        symbols=symbols,
    )

    out = {
        "net_return_percent": result.net_return_percent,
        "total_return_percent": result.total_return_percent,
        "total_fees_percent": result.total_fees_percent,
        "total_slippage_percent": result.total_slippage_percent,
        "trades_count": result.trades_count,
        "by_symbol": result.by_symbol,
        "period": [start_str, end_str],
        "symbols": symbols,
    }
    print("net_return_percent:", result.net_return_percent)
    print("trades_count:", result.trades_count)
    print("total_fees_percent:", result.total_fees_percent)
    print("total_slippage_percent:", result.total_slippage_percent)

    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
        print("Escrito:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
