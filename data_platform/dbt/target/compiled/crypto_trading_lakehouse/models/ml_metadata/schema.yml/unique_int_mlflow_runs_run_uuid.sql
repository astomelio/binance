
    
    

select
    run_uuid as unique_field,
    count(*) as n_records

from "crypto"."main"."int_mlflow_runs"
where run_uuid is not null
group by run_uuid
having count(*) > 1


