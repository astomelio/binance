{{ config(materialized='view') }}

select
    uuid,
    symbol,
    cast(sentiment_score as double) as sentiment_score,
    sentiment_label,
    ai_summary,
    cast(analyzed_at as timestamp) as analyzed_at
from {{ source('raw', 'news_sentiment') }}