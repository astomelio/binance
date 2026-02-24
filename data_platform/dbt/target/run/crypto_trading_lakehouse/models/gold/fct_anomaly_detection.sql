
  
    
    

    create  table
      "crypto"."main"."fct_anomaly_detection__dbt_tmp"
  
    as (
      

-- Detección de anomalías: movimientos extremos, volumen inusual, funding extremo
with base as (
    select
        symbol,
        event_time,
        futures_last_price,
        momentum_3,
        momentum_12,
        price_change_percent_24h,
        open_interest,
        quote_volume_24h,
        funding_rate_8h,
        basis_bps,
        long_short_account_ratio,
        buy_sell_ratio,
        liquidity_event_score,
        liquidity_event_label,
        alpha_signal
    from "crypto"."main"."decision_features"
    where futures_last_price > 0
),
symbol_stats as (
    select
        symbol,
        avg(momentum_3) as avg_momentum_3,
        stddev(momentum_3) as std_momentum_3,
        avg(quote_volume_24h) as avg_volume,
        stddev(quote_volume_24h) as std_volume,
        avg(abs(funding_rate_8h)) as avg_abs_funding,
        stddev(funding_rate_8h) as std_funding,
        avg(abs(basis_bps)) as avg_abs_basis,
        stddev(basis_bps) as std_basis
    from base
    group by symbol
),
with_zscore as (
    select
        b.*,
        s.avg_momentum_3,
        s.std_momentum_3,
        s.avg_volume,
        s.std_volume,
        s.avg_abs_funding,
        s.std_funding,
        s.avg_abs_basis,
        s.std_basis,
        -- Z-scores
        case 
            when s.std_momentum_3 > 0 
            then (b.momentum_3 - s.avg_momentum_3) / s.std_momentum_3
            else 0
        end as momentum_zscore,
        case 
            when s.std_volume > 0 
            then (b.quote_volume_24h - s.avg_volume) / s.std_volume
            else 0
        end as volume_zscore,
        case 
            when s.std_funding > 0 
            then (b.funding_rate_8h - 0) / s.std_funding
            else 0
        end as funding_zscore,
        case 
            when s.std_basis > 0 
            then (b.basis_bps - 0) / s.std_basis
            else 0
        end as basis_zscore
    from base b
    join symbol_stats s using (symbol)
),
anomalies as (
    select
        *,
        -- Anomaly flags
        case when abs(momentum_zscore) > 3 then 1 else 0 end as momentum_anomaly,
        case when volume_zscore > 3 then 1 else 0 end as volume_spike,
        case when abs(funding_zscore) > 3 then 1 else 0 end as funding_extreme,
        case when abs(basis_zscore) > 3 then 1 else 0 end as basis_extreme,
        case when abs(price_change_percent_24h) > 10 then 1 else 0 end as price_crash_pump,
        case when liquidity_event_score > 0.7 then 1 else 0 end as liquidity_event,
        -- Anomaly type
        case
            when momentum_3 > 5 and volume_zscore > 2 then 'PUMP'
            when momentum_3 < -5 and volume_zscore > 2 then 'DUMP'
            when abs(funding_zscore) > 3 and abs(basis_zscore) > 2 then 'FUNDING_SQUEEZE'
            when long_short_account_ratio > 2.0 then 'EXTREME_LONG_CROWDING'
            when long_short_account_ratio < 0.5 then 'EXTREME_SHORT_CROWDING'
            when volume_zscore > 4 then 'VOLUME_EXPLOSION'
            when liquidity_event_label in ('LONG_CROWDING', 'SHORT_CROWDING') then liquidity_event_label
            else null
        end as anomaly_type,
        -- Severity score (0-10)
        least(10, (
            abs(momentum_zscore) * 1.5 +
            greatest(0, volume_zscore) * 1.0 +
            abs(funding_zscore) * 1.5 +
            abs(basis_zscore) * 1.0 +
            abs(price_change_percent_24h) * 0.3
        )) as severity_score
    from with_zscore
)
select
    symbol,
    event_time,
    futures_last_price,
    -- Metrics
    round(momentum_3, 2) as momentum_3h_pct,
    round(price_change_percent_24h, 2) as change_24h_pct,
    round(quote_volume_24h, 0) as volume_24h,
    round(funding_rate_8h * 10000, 4) as funding_bps,
    round(basis_bps, 2) as basis_bps,
    round(long_short_account_ratio, 3) as ls_ratio,
    -- Z-scores
    round(momentum_zscore, 2) as momentum_zscore,
    round(volume_zscore, 2) as volume_zscore,
    round(funding_zscore, 2) as funding_zscore,
    round(basis_zscore, 2) as basis_zscore,
    -- Flags
    momentum_anomaly,
    volume_spike,
    funding_extreme,
    basis_extreme,
    price_crash_pump,
    liquidity_event,
    -- Anomaly info
    anomaly_type,
    round(severity_score, 1) as severity_score,
    liquidity_event_label,
    alpha_signal,
    -- Total anomaly score
    (momentum_anomaly + volume_spike + funding_extreme + basis_extreme + price_crash_pump + liquidity_event) as anomaly_count
from anomalies
where anomaly_type is not null
   or severity_score > 5
   or momentum_anomaly = 1
   or volume_spike = 1
   or funding_extreme = 1
order by event_time desc, severity_score desc
    );
  
  