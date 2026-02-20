

with market as (
    select
        event_time,
        symbol,
        cast(spot_last_price as double) as spot_last_price,
        cast(futures_last_price as double) as futures_last_price,
        cast(spot_volume as double) as spot_volume,
        cast(futures_volume as double) as futures_volume
    from "crypto"."main"."market_snapshot_raw"
),
derivatives as (
    select
        event_time,
        symbol,
        cast(mark_price as double) as mark_price,
        cast(index_price as double) as index_price,
        cast(last_funding_rate as double) as funding_rate_8h,
        cast(open_interest as double) as open_interest,
        cast(price_change_percent_24h as double) as price_change_percent_24h,
        cast(quote_volume_24h as double) as quote_volume_24h
    from "crypto"."main"."derivatives_snapshot_raw"
),
flow as (
    select
        event_time,
        symbol,
        cast(long_short_account_ratio as double) as long_short_account_ratio,
        cast(buy_sell_ratio as double) as buy_sell_ratio
    from "crypto"."main"."derivatives_flow_raw"
),
cross_ex as (
    select
        event_time,
        symbol,
        avg(cast(last_price as double)) as cross_exchange_peer_last_price_mean,
        avg(
            case
                when cast(bid_price as double) > 0 and cast(ask_price as double) > 0
                    then ((cast(ask_price as double) - cast(bid_price as double)) / ((cast(ask_price as double) + cast(bid_price as double)) / 2.0)) * 10000
                else 0
            end
        ) as cross_exchange_bid_ask_bps_mean,
        max(case when lower(exchange) = 'bybit' then cast(last_price as double) end) as bybit_last_price,
        max(case when lower(exchange) = 'okx' then cast(last_price as double) end) as okx_last_price
    from "crypto"."main"."cross_exchange_snapshot_raw"
    group by 1, 2
),
dex as (
    select
        event_time,
        symbol,
        cast(dex_price_usd as double) as dex_price_usd,
        cast(dex_liquidity_usd as double) as dex_liquidity_usd,
        cast(dex_volume_24h_usd as double) as dex_volume_24h_usd,
        cast(dex_txn_imbalance_24h as double) as dex_txn_imbalance_24h
    from "crypto"."main"."dex_snapshot_raw"
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