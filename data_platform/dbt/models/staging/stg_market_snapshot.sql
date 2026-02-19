{{ config(enabled=false) }}

with market as (
    select
        event_time,
        symbol,
        cast(spot_last_price as float64) as spot_last_price,
        cast(futures_last_price as float64) as futures_last_price,
        cast(spot_volume as float64) as spot_volume,
        cast(futures_volume as float64) as futures_volume
    from {{ source('raw', 'market_snapshot_normalized') }}
),
derivatives as (
    select
        event_time,
        symbol,
        cast(mark_price as float64) as mark_price,
        cast(index_price as float64) as index_price,
        cast(last_funding_rate as float64) as funding_rate_8h,
        cast(open_interest as float64) as open_interest,
        cast(price_change_percent_24h as float64) as price_change_percent_24h,
        cast(quote_volume_24h as float64) as quote_volume_24h
    from {{ source('raw', 'derivatives_snapshot_normalized') }}
),
flow as (
    select
        event_time,
        symbol,
        cast(long_short_account_ratio as float64) as long_short_account_ratio,
        cast(buy_sell_ratio as float64) as buy_sell_ratio
    from {{ source('raw', 'derivatives_flow_normalized') }}
),
cross_ex as (
    select
        event_time,
        symbol,
        avg(cast(spread_bps as float64)) as cross_exchange_bid_ask_bps_mean,
        avg(cast(last_price as float64)) as cross_exchange_peer_last_price_mean,
        max(if(lower(exchange) = 'bybit', cast(last_price as float64), null)) as bybit_last_price,
        max(if(lower(exchange) = 'okx', cast(last_price as float64), null)) as okx_last_price
    from {{ source('raw', 'cross_exchange_snapshot_normalized') }}
    group by 1, 2
),
dex as (
    select
        event_time,
        symbol,
        cast(dex_price_usd as float64) as dex_price_usd,
        cast(dex_liquidity_usd as float64) as dex_liquidity_usd,
        cast(dex_volume_24h_usd as float64) as dex_volume_24h_usd,
        cast(dex_txn_imbalance_24h as float64) as dex_txn_imbalance_24h
    from {{ source('raw', 'dex_snapshot_normalized') }}
)
select
    m.event_time,
    m.symbol,
    m.spot_last_price,
    m.futures_last_price,
    m.spot_volume,
    m.futures_volume,
    d.mark_price,
    d.index_price,
    d.funding_rate_8h,
    d.open_interest,
    d.price_change_percent_24h,
    d.quote_volume_24h,
    f.long_short_account_ratio,
    f.buy_sell_ratio,
    c.cross_exchange_bid_ask_bps_mean,
    c.cross_exchange_peer_last_price_mean,
    c.bybit_last_price,
    c.okx_last_price,
    x.dex_price_usd,
    x.dex_liquidity_usd,
    x.dex_volume_24h_usd,
    x.dex_txn_imbalance_24h
from market m
left join derivatives d using (event_time, symbol)
left join flow f using (event_time, symbol)
left join cross_ex c using (event_time, symbol)
left join dex x using (event_time, symbol)

