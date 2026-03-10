
        
            delete from "crypto"."main"."slv_decision_features" as DBT_INCREMENTAL_TARGET
            using "slv_decision_features__dbt_tmp20260307100219174024"
            where (
                
                    "slv_decision_features__dbt_tmp20260307100219174024".symbol = DBT_INCREMENTAL_TARGET.symbol
                    and 
                
                    "slv_decision_features__dbt_tmp20260307100219174024".event_time = DBT_INCREMENTAL_TARGET.event_time
                    
                
                
            );
        
    

    insert into "crypto"."main"."slv_decision_features" ("event_time", "symbol", "spot_last_price", "futures_last_price", "basis_bps", "spot_volume", "futures_volume", "mark_price", "index_price", "funding_rate_8h", "open_interest", "price_change_percent_24h", "quote_volume_24h", "long_short_account_ratio", "buy_sell_ratio", "cross_exchange_bid_ask_bps_mean", "cross_exchange_mean_diff_bps", "bybit_okx_delta_bps", "dex_price_usd", "dex_cex_basis_bps", "dex_liquidity_usd", "dex_volume_24h_usd", "dex_txn_imbalance_24h", "btc_dominance", "total_market_cap_usd", "fear_greed_value", "fed_funds_rate", "next_fed_decision_date", "sp500_close", "oil_wti_usd", "sentiment_score_1h", "grok_x_sentiment_1h")
    (
        select "event_time", "symbol", "spot_last_price", "futures_last_price", "basis_bps", "spot_volume", "futures_volume", "mark_price", "index_price", "funding_rate_8h", "open_interest", "price_change_percent_24h", "quote_volume_24h", "long_short_account_ratio", "buy_sell_ratio", "cross_exchange_bid_ask_bps_mean", "cross_exchange_mean_diff_bps", "bybit_okx_delta_bps", "dex_price_usd", "dex_cex_basis_bps", "dex_liquidity_usd", "dex_volume_24h_usd", "dex_txn_imbalance_24h", "btc_dominance", "total_market_cap_usd", "fear_greed_value", "fed_funds_rate", "next_fed_decision_date", "sp500_close", "oil_wti_usd", "sentiment_score_1h", "grok_x_sentiment_1h"
        from "slv_decision_features__dbt_tmp20260307100219174024"
    )
  