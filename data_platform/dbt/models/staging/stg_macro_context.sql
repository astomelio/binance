{{ config(enabled=false) }}

with global_m as (
    select
        event_time,
        cast(btc_dominance as float64) as btc_dominance,
        cast(total_market_cap_usd as float64) as total_market_cap_usd
    from {{ source('raw', 'global_market_normalized') }}
),
macro_r as (
    select
        event_time,
        cast(fed_funds_rate as float64) as fed_funds_rate
    from {{ source('raw', 'macro_rates_normalized') }}
),
fed_cal as (
    select
        event_time,
        next_fed_decision_date
    from {{ source('raw', 'fed_calendar_normalized') }}
)
select
    coalesce(g.event_time, m.event_time, f.event_time) as event_time,
    g.btc_dominance,
    g.total_market_cap_usd,
    m.fed_funds_rate,
    f.next_fed_decision_date
from global_m g
full outer join macro_r m using (event_time)
full outer join fed_cal f using (event_time)

