from __future__ import annotations

from trading_lib.planner import StrategySpec, compute_model_allocations


def _row(symbol: str, score: float, fed_window: str = "NORMAL", oi: float = 1_000_000, qv: float = 500_000_000):
    return {
        "symbol": symbol,
        "alpha_score": score,
        "fed_window": fed_window,
        "open_interest": oi,
        "quote_volume_24h": qv,
    }


def test_multicurrency_allocations_are_proportional_and_bounded():
    spec = StrategySpec(
        name="test",
        long_score_threshold=0.25,
        short_score_threshold=-0.25,
        min_open_interest=0,
        min_quote_volume_24h=0,
        allow_trading_in_event_window=False,
    )
    rows = [
        _row("BTCUSDT", 0.8),
        _row("ETHUSDT", 0.4),
        _row("SOLUSDT", -0.6),
    ]

    allocs = compute_model_allocations(rows, spec, max_gross_exposure_pct=1.0, max_symbol_pct=0.6)
    assert len(allocs) == 3

    by_symbol = {a.symbol: a for a in allocs}
    assert by_symbol["BTCUSDT"].side == "LONG"
    assert by_symbol["ETHUSDT"].side == "LONG"
    assert by_symbol["SOLUSDT"].side == "SHORT"

    total = sum(a.allocation_pct for a in allocs)
    assert total <= 1.0 + 1e-9
    assert all(a.allocation_pct <= 0.6 + 1e-9 for a in allocs)
    assert by_symbol["BTCUSDT"].allocation_pct > by_symbol["ETHUSDT"].allocation_pct


def test_event_window_blocks_entries_when_disabled():
    spec = StrategySpec(
        name="test",
        long_score_threshold=0.2,
        short_score_threshold=-0.2,
        allow_trading_in_event_window=False,
        min_open_interest=0,
        min_quote_volume_24h=0,
    )
    rows = [_row("BTCUSDT", 0.9, fed_window="PRE_EVENT"), _row("ETHUSDT", -0.9, fed_window="POST_EVENT")]
    allocs = compute_model_allocations(rows, spec, max_gross_exposure_pct=1.0, max_symbol_pct=0.5)
    assert allocs == []


def test_liquidity_filters_are_applied():
    spec = StrategySpec(
        name="test",
        long_score_threshold=0.2,
        short_score_threshold=-0.2,
        min_open_interest=100_000,
        min_quote_volume_24h=200_000_000,
        allow_trading_in_event_window=True,
    )
    rows = [
        _row("BTCUSDT", 0.5, oi=90_000, qv=500_000_000),  # low OI
        _row("ETHUSDT", 0.6, oi=200_000, qv=100_000_000),  # low volume
        _row("BNBUSDT", -0.7, oi=300_000, qv=400_000_000),  # valid
    ]
    allocs = compute_model_allocations(rows, spec, max_gross_exposure_pct=1.0, max_symbol_pct=0.7)
    assert len(allocs) == 1
    assert allocs[0].symbol == "BNBUSDT"
    assert allocs[0].side == "SHORT"

