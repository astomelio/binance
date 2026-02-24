from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Tuple


def _parse_iso_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            dt = datetime.fromisoformat(f"{value}T00:00:00+00:00")
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _fed_window_label(event_time: str, next_fed_decision_date: str) -> str:
    now = _parse_iso_date(event_time)
    fed_dt = _parse_iso_date(next_fed_decision_date)
    if not now or not fed_dt:
        return "UNKNOWN"
    delta_h = (fed_dt - now).total_seconds() / 3600.0
    if -2 <= delta_h <= 24:
        return "PRE_EVENT"
    if -24 <= delta_h < -2:
        return "POST_EVENT"
    return "NORMAL"


def _trade_bias(
    basis_bps: float,
    funding_rate_8h: float,
    open_interest: float,
    price_change_percent_24h: float,
    fed_window: str,
) -> str:
    # During FED event windows we prioritize risk control over prediction.
    if fed_window in {"PRE_EVENT", "POST_EVENT"}:
        return "NO_TRADE"

    # Contrarian/flow blended heuristics:
    # - crowded longs -> short bias
    # - deeply negative basis + negative funding with stable OI -> long reversion bias
    if basis_bps > 4 and funding_rate_8h > 0.00005 and price_change_percent_24h > 0.8:
        return "SHORT"
    if basis_bps < -4 and funding_rate_8h < -0.00005 and open_interest > 0 and price_change_percent_24h < -0.4:
        return "LONG"
    return "NO_TRADE"


def _alpha_score(basis_bps: float, funding_rate_8h: float, price_change_percent_24h: float) -> float:
    # score > 0 favors long-reversion; score < 0 favors short-reversion
    # normalized using practical ranges for intraday futures conditions.
    basis_component = max(min((-basis_bps) / 10.0, 1.0), -1.0)
    funding_component = max(min((-funding_rate_8h) / 0.0004, 1.0), -1.0)
    momentum_component = max(min((-price_change_percent_24h) / 4.0, 1.0), -1.0)
    return round((0.45 * basis_component) + (0.35 * funding_component) + (0.20 * momentum_component), 4)


def _pct_change_timed(
    series: List[Tuple[str, float]],
    steps_back: int,
    max_gap_hours: float = 6.0,
) -> float:
    """Momentum that validates temporal continuity.

    Returns 0.0 when the time gap between the reference point and the
    current observation exceeds *max_gap_hours*, preventing stale
    lookbacks from leaking into the score.
    """
    if len(series) <= steps_back:
        return 0.0
    ts_prev, prev = series[-(steps_back + 1)]
    ts_curr, curr = series[-1]
    if prev == 0:
        return 0.0
    dt_prev = _parse_iso_date(ts_prev)
    dt_curr = _parse_iso_date(ts_curr)
    if dt_prev and dt_curr:
        gap_h = abs((dt_curr - dt_prev).total_seconds()) / 3600.0
        if gap_h > max_gap_hours * steps_back:
            return 0.0
    return ((curr - prev) / prev) * 100.0


def _momentum_score(momentum_3: float, momentum_12: float) -> float:
    # normalized to keep score in [-1, 1] for planner thresholds.
    short_component = max(min(momentum_3 / 2.5, 1.0), -1.0)
    medium_component = max(min(momentum_12 / 5.0, 1.0), -1.0)
    return round((0.55 * short_component) + (0.45 * medium_component), 4)


def _session_band(event_time: str) -> str:
    dt = _parse_iso_date(event_time)
    if not dt:
        return "UNKNOWN"
    h = dt.hour
    # Practical UTC trading bands.
    if 0 <= h < 7:
        return "ASIA"
    if 7 <= h < 13:
        return "EUROPE"
    if 13 <= h < 21:
        return "US"
    return "OFF_HOURS"


