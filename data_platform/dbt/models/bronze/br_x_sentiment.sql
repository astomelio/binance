{{ config(materialized='view') }}

select
    account_handle,
    cast(sentiment_score as double) as sentiment_score,
    sentiment_label,
    grok_summary,
    cast(analyzed_at as timestamp) as analyzed_at
from {{ source('raw', 'x_account_sentiment') }}