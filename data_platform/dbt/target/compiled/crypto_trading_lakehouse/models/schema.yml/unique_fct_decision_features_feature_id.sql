
    
    

select
    feature_id as unique_field,
    count(*) as n_records

from "crypto"."gold"."fct_decision_features"
where feature_id is not null
group by feature_id
having count(*) > 1


