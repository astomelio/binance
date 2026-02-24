# Backfill script for Windows
# Usage: .\scripts\backfill-windows.ps1 [-Mode vision-all|vision-top|load|full]

param(
    [Parameter(Position=0)]
    [ValidateSet("vision-all", "vision-top", "load", "full")]
    [string]$Mode = "vision-all"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$LakeRoot = Join-Path $ProjectRoot "data_lake"
$DbPath = Join-Path $ProjectRoot "artifacts\warehouse\crypto.duckdb"

# Set environment variables
$env:LAKE_ROOT = $LakeRoot
$env:DBT_DUCKDB_PATH = $DbPath

Write-Host "=== Binance Data Lake Backfill (Windows) ===" -ForegroundColor Cyan
Write-Host "Mode: $Mode"
Write-Host "LAKE_ROOT: $LakeRoot"
Write-Host "DB_PATH: $DbPath"
Write-Host ""

function Run-BackfillVisionAll {
    Write-Host "Downloading ALL symbols from data.binance.vision (~500 symbols, 36 months)..." -ForegroundColor Yellow
    Write-Host "This may take several hours. Progress will be shown." -ForegroundColor Yellow
    Write-Host ""
    
    $env:DP_SYMBOLS = "all"
    & $VenvPython -m data_platform.backfill_from_vision --interval 1h --months 36
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Backfill complete. Run: .\scripts\backfill-windows.ps1 -Mode load" -ForegroundColor Green
    }
}

function Run-BackfillVisionTop {
    Write-Host "Downloading TOP symbols from data.binance.vision (~20 symbols, 36 months)..." -ForegroundColor Yellow
    
    $env:DP_SYMBOLS = "top"
    & $VenvPython -m data_platform.backfill_from_vision --interval 1h --months 36
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Backfill complete. Run: .\scripts\backfill-windows.ps1 -Mode load" -ForegroundColor Green
    }
}

function Run-Load {
    Write-Host "Loading bronze data into DuckDB..." -ForegroundColor Yellow
    
    & $VenvPython -c @"
from data_platform.config import DataPlatformConfig
from data_platform.loaders.bronze_to_duckdb import load_bronze_to_duckdb
import os

cfg = DataPlatformConfig()
db_path = os.environ.get('DBT_DUCKDB_PATH', 'artifacts/warehouse/crypto.duckdb')
count = load_bronze_to_duckdb(cfg, db_path)
print(f'Loaded {count} records into DuckDB')
"@
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Load complete. DuckDB ready at: $DbPath" -ForegroundColor Green
    }
}

switch ($Mode) {
    "vision-all" { Run-BackfillVisionAll }
    "vision-top" { Run-BackfillVisionTop }
    "load" { Run-Load }
    "full" {
        Run-BackfillVisionAll
        if ($LASTEXITCODE -eq 0) { Run-Load }
    }
}
