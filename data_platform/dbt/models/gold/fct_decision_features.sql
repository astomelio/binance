{{ config(materialized='table', alias='decision_features') }}

with earnings_dates as (
    select unnest([
        DATE '2023-01-15', DATE '2023-04-15', DATE '2023-07-15', DATE '2023-10-15',
        DATE '2024-01-15', DATE '2024-04-15', DATE '2024-07-15', DATE '2024-10-15',
        DATE '2025-01-15', DATE '2025-04-15', DATE '2025-07-15', DATE '2025-10-15',
        DATE '2026-01-15', DATE '2026-04-15', DATE '2026-07-15', DATE '2026-10-15'
    ]) as d
),
src as (
    select * from {{ ref('slv_decision_features') }}
),
with_microstructure as (
    select
        *,
        -- Microstructure features from cross-exchange bid/ask
        -- Spread (already calculated in silver, but we normalize it)
        cross_exchange_bid_ask_bps_mean as spread_bps,
        -- Depth imbalance proxy: use cross-exchange spread as liquidity proxy
        -- Higher spread = lower liquidity = higher imbalance risk
        case
            when cross_exchange_bid_ask_bps_mean > 0 then least(cross_exchange_bid_ask_bps_mean / 50.0, 1.0)
            else 0.0
        end as depth_imbalance_score,
        -- Microprice: weighted mid-price proxy using futures price and cross-exchange mean
        -- Note: cross_exchange_mean_diff_bps is already (peer_mean - futures) / futures * 10000
        -- So peer_mean = futures * (1 + cross_exchange_mean_diff_bps / 10000)
        case
            when futures_last_price > 0 and cross_exchange_mean_diff_bps is not null then
                (futures_last_price * 0.6 + futures_last_price * (1.0 + cross_exchange_mean_diff_bps / 10000.0) * 0.4)
            else futures_last_price
        end as microprice,
        -- Depth slope proxy: rate of change of spread (using rolling window)
        -- For now, use spread normalized by price as proxy
        case
            when futures_last_price > 0 and cross_exchange_bid_ask_bps_mean > 0 then
                cross_exchange_bid_ask_bps_mean / (futures_last_price / 10000.0)
            else 0.0
        end as depth_slope_proxy,
        -- Order flow imbalance: use buy_sell_ratio as proxy
        case
            when buy_sell_ratio > 0 then (buy_sell_ratio - 1.0) / 0.5
            else 0.0
        end as order_flow_imbalance
    from src
),
with_momentum as (
    select
        *,
        -- Momentum features (3 and 12 steps back, assuming 1h intervals)
        lag(futures_last_price, 3) over (partition by symbol order by event_time) as price_3h_ago,
        lag(futures_last_price, 12) over (partition by symbol order by event_time) as price_12h_ago,
        -- Mean reversion: rolling mean/std (24h window)
        avg(futures_last_price) over (partition by symbol order by event_time rows between 23 preceding and current row) as price_ma_24h,
        stddev(futures_last_price) over (partition by symbol order by event_time rows between 23 preceding and current row) as price_std_24h,
        -- Microstructure momentum: spread change
        lag(spread_bps, 1) over (partition by symbol order by event_time) as spread_bps_lag1,
        case
            when lag(futures_last_price, 3) over (partition by symbol order by event_time) = 0 then 0
            else ((futures_last_price - lag(futures_last_price, 3) over (partition by symbol order by event_time)) / lag(futures_last_price, 3) over (partition by symbol order by event_time)) * 100.0
        end as momentum_3,
        case
            when lag(futures_last_price, 12) over (partition by symbol order by event_time) = 0 then 0
            else ((futures_last_price - lag(futures_last_price, 12) over (partition by symbol order by event_time)) / lag(futures_last_price, 12) over (partition by symbol order by event_time)) * 100.0
        end as momentum_12,
        -- Spread momentum (change in spread)
        case
            when lag(spread_bps, 1) over (partition by symbol order by event_time) = 0 then 0
            else spread_bps - lag(spread_bps, 1) over (partition by symbol order by event_time)
        end as spread_momentum_bps,
        -- Mean reversion: z-score and deviation from MA
        case
            when stddev(futures_last_price) over (partition by symbol order by event_time rows between 23 preceding and current row) > 0 then
                (futures_last_price - avg(futures_last_price) over (partition by symbol order by event_time rows between 23 preceding and current row))
                / stddev(futures_last_price) over (partition by symbol order by event_time rows between 23 preceding and current row)
            else 0.0
        end as price_zscore_24h,
        case
            when avg(futures_last_price) over (partition by symbol order by event_time rows between 23 preceding and current row) > 0 then
                ((futures_last_price - avg(futures_last_price) over (partition by symbol order by event_time rows between 23 preceding and current row))
                 / avg(futures_last_price) over (partition by symbol order by event_time rows between 23 preceding and current row)) * 100.0
            else 0.0
        end as price_deviation_pct_24h
    from with_microstructure
),
with_forward_returns as (
    select
        *,
        -- Forward returns for labels (1h, 4h, 24h ahead)
        lead(futures_last_price, 1) over (partition by symbol order by event_time) as price_1h_fwd,
        lead(futures_last_price, 4) over (partition by symbol order by event_time) as price_4h_fwd,
        lead(futures_last_price, 24) over (partition by symbol order by event_time) as price_24h_fwd,
        case
            when futures_last_price = 0 then 0
            else ((lead(futures_last_price, 1) over (partition by symbol order by event_time) - futures_last_price) / futures_last_price) * 100.0
        end as fwd_return_1h,
        case
            when futures_last_price = 0 then 0
            else ((lead(futures_last_price, 4) over (partition by symbol order by event_time) - futures_last_price) / futures_last_price) * 100.0
        end as fwd_return_4h,
        case
            when futures_last_price = 0 then 0
            else ((lead(futures_last_price, 24) over (partition by symbol order by event_time) - futures_last_price) / futures_last_price) * 100.0
        end as fwd_return_24h
    from with_momentum
),
with_enriched_features as (
    select
        *,
        -- Momentum score (normalized composite)
        case
            when abs(momentum_3) > 2.5 then sign(momentum_3) * 1.0
            else momentum_3 / 2.5
        end * 0.55 + 
        case
            when abs(momentum_12) > 5.0 then sign(momentum_12) * 1.0
            else momentum_12 / 5.0
        end * 0.45 as momentum_score,
        -- Session band (UTC hour)
        case
            when date_part('hour', cast(event_time as timestamp)) >= 0 and date_part('hour', cast(event_time as timestamp)) < 7 then 'ASIA'
            when date_part('hour', cast(event_time as timestamp)) >= 7 and date_part('hour', cast(event_time as timestamp)) < 13 then 'EUROPE'
            when date_part('hour', cast(event_time as timestamp)) >= 13 and date_part('hour', cast(event_time as timestamp)) < 21 then 'US'
            else 'OFF_HOURS'
        end as session_band,
        -- Session overlap score
        case
            when date_part('hour', cast(event_time as timestamp)) >= 13 and date_part('hour', cast(event_time as timestamp)) < 21 then 1.0
            when date_part('hour', cast(event_time as timestamp)) >= 7 and date_part('hour', cast(event_time as timestamp)) < 13 then 0.6
            when date_part('hour', cast(event_time as timestamp)) >= 0 and date_part('hour', cast(event_time as timestamp)) < 7 then 0.35
            else 0.15
        end as session_overlap_score,
        -- US market hours (9:30-16:00 ET ≈ 14:30-21:00 UTC, simplified 14-21 UTC)
        case when date_part('hour', cast(event_time as timestamp)) >= 14 and date_part('hour', cast(event_time as timestamp)) < 21 then 1 else 0 end as session_us_open,
        -- China market hours (9:30-15:00 CST = 1:30-7:00 UTC, simplified 1-7 UTC)
        case when date_part('hour', cast(event_time as timestamp)) >= 1 and date_part('hour', cast(event_time as timestamp)) < 7 then 1 else 0 end as session_china_open,
        -- Overlap US+China (rare; US 14-21, China 1-7 -> no overlap; US+Asia overlap 14-16 UTC when Asia late session)
        case when (date_part('hour', cast(event_time as timestamp)) >= 14 and date_part('hour', cast(event_time as timestamp)) < 21)
                  or (date_part('hour', cast(event_time as timestamp)) >= 1 and date_part('hour', cast(event_time as timestamp)) < 7) then 1 else 0 end as session_us_or_china_open,
        -- Earnings window: within 5 days of typical US earnings cluster (risk-on/volatile)
        case when exists (select 1 from earnings_dates e where abs(date_diff('day', cast(date_trunc('day', cast(event_time as timestamp)) as date), e.d)) <= 5) then 1 else 0 end as earnings_window,
        -- Alpha microstructure score (basis + funding + momentum composite)
        case
            when abs(basis_bps) > 10.0 then sign(-basis_bps) * 1.0
            else -basis_bps / 10.0
        end * 0.45 +
        case
            when abs(funding_rate_8h) > 0.0004 then sign(-funding_rate_8h) * 1.0
            else -funding_rate_8h / 0.0004
        end * 0.35 +
        case
            when abs(price_change_percent_24h) > 4.0 then sign(-price_change_percent_24h) * 1.0
            else -price_change_percent_24h / 4.0
        end * 0.20 as alpha_microstructure_score,
        -- Cross-exchange signal
        case
            when abs(cross_exchange_mean_diff_bps) > 8.0 then sign(cross_exchange_mean_diff_bps) * 1.0
            else cross_exchange_mean_diff_bps / 8.0
        end * (1.0 - 0.4 * least(abs(cross_exchange_bid_ask_bps_mean) / 25.0, 1.0)) as cross_exchange_score,
        -- DEX alpha signal
        case
            when abs(dex_cex_basis_bps) > 12.0 then sign(dex_cex_basis_bps) * 1.0
            else dex_cex_basis_bps / 12.0
        end * 0.7 +
        case
            when abs(dex_txn_imbalance_24h) > 1.0 then sign(dex_txn_imbalance_24h) * 1.0
            else dex_txn_imbalance_24h
        end * 0.3 as dex_alpha_score,
        -- Liquidity event score
        least(open_interest / 5000000.0, 1.0) * 0.30 +
        least(abs((buy_sell_ratio - 1.0) / 0.35), 1.0) * 0.25 +
        least(abs((long_short_account_ratio - 1.0) / 1.2), 1.0) * 0.20 +
        least(abs(basis_bps) / 15.0, 1.0) * 0.15 +
        least(quote_volume_24h / 20000000000.0, 1.0) * 0.10 as liquidity_event_score,
        -- Liquidity event label
        case
            when (least(open_interest / 5000000.0, 1.0) * 0.30 +
                  least(abs((buy_sell_ratio - 1.0) / 0.35), 1.0) * 0.25 +
                  least(abs((long_short_account_ratio - 1.0) / 1.2), 1.0) * 0.20 +
                  least(abs(basis_bps) / 15.0, 1.0) * 0.15 +
                  least(quote_volume_24h / 20000000000.0, 1.0) * 0.10) < 0.35 then 'NONE'
            when buy_sell_ratio > 1.15 and long_short_account_ratio > 1.2 and basis_bps > 2 then 'LONG_CROWDING'
            when buy_sell_ratio < 0.85 and long_short_account_ratio < 0.9 and basis_bps < -2 then 'SHORT_CROWDING'
            else 'BALANCED_PRESSURE'
        end as liquidity_event_label,
        -- FED window label
        case
            when next_fed_decision_date is null or next_fed_decision_date = '' then 'UNKNOWN'
            when date_diff('hour', cast(event_time as timestamp), cast(next_fed_decision_date as timestamp)) between -2 and 24 then 'PRE_EVENT'
            when date_diff('hour', cast(event_time as timestamp), cast(next_fed_decision_date as timestamp)) between -24 and -2 then 'POST_EVENT'
            else 'NORMAL'
        end as fed_window,
        -- Alpha signal (heuristic trade bias)
        case
            when (case
                when next_fed_decision_date is null or next_fed_decision_date = '' then 'UNKNOWN'
                when date_diff('hour', cast(event_time as timestamp), cast(next_fed_decision_date as timestamp)) between -2 and 24 then 'PRE_EVENT'
                when date_diff('hour', cast(event_time as timestamp), cast(next_fed_decision_date as timestamp)) between -24 and -2 then 'POST_EVENT'
                else 'NORMAL'
            end) in ('PRE_EVENT', 'POST_EVENT') then 'NO_TRADE'
            when basis_bps > 4 and funding_rate_8h > 0.00005 and price_change_percent_24h > 0.8 then 'SHORT'
            when basis_bps < -4 and funding_rate_8h < -0.00005 and open_interest > 0 and price_change_percent_24h < -0.4 then 'LONG'
            else 'NO_TRADE'
        end as alpha_signal,
        -- Regime labels
        case
            when momentum_12 >= 1.0 and price_change_percent_24h >= 0.5 then 'BULL'
            when momentum_12 <= -1.0 and price_change_percent_24h <= -0.5 then 'BEAR'
            else 'NEUTRAL'
        end as regime_label,
        case
            when abs(momentum_3) >= 1.5 or (least(open_interest / 5000000.0, 1.0) * 0.30 +
                  least(abs((buy_sell_ratio - 1.0) / 0.35), 1.0) * 0.25 +
                  least(abs((long_short_account_ratio - 1.0) / 1.2), 1.0) * 0.20 +
                  least(abs(basis_bps) / 15.0, 1.0) * 0.15 +
                  least(quote_volume_24h / 20000000000.0, 1.0) * 0.10) >= 0.5 then 'HIGH_VOL'
            else 'LOW_VOL'
        end as vol_label
    from with_forward_returns
)
select
    md5(cast(event_time as varchar) || '-' || symbol) as feature_id,
    event_time,
    symbol,
    spot_last_price,
    futures_last_price,
    basis_bps,
    spot_volume,
    futures_volume,
    mark_price,
    index_price,
    funding_rate_8h,
    open_interest,
    price_change_percent_24h,
    quote_volume_24h,
    long_short_account_ratio,
    buy_sell_ratio,
    cross_exchange_bid_ask_bps_mean,
    cross_exchange_mean_diff_bps,
    bybit_okx_delta_bps,
    cross_exchange_score,
    dex_price_usd,
    dex_cex_basis_bps,
    dex_liquidity_usd,
    dex_volume_24h_usd,
    dex_txn_imbalance_24h,
    dex_alpha_score,
    btc_dominance,
    total_market_cap_usd,
    fear_greed_value,
    fed_funds_rate,
    next_fed_decision_date,
    sp500_close,
    oil_wti_usd,
    -- Enriched features
    momentum_3,
    momentum_12,
    momentum_score,
    session_band,
    session_overlap_score,
    session_us_open,
    session_china_open,
    session_us_or_china_open,
    earnings_window,
    alpha_microstructure_score,
    liquidity_event_score,
    liquidity_event_label,
    fed_window,
    alpha_signal,
    regime_label,
    vol_label,
    -- Microstructure features
    spread_bps,
    depth_imbalance_score,
    microprice,
    depth_slope_proxy,
    order_flow_imbalance,
    spread_momentum_bps,
    price_zscore_24h,
    price_deviation_pct_24h,
    -- Composite alpha score (weighted blend with microstructure)
    (alpha_microstructure_score * 0.40 +
     momentum_score * 0.25 +
     session_overlap_score * 0.10 +
     liquidity_event_score * 0.10 +
     cross_exchange_score * 0.05 +
     dex_alpha_score * 0.05 +
     (1.0 - depth_imbalance_score) * 0.05) as alpha_score,
    -- Forward returns (labels for training)
    fwd_return_1h,
    fwd_return_4h,
    fwd_return_24h,
    -- Regime combo (for policy blocking)
    regime_label || '__' || vol_label as regime_combo
from with_enriched_features
