#!/usr/bin/env python3
"""
Calcula el retorno realizado % a partir del log de ejecución en paper (execution_log.jsonl).
Así puedes comparar con el retorno neto % del backtest (make ai-backtest) para el mismo período.

Uso:
  python examples/compare_backtest_vs_paper.py --execution-log artifacts/quant_model/execution_log.jsonl
  python examples/compare_backtest_vs_paper.py  # usa ruta por defecto
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read_execution_log(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _build_paper_scenarios(executed: list[dict]) -> list[dict]:
    """Construye lista de escenarios (entrada/salida) por trade cerrado."""
    open_pos: dict[tuple[str, str], dict] = {}
    scenarios: list[dict] = []

    for r in executed:
        symbol = str(r.get("symbol", "")).upper()
        action = str(r.get("action", "")).upper()
        position_side = str(r.get("position_side", "")).upper()
        event_time = str(r.get("event_time", ""))
        price = float(r.get("price_used", 0) or 0)
        notional = float(r.get("notional_usd", 0) or 0)
        qty = float(r.get("quantity", 0) or 0)
        if not symbol or price <= 0:
            continue

        key = (symbol, position_side)

        if action in ("OPEN", "REBALANCE", "FLIP"):
            open_pos[key] = {
                "entry_time": event_time,
                "entry_price": price,
                "notional": notional,
                "qty": qty,
            }
        elif action == "CLOSE":
            if key not in open_pos:
                continue
            entry = open_pos[key]
            entry_price = entry["entry_price"]
            if position_side == "LONG":
                pnl_pct = (price - entry_price) / entry_price * 100.0
            else:
                pnl_pct = (entry_price - price) / entry_price * 100.0
            scenarios.append({
                "source": "paper",
                "symbol": symbol,
                "side": position_side,
                "entry_time": entry["entry_time"],
                "exit_time": event_time,
                "entry_price": round(entry_price, 6),
                "exit_price": round(price, 6),
                "notional_usd": round(entry["notional"], 2),
                "pnl_pct": round(pnl_pct, 4),
            })
            del open_pos[key]

    return scenarios


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retorno realizado y escenarios de entrada/salida (paper) para comparar con backtest"
    )
    parser.add_argument(
        "--execution-log",
        default="artifacts/quant_model/execution_log.jsonl",
        help="Ruta al execution_log.jsonl (salida de quant_execute_orders.py --mode paper)",
    )
    parser.add_argument(
        "--backtest-net-percent",
        type=float,
        default=None,
        help="Opcional: retorno neto %% del backtest para comparar (ej. -0.5)",
    )
    parser.add_argument(
        "--scenarios",
        action="store_true",
        help="Imprimir tabla de escenarios (entrada/salida por trade)",
    )
    parser.add_argument(
        "--out-scenarios",
        metavar="FILE",
        default=None,
        help="Escribir escenarios paper en JSONL para comparar después",
    )
    parser.add_argument(
        "--backtest-scenarios",
        metavar="FILE",
        default=None,
        help="Archivo backtest_scenarios.jsonl (generado por examples/backtest_scenarios.py)",
    )
    args = parser.parse_args()

    path = Path(args.execution_log)
    if not path.exists():
        print(f"No existe el archivo: {path}")
        print("Genera antes el log con: python examples/quant_execute_orders.py --mode paper --paper-fill-source file")
        return 1

    rows = _read_execution_log(path)
    executed = [r for r in rows if r.get("status") == "EXECUTED" and r.get("price_used")]
    if not executed:
        print("No hay filas EXECUTED con price_used en el log.")
        return 1

    scenarios = _build_paper_scenarios(executed)
    if not scenarios:
        print("No se encontraron trades cerrados (OPEN/REBALANCE seguidos de CLOSE) en el log.")
        print("Ejecutados total:", len(executed))
        return 0

    total_notional = sum(s["notional_usd"] for s in scenarios)
    notional_weighted_pnl = (
        sum(s["pnl_pct"] * s["notional_usd"] for s in scenarios) / total_notional if total_notional else 0.0
    )
    simple_avg_pnl = sum(s["pnl_pct"] for s in scenarios) / len(scenarios)

    print("=== Retorno realizado (simulación paper) ===")
    print(f"  Archivo: {path}")
    print(f"  Trades cerrados: {len(scenarios)}")
    print(f"  Retorno realizado % (ponderado por notional): {notional_weighted_pnl:+.3f}%")
    print(f"  Retorno realizado % (media simple por trade):   {simple_avg_pnl:+.3f}%")

    if args.scenarios:
        print()
        print("=== Escenarios de entrada/salida (paper) ===")
        print(f"{'Symbol':<12} {'Side':<6} {'Entry time':<24} {'Exit time':<24} {'Entry $':>10} {'Exit $':>10} {'PnL %':>8}")
        print("-" * 100)
        for s in scenarios:
            print(
                f"{s['symbol']:<12} {s['side']:<6} {s['entry_time']:<24} {s['exit_time']:<24} "
                f"{s['entry_price']:>10.2f} {s['exit_price']:>10.2f} {s['pnl_pct']:>+7.3f}%"
            )

    if args.out_scenarios:
        out_path = Path(args.out_scenarios)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            for s in scenarios:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        print()
        print(f"Escenarios escritos en: {out_path}")

    if args.backtest_scenarios:
        bt_path = Path(args.backtest_scenarios)
        if bt_path.exists():
            bt_scenarios = []
            for line in bt_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    bt_scenarios.append(json.loads(line))
            print()
            print("=== Comparación con backtest (periodos con asignación) ===")
            print(f"  Backtest periodos: {len(bt_scenarios)}")
            by_sym: dict[str, list[float]] = {}
            for b in bt_scenarios:
                sym = b.get("symbol", "")
                by_sym.setdefault(sym, []).append(float(b.get("period_return_pct", 0)))
            print("  Retorno por símbolo (backtest, media periodos):")
            for sym in sorted(by_sym.keys()):
                rets = by_sym[sym]
                avg = sum(rets) / len(rets) if rets else 0
                print(f"    {sym}: {avg:+.3f}% (periodos: {len(rets)})")
            if args.scenarios:
                print("  (Compara con la tabla de escenarios paper arriba: mismos símbolos, fechas similares)")

    if args.backtest_net_percent is not None:
        diff = notional_weighted_pnl - args.backtest_net_percent
        print()
        print("=== Comparación con backtest (net) ===")
        print(f"  Backtest net % (que pasaste): {args.backtest_net_percent:+.3f}%")
        print(f"  Diferencia (paper - backtest): {diff:+.3f}%")
        if abs(diff) > 1.0:
            print("  Nota: Si la diferencia es grande, puede ser por órdenes SKIP (límites, price_diff),")
            print("         por no usar el mismo período, o por distinta lógica de asignación.")

    print()
    print("Compara este retorno con el 'Net' de: make ai-backtest")
    print("Para generar escenarios del backtest: python examples/backtest_scenarios.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
