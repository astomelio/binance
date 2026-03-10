

with global_m as (
    select
        date_trunc('hour', cast(event_time as timestamp)) as event_time,
        cast(json_extract_string(payload, '$.market_cap_percentage.btc') as double) as btc_dominance,
        cast(json_extract_string(payload, '$.total_market_cap.usd') as double) as total_market_cap_usd
    from "crypto"."main"."global_market_raw"
    
    where cast(event_time as timestamp) > (select max(cast(event_time as timestamp)) from "crypto"."main"."br_macro_context")
    
),
fear_greed as (
    select
        date_trunc('hour', cast(event_time as timestamp)) as event_time,
        -- fallback to null if value column doesn't exist yet due to empty data
        try_cast(NULL as double) as fear_greed_value
    from "crypto"."main"."fear_greed_raw"
    
    where cast(event_time as timestamp) > (select max(cast(event_time as timestamp)) from "crypto"."main"."br_macro_context")
    
),
macro_r as (
    select
        date_trunc('hour', cast(event_time as timestamp)) as event_time,
        try_cast(NULL as double) as fed_funds_rate
    from "crypto"."main"."macro_rates_raw"
    
    where cast(event_time as timestamp) > (select max(cast(event_time as timestamp)) from "crypto"."main"."br_macro_context")
    
),
macro_assets as (
    select
        date_trunc('day', cast(event_time as timestamp)) as event_date,
        try_cast(NULL as double) as sp500_close,
        try_cast(NULL as double) as oil_wti_usd
    from "crypto"."main"."macro_assets_raw"
    
    where cast(event_time as timestamp) > (select max(cast(event_time as timestamp)) from "crypto"."main"."br_macro_context")
    
),
fed_cal as (
    select
        date_trunc('hour', cast(event_time as timestamp)) as event_time,
        try_cast(dt as timestamp) as next_fed_decision_date
    from "crypto"."main"."fed_calendar_raw"
    
    where cast(event_time as timestamp) > (select max(cast(event_time as timestamp)) from "crypto"."main"."br_macro_context")
    
),
-- Create a master timeline from all sources
timeline as (
    select event_time from global_m
    union
    select event_time from fear_greed
    union
    select event_time from macro_r
    union
    select event_time from fed_cal
),
base as (
    select
        t.event_time,
        g.btc_dominance,
        g.total_market_cap_usd,
        fg.fear_greed_value,
        m.fed_funds_rate,
        f.next_fed_decision_date
    from timeline t
    left join global_m g using (event_time)
    left join fear_greed fg using (event_time)
    left join macro_r m using (event_time)
    left join fed_cal f using (event_time)
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
from base b
left join macro_assets ma on (date_trunc('day', b.event_time) - interval 1 day) = ma.event_date