select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select event_time
from "crypto"."main"."decision_features"
where event_time is null



      
    ) dbt_internal_test