
        
            delete from "crypto"."main"."br_stock_prices" as DBT_INCREMENTAL_TARGET
            using "br_stock_prices__dbt_tmp20260307100215433142"
            where (
                
                    "br_stock_prices__dbt_tmp20260307100215433142".symbol = DBT_INCREMENTAL_TARGET.symbol
                    and 
                
                    "br_stock_prices__dbt_tmp20260307100215433142".event_time = DBT_INCREMENTAL_TARGET.event_time
                    
                
                
            );
        
    

    insert into "crypto"."main"."br_stock_prices" ("event_time", "symbol", "open_price", "high_price", "low_price", "close_price", "volume")
    (
        select "event_time", "symbol", "open_price", "high_price", "low_price", "close_price", "volume"
        from "br_stock_prices__dbt_tmp20260307100215433142"
    )
  