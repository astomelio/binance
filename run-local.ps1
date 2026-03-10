# Correr SIN Docker - solo API (monitor testnet)
# pip install -r requirements.txt

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    Write-Host "ERROR: Crea .env con BINANCE_API_KEY y BINANCE_SECRET_KEY" -ForegroundColor Red
    exit 1
}

Write-Host "Iniciando API en http://localhost:8000" -ForegroundColor Green
Write-Host "Monitor: http://localhost:8000/monitor" -ForegroundColor Cyan
Write-Host ""
python run.py
