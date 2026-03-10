
        
            delete from "crypto"."main"."br_macro_context"
            where (
                event_time) in (
                select (event_time)
                from "br_macro_context__dbt_tmp20260307100217414062"
            );

        
    

    insert into "crypto"."main"."br_macro_context" ("event_time", "btc_dominance", "total_market_cap_usd", "fear_greed_value", "fed_funds_rate", "next_fed_decision_date", "sp500_close", "oil_wti_usd")
    (
        select "event_time", "btc_dominance", "total_market_cap_usd", "fear_greed_value", "fed_funds_rate", "next_fed_decision_date", "sp500_close", "oil_wti_usd"
        from "br_macro_context__dbt_tmp20260307100217414062"
    )
  