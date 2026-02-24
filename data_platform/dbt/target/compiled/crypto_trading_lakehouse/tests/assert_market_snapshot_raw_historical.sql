-- Fail if market_snapshot_raw has data but min(event_time) is too recent (< 2 years).
-- Tables with backfill should always have historical coverage from as far back as possible.
select 1 as fail
from (
  select min(cast(event_time as timestamp)) as min_ts
  from "crypto"."main"."market_snapshot_raw"
) where min_ts is not null and min_ts > current_timestamp - interval '2 years'