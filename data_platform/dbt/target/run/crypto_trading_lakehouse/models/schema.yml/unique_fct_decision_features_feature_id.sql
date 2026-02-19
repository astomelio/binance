select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    

select
    feature_id as unique_field,
    count(*) as n_records

from "crypto"."gold"."fct_decision_features"
where feature_id is not null
group by feature_id
having count(*) > 1



      
    ) dbt_internal_test