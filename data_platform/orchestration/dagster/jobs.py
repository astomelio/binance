from __future__ import annotations

from dagster import define_asset_job


crypto_lake_high_job = define_asset_job(
    name="crypto_lake_high_job",
    selection=["bronze_high_ingestion"],
)

crypto_lake_medium_job = define_asset_job(
    name="crypto_lake_medium_job",
    selection=["bronze_medium_ingestion"],
)

crypto_lake_low_job = define_asset_job(
    name="crypto_lake_low_job",
    selection=["bronze_low_ingestion"],
)

crypto_lake_full_job = define_asset_job(
    name="crypto_lake_full_job",
    selection=[
        "bronze_high_ingestion",
        "bronze_medium_ingestion",
        "bronze_low_ingestion",
        "warehouse_raw_load",
        "warehouse_dbt_build",
    ],
)

# Datos + entrenamiento de modelo (para schedule semanal o manual)
crypto_lake_full_plus_train_job = define_asset_job(
    name="crypto_lake_full_plus_train_job",
    selection=[
        "bronze_high_ingestion",
        "bronze_medium_ingestion",
        "bronze_low_ingestion",
        "warehouse_raw_load",
        "warehouse_dbt_build",
        "quant_model_train",
        "quant_suite_cycle",
    ],
)

# Suite de agentes: un ciclo (tuning → decisión → informe → evolución). Lee de DuckDB.
quant_suite_job = define_asset_job(
    name="quant_suite_job",
    selection=["quant_suite_cycle"],
)

