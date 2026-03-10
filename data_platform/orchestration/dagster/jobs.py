from __future__ import annotations

from dagster import AssetSelection, define_asset_job

# Bronze-only jobs (per frequency group)
bronze_high_job = define_asset_job(
    name="01_datos_cripto",
    selection=AssetSelection.assets("bronze_high"),
    tags={"job": "datos_cripto", "desc": "Binance, Bybit, OKX"},
)

bronze_medium_job = define_asset_job(
    name="02_datos_medio",
    selection=AssetSelection.assets("bronze_medium"),
    tags={"job": "datos_medio", "desc": "CoinGecko, Fear&Greed, DEX"},
)

bronze_low_job = define_asset_job(
    name="03_datos_macro",
    selection=AssetSelection.assets("bronze_low"),
    tags={"job": "datos_macro", "desc": "FRED, FED, on-chain"},
)

# Full data pipeline: bronze (all) → warehouse load → dbt build + sentiment + x_tracking
data_pipeline_job = define_asset_job(
    name="04_pipeline_datos_completo",
    selection=AssetSelection.assets(
        "bronze_high", "bronze_medium", "bronze_low", "stock_market_ingest",
        "warehouse_raw_load", "ml_metadata_sync", "warehouse_dbt_build", "news_sentiment_analysis", "x_account_tracking"
    ),
    tags={"job": "pipeline_datos", "desc": "Carga todo + dbt + sentimiento"},
)

# Full pipeline + ML training + agent suite
full_pipeline_job = define_asset_job(
    name="05_pipeline_full_con_ml",
    selection=AssetSelection.assets(
        "bronze_high", "bronze_medium", "bronze_low", "stock_market_ingest",
        "warehouse_raw_load", "ml_metadata_sync", "warehouse_dbt_build", "news_sentiment_analysis", "x_account_tracking",
        "quant_model_train", "quant_suite_cycle", "quant_risk_evaluation", "execute_pending_orders"
    ),
    tags={"job": "pipeline_full", "desc": "Todo + entrenar modelos + risk engine + execution"},
)

# Train + suite only (assumes warehouse data is fresh)
ml_train_suite_job = define_asset_job(
    name="06_entrenar_modelos",
    selection=AssetSelection.assets("quant_model_train", "quant_suite_cycle", "quant_risk_evaluation", "execute_pending_orders"),
    tags={"job": "entrenar", "desc": "LightGBM/RF + Optuna suite + risk + execution"},
)

# Suite-only (assumes data is fresh)
quant_suite_job = define_asset_job(
    name="07_optimizar_suite",
    selection=AssetSelection.assets("quant_suite_cycle"),
    tags={"job": "optimizar", "desc": "Solo Optuna"},
)

# Operación Testnet cada 15 min: datos + risk + ejecución
trading_execution_job = define_asset_job(
    name="08_operacion_testnet_15m",
    selection=AssetSelection.assets(
        "bronze_high", "bronze_medium", "bronze_low", "stock_market_ingest",
        "warehouse_raw_load", "ml_metadata_sync", "warehouse_dbt_build",
        "quant_risk_evaluation", "execute_pending_orders"
    ),
    tags={"job": "trading_live", "desc": "Datos + risk + ejecución Testnet (frame 15m)"},
)

# Solo risk + ejecución (usa datos ya materializados por 04; para no duplicar pipeline)
execution_only_job = define_asset_job(
    name="09_ejecutar_testnet_solo",
    selection=AssetSelection.assets("quant_risk_evaluation", "execute_pending_orders"),
    tags={"job": "execution_only", "desc": "Risk + ejecución sin refresco (frame 1h)"},
)

# Optimizar RiskEngine (max_open_trades, max_position_size_pct) vía backtest
risk_optimize_job = define_asset_job(
    name="10_optimizar_risk_engine",
    selection=AssetSelection.assets("quant_risk_optimize"),
    tags={"job": "risk_optimize", "desc": "Backtest para optimizar entradas y monedas"},
)
