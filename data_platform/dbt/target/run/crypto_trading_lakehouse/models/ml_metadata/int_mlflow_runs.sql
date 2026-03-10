
  
    
    

    create  table
      "crypto"."main"."int_mlflow_runs__dbt_tmp"
  
    as (
      

WITH runs AS (
    SELECT * FROM "crypto"."main"."mlflow_runs"
),
metrics AS (
    SELECT 
        run_uuid,
        key as metric_name,
        value as metric_value
    FROM "crypto"."main"."mlflow_metrics"
),
params AS (
    SELECT 
        run_uuid,
        key as param_name,
        value as param_value
    FROM "crypto"."main"."mlflow_params"
),
tags AS (
    SELECT 
        run_uuid,
        key as tag_name,
        value as tag_value
    FROM "crypto"."main"."mlflow_tags"
)

SELECT 
    r.run_uuid,
    r.experiment_id,
    r.name as run_name,
    r.status,
    r.start_time,
    r.end_time,
    -- Agregamos algunas métricas comunes como columnas si existen
    MAX(CASE WHEN m.metric_name = 'accuracy' THEN m.metric_value END) as accuracy,
    MAX(CASE WHEN m.metric_name = 'loss' THEN m.metric_value END) as loss,
    -- Agregamos tags importantes
    MAX(CASE WHEN t.tag_name = 'model_type' THEN t.tag_value END) as model_type,
    MAX(CASE WHEN t.tag_name = 'mlflow.runName' THEN t.tag_value END) as display_name
FROM runs r
LEFT JOIN metrics m ON r.run_uuid = m.run_uuid
LEFT JOIN tags t ON r.run_uuid = t.run_uuid
GROUP BY 1, 2, 3, 4, 5, 6
    );
  
  