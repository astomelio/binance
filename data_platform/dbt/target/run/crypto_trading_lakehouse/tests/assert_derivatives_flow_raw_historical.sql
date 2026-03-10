select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      -- Fail if derivatives_flow_raw has data but min(event_time) is too recent (< 2 years).
select 1 as fail
from (
  select min(cast(event_time as timestamp)) as min_ts
  from "crypto"."main"."derivatives_flow_raw"
) where min_ts is not null and min_ts > current_timestamp - interval '2 years'
      
    ) dbt_internal_test