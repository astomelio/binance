{{ config(materialized='table') }}

-- Métricas de rendimiento por símbolo: Sharpe, volatilidad, drawdown, retornos
with base as (
    select
        symbol,
        event_time,
        futures_last_price,
        lag(futures_last_price, 1) over (partition by symbol order by event_time) as prev_price,
        case
            when lag(futures_last_price, 1) over (partition by symbol order by event_time) > 0
            then (futures_last_price - lag(futures_last_price, 1) over (partition by symbol order by event_time)) 
                 / lag(futures_last_price, 1) over (partition by symbol order by event_time)
            else 0
        end as hourly_return
    from {{ ref('slv_decision_features') }}
    where futures_last_price > 0
),
daily_stats as (
    select
        symbol,
        date_trunc('day', cast(event_time as timestamp)) as trade_date,
        count(*) as hourly_observations,
        avg(hourly_return) as avg_hourly_return,
        stddev(hourly_return) as hourly_volatility,
        min(futures_last_price) as daily_low,
        max(futures_last_price) as daily_high,
        first(futures_last_price) as daily_open,
        last(futures_last_price) as daily_close
    from base
    where hourly_return is not null
    group by 1, 2
),
symbol_metrics as (
    select
        symbol,
        count(distinct trade_date) as trading_days,
        sum(hourly_observations) as total_observations,
        -- Returns
        avg(avg_hourly_return) * 24 * 365 as annualized_return,
        -- Volatility (annualized)
        avg(hourly_volatility) * sqrt(24 * 365) as annualized_volatility,
        -- Sharpe (assuming 0% risk-free rate)
        case 
            when avg(hourly_volatility) > 0 
            then (avg(avg_hourly_return) * 24 * 365) / (avg(hourly_volatility) * sqrt(24 * 365))
            else 0
        end as sharpe_ratio,
        -- Max drawdown approximation
        min((daily_close - daily_high) / nullif(daily_high, 0)) as max_daily_drawdown,
        -- Average daily range
        avg((daily_high - daily_low) / nullif(daily_low, 0)) as avg_daily_range,
        -- Price stats
        min(daily_low) as all_time_low,
        max(daily_high) as all_time_high,
        last(daily_close order by trade_date) as latest_price,
        first(daily_open order by trade_date) as first_price
    from daily_stats
    group by symbol
),
with_total_return as (
    select
        *,
        case 
            when first_price > 0 
            then (latest_price - first_price) / first_price * 100
            else 0
        end as total_return_pct,
        -- Rank by performance
        row_number() over (order by sharpe_ratio desc) as sharpe_rank,
        row_number() over (order by annualized_return desc) as return_rank,
        row_number() over (order by annualized_volatility asc) as volatility_rank
    from symbol_metrics
)
select
    symbol,
    trading_days,
    total_observations,
    round(annualized_return * 100, 2) as annualized_return_pct,
    round(annualized_volatility * 100, 2) as annualized_volatility_pct,
    round(sharpe_ratio, 3) as sharpe_ratio,
    round(max_daily_drawdown * 100, 2) as max_daily_drawdown_pct,
    round(avg_daily_range * 100, 2) as avg_daily_range_pct,
    round(total_return_pct, 2) as total_return_pct,
    all_time_low,
    all_time_high,
    latest_price,
    sharpe_rank,
    return_rank,
    volatility_rank,
    -- Categorización
    case
        when sharpe_ratio > 1.5 then 'EXCELLENT'
        when sharpe_ratio > 0.5 then 'GOOD'
        when sharpe_ratio > 0 then 'NEUTRAL'
        else 'POOR'
    end as performance_tier,
    case
        when annualized_volatility < 0.5 then 'LOW_VOL'
        when annualized_volatility < 1.0 then 'MEDIUM_VOL'
        else 'HIGH_VOL'
    end as volatility_tier
from with_total_return
