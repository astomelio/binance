"""Backtest: vectores de asignación (0=nada, 0.2=20% long, -0.2=20% short)."""

from __future__ import annotations

from trading_lib import FeeModel

from ai.allocation.backtest import run_allocation_backtest
from ai.data.loader import load_decision_features
from ai.registry import log_run


def run_backtest(
    horizon: str = "4h",
    symbols: list[str] | None = None,
    fee_percent: float = 0.04,
    slippage_percent: float = 0.0,
    min_quote_volume_24h: float | None = None,
    prob_threshold: float = 0.55,
):
    """
    Backtest con vectores de asignación.
    En cada event_time: allocation[symbol] = 0 (nada), 0.2 (20% long), -0.2 (20% short).
    Retorno = sum(alloc * fwd_return). Fees y slippage sobre cambios de posición.
    min_quote_volume_24h: excluir símbolos con volumen (USD) por debajo de este umbral.
    """
    rows = load_decision_features(
        horizon=horizon,
        symbols=symbols,
        label_not_null=True,
    )
    if not rows:
        raise ValueError("No decision_features in DuckDB. Run warehouse-load first.")

    from ai.allocation.strategies import compute_allocations

    def _compute(features: dict, _ts: str):
        return compute_allocations(
            features,
            prob_threshold=prob_threshold,
            min_allocation=0.1,
            max_allocation=0.4,
            max_exposure=1.0,
        )

    result = run_allocation_backtest(
        rows,
        horizon=horizon,
        fee_percent=fee_percent,
        slippage_percent=slippage_percent,
        min_quote_volume_24h=min_quote_volume_24h,
        compute_fn=_compute,
        symbols=symbols,
    )

    log_run(
        run_type="backtest",
        config={"horizon": horizon, "symbols": symbols, "prob_threshold": prob_threshold},
        metrics={
            "trades": result.trades_count,
            "total_return_percent": result.total_return_percent,
            "net_return_percent": result.net_return_percent,
            "total_fees_percent": result.total_fees_percent,
            "total_slippage_percent": result.total_slippage_percent,
            "by_symbol": result.by_symbol,
        },
        data_rows=rows,
    )
    return result
