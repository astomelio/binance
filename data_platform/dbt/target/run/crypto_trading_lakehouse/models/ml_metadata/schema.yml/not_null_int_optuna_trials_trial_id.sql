select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select trial_id
from "crypto"."main"."int_optuna_trials"
where trial_id is null



      
    ) dbt_internal_test