#!/usr/bin/env python3
"""
Compara backtest: sin realismo vs con slippage vs con slippage + filtro liquidez.
Si no hay DuckDB o decision_features, usa datos sintéticos para mostrar el efecto.
"""
from __future__ import annotations

import sys


def _synthetic_rows():
    """Filas sintéticas: 2 timestamps, 3 símbolos (uno con poco volumen)."""
    return [
        {"event_time": "2025-01-01T00:00:00", "symbol": "BTCUSDT", "alpha_score": 0.6, "fwd_return_4h": 0.5, "quote_volume_24h": 2e9},
        {"event_time": "2025-01-01T00:00:00", "symbol": "ETHUSDT", "alpha_score": -0.5, "fwd_return_4h": -0.3, "quote_volume_24h": 1e9},
        {"event_time": "2025-01-01T00:00:00", "symbol": "LOWVOL", "alpha_score": 0.8, "fwd_return_4h": 1.0, "quote_volume_24h": 500_000},
        {"event_time": "2025-01-01T04:00:00", "symbol": "BTCUSDT", "alpha_score": 0.0, "fwd_return_4h": 0.0, "quote_volume_24h": 2e9},
        {"event_time": "2025-01-01T04:00:00", "symbol": "ETHUSDT", "alpha_score": 0.0, "fwd_return_4h": 0.0, "quote_volume_24h": 1e9},
        {"event_time": "2025-01-01T04:00:00", "symbol": "LOWVOL", "alpha_score": 0.0, "fwd_return_4h": 0.0, "quote_volume_24h": 500_000},
    ]


def main():
    import argparse
    p = argparse.ArgumentParser(description="Compara backtest: sin realismo vs slippage vs liquidez")
    p.add_argument("--synthetic", action="store_true", help="Usar solo datos sintéticos (rápido, sin DuckDB)")
    args = p.parse_args()

    from ai.allocation.backtest import run_allocation_backtest
    from ai.allocation.strategies import compute_allocations

    fee = 0.04
    horizon = "4h"
    compute = lambda f, _: compute_allocations(f, prob_threshold=0.55, min_allocation=0.1, max_allocation=0.4, max_exposure=1.0)

    if args.synthetic:
        rows = _synthetic_rows()
        print("(Datos sintéticos)\n")
    else:
        try:
            from ai.data.loader import load_decision_features
            rows = load_decision_features(horizon=horizon, label_not_null=True)
            if not rows:
                rows = _synthetic_rows()
                print("(Sin datos en DuckDB; usando datos sintéticos)\n")
            else:
                print(f"(DuckDB: {len(rows)} filas)\n")
        except Exception as e:
            rows = _synthetic_rows()
            print(f"(DuckDB no disponible: {e}; usando datos sintéticos)\n")

    # 1) Sin realismo
    r0 = run_allocation_backtest(rows, horizon=horizon, fee_percent=fee, compute_fn=compute)
    # 2) Con slippage 0.02%
    r1 = run_allocation_backtest(rows, horizon=horizon, fee_percent=fee, slippage_percent=0.02, compute_fn=compute)
    # 3) Slippage + solo pares con >= 1M USD volumen 24h
    r2 = run_allocation_backtest(rows, horizon=horizon, fee_percent=fee, slippage_percent=0.02, min_quote_volume_24h=1_000_000, compute_fn=compute)

    print("Backtest 4h | Return % | Net % | Fees % | Slippage % | Trades")
    print("-" * 65)
    print(f"Sin realismo     | {r0.total_return_percent:+.3f}  | {r0.net_return_percent:+.3f} | {r0.total_fees_percent:.3f}  | {r0.total_slippage_percent:.3f}     | {r0.trades_count}")
    print(f"Slippage 0.02%  | {r1.total_return_percent:+.3f}  | {r1.net_return_percent:+.3f} | {r1.total_fees_percent:.3f}  | {r1.total_slippage_percent:.3f}     | {r1.trades_count}")
    print(f"+ liq. >= 1M USD| {r2.total_return_percent:+.3f}  | {r2.net_return_percent:+.3f} | {r2.total_fees_percent:.3f}  | {r2.total_slippage_percent:.3f}     | {r2.trades_count}")
    print()
    print("Slippage 0.02% = 0,02% del notional por cada cambio de posición.")
    print("min_quote_volume_24h=1e6 = se excluyen pares con volumen 24h < 1M USD.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
