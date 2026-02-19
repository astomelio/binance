

with global_m as (
    select
        event_time,
        cast(btc_dominance as double) as btc_dominance,
        cast(total_market_cap_usd as double) as total_market_cap_usd
    from "crypto"."raw"."global_market_raw"
),
fear_greed as (
    select
        event_time,
        cast(fear_greed_value as double) as fear_greed_value
    from "crypto"."raw"."fear_greed_raw"
),
macro_r as (
    select
        event_time,
        cast(fed_funds_rate as double) as fed_funds_rate
    from "crypto"."raw"."macro_rates_raw"
),
fed_cal as (
    select
        event_time,
        next_fed_decision_date
    from "crypto"."raw"."fed_calendar_raw"
)
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