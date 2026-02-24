

-- Perfil de liquidez por símbolo: OI, volumen, funding, spreads
with base as (
    select
        symbol,
        event_time,
        open_interest,
        quote_volume_24h,
        funding_rate_8h,
        long_short_account_ratio,
        buy_sell_ratio,
        futures_volume,
        spot_volume,
        basis_bps
    from "crypto"."main"."slv_decision_features"
    where futures_last_price > 0
),
symbol_liquidity as (
    select
        symbol,
        count(*) as total_observations,
        -- Open Interest
        avg(open_interest) as avg_open_interest,
        max(open_interest) as max_open_interest,
        min(open_interest) as min_open_interest,
        stddev(open_interest) as oi_volatility,
        -- Volume
        avg(quote_volume_24h) as avg_daily_volume,
        max(quote_volume_24h) as max_daily_volume,
        sum(futures_volume) as total_futures_volume,
        sum(spot_volume) as total_spot_volume,
        -- Funding
        avg(funding_rate_8h) as avg_funding_rate,
        stddev(funding_rate_8h) as funding_volatility,
        avg(abs(funding_rate_8h)) as avg_abs_funding,
        -- Positioning
        avg(long_short_account_ratio) as avg_ls_ratio,
        avg(buy_sell_ratio) as avg_bs_ratio,
        stddev(long_short_account_ratio) as ls_ratio_volatility,
        -- Basis
        avg(basis_bps) as avg_basis_bps,
        stddev(basis_bps) as basis_volatility,
        avg(abs(basis_bps)) as avg_abs_basis
    from base
    group by symbol
),
with_scores as (
    select
        *,
        -- Liquidity score (0-100)
        least(100, (
            least(avg_open_interest / 10000000.0, 1.0) * 40 +
            least(avg_daily_volume / 500000000.0, 1.0) * 40 +
            (1.0 - least(avg_abs_basis / 20.0, 1.0)) * 20
        )) as liquidity_score,
        -- Rankings
        row_number() over (order by avg_open_interest desc) as oi_rank,
        row_number() over (order by avg_daily_volume desc) as volume_rank,
        row_number() over (order by abs(avg_funding_rate) desc) as funding_rank
    from symbol_liquidity
)
select
    symbol,
    total_observations,
    -- Open Interest
    round(avg_open_interest, 0) as avg_open_interest,
    round(max_open_interest, 0) as max_open_interest,
    round(oi_volatility, 0) as oi_volatility,
    oi_rank,
    -- Volume
    round(avg_daily_volume, 0) as avg_daily_volume_usd,
    round(max_daily_volume, 0) as max_daily_volume_usd,
    round(total_futures_volume, 0) as total_futures_volume,
    volume_rank,
    -- Funding
    round(avg_funding_rate * 10000, 4) as avg_funding_rate_bps,
    round(funding_volatility * 10000, 4) as funding_volatility_bps,
    funding_rank,
    -- Positioning
    round(avg_ls_ratio, 3) as avg_long_short_ratio,
    round(avg_bs_ratio, 3) as avg_buy_sell_ratio,
    round(ls_ratio_volatility, 3) as positioning_volatility,
    -- Basis
    round(avg_basis_bps, 2) as avg_basis_bps,
    round(basis_volatility, 2) as basis_volatility_bps,
    -- Scores
    round(liquidity_score, 1) as liquidity_score,
    -- Tiers
    case
        when oi_rank <= 20 then 'TIER_1'
        when oi_rank <= 50 then 'TIER_2'
        when oi_rank <= 150 then 'TIER_3'
        else 'TIER_4'
    end as liquidity_tier,
    case
        when avg_funding_rate > 0.0001 then 'BULLISH_FUNDING'
        when avg_funding_rate < -0.0001 then 'BEARISH_FUNDING'
        else 'NEUTRAL_FUNDING'
    end as funding_bias,
    case
        when avg_ls_ratio > 1.2 then 'LONG_HEAVY'
        when avg_ls_ratio < 0.8 then 'SHORT_HEAVY'
        else 'BALANCED'
    end as positioning_bias
from with_scores
order by liquidity_score desc