from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

try:
    from trading_lib.quant.multi_timeframe import enrich_with_multi_timeframe
except (ImportError, AttributeError):
    try:
        from .multi_timeframe import enrich_with_multi_timeframe
    except ImportError:
        enrich_with_multi_timeframe = None


@dataclass
class LabeledRow:
    event_time: str
    symbol: str
    features: Dict[str, float]
    fwd_return_1h: float
    fwd_return_4h: float
    fwd_return_24h: float


def _safe_float(row: Dict, key: str) -> float:
    return float(row.get(key, 0) or 0)


def build_labeled_rows(
    decision_rows: List[Dict],
    rows_4h: List[Dict] | None = None,
    rows_1d: List[Dict] | None = None,
) -> List[LabeledRow]:
    """
    Build labeled rows with optional multi-timeframe enrichment.
    If rows_4h and rows_1d are provided, enriches 1h data with 4h and 1d features.
    """
    # Enrich with multi-timeframe if available
    if enrich_with_multi_timeframe and (rows_4h is not None or rows_1d is not None):
        decision_rows = enrich_with_multi_timeframe(
            decision_rows,
            rows_4h or [],
            rows_1d or [],
        )
    
    by_symbol: Dict[str, List[Dict]] = {}
    for row in decision_rows:
        symbol = row.get("symbol")
        if not symbol or not row.get("event_time"):
            continue
        by_symbol.setdefault(symbol, []).append(row)

    out: List[LabeledRow] = []
    feature_keys = [
        "alpha_microstructure_score",
        "momentum_score",
        "basis_bps",
        "funding_rate_8h",
        "long_short_account_ratio",
        "buy_sell_ratio",
        "fear_greed_value",
        "session_overlap_score",
        "liquidity_event_score",
        "cross_exchange_spread_bps",
        "cross_exchange_mean_diff_bps",
        "cross_exchange_bid_ask_bps_mean",
        "bybit_okx_delta_bps",
        "cross_exchange_score",
        "dex_cex_basis_bps",
        "dex_liquidity_usd",
        "dex_volume_24h_usd",
        "dex_txn_imbalance_24h",
        "dex_alpha_score",
        # Microstructure features (Sprint 1)
        "spread_bps",
        "depth_imbalance_score",
        "microprice",
        "depth_slope_proxy",
        "order_flow_imbalance",
        "spread_momentum_bps",
        # Multi-timeframe features (4h and 1d integrated)
        "tf4h_alpha_score",
        "tf4h_momentum_score",
        "tf4h_basis_bps",
        "tf4h_funding_rate_8h",
        "tf4h_liquidity_event_score",
        "tf1d_alpha_score",
        "tf1d_momentum_score",
        "tf1d_basis_bps",
        "tf1d_funding_rate_8h",
    ]
    for symbol, rows in by_symbol.items():
        rows.sort(key=lambda x: x["event_time"])
        closes = [_safe_float(r, "futures_last_price") for r in rows]
        for i, row in enumerate(rows):
            px = closes[i]
            if px <= 0:
                continue

            def fwd(steps: int) -> float:
                j = i + steps
                if j >= len(closes):
                    return 0.0
                nxt = closes[j]
                if nxt <= 0:
                    return 0.0
                return ((nxt - px) / px) * 100.0

            feats = {k: _safe_float(row, k) for k in feature_keys}
            out.append(
                LabeledRow(
                    event_time=row["event_time"],
                    symbol=symbol,
                    features=feats,
                    fwd_return_1h=fwd(1),
                    fwd_return_4h=fwd(4),
                    fwd_return_24h=fwd(24),
                )
            )
    out.sort(key=lambda x: x.event_time)
    return out

