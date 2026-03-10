
  
  create view "crypto"."main"."br_news_sentiment__dbt_tmp" as (
    

select
    uuid,
    symbol,
    cast(sentiment_score as double) as sentiment_score,
    sentiment_label,
    ai_summary,
    cast(analyzed_at as timestamp) as analyzed_at
from "crypto"."main"."news_sentiment"
  );
