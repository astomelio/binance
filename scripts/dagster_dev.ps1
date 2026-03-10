# Arrancar Dagster UI sin usar dagster.exe (evita error de launcher con rutas OneDrive/venv viejas).
# Ejecutar desde la raiz del repo: .\scripts\dagster_dev.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path $root)) { $root = (Get-Location).Path }
Set-Location $root
$env:LAKE_ROOT = Join-Path $root "data_lake"
$env:DBT_DUCKDB_PATH = Join-Path $root "artifacts\warehouse\crypto.duckdb"
$env:PYTHONPATH = $root
& python -m dagster dev -w data_platform/orchestration/dagster/workspace.yaml
