
  
    
    

    create  table
      "crypto"."main"."fct_momentum_rankings__dbt_tmp"
  
    as (
      

-- Rankings de momentum actualizados por hora para todos los símbolos
with latest_data as (
    select
        symbol,
        event_time,
        futures_last_price,
        momentum_3,
        momentum_12,
        momentum_score,
        funding_rate_8h,
        open_interest,
        quote_volume_24h,
        price_change_percent_24h,
        regime_label,
        vol_label,
        alpha_signal,
        row_number() over (partition by symbol order by event_time desc) as rn
    from "crypto"."main"."decision_features"
    where futures_last_price > 0
),
current_state as (
    select * from latest_data where rn = 1
),
with_rankings as (
    select
        symbol,
        event_time as last_update,
        futures_last_price,
        momentum_3,
        momentum_12,
        momentum_score,
        funding_rate_8h,
        open_interest,
        quote_volume_24h,
        price_change_percent_24h,
        regime_label,
        vol_label,
        alpha_signal,
        -- Rankings
        row_number() over (order by momentum_3 desc) as momentum_3h_rank,
        row_number() over (order by momentum_12 desc) as momentum_12h_rank,
        row_number() over (order by momentum_score desc) as momentum_score_rank,
        row_number() over (order by price_change_percent_24h desc) as change_24h_rank,
        row_number() over (order by open_interest desc) as oi_rank,
        row_number() over (order by quote_volume_24h desc) as volume_rank,
        row_number() over (order by abs(funding_rate_8h) desc) as funding_rank,
        -- Percentiles
        percent_rank() over (order by momentum_score) as momentum_percentile,
        percent_rank() over (order by quote_volume_24h) as volume_percentile,
        percent_rank() over (order by open_interest) as oi_percentile
    from current_state
)
select
    symbol,
    last_update,
    futures_last_price,
    round(momentum_3, 2) as momentum_3h_pct,
    round(momentum_12, 2) as momentum_12h_pct,
    round(momentum_score, 3) as momentum_score,
    round(price_change_percent_24h, 2) as change_24h_pct,
    funding_rate_8h,
    open_interest,
    quote_volume_24h,
    regime_label,
    vol_label,
    alpha_signal,
    -- Rankings
    momentum_3h_rank,
    momentum_12h_rank,
    momentum_score_rank,
    change_24h_rank,
    oi_rank,
    volume_rank,
    funding_rank,
    -- Percentiles
    round(momentum_percentile * 100, 1) as momentum_percentile,
    round(volume_percentile * 100, 1) as volume_percentile,
    round(oi_percentile * 100, 1) as oi_percentile,
    -- Composite rank (lower is better)
    (momentum_score_rank + volume_rank + oi_rank) / 3.0 as composite_rank,
    -- Categorías
    case
        when momentum_score_rank <= 20 then 'TOP_MOMENTUM'
        when momentum_score_rank <= 50 then 'HIGH_MOMENTUM'
        when momentum_score_rank <= 200 then 'MEDIUM_MOMENTUM'
        else 'LOW_MOMENTUM'
    end as momentum_tier,
    case
        when volume_rank <= 20 then 'HIGH_VOLUME'
        when volume_rank <= 100 then 'MEDIUM_VOLUME'
        else 'LOW_VOLUME'
    end as volume_tier
from with_rankings
order by momentum_score_rank
    );
  
  