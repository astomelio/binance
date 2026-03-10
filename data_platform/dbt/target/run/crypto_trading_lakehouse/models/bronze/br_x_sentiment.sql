
  
  create view "crypto"."main"."br_x_sentiment__dbt_tmp" as (
    

select
    account_handle,
    cast(sentiment_score as double) as sentiment_score,
    sentiment_label,
    grok_summary,
    cast(analyzed_at as timestamp) as analyzed_at
from "crypto"."main"."x_account_sentiment"
  );