def _session_overlap_score(session_band: str) -> float:
    # Higher activity expected during Europe/US overlap and US session.
    if session_band == "US":
        return 1.0
    if session_band == "EUROPE":
        return 0.6
    if session_band == "ASIA":
        return 0.35
    if session_band == "OFF_HOURS":
        return 0.15
    return 0.0


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _cross_exchange_signal(cross_exchange_mean_diff_bps: float, cross_exchange_spread_bps: float) -> float:
    # Positive when Binance is relatively cheaper vs peers and dislocation is moderate.
    mean_diff_component = _clamp(cross_exchange_mean_diff_bps / 8.0)
    spread_penalty = _clamp(cross_exchange_spread_bps / 25.0, 0.0, 1.0)
    return round(mean_diff_component * (1.0 - 0.4 * spread_penalty), 4)


def _dex_signal(dex_cex_basis_bps: float, dex_txn_imbalance_24h: float) -> float:
    basis_component = _clamp(dex_cex_basis_bps / 12.0)
    flow_component = _clamp(dex_txn_imbalance_24h)
    return round((0.7 * basis_component) + (0.3 * flow_component), 4)


def _liquidity_event_score(
    quote_volume_24h: float,
    open_interest: float,
    buy_sell_ratio: float,
    long_short_account_ratio: float,
    basis_bps: float,
) -> float:
    # Flow/positioning pressure proxy:
    # - elevated OI + very imbalanced taker flow can precede squeezes
    # - large basis adds carry/crowding context
    oi_component = _clamp(open_interest / 5_000_000.0)
    taker_imbalance = _clamp((buy_sell_ratio - 1.0) / 0.35)
    crowding_component = _clamp((long_short_account_ratio - 1.0) / 1.2)
    basis_component = _clamp(abs(basis_bps) / 15.0)
    vol_component = _clamp(quote_volume_24h / 20_000_000_000.0)
    return round(
        0.30 * oi_component
        + 0.25 * abs(taker_imbalance)
        + 0.20 * abs(crowding_component)
        + 0.15 * basis_component
        + 0.10 * vol_component,
        4,
    )


def _liquidity_event_label(
    buy_sell_ratio: float,
    long_short_account_ratio: float,
    basis_bps: float,
    liquidity_event_score: float,
) -> str:
    if liquidity_event_score < 0.35:
        return "NONE"
    if buy_sell_ratio > 1.15 and long_short_account_ratio > 1.2 and basis_bps > 2:
        return "LONG_CROWDING"
    if buy_sell_ratio < 0.85 and long_short_account_ratio < 0.9 and basis_bps < -2:
        return "SHORT_CROWDING"
    return "BALANCED_PRESSURE"


def build_decision_features(
    market_rows: List[Dict],
    derivatives_rows: List[Dict],
    derivatives_flow_rows: List[Dict],
    cross_exchange_rows: List[Dict],
    dex_rows: List[Dict],
    global_rows: List[Dict],
    fear_greed_rows: List[Dict],
    macro_rows: List[Dict],
    fed_rows: List[Dict],
) -> List[Dict]:
    if not market_rows:
        return []

    latest_global = global_rows[-1] if global_rows else {}
    latest_macro = macro_rows[-1] if macro_rows else {}
    latest_fed = fed_rows[-1] if fed_rows else {}
    latest_fear_greed = fear_greed_rows[-1] if fear_greed_rows else {}
    latest_derivatives_by_symbol = {}
    for row in derivatives_rows:
        latest_derivatives_by_symbol[row.get("symbol")] = row
    latest_flow_by_symbol = {}
    for row in derivatives_flow_rows:
        latest_flow_by_symbol[row.get("symbol")] = row
    latest_cross_exchange_by_symbol: Dict[str, List[Dict]] = {}
    for row in cross_exchange_rows:
        latest_cross_exchange_by_symbol.setdefault(str(row.get("symbol")), []).append(row)
    latest_dex_by_symbol = {}
    for row in dex_rows:
        latest_dex_by_symbol[str(row.get("symbol"))] = row

    price_history_by_symbol: Dict[str, List[Tuple[str, float]]] = {}
    out: List[Dict] = []
    for row in market_rows:
        symbol = row.get("symbol")
        spot = row.get("spot_last_price", 0.0)
        fut = row.get("futures_last_price", 0.0)
        et = row.get("event_time", "")
        if symbol not in price_history_by_symbol:
            price_history_by_symbol[symbol] = []
        price_history_by_symbol[symbol].append((et, fut))
        momentum_3 = _pct_change_timed(price_history_by_symbol[symbol], 3)
        momentum_12 = _pct_change_timed(price_history_by_symbol[symbol], 12)
        momentum_score = _momentum_score(momentum_3, momentum_12)
        session_band = _session_band(row.get("event_time", ""))
        session_overlap_score = _session_overlap_score(session_band)

        basis_bps = ((fut - spot) / spot) * 10000 if spot else 0.0
        derivatives = latest_derivatives_by_symbol.get(symbol, {})
        flow = latest_flow_by_symbol.get(symbol, {})
        cross_rows_symbol = latest_cross_exchange_by_symbol.get(str(symbol), [])
        peer_prices = [float(r.get("last_price", 0.0) or 0.0) for r in cross_rows_symbol if float(r.get("last_price", 0.0) or 0.0) > 0]
        peer_spreads = [float(r.get("spread_bps", 0.0) or 0.0) for r in cross_rows_symbol]
        cross_exchange_spread_bps = (((max(peer_prices) - min(peer_prices)) / fut) * 10000.0) if (peer_prices and fut > 0) else 0.0
        cross_exchange_mean_diff_bps = ((((sum(peer_prices) / len(peer_prices)) - fut) / fut) * 10000.0) if (peer_prices and fut > 0) else 0.0
        cross_exchange_bid_ask_bps_mean = (sum(peer_spreads) / len(peer_spreads)) if peer_spreads else 0.0
        bybit_price = 0.0
        okx_price = 0.0
        for ex_row in cross_rows_symbol:
            ex_name = str(ex_row.get("exchange", "")).lower()
            px = float(ex_row.get("last_price", 0.0) or 0.0)
            if ex_name == "bybit":
                bybit_price = px
            elif ex_name == "okx":
                okx_price = px
        bybit_okx_delta_bps = (((bybit_price - okx_price) / fut) * 10000.0) if (bybit_price > 0 and okx_price > 0 and fut > 0) else 0.0
        dex = latest_dex_by_symbol.get(str(symbol), {})
        dex_price_usd = float(dex.get("dex_price_usd", 0.0) or 0.0)
        dex_cex_basis_bps = (((dex_price_usd - spot) / spot) * 10000.0) if (dex_price_usd > 0 and spot > 0) else 0.0
        fed_window = _fed_window_label(
            row.get("event_time", ""),
            latest_fed.get("next_fed_decision_date", ""),
        )
        microstructure_score = _alpha_score(
            basis_bps=basis_bps,
            funding_rate_8h=derivatives.get("last_funding_rate", 0.0) or 0.0,
            price_change_percent_24h=derivatives.get("price_change_percent_24h", 0.0) or 0.0,
        )
        liquidity_event_score = _liquidity_event_score(
            quote_volume_24h=derivatives.get("quote_volume_24h", 0.0) or 0.0,
            open_interest=derivatives.get("open_interest", 0.0) or 0.0,
            buy_sell_ratio=flow.get("buy_sell_ratio", 1.0) or 1.0,
            long_short_account_ratio=flow.get("long_short_account_ratio", 1.0) or 1.0,
            basis_bps=basis_bps,
        )
        liquidity_event_label = _liquidity_event_label(
            buy_sell_ratio=flow.get("buy_sell_ratio", 1.0) or 1.0,
            long_short_account_ratio=flow.get("long_short_account_ratio", 1.0) or 1.0,
            basis_bps=basis_bps,
            liquidity_event_score=liquidity_event_score,
        )
        cross_exchange_score = _cross_exchange_signal(
            cross_exchange_mean_diff_bps=cross_exchange_mean_diff_bps,
            cross_exchange_spread_bps=cross_exchange_spread_bps,
        )
        dex_alpha_score = _dex_signal(
            dex_cex_basis_bps=dex_cex_basis_bps,
            dex_txn_imbalance_24h=float(dex.get("dex_txn_imbalance_24h", 0.0) or 0.0),
        )
        # Composite: reversion + momentum + market-driven signals.
        # session_overlap is time-deterministic (not alpha), kept at minimal weight.
        composite_alpha_score = round(
            (0.40 * microstructure_score)
            + (0.25 * momentum_score)
            + (0.03 * session_overlap_score)
            + (0.12 * liquidity_event_score)
            + (0.10 * cross_exchange_score)
            + (0.10 * dex_alpha_score),
            4,
        )

        out.append(
            {
                "event_time": row.get("event_time"),
                "symbol": symbol,
                "spot_last_price": spot,
                "futures_last_price": fut,
                "basis_bps": basis_bps,
                "spot_volume": row.get("spot_volume", 0.0),
                "futures_volume": row.get("futures_volume", 0.0),
                "funding_rate_8h": derivatives.get("last_funding_rate", 0.0),
                "open_interest": derivatives.get("open_interest", 0.0),
                "mark_price": derivatives.get("mark_price", 0.0),
                "index_price": derivatives.get("index_price", 0.0),
                "price_change_percent_24h": derivatives.get("price_change_percent_24h", 0.0),
                "quote_volume_24h": derivatives.get("quote_volume_24h", 0.0),
                "btc_dominance": latest_global.get("btc_dominance", 0.0),
                "total_market_cap_usd": latest_global.get("total_market_cap_usd", 0.0),
                "fear_greed_value": latest_fear_greed.get("fear_greed_value", 0.0),
                "fear_greed_classification": latest_fear_greed.get("fear_greed_classification", ""),
                "long_short_account_ratio": flow.get("long_short_account_ratio", 0.0),
                "buy_sell_ratio": flow.get("buy_sell_ratio", 0.0),
                "session_band": session_band,
                "session_overlap_score": session_overlap_score,
                "liquidity_event_score": liquidity_event_score,
                "liquidity_event_label": liquidity_event_label,
                "cross_exchange_spread_bps": cross_exchange_spread_bps,
                "cross_exchange_mean_diff_bps": cross_exchange_mean_diff_bps,
                "cross_exchange_bid_ask_bps_mean": cross_exchange_bid_ask_bps_mean,
                "bybit_okx_delta_bps": bybit_okx_delta_bps,
                "cross_exchange_score": cross_exchange_score,
                "dex_price_usd": dex_price_usd,
                "dex_cex_basis_bps": dex_cex_basis_bps,
                "dex_liquidity_usd": float(dex.get("dex_liquidity_usd", 0.0) or 0.0),
                "dex_volume_24h_usd": float(dex.get("dex_volume_24h_usd", 0.0) or 0.0),
                "dex_txn_imbalance_24h": float(dex.get("dex_txn_imbalance_24h", 0.0) or 0.0),
                "dex_alpha_score": dex_alpha_score,
                "fed_funds_rate": latest_macro.get("fed_funds_rate", 0.0),
                "next_fed_decision_date": latest_fed.get("next_fed_decision_date", ""),
                "fed_window": fed_window,
                "momentum_3": momentum_3,
                "momentum_12": momentum_12,
                "momentum_score": momentum_score,
                "alpha_microstructure_score": microstructure_score,
                "alpha_signal": _trade_bias(
                    basis_bps=basis_bps,
                    funding_rate_8h=derivatives.get("last_funding_rate", 0.0) or 0.0,
                    open_interest=derivatives.get("open_interest", 0.0) or 0.0,
                    price_change_percent_24h=derivatives.get("price_change_percent_24h", 0.0) or 0.0,
                    fed_window=fed_window,
                ),
                "alpha_score": composite_alpha_score,
            }
        )
    return out

