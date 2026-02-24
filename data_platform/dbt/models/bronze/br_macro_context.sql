{{ config(materialized='table') }}

with global_m as (
    select
        event_time,
        cast(btc_dominance as double) as btc_dominance,
        cast(total_market_cap_usd as double) as total_market_cap_usd
    from {{ source('raw', 'global_market_raw') }}
),
fear_greed as (
    select
        event_time,
        cast(fear_greed_value as double) as fear_greed_value
    from {{ source('raw', 'fear_greed_raw') }}
),
macro_r as (
    select
        event_time,
        cast(fed_funds_rate as double) as fed_funds_rate
    from {{ source('raw', 'macro_rates_raw') }}
),
macro_assets as (
    select
        cast(event_time as timestamp) as event_date,
        cast(sp500_close as double) as sp500_close,
        cast(oil_wti_usd as double) as oil_wti_usd
    from {{ source('raw', 'macro_assets_raw') }}
),
fed_cal as (
    select
        event_time,
        next_fed_decision_date
    from {{ source('raw', 'fed_calendar_raw') }}
),
base as (
    select
        coalesce(g.event_time, fg.event_time, m.event_time, f.event_time) as event_time,
        g.btc_dominance,
        g.total_market_cap_usd,
        fg.fear_greed_value,
        m.fed_funds_rate,
        f.next_fed_decision_date
    from global_m g
    full outer join fear_greed fg using (event_time)
    full outer join macro_r m using (event_time)
    full outer join fed_cal f using (event_time)
)
select
    b.event_time,
    b.btc_dominance,
    b.total_market_cap_usd,
    b.fear_greed_value,
    b.fed_funds_rate,
    b.next_fed_decision_date,
    ma.sp500_close,
    ma.oil_wti_usd
-- Macro assets: use PREVIOUS day close to avoid lookahead (SP500/oil close at 21:00 UTC;
-- any event_time earlier that day would otherwise see "future" close).
from base b
left join macro_assets ma on (date_trunc('day', cast(b.event_time as timestamp)) - interval 1 day) = ma.event_date
