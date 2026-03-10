{{ config(
    materialized='incremental',
    unique_key=['symbol', 'event_time']
) }}

with market_base as (
    -- Crypto market data
    select
        event_time,
        symbol,
        spot_last_price,
        futures_last_price,
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
        cross_exchange_peer_last_price_mean,
        bybit_last_price,
        okx_last_price,
        dex_price_usd,
        dex_liquidity_usd,
        dex_volume_24h_usd,
        dex_txn_imbalance_24h
    from {{ ref('br_market_snapshot') }}
    {% if is_incremental() %}
    where try_cast(event_time as timestamp) >= (select max(try_cast(event_time as timestamp)) - interval '3 days' from {{ this }})
    {% endif %}

    union all

    -- Stock market data mapped to same schema
    select
        event_time,
        symbol,
        close_price as spot_last_price,
        close_price as futures_last_price,
        volume as spot_volume,
        0 as futures_volume,
        close_price as mark_price,
        close_price as index_price,
        0.0 as funding_rate_8h,
        0.0 as open_interest,
        0.0 as price_change_percent_24h, -- Could calculate this, but leaving 0 for now
        0.0 as quote_volume_24h,
        1.0 as long_short_account_ratio,
        1.0 as buy_sell_ratio,
        0.0 as cross_exchange_bid_ask_bps_mean,
        close_price as cross_exchange_peer_last_price_mean,
        close_price as bybit_last_price,
        close_price as okx_last_price,
        close_price as dex_price_usd,
        volume * close_price as dex_liquidity_usd,
        volume * close_price as dex_volume_24h_usd,
        0.0 as dex_txn_imbalance_24h
    from {{ ref('br_stock_prices') }}
    {% if is_incremental() %}
    where try_cast(event_time as timestamp) >= (select max(try_cast(event_time as timestamp)) - interval '3 days' from {{ this }})
    {% endif %}
),
market as (
    select * from market_base
),
macro as (
    select * from {{ ref('br_macro_context') }}
),
sentiment_base as (
    select
        symbol,
        date_trunc('hour', analyzed_at) as event_time,
        avg(sentiment_score) as sentiment_score_1h
    from {{ ref('br_news_sentiment') }}
    group by 1, 2
),
x_sentiment_base as (
    select
        date_trunc('hour', analyzed_at) as event_time,
        avg(sentiment_score) as grok_x_sentiment_1h
    from {{ ref('br_x_sentiment') }}
    group by 1
),
joined as (
    select
        m.event_time,
        m.symbol,
        m.spot_last_price,
        m.futures_last_price,
        case
            when m.spot_last_price = 0 then 0
            else ((m.futures_last_price - m.spot_last_price) / m.spot_last_price) * 10000
        end as basis_bps,
        m.spot_volume,
        m.futures_volume,
        m.mark_price,
        m.index_price,
        m.funding_rate_8h,
        m.open_interest,
        m.price_change_percent_24h,
        m.quote_volume_24h,
        m.long_short_account_ratio,
        m.buy_sell_ratio,
        m.cross_exchange_bid_ask_bps_mean,
        case
            when m.futures_last_price = 0 then 0
            else ((m.cross_exchange_peer_last_price_mean - m.futures_last_price) / m.futures_last_price) * 10000
        end as cross_exchange_mean_diff_bps,
        case
            when m.futures_last_price = 0 then 0
            else ((greatest(coalesce(m.bybit_last_price, 0), coalesce(m.okx_last_price, 0)) - least(coalesce(m.bybit_last_price, 0), coalesce(m.okx_last_price, 0))) / m.futures_last_price) * 10000
        end as bybit_okx_delta_bps,
        m.dex_price_usd,
        case
            when m.spot_last_price = 0 then 0
            else ((m.dex_price_usd - m.spot_last_price) / m.spot_last_price) * 10000
        end as dex_cex_basis_bps,
        m.dex_liquidity_usd,
        m.dex_volume_24h_usd,
        m.dex_txn_imbalance_24h,
        mc.btc_dominance,
        mc.total_market_cap_usd,
        mc.fear_greed_value,
        mc.fed_funds_rate,
        mc.next_fed_decision_date,
        mc.sp500_close,
        mc.oil_wti_usd,
        coalesce(s.sentiment_score_1h, 0.0) as sentiment_score_1h,
        coalesce(xs.grok_x_sentiment_1h, 0.0) as grok_x_sentiment_1h
    from market m
    left join macro mc
      on date_trunc('hour', cast(mc.event_time as timestamp)) = date_trunc('hour', cast(m.event_time as timestamp))
    left join sentiment_base s
      on s.symbol = m.symbol
      and s.event_time = date_trunc('hour', cast(m.event_time as timestamp))
    left join x_sentiment_base xs
      on xs.event_time = date_trunc('hour', cast(m.event_time as timestamp))
)
select * from joined