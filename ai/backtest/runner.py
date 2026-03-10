"""Backtest: compute_allocations + RiskEngine (mismo flujo que live)."""

from __future__ import annotations

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
    use_risk_engine: bool = True,
    risk_engine_params: dict | None = None,
):
    """
    Backtest: compute_allocations (probado) + RiskEngine.
    use_risk_engine=True: aplica RiskEngine al sizing (mismo que live).
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
            long_threshold=prob_threshold,
            short_threshold=-prob_threshold,
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
        use_risk_engine=use_risk_engine,
        risk_engine_params=risk_engine_params,
    )

    log_run(
        run_type="backtest",
        config={"horizon": horizon, "symbols": symbols, "prob_threshold": prob_threshold, "use_risk_engine": use_risk_engine},
        metrics={
            "trades": result.trades_count,
            "total_return_percent": result.total_return_percent,
            "net_return_percent": result.net_return_percent,
            "total_fees_percent": result.total_fees_percent,
            "total_slippage_percent": result.total_slippage_percent,
            "max_drawdown_percent": result.max_drawdown_percent,
            "sharpe_ratio": result.sharpe_ratio,
            "win_rate_percent": result.win_rate_percent,
            "by_symbol": result.by_symbol,
        },
        data_rows=rows,
    )
    return result
