select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select symbol
from "crypto"."gold"."fct_decision_features"
where symbol is null



      
    ) dbt_internal_test