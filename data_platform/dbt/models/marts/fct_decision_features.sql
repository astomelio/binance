{{ config(enabled=false) }}

with market as (
    select * from {{ ref('stg_market_snapshot') }}
),
macro as (
    select * from {{ ref('stg_macro_context') }}
),
joined as (
    select
        to_hex(md5(concat(cast(m.event_time as string), '-', m.symbol))) as feature_id,
        m.event_time,
        m.symbol,
        m.spot_last_price,
        m.futures_last_price,
        safe_divide((m.futures_last_price - m.spot_last_price), nullif(m.spot_last_price, 0)) * 10000 as basis_bps,
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
        m.cross_exchange_peer_last_price_mean,
        safe_divide((m.cross_exchange_peer_last_price_mean - m.futures_last_price), nullif(m.futures_last_price, 0)) * 10000 as cross_exchange_mean_diff_bps,
        safe_divide((greatest(m.bybit_last_price, m.okx_last_price) - least(m.bybit_last_price, m.okx_last_price)), nullif(m.futures_last_price, 0)) * 10000 as bybit_okx_delta_bps,
        m.dex_price_usd,
        safe_divide((m.dex_price_usd - m.spot_last_price), nullif(m.spot_last_price, 0)) * 10000 as dex_cex_basis_bps,
        m.dex_liquidity_usd,
        m.dex_volume_24h_usd,
        m.dex_txn_imbalance_24h,
        mc.btc_dominance,
        mc.total_market_cap_usd,
        mc.fed_funds_rate,
        mc.next_fed_decision_date
    from market m
    left join macro mc
      on mc.event_time = m.event_time
)
select * from joined
{% if is_incremental() %}
where event_time > (select coalesce(max(event_time), timestamp('1970-01-01')) from {{ this }})
{% endif %}

