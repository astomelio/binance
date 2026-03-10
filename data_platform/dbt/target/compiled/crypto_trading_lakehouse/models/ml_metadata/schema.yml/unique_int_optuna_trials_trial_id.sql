
    
    

select
    trial_id as unique_field,
    count(*) as n_records

from "crypto"."main"."int_optuna_trials"
where trial_id is not null
group by trial_id
having count(*) > 1


