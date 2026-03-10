
        
            delete from "crypto"."main"."decision_features"
            where (
                feature_id) in (
                select (feature_id)
                from "decision_features__dbt_tmp20260307100220921336"
            );

        
    

    insert into "crypto"."main"."decision_features" ("feature_id", "event_time", "symbol", "spot_last_price", "futures_last_price", "basis_bps", "spot_volume", "futures_volume", "mark_price", "index_price", "funding_rate_8h", "open_interest", "price_change_percent_24h", "quote_volume_24h", "long_short_account_ratio", "buy_sell_ratio", "cross_exchange_bid_ask_bps_mean", "cross_exchange_mean_diff_bps", "bybit_okx_delta_bps", "cross_exchange_score", "dex_price_usd", "dex_cex_basis_bps", "dex_liquidity_usd", "dex_volume_24h_usd", "dex_txn_imbalance_24h", "dex_alpha_score", "btc_dominance", "total_market_cap_usd", "fear_greed_value", "fed_funds_rate", "next_fed_decision_date", "sp500_close", "oil_wti_usd", "momentum_3", "momentum_12", "momentum_score", "session_band", "session_overlap_score", "session_us_open", "session_china_open", "session_us_or_china_open", "earnings_window", "alpha_microstructure_score", "liquidity_event_score", "liquidity_event_label", "fed_window", "alpha_signal", "regime_label", "vol_label", "spread_bps", "depth_imbalance_score", "microprice", "depth_slope_proxy", "order_flow_imbalance", "spread_momentum_bps", "price_zscore_24h", "price_deviation_pct_24h", "alpha_score", "fwd_return_1h", "fwd_return_4h", "fwd_return_24h", "regime_combo")
    (
        select "feature_id", "event_time", "symbol", "spot_last_price", "futures_last_price", "basis_bps", "spot_volume", "futures_volume", "mark_price", "index_price", "funding_rate_8h", "open_interest", "price_change_percent_24h", "quote_volume_24h", "long_short_account_ratio", "buy_sell_ratio", "cross_exchange_bid_ask_bps_mean", "cross_exchange_mean_diff_bps", "bybit_okx_delta_bps", "cross_exchange_score", "dex_price_usd", "dex_cex_basis_bps", "dex_liquidity_usd", "dex_volume_24h_usd", "dex_txn_imbalance_24h", "dex_alpha_score", "btc_dominance", "total_market_cap_usd", "fear_greed_value", "fed_funds_rate", "next_fed_decision_date", "sp500_close", "oil_wti_usd", "momentum_3", "momentum_12", "momentum_score", "session_band", "session_overlap_score", "session_us_open", "session_china_open", "session_us_or_china_open", "earnings_window", "alpha_microstructure_score", "liquidity_event_score", "liquidity_event_label", "fed_window", "alpha_signal", "regime_label", "vol_label", "spread_bps", "depth_imbalance_score", "microprice", "depth_slope_proxy", "order_flow_imbalance", "spread_momentum_bps", "price_zscore_24h", "price_deviation_pct_24h", "alpha_score", "fwd_return_1h", "fwd_return_4h", "fwd_return_24h", "regime_combo"
        from "decision_features__dbt_tmp20260307100220921336"
    )
  