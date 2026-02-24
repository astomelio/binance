-- Fail if derivatives_snapshot_raw has data but min(event_time) is too recent (< 2 years).
select 1 as fail
from (
  select min(cast(event_time as timestamp)) as min_ts
  from "crypto"."main"."derivatives_snapshot_raw"
) where min_ts is not null and min_ts > current_timestamp - interval '2 years'