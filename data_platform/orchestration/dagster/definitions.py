from __future__ import annotations

from dagster import Definitions, multiprocess_executor

from .assets import (
    bronze_high,
    bronze_low,
    bronze_medium,
    stock_market_ingest,
    news_sentiment_analysis,
    x_account_tracking,
    quant_model_train,
    quant_suite_cycle,
    quant_risk_optimize,
    quant_risk_evaluation,
    execute_pending_orders,
    warehouse_dbt_build,
    warehouse_raw_load,
    ml_metadata_sync,
)
from .dbt_assets import trading_dbt_assets, dbt_resource
from .backfill_ops import backfill_full_job, reload_external_job
from .jobs import (
    bronze_high_job,
    bronze_low_job,
    bronze_medium_job,
    data_pipeline_job,
    execution_only_job,
    full_pipeline_job,
    ml_train_suite_job,
    quant_suite_job,
    risk_optimize_job,
    trading_execution_job,
)
from .schedules import (
    bronze_high_schedule,
    bronze_low_schedule,
    bronze_medium_schedule,
    data_pipeline_hourly_schedule,
    execution_only_schedule,
    full_pipeline_weekly_schedule,
    ml_train_suite_schedule,
    quant_suite_schedule,
    trading_execution_schedule,
)

# Assets: Python-defined + dbt (si manifest existe; si no, trading_dbt_assets es [])
_asset_list = [
    bronze_high,
    bronze_medium,
    bronze_low,
    stock_market_ingest,
    news_sentiment_analysis,
    x_account_tracking,
    warehouse_raw_load,
    ml_metadata_sync,
    warehouse_dbt_build,
    quant_model_train,
    quant_suite_cycle,
    quant_risk_optimize,
    quant_risk_evaluation,
    execute_pending_orders,
]
if not isinstance(trading_dbt_assets, list):
    _asset_list.append(trading_dbt_assets)

defs = Definitions(
    executor=multiprocess_executor.configured({"max_concurrent": 1}),
    assets=_asset_list,
    jobs=[
        backfill_full_job,
        reload_external_job,
        bronze_high_job,
        bronze_medium_job,
        bronze_low_job,
        data_pipeline_job,
        execution_only_job,
        full_pipeline_job,
        ml_train_suite_job,
        quant_suite_job,
        risk_optimize_job,
        trading_execution_job,
    ],
    schedules=[
        bronze_high_schedule,
        bronze_medium_schedule,
        bronze_low_schedule,
        data_pipeline_hourly_schedule,
        execution_only_schedule,
        full_pipeline_weekly_schedule,
        ml_train_suite_schedule,
        quant_suite_schedule,
        trading_execution_schedule,
    ],
    resources={
        "dbt": dbt_resource,
    } if dbt_resource else {},
)
