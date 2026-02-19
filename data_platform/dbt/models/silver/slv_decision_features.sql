{{ config(materialized='table') }}

with market as (
    select * from {{ ref('br_market_snapshot') }}
),
macro as (
    select * from {{ ref('br_macro_context') }}
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
        mc.next_fed_decision_date
    from market m
    left join macro mc
      on mc.event_time = m.event_time
)
select * from joined
