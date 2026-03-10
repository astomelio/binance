

with market as (
    select
        event_time,
        symbol,
        cast(json_extract_string(spot_ticker, '$.lastPrice') as double) as spot_last_price,
        cast(json_extract_string(futures_ticker, '$.lastPrice') as double) as futures_last_price,
        cast(json_extract_string(spot_ticker, '$.volume') as double) as spot_volume,
        cast(json_extract_string(futures_ticker, '$.volume') as double) as futures_volume
    from "crypto"."main"."market_snapshot_raw"
    
    where try_cast(event_time as timestamp) > (select max(try_cast(event_time as timestamp)) from "crypto"."main"."br_market_snapshot")
    
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
    
    where try_cast(event_time as timestamp) > (select max(try_cast(event_time as timestamp)) from "crypto"."main"."br_market_snapshot")
    
),
flow as (
    select
        event_time,
        symbol,
        -- fallback a nulo si la tabla cruda aún no tiene estas columnas
        try_cast(NULL as double) as long_short_account_ratio,
        try_cast(NULL as double) as buy_sell_ratio
    from "crypto"."main"."derivatives_flow_raw"
    
    where try_cast(event_time as timestamp) > (select max(try_cast(event_time as timestamp)) from "crypto"."main"."br_market_snapshot")
    
),
cross_ex as (
    select
        event_time,
        symbol,
        avg(cast(raw_last as double)) as cross_exchange_peer_last_price_mean,
        avg(
            case
                when cast(raw_bid as double) > 0 and cast(raw_ask as double) > 0
                    then ((cast(raw_ask as double) - cast(raw_bid as double)) / ((cast(raw_ask as double) + cast(raw_bid as double)) / 2.0)) * 10000
                else 0
            end
        ) as cross_exchange_bid_ask_bps_mean,
        max(case when lower(exchange) = 'bybit' then cast(raw_last as double) end) as bybit_last_price,
        max(case when lower(exchange) = 'okx' then cast(raw_last as double) end) as okx_last_price,
        max(case when lower(exchange) = 'aster' then cast(raw_last as double) end) as aster_last_price
    from (
        select event_time, exchange, symbol, cast(last_price as double) as raw_last, cast(bid_price as double) as raw_bid, cast(ask_price as double) as raw_ask, cast(quote_volume_24h as double) as raw_quote from "crypto"."main"."cross_exchange_snapshot_raw"
        
        where try_cast(event_time as timestamp) > (select max(try_cast(event_time as timestamp)) from "crypto"."main"."br_market_snapshot")
        
        union all
        select 
            event_time, 
            'aster' as exchange, 
            symbol, 
            try_cast(NULL as double) as raw_last, 
            try_cast(null as double) as raw_bid, 
            try_cast(null as double) as raw_ask, 
            try_cast(null as double) as raw_quote
        from "crypto"."main"."aster_dex_raw"
        
        where try_cast(event_time as timestamp) > (select max(try_cast(event_time as timestamp)) from "crypto"."main"."br_market_snapshot")
        
    ) sub
    group by 1, 2
),
dex as (
    select
        event_time,
        symbol,
        avg(cast(raw_price as double)) as dex_price_usd,
        avg(cast(raw_liq as double)) as dex_liquidity_usd,
        avg(cast(raw_vol as double)) as dex_volume_24h_usd,
        avg(cast(raw_imb as double)) as dex_txn_imbalance_24h
    from (
        select 
            event_time, 
            symbol, 
            cast(dex_price_usd as double) as raw_price, 
            cast(dex_liquidity_usd as double) as raw_liq, 
            cast(dex_volume_24h_usd as double) as raw_vol, 
            case 
                when try_cast(NULL as double) > 0 
                then 0.0
                else 0.0
            end as raw_imb 
        from "crypto"."main"."dex_snapshot_raw"
        
        where try_cast(event_time as timestamp) > (select max(try_cast(event_time as timestamp)) from "crypto"."main"."br_market_snapshot")
        
        union all
        select
            event_time,
            symbol,
            try_cast(NULL as double) as raw_price,
            cast(0.0 as double) as raw_liq,
            try_cast(NULL as double) as raw_vol,
            cast(0.0 as double) as raw_imb
        from "crypto"."main"."aster_dex_raw"
        
        where try_cast(event_time as timestamp) > (select max(try_cast(event_time as timestamp)) from "crypto"."main"."br_market_snapshot")
        
    ) sub
    group by 1, 2
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
    c.aster_last_price,
    x.dex_price_usd,
    x.dex_liquidity_usd,
    x.dex_volume_24h_usd,
    x.dex_txn_imbalance_24h
from market m
left join derivatives d on m.event_time = d.event_time and m.symbol = d.symbol
left join flow f on m.event_time = f.event_time and m.symbol = f.symbol
left join cross_ex c on m.event_time = c.event_time and m.symbol = c.symbol
left join dex x on m.event_time = x.event_time and m.symbol = x.symbol