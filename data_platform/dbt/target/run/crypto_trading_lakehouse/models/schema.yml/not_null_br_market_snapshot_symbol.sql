select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select symbol
from "crypto"."main"."br_market_snapshot"
where symbol is null



      
    ) dbt_internal_test