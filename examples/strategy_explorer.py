#!/usr/bin/env python3
"""
Explorador de estrategias (script legacy). Para uso automático/agente: ai.explorer.
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from ai.allocation.backtest import run_allocation_backtest
from ai.allocation.constraints import normalize_exposure
from ai.allocation.strategies import compute_allocations
from ai.allocation.types import AllocationVector
from ai.data.loader import load_decision_features


def _rank_volatile_symbols(
    rows: list[dict],
    top_n: int = 10,
    vol_metric: str = "momentum_3",
) -> list[str]:
    """
    Ordena símbolos por volatilidad (mean abs de momentum o price_change).
    vol_metric: momentum_3, momentum_12, price_change_percent_24h
    """
    by_sym: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        v = r.get(vol_metric)
        if v is not None:
            try:
                by_sym[r["symbol"]].append(abs(float(v)))
            except (TypeError, ValueError):
                pass
    # mean abs = proxy de volatilidad
    ranked = sorted(
        by_sym.items(),
        key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 0,
        reverse=True,
    )
    return [s for s, _ in ranked[:top_n]]


def _alloc_mean_reversion(
    features_by_symbol: dict[str, dict],
    volatile_symbols: list[str] | None,
    oversold: float = -2.0,
    overbought: float = 2.0,
    allocation_size: float = 0.2,
    max_exposure: float = 1.0,
    momentum_key: str = "momentum_3",
) -> AllocationVector:
    """
    Mean reversion: oversold (momentum < umbral) -> LONG, overbought (momentum > umbral) -> SHORT.
    Solo opera en símbolos volátiles si se especifica.
    """
    alloc: AllocationVector = {}
    for symbol, feats in features_by_symbol.items():
        if volatile_symbols and symbol not in volatile_symbols:
            alloc[symbol] = 0.0
            continue
        m = float(feats.get(momentum_key) or 0)
        if m <= oversold:
            # Oversold: expect bounce -> long. Más extremo = más allocation
            strength = min(1.0, abs(m - oversold) / abs(oversold))
            alloc[symbol] = allocation_size * (0.5 + 0.5 * strength)
        elif m >= overbought:
            # Overbought: expect pullback -> short
            strength = min(1.0, abs(m - overbought) / overbought)
            alloc[symbol] = -allocation_size * (0.5 + 0.5 * strength)
        else:
            alloc[symbol] = 0.0
    return normalize_exposure(alloc, max_exposure)


def _alloc_from_alpha_signal(
    features_by_symbol: dict[str, dict],
    allocation_size: float = 0.2,
    max_exposure: float = 1.0,
) -> AllocationVector:
    """
    Estrategia heurística: alpha_signal = LONG | SHORT | NO_TRADE.
    LONG -> +allocation_size, SHORT -> -allocation_size.
    """
    alloc: AllocationVector = {}
    for symbol, feats in features_by_symbol.items():
        signal = (feats.get("alpha_signal") or "NO_TRADE").strip().upper()
        if signal == "LONG":
            alloc[symbol] = allocation_size
        elif signal == "SHORT":
            alloc[symbol] = -allocation_size
        else:
            alloc[symbol] = 0.0
    return normalize_exposure(alloc, max_exposure)


def run_grid(
    rows: list[dict],
    horizons: list[str] = ("1h", "4h", "24h"),
    prob_thresholds: list[float] = (0.50, 0.52, 0.55, 0.58),
    fee_percent: float = 0.04,
) -> list[dict]:
    """Grid search: horizon x prob_threshold para alpha_score."""
    results = []
    for h in horizons:
        for pt in prob_thresholds:
            def _compute(feats: dict, _ts: str):
                return compute_allocations(
                    feats,
                    prob_threshold=pt,
                    min_allocation=0.1,
                    max_allocation=0.4,
                    max_exposure=1.0,
                )
            r = run_allocation_backtest(
                rows,
                horizon=h,
                fee_percent=fee_percent,
                compute_fn=_compute,
            )
            results.append({
                "horizon": h,
                "prob_threshold": pt,
                "strategy": "alpha_score",
                "net_return": r.net_return_percent,
                "total_return": r.total_return_percent,
                "fees": r.total_fees_percent,
                "trades": r.trades_count,
            })
    return results


def main():
    p = argparse.ArgumentParser(description="Explorador de estrategias 1h")
    p.add_argument(
        "--strategy",
        choices=["alpha_score", "heuristic", "mean_reversion", "both", "all"],
        default="both",
        help="all = alpha_score + heuristic + mean_reversion",
    )
    p.add_argument("--horizon", default="4h", choices=["1h", "4h", "24h"])
    p.add_argument("--fee-percent", type=float, default=0.04)
    p.add_argument("--symbols", nargs="*", help="Filtrar símbolos")
    p.add_argument("--grid", action="store_true", help="Grid search alpha_score (horizon x threshold)")
    p.add_argument("--grid-mr", action="store_true", help="Grid search mean_reversion (oversold x overbought)")
    # Mean reversion
    p.add_argument("--top-volatile", type=int, default=0, help="Solo operar top N más volátiles (0= todos)")
    p.add_argument("--oversold", type=float, default=-2.0, help="momentum < oversold -> LONG")
    p.add_argument("--overbought", type=float, default=2.0, help="momentum > overbought -> SHORT")
    p.add_argument("--vol-metric", default="momentum_3", choices=["momentum_3", "momentum_12", "price_change_percent_24h"])
    args = p.parse_args()

    rows = load_decision_features(
        horizon=args.horizon,
        symbols=args.symbols or None,
        label_not_null=True,
    )
    if not rows:
        print("❌ No decision_features. Ejecuta: make warehouse-load")
        return 1

    # Resumen de datos
    times = sorted(set(r["event_time"] for r in rows))
    symbols = sorted(set(r["symbol"] for r in rows))
    print(f"📊 Datos: {len(rows)} filas | {len(symbols)} símbolos | {len(times)} event_times")
    print(f"   Rango: {times[0][:10]} ... {times[-1][:10]}")
    print()

    if args.grid:
        print("🔍 Grid search (alpha_score): horizon x prob_threshold")
        print("-" * 70)
        res = run_grid(rows, fee_percent=args.fee_percent)
        # Ordenar por net_return
        res.sort(key=lambda x: -x["net_return"])
        for r in res:
            print(f"  {r['horizon']:>4} | threshold={r['prob_threshold']:.2f} | "
                  f"net={r['net_return']:+.2f}% | trades={r['trades']:>5}")
        best = res[0]
        print()
        print(f"✅ Mejor: {best['horizon']} threshold={best['prob_threshold']} -> net={best['net_return']:+.2f}%")
        return 0

    if args.grid_mr:
        print("🔍 Grid search (mean_reversion): oversold x overbought")
        print("-" * 70)
        thresholds = [(-1.5, 1.5), (-2.0, 2.0), (-2.5, 2.5), (-3.0, 3.0), (-1.0, 1.0)]
        volatile = _rank_volatile_symbols(rows, top_n=args.top_volatile or 10, vol_metric=args.vol_metric) if args.top_volatile else None
        if not volatile and args.top_volatile:
            volatile = _rank_volatile_symbols(rows, top_n=10, vol_metric=args.vol_metric)
        res = []
        for os_val, ob_val in thresholds:
            def _make_mr(o=os_val, b=ob_val):
                def fn(feats, _ts):
                    return _alloc_mean_reversion(feats, volatile, oversold=o, overbought=b, momentum_key=args.vol_metric)
                return fn
            r = run_allocation_backtest(rows, horizon=args.horizon, fee_percent=args.fee_percent, compute_fn=_make_mr(), symbols=args.symbols)
            res.append({"oversold": os_val, "overbought": ob_val, "net": r.net_return_percent, "trades": r.trades_count})
        res.sort(key=lambda x: -x["net"])
        for r in res:
            print(f"  oversold={r['oversold']:+.1f} overbought={r['overbought']:+.1f} | net={r['net']:+.2f}% | trades={r['trades']}")
        print(f"\n✅ Mejor: oversold={res[0]['oversold']} overbought={res[0]['overbought']} -> net={res[0]['net']:+.2f}%")
        return 0

    # Backtest por estrategia
    print(f"📈 Backtest horizon={args.horizon} fee={args.fee_percent}%")
    print("-" * 50)

    if args.strategy in ("alpha_score", "both", "all"):
        def _alpha_score(feats: dict, _ts: str):
            return compute_allocations(
                feats,
                prob_threshold=0.55,
                min_allocation=0.1,
                max_allocation=0.4,
                max_exposure=1.0,
            )
        r1 = run_allocation_backtest(
            rows,
            horizon=args.horizon,
            fee_percent=args.fee_percent,
            compute_fn=_alpha_score,
            symbols=args.symbols,
        )
        print(f"  alpha_score (composite): net={r1.net_return_percent:+.2f}% | "
              f"trades={r1.trades_count} | fees={r1.total_fees_percent:.2f}%")

    if args.strategy in ("heuristic", "both", "all"):
        def _heuristic(feats: dict, _ts: str):
            return _alloc_from_alpha_signal(feats, allocation_size=0.2, max_exposure=1.0)
        r2 = run_allocation_backtest(
            rows,
            horizon=args.horizon,
            fee_percent=args.fee_percent,
            compute_fn=_heuristic,
            symbols=args.symbols,
        )
        print(f"  alpha_signal (heurística): net={r2.net_return_percent:+.2f}% | "
              f"trades={r2.trades_count} | fees={r2.total_fees_percent:.2f}%")

    if args.strategy in ("mean_reversion", "all"):
        volatile = (
            _rank_volatile_symbols(rows, top_n=args.top_volatile, vol_metric=args.vol_metric)
            if args.top_volatile
            else None
        )
        if volatile:
            print(f"   Pares volátiles (top {args.top_volatile}): {', '.join(volatile)}")

        def _mr(feats: dict, _ts: str):
            return _alloc_mean_reversion(
                feats,
                volatile_symbols=volatile,
                oversold=args.oversold,
                overbought=args.overbought,
                momentum_key=args.vol_metric,
            )
        r3 = run_allocation_backtest(
            rows,
            horizon=args.horizon,
            fee_percent=args.fee_percent,
            compute_fn=_mr,
            symbols=args.symbols,
        )
        print(f"  mean_reversion (oversold<{args.oversold} overbought>{args.overbought}): "
              f"net={r3.net_return_percent:+.2f}% | trades={r3.trades_count} | fees={r3.total_fees_percent:.2f}%")

    print()
    print("Siguiente: python examples/strategy_explorer.py --strategy mean_reversion --top-volatile 10")
    print("          python examples/strategy_explorer.py --strategy all  # comparar las 3")
    print("          make ai-train   # entrenar modelo + calibration")
    return 0


if __name__ == "__main__":
    exit(main())
