
  
    
    

    create  table
      "crypto"."main"."int_optuna_trials__dbt_tmp"
  
    as (
      

WITH studies AS (
    SELECT * FROM "crypto"."main"."optuna_studies"
),
trials AS (
    SELECT * FROM "crypto"."main"."optuna_trials"
),
params AS (
    SELECT 
        trial_id,
        param_name,
        param_value
    FROM "crypto"."main"."optuna_trial_params"
),
values AS (
    SELECT 
        trial_id,
        objective,
        value as objective_value
    FROM "crypto"."main"."optuna_trial_values"
)

SELECT 
    t.trial_id,
    s.study_name,
    t.state,
    t.datetime_start,
    t.datetime_complete,
    v.objective_value,
    -- Agregamos parámetros como un JSON o columnas pivotadas si se conoce
    (SELECT group_concat(param_name || ': ' || param_value, ', ') FROM params p WHERE p.trial_id = t.trial_id) as params_summary
FROM trials t
JOIN studies s ON t.study_id = s.study_id
LEFT JOIN values v ON t.trial_id = v.trial_id
    );
  
  