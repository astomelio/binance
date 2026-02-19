from __future__ import annotations

from pathlib import Path

from dagster_dbt import DbtCliResource, dbt_assets


DBT_PROJECT_DIR = Path(__file__).resolve().parents[2] / "dbt"


@dbt_assets(manifest=DBT_PROJECT_DIR / "target" / "manifest.json")
def dbt_crypto_assets(context, dbt: DbtCliResource):
    # Requires `dbt parse` or `dbt build` to generate manifest first.
    yield from dbt.cli(["build", "--target", "prod"], context=context).stream()

