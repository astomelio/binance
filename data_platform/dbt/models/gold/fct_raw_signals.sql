{{ config(materialized='table') }}

with model_outputs as (
    -- In a live environment, this table would be populated by the Python ML scripts 
    -- writing back to DuckDB. For now, we create the structure.
    select
        cast(null as timestamp) as event_time,
        cast(null as varchar) as symbol,
        cast(null as varchar) as signal_type,
        cast(null as double) as confidence,
        cast(null as double) as asset_volatility_24h,
        cast(null as varchar) as model_version
    where 1=0
)
select * from model_outputs