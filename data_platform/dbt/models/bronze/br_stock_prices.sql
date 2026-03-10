{{ config(
    materialized='incremental',
    unique_key=['symbol', 'event_time']
) }}

select
    cast(event_time as timestamp) as event_time,
    symbol,
    cast(open_price as double) as open_price,
    cast(high_price as double) as high_price,
    cast(low_price as double) as low_price,
    cast(close_price as double) as close_price,
    cast(volume as double) as volume
from {{ source('raw', 'stock_prices') }}
{% if is_incremental() %}
where cast(event_time as timestamp) > (select max(cast(event_time as timestamp)) from {{ this }})
{% endif %}
