from __future__ import annotations

from dagster import Definitions

from .assets import (
    bronze_high_ingestion,
    bronze_low_ingestion,
    bronze_medium_ingestion,
    gold_high_features,
    gold_low_features,
    gold_medium_features,
    silver_high_transform,
    silver_low_transform,
    silver_medium_transform,
    warehouse_dbt_build,
    warehouse_raw_load,
)
from .jobs import crypto_lake_full_job, crypto_lake_high_job, crypto_lake_low_job, crypto_lake_medium_job
from .schedules import crypto_lake_full_schedule, crypto_lake_high_schedule, crypto_lake_low_schedule, crypto_lake_medium_schedule

base_assets = [
    bronze_high_ingestion,
    silver_high_transform,
    gold_high_features,
    bronze_medium_ingestion,
    silver_medium_transform,
    gold_medium_features,
    bronze_low_ingestion,
    silver_low_transform,
    gold_low_features,
    warehouse_raw_load,
    warehouse_dbt_build,
]
resources = {}

# dbt integration is optional; loaded only if dagster-dbt is installed and manifest exists.
try:
    from pathlib import Path

    from dagster_dbt import DbtCliResource

    from .dbt_assets import DBT_PROJECT_DIR, dbt_crypto_assets

    manifest_path = DBT_PROJECT_DIR / "target" / "manifest.json"
    if manifest_path.exists():
        base_assets.append(dbt_crypto_assets)
        resources["dbt"] = DbtCliResource(project_dir=DBT_PROJECT_DIR)
except Exception:
    pass


defs = Definitions(
    assets=base_assets,
    jobs=[crypto_lake_high_job, crypto_lake_medium_job, crypto_lake_low_job, crypto_lake_full_job],
    schedules=[crypto_lake_high_schedule, crypto_lake_medium_schedule, crypto_lake_low_schedule, crypto_lake_full_schedule],
    resources=resources,
)

