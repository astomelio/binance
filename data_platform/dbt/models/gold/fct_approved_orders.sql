{{ config(materialized='table') }}

with risk_evaluated as (
    -- In a live environment, this table is populated by the Python Risk Engine
    select
        cast(null as timestamp) as event_time,
        cast(null as varchar) as symbol,
        cast(null as varchar) as signal_type,
        cast(null as double) as size_usd,
        cast(null as double) as confidence,
        cast(null as double) as risk_vol_multiplier,
        cast(null as varchar) as status -- PENDING, EXECUTED, FAILED
    where 1=0
)
select * from risk_evaluated