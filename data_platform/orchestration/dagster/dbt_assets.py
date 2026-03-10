from pathlib import Path
from dagster import AssetExecutionContext, AssetKey, AssetSelection
import os

# Project root path
REPO_ROOT = Path(__file__).resolve().parents[3]
DBT_PROJECT_DIR = REPO_ROOT / "data_platform" / "dbt"
DBT_MANIFEST_PATH = DBT_PROJECT_DIR / "target" / "manifest.json"

try:
    from dagster_dbt import (  # type: ignore
        DbtCliResource,
        DagsterDbtTranslator,
        DagsterDbtTranslatorSettings,
        dbt_assets,
    )
except Exception:  # noqa: BLE001
    # Dagster debe poder arrancar aun si falta dagster-dbt (ej. imagen vieja).
    DbtCliResource = None  # type: ignore
    DagsterDbtTranslator = object  # type: ignore
    DagsterDbtTranslatorSettings = object  # type: ignore
    dbt_assets = None  # type: ignore


# Resource configuration (opcional si dagster-dbt está instalado)
dbt_resource = (
    DbtCliResource(
        project_dir=str(DBT_PROJECT_DIR),
        profiles_dir=str(DBT_PROJECT_DIR),
        target=os.getenv("DBT_TARGET", "local"),
    )
    if DbtCliResource
    else None
)

# Translator to customize Dagster asset metadata
class CustomDagsterDbtTranslator(DagsterDbtTranslator):
    def get_asset_key(self, dbt_resource_props):
        # We can customize the asset key if needed
        return super().get_asset_key(dbt_resource_props)

    def get_group_name(self, dbt_resource_props):
        # Organize models into groups based on their dbt tags or directory structure
        meta = dbt_resource_props.get("meta", {})
        if "dagster_group" in meta:
            return meta["dagster_group"]
        
        path = dbt_resource_props.get("original_file_path", "")
        if "models/bronze" in path:
            return "bronze"
        if "models/silver" in path:
            return "silver"
        if "models/gold" in path:
            return "gold"
        
        return "warehouse"

# Load dbt assets
if DBT_MANIFEST_PATH.exists() and dbt_assets and dbt_resource:
    @dbt_assets(
        manifest=DBT_MANIFEST_PATH,
        dagster_dbt_translator=CustomDagsterDbtTranslator(),
    )
    def trading_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
        db_path = os.getenv("DBT_DUCKDB_PATH", str((REPO_ROOT / "artifacts/warehouse/crypto.duckdb").resolve()))
        # Ensure the path is forward-slash for DuckDB on Windows if injected via env
        db_path = db_path.replace("\\", "/")
        
        yield from dbt.cli(["build"], context=context, env={"DBT_DUCKDB_PATH": db_path}).stream()
else:
    # Fallback or error if manifest is not found during initial load
    # In a real environment, we'd probably want to run dbt parse first.
    trading_dbt_assets = []
