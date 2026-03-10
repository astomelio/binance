{{ config(materialized='table') }}

WITH studies AS (
    SELECT * FROM {{ source('raw', 'optuna_studies') }}
),
trials AS (
    SELECT * FROM {{ source('raw', 'optuna_trials') }}
),
params AS (
    SELECT 
        trial_id,
        param_name,
        param_value
    FROM {{ source('raw', 'optuna_trial_params') }}
),
values AS (
    SELECT 
        trial_id,
        objective,
        value as objective_value
    FROM {{ source('raw', 'optuna_trial_values') }}
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
