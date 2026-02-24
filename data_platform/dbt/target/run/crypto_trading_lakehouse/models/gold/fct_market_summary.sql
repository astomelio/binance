
  
    
    

    create  table
      "crypto"."main"."fct_market_summary__dbt_tmp"
  
    as (
      

-- Resumen agregado del mercado por hora: métricas globales de las 538 monedas
with hourly_data as (
    select
        date_trunc('hour', cast(event_time as timestamp)) as hour,
        symbol,
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
        alpha_signal,
        regime_label,
        vol_label,
        fear_greed_value,
        fed_funds_rate
    from "crypto"."main"."decision_features"
    where futures_last_price > 0
),
market_aggregates as (
    select
        hour,
        count(distinct symbol) as active_symbols,
        -- Momentum distribution
        avg(momentum_3) as avg_momentum_3h,
        avg(momentum_12) as avg_momentum_12h,
        sum(case when momentum_3 > 0 then 1 else 0 end) as symbols_momentum_positive,
        sum(case when momentum_3 < 0 then 1 else 0 end) as symbols_momentum_negative,
        -- Price changes
        avg(price_change_percent_24h) as avg_change_24h,
        max(price_change_percent_24h) as max_gainer_24h,
        min(price_change_percent_24h) as max_loser_24h,
        -- Open Interest
        sum(open_interest) as total_open_interest,
        avg(open_interest) as avg_open_interest,
        -- Volume
        sum(quote_volume_24h) as total_volume_24h,
        avg(quote_volume_24h) as avg_volume_24h,
        -- Funding
        avg(funding_rate_8h) as avg_funding_rate,
        sum(case when funding_rate_8h > 0 then 1 else 0 end) as symbols_positive_funding,
        sum(case when funding_rate_8h < 0 then 1 else 0 end) as symbols_negative_funding,
        -- Basis
        avg(basis_bps) as avg_basis_bps,
        -- Positioning
        avg(long_short_account_ratio) as avg_ls_ratio,
        avg(buy_sell_ratio) as avg_bs_ratio,
        -- Signals
        sum(case when alpha_signal = 'LONG' then 1 else 0 end) as long_signals,
        sum(case when alpha_signal = 'SHORT' then 1 else 0 end) as short_signals,
        sum(case when alpha_signal = 'NO_TRADE' then 1 else 0 end) as no_trade_signals,
        -- Regimes
        sum(case when regime_label = 'BULL' then 1 else 0 end) as symbols_bullish,
        sum(case when regime_label = 'BEAR' then 1 else 0 end) as symbols_bearish,
        sum(case when regime_label = 'NEUTRAL' then 1 else 0 end) as symbols_neutral,
        -- Volatility
        sum(case when vol_label = 'HIGH_VOL' then 1 else 0 end) as symbols_high_vol,
        -- Macro
        max(fear_greed_value) as fear_greed_value,
        max(fed_funds_rate) as fed_funds_rate
    from hourly_data
    group by hour
),
with_derived as (
    select
        *,
        -- Market breadth
        round(symbols_momentum_positive * 100.0 / nullif(active_symbols, 0), 1) as breadth_positive_pct,
        round(symbols_bullish * 100.0 / nullif(active_symbols, 0), 1) as breadth_bullish_pct,
        -- Funding skew
        round(symbols_positive_funding * 100.0 / nullif(active_symbols, 0), 1) as funding_positive_pct,
        -- Signal distribution
        round(long_signals * 100.0 / nullif(active_symbols, 0), 1) as long_signal_pct,
        round(short_signals * 100.0 / nullif(active_symbols, 0), 1) as short_signal_pct,
        -- Market regime
        case
            when symbols_bullish > symbols_bearish * 2 then 'STRONG_BULL'
            when symbols_bullish > symbols_bearish then 'BULL'
            when symbols_bearish > symbols_bullish * 2 then 'STRONG_BEAR'
            when symbols_bearish > symbols_bullish then 'BEAR'
            else 'MIXED'
        end as market_regime,
        -- Volatility regime
        case
            when symbols_high_vol * 100.0 / nullif(active_symbols, 0) > 50 then 'HIGH_VOL_REGIME'
            when symbols_high_vol * 100.0 / nullif(active_symbols, 0) > 25 then 'ELEVATED_VOL'
            else 'LOW_VOL_REGIME'
        end as volatility_regime
    from market_aggregates
)
select
    hour,
    active_symbols,
    -- Momentum
    round(avg_momentum_3h, 3) as avg_momentum_3h,
    round(avg_momentum_12h, 3) as avg_momentum_12h,
    breadth_positive_pct,
    -- Price
    round(avg_change_24h, 2) as avg_change_24h_pct,
    round(max_gainer_24h, 2) as max_gainer_24h_pct,
    round(max_loser_24h, 2) as max_loser_24h_pct,
    -- OI & Volume
    round(total_open_interest, 0) as total_open_interest,
    round(total_volume_24h, 0) as total_volume_24h,
    -- Funding
    round(avg_funding_rate * 10000, 4) as avg_funding_bps,
    funding_positive_pct,
    -- Basis & Positioning
    round(avg_basis_bps, 2) as avg_basis_bps,
    round(avg_ls_ratio, 3) as avg_long_short_ratio,
    -- Signals
    long_signals,
    short_signals,
    long_signal_pct,
    short_signal_pct,
    -- Regimes
    symbols_bullish,
    symbols_bearish,
    breadth_bullish_pct,
    market_regime,
    volatility_regime,
    -- Macro
    fear_greed_value,
    fed_funds_rate
from with_derived
order by hour desc
    );
  
  