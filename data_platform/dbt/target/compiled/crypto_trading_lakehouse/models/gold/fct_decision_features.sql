

with src as (
    select * from "crypto"."main"."slv_decision_features"
    
    -- Lookback window for rolling calculations: 3 days of data needed for 12h momentum, SMA50, etc.
    where try_cast(event_time as timestamp) >= (select max(try_cast(event_time as timestamp)) - interval '3 days' from "crypto"."main"."decision_features")
    
),
-- Detect interval and calculate steps per hour
interval_detect as (
    select
        case 
            when avg_diff <= 1 then 60
            when avg_diff <= 15 then 4
            when avg_diff <= 60 then 1
            else 1
        end as steps_per_hour
    from (
        select 
            avg(date_diff('minute', prev_time, cast(event_time as timestamp))) as avg_diff
        from (
            select 
                cast(event_time as timestamp) as event_time,
                lag(cast(event_time as timestamp)) over (partition by symbol order by cast(event_time as timestamp)) as prev_time
            from src
            limit 100
        )
    )
),
earnings_dates as (
    select unnest([
        DATE '2023-01-15', DATE '2023-04-15', DATE '2023-07-15', DATE '2023-10-15',
        DATE '2024-01-15', DATE '2024-04-15', DATE '2024-07-15', DATE '2024-10-15',
        DATE '2025-01-15', DATE '2025-04-15', DATE '2025-07-15', DATE '2025-10-15',
        DATE '2026-01-15', DATE '2026-04-15', DATE '2026-07-15', DATE '2026-10-15'
    ]) as d
),
with_microstructure as (
    select
        s.*,
        -- Spread (already calculated in silver, but we normalize it)
        s.cross_exchange_bid_ask_bps_mean as spread_bps,
        -- Depth imbalance proxy
        case
            when s.cross_exchange_bid_ask_bps_mean > 0 then least(s.cross_exchange_bid_ask_bps_mean / 50.0, 1.0)
            else 0.0
        end as depth_imbalance_score,
        -- Microprice
        case
            when s.futures_last_price > 0 and s.cross_exchange_mean_diff_bps is not null then
                (s.futures_last_price * 0.6 + s.futures_last_price * (1.0 + s.cross_exchange_mean_diff_bps / 10000.0) * 0.4)
            else s.futures_last_price
        end as microprice,
        -- Depth slope proxy
        case
            when s.futures_last_price > 0 and s.cross_exchange_bid_ask_bps_mean > 0 then
                s.cross_exchange_bid_ask_bps_mean / (s.futures_last_price / 10000.0)
            else 0.0
        end as depth_slope_proxy,
        -- Order flow imbalance
        case
            when s.buy_sell_ratio > 0 then (s.buy_sell_ratio - 1.0) / 0.5
            else 0.0
        end as order_flow_imbalance
    from src s
),
with_momentum as (
    select
        wm.*,
        -- Use dynamic window sizes based on interval
        -- Momentum 3h and 12h
        lag(futures_last_price, 3 * cast((select steps_per_hour from interval_detect) as int)) over (partition by symbol order by event_time) as price_3h_ago,
        lag(futures_last_price, 12 * cast((select steps_per_hour from interval_detect) as int)) over (partition by symbol order by event_time) as price_12h_ago,
        -- Mean reversion: 24h rolling window
        avg(futures_last_price) over (partition by symbol order by event_time rows between (24 * cast((select steps_per_hour from interval_detect) as int)) preceding and current row) as price_ma_24h,
        stddev(futures_last_price) over (partition by symbol order by event_time rows between (24 * cast((select steps_per_hour from interval_detect) as int)) preceding and current row) as price_std_24h,
        -- Lag spread
        lag(spread_bps, 1) over (partition by symbol order by event_time) as spread_bps_lag1,
        -- RSI 14 components
        futures_last_price - lag(futures_last_price, 1) over (partition by symbol order by event_time) as price_diff,
        -- SMA 50
        avg(futures_last_price) over (partition by symbol order by event_time rows between (50 * cast((select steps_per_hour from interval_detect) as int)) preceding and current row) as sma50,
        -- ATR 14 components
        greatest(
            mark_price - index_price, -- proxy for high-low if not available
            abs(mark_price - lag(futures_last_price, 1) over (partition by symbol order by event_time)),
            abs(index_price - lag(futures_last_price, 1) over (partition by symbol order by event_time))
        ) as true_range
    from with_microstructure wm
),
with_indicators_avg as (
    select
        *,
        case when price_diff > 0 then price_diff else 0 end as gain,
        case when price_diff < 0 then abs(price_diff) else 0 end as loss,
        avg(case when price_diff > 0 then price_diff else 0 end) over (partition by symbol order by event_time rows between (14 * cast((select steps_per_hour from interval_detect) as int)) preceding and current row) as avg_gain,
        avg(case when price_diff < 0 then abs(price_diff) else 0 end) over (partition by symbol order by event_time rows between (14 * cast((select steps_per_hour from interval_detect) as int)) preceding and current row) as avg_loss,
        avg(true_range) over (partition by symbol order by event_time rows between (14 * cast((select steps_per_hour from interval_detect) as int)) preceding and current row) as atr14
    from with_momentum
),
with_momentum_calc as (
    select
        *,
        case 
            when avg_loss is null or avg_loss = 0 then 100
            else 100 - (100 / (1 + (avg_gain / avg_loss)))
        end as rsi14,
        case
            when price_3h_ago = 0 or price_3h_ago is null then 0
            else ((futures_last_price - price_3h_ago) / price_3h_ago) * 100.0
        end as momentum_3,
        case
            when price_12h_ago = 0 or price_12h_ago is null then 0
            else ((futures_last_price - price_12h_ago) / price_12h_ago) * 100.0
        end as momentum_12,
        case
            when spread_bps_lag1 = 0 or spread_bps_lag1 is null then 0
            else spread_bps - spread_bps_lag1
        end as spread_momentum_bps,
        case
            when price_std_24h > 0 then (futures_last_price - price_ma_24h) / price_std_24h
            else 0.0
        end as price_zscore_24h,
        case
            when price_ma_24h > 0 then ((futures_last_price - price_ma_24h) / price_ma_24h) * 100.0
            else 0.0
        end as price_deviation_pct_24h
    from with_indicators_avg
),
with_forward_returns as (
    select
        *,
        -- Forward returns for labels (1 interval, 4h, 24h ahead)
        lead(futures_last_price, 1) over (partition by symbol order by event_time) as price_next_fwd,
        lead(futures_last_price, 4 * cast((select steps_per_hour from interval_detect) as int)) over (partition by symbol order by event_time) as price_4h_fwd,
        lead(futures_last_price, 24 * cast((select steps_per_hour from interval_detect) as int)) over (partition by symbol order by event_time) as price_24h_fwd
    from with_momentum_calc
),
with_returns_calc as (
    select
        *,
        case
            when futures_last_price = 0 then 0
            else ((price_next_fwd - futures_last_price) / futures_last_price) * 100.0
        end as fwd_return_1h, -- Keeping column name for compatibility, but it's 1-interval forward
        case
            when futures_last_price = 0 then 0
            else ((price_4h_fwd - futures_last_price) / futures_last_price) * 100.0
        end as fwd_return_4h,
        case
            when futures_last_price = 0 then 0
            else ((price_24h_fwd - futures_last_price) / futures_last_price) * 100.0
        end as fwd_return_24h
    from with_forward_returns
),
with_market_returns as (
    select
        *,
        case 
            when symbol = 'BTCUSDT' then fwd_return_1h 
            else first_value(case when symbol = 'BTCUSDT' then fwd_return_1h end) over (partition by event_time order by symbol) 
        end as market_return_crypto_1h,
        case
            when sp500_close > 0 then (sp500_close - lag(sp500_close) over (partition by symbol order by event_time)) / lag(sp500_close) over (partition by symbol order by event_time) * 100.0
            else 0.0
        end as market_return_sp500_1h
    from with_returns_calc
),
with_betas as (
    select
        *,
        covar_pop(fwd_return_1h, market_return_crypto_1h) over (partition by symbol order by event_time rows between (24 * cast((select steps_per_hour from interval_detect) as int)) preceding and current row) / 
        nullif(var_pop(market_return_crypto_1h) over (partition by symbol order by event_time rows between (24 * cast((select steps_per_hour from interval_detect) as int)) preceding and current row), 0) as beta_btc_24h,
        
        covar_pop(fwd_return_1h, market_return_sp500_1h) over (partition by symbol order by event_time rows between (24 * cast((select steps_per_hour from interval_detect) as int)) preceding and current row) / 
        nullif(var_pop(market_return_sp500_1h) over (partition by symbol order by event_time rows between (24 * cast((select steps_per_hour from interval_detect) as int)) preceding and current row), 0) as beta_sp500_24h
    from with_market_returns
),
with_neutral_returns as (
    select
        *,
        fwd_return_1h - (coalesce(beta_btc_24h, 1.0) * coalesce(market_return_crypto_1h, 0.0)) as alpha_return_1h_btc,
        fwd_return_1h - (coalesce(beta_sp500_24h, 1.0) * coalesce(market_return_sp500_1h, 0.0)) as alpha_return_1h_sp500
    from with_betas
),
with_enriched_features as (
    select
        *,
        case
            when abs(momentum_3) > 2.5 then sign(momentum_3) * 1.0
            else momentum_3 / 2.5
        end * 0.55 + 
        case
            when abs(momentum_12) > 5.0 then sign(momentum_12) * 1.0
            else momentum_12 / 5.0
        end * 0.45 as momentum_score,
        case
            when date_part('hour', cast(event_time as timestamp)) >= 0 and date_part('hour', cast(event_time as timestamp)) < 7 then 'ASIA'
            when date_part('hour', cast(event_time as timestamp)) >= 7 and date_part('hour', cast(event_time as timestamp)) < 13 then 'EUROPE'
            when date_part('hour', cast(event_time as timestamp)) >= 13 and date_part('hour', cast(event_time as timestamp)) < 21 then 'US'
            else 'OFF_HOURS'
        end as session_band,
        case
            when date_part('hour', cast(event_time as timestamp)) >= 13 and date_part('hour', cast(event_time as timestamp)) < 21 then 1.0
            when date_part('hour', cast(event_time as timestamp)) >= 7 and date_part('hour', cast(event_time as timestamp)) < 13 then 0.6
            when date_part('hour', cast(event_time as timestamp)) >= 0 and date_part('hour', cast(event_time as timestamp)) < 7 then 0.35
            else 0.15
        end as session_overlap_score,
        case when date_part('hour', cast(event_time as timestamp)) >= 14 and date_part('hour', cast(event_time as timestamp)) < 21 then 1 else 0 end as session_us_open,
        case when date_part('hour', cast(event_time as timestamp)) >= 1 and date_part('hour', cast(event_time as timestamp)) < 7 then 1 else 0 end as session_china_open,
        case when (date_part('hour', cast(event_time as timestamp)) >= 14 and date_part('hour', cast(event_time as timestamp)) < 21)
                  or (date_part('hour', cast(event_time as timestamp)) >= 1 and date_part('hour', cast(event_time as timestamp)) < 7) then 1 else 0 end as session_us_or_china_open,
        case when exists (select 1 from earnings_dates e where abs(date_diff('day', cast(date_trunc('day', cast(event_time as timestamp)) as date), e.d)) <= 5) then 1 else 0 end as earnings_window,
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
        case
            when cross_exchange_mean_diff_bps is null then 0.0
            when abs(cross_exchange_mean_diff_bps) > 8.0 then sign(cross_exchange_mean_diff_bps) * 1.0
            else cross_exchange_mean_diff_bps / 8.0
        end * (1.0 - 0.4 * least(abs(coalesce(cross_exchange_bid_ask_bps_mean, 0.0)) / 25.0, 1.0)) as cross_exchange_score,
        case
            when dex_cex_basis_bps is null then 0.0
            when abs(dex_cex_basis_bps) > 12.0 then sign(dex_cex_basis_bps) * 1.0
            else dex_cex_basis_bps / 12.0
        end * 0.7 +
        case
            when dex_txn_imbalance_24h is null then 0.0
            when abs(dex_txn_imbalance_24h) > 1.0 then sign(dex_txn_imbalance_24h) * 1.0
            else dex_txn_imbalance_24h
        end * 0.3 as dex_alpha_score,
        least(open_interest / 5000000.0, 1.0) * 0.30 +
        least(abs((buy_sell_ratio - 1.0) / 0.35), 1.0) * 0.25 +
        least(abs((long_short_account_ratio - 1.0) / 1.2), 1.0) * 0.20 +
        least(abs(basis_bps) / 15.0, 1.0) * 0.15 +
        least(quote_volume_24h / 20000000000.0, 1.0) * 0.10 as liquidity_event_score,
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
        case
            when next_fed_decision_date is null then 'NORMAL'
            when try_cast(next_fed_decision_date as varchar) = '' then 'NORMAL'
            when date_diff('hour', cast(event_time as timestamp), try_cast(next_fed_decision_date as timestamp)) between -2 and 24 then 'PRE_EVENT'
            when date_diff('hour', cast(event_time as timestamp), try_cast(next_fed_decision_date as timestamp)) between -24 and -2 then 'POST_EVENT'
            else 'NORMAL'
        end as fed_window,
        case
            when next_fed_decision_date is not null and try_cast(next_fed_decision_date as varchar) != '' and (
                date_diff('hour', cast(event_time as timestamp), try_cast(next_fed_decision_date as timestamp)) between -2 and 24
                or date_diff('hour', cast(event_time as timestamp), try_cast(next_fed_decision_date as timestamp)) between -24 and -2
            ) then 'NO_TRADE'
            when basis_bps > 3 and funding_rate_8h > 0.00003 and price_change_percent_24h > 0.5 then 'SHORT'
            when basis_bps < -3 and funding_rate_8h < -0.00003 and price_change_percent_24h < -0.3 then 'LONG'
            when momentum_3 > 1.5 and momentum_12 > 0.5 then 'LONG'
            when momentum_3 < -1.5 and momentum_12 < -0.5 then 'SHORT'
            else 'NO_TRADE'
        end as alpha_signal,
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
    from with_neutral_returns
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
    rsi14,
    atr14,
    sma50,
    sentiment_score_1h,
    grok_x_sentiment_1h,
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
    spread_bps,
    depth_imbalance_score,
    microprice,
    depth_slope_proxy,
    order_flow_imbalance,
    spread_momentum_bps,
    price_zscore_24h,
    price_deviation_pct_24h,
    beta_btc_24h,
    beta_sp500_24h,
    alpha_return_1h_btc,
    alpha_return_1h_sp500,
    (coalesce(alpha_microstructure_score, 0.0) * 0.35 +
     coalesce(momentum_score, 0.0) * 0.20 +
     coalesce(session_overlap_score, 0.0) * 0.10 +
     coalesce(liquidity_event_score, 0.0) * 0.10 +
     coalesce(cross_exchange_score, 0.0) * 0.05 +
     coalesce(dex_alpha_score, 0.0) * 0.05 +
     coalesce(sentiment_score_1h, 0.0) * 0.05 +
     coalesce(grok_x_sentiment_1h, 0.0) * 0.05 +
     (1.0 - coalesce(depth_imbalance_score, 0.0)) * 0.05) as alpha_score,
    fwd_return_1h,
    fwd_return_4h,
    fwd_return_24h,
    regime_label || '__' || vol_label as regime_combo
from with_enriched_features