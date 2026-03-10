select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select run_uuid
from "crypto"."main"."int_mlflow_runs"
where run_uuid is null



      
    ) dbt_internal_test