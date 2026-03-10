
        
            delete from "crypto"."main"."br_market_snapshot" as DBT_INCREMENTAL_TARGET
            using "br_market_snapshot__dbt_tmp20260307100217541439"
            where (
                
                    "br_market_snapshot__dbt_tmp20260307100217541439".symbol = DBT_INCREMENTAL_TARGET.symbol
                    and 
                
                    "br_market_snapshot__dbt_tmp20260307100217541439".event_time = DBT_INCREMENTAL_TARGET.event_time
                    
                
                
            );
        
    

    insert into "crypto"."main"."br_market_snapshot" ("event_time", "symbol", "spot_last_price", "futures_last_price", "spot_volume", "futures_volume", "mark_price", "index_price", "funding_rate_8h", "open_interest", "price_change_percent_24h", "quote_volume_24h", "long_short_account_ratio", "buy_sell_ratio", "cross_exchange_bid_ask_bps_mean", "cross_exchange_peer_last_price_mean", "bybit_last_price", "okx_last_price", "aster_last_price", "dex_price_usd", "dex_liquidity_usd", "dex_volume_24h_usd", "dex_txn_imbalance_24h")
    (
        select "event_time", "symbol", "spot_last_price", "futures_last_price", "spot_volume", "futures_volume", "mark_price", "index_price", "funding_rate_8h", "open_interest", "price_change_percent_24h", "quote_volume_24h", "long_short_account_ratio", "buy_sell_ratio", "cross_exchange_bid_ask_bps_mean", "cross_exchange_peer_last_price_mean", "bybit_last_price", "okx_last_price", "aster_last_price", "dex_price_usd", "dex_liquidity_usd", "dex_volume_24h_usd", "dex_txn_imbalance_24h"
        from "br_market_snapshot__dbt_tmp20260307100217541439"
    )
  