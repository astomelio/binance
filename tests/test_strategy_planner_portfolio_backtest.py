from __future__ import annotations

from trading_lib import FeeModel, StrategySpec, evaluate_strategy_walk_forward


def _row(ts: str, symbol: str, price: float, score: float) -> dict:
    return {
        "event_time": ts,
        "symbol": symbol,
        "futures_last_price": price,
        "alpha_score": score,
        "fed_window": "NORMAL",
        "open_interest": 1_000_000,
        "quote_volume_24h": 1_000_000_000,
    }


def test_portfolio_backtest_uses_weighted_multicurrency_allocations():
    spec = StrategySpec(
        name="portfolio_test",
        long_score_threshold=0.5,
        short_score_threshold=-0.5,
        min_open_interest=0.0,
        min_quote_volume_24h=0.0,
        allow_trading_in_event_window=False,
        max_gross_exposure_pct=1.0,
        max_symbol_pct=0.8,
    )

    rows = [
        _row("2026-02-10T00:00:00+00:00", "BTCUSDT", 100.0, 1.0),
        _row("2026-02-10T00:00:00+00:00", "ETHUSDT", 100.0, 0.5),
        _row("2026-02-10T01:00:00+00:00", "BTCUSDT", 110.0, 0.0),
        _row("2026-02-10T01:00:00+00:00", "ETHUSDT", 90.0, 0.0),
    ]

    result, folds = evaluate_strategy_walk_forward(rows=rows, spec=spec, fee_model=FeeModel(), train_days=30)

    assert folds == []
    assert result.trades == 2
    # Weighted portfolio return should be positive here:
    # BTC strong gain outweighs ETH loss after allocation and fees.
    assert result.net_return_percent > 0
    assert result.turnover_percent > 0

