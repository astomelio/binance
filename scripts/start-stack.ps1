# Arranca todo el stack (API + Dagster + Postgres)
# Uso: .\scripts\start-stack.ps1
# Si falla el mount de LAKE_ROOT: crea .\data_lake y ejecuta de nuevo

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

# Crear data_lake si no existe (evita fallo de mount en Windows)
$dataLake = Join-Path $ProjectRoot "data_lake"
if (-not (Test-Path $dataLake)) {
    New-Item -ItemType Directory -Path $dataLake -Force | Out-Null
    Write-Host "Creado data_lake en $dataLake"
}

# Si LAKE_ROOT_HOST no está en .env, usa data_lake local
if (-not $env:LAKE_ROOT_HOST) {
    $env:LAKE_ROOT_HOST = (Resolve-Path $dataLake).Path
}

Write-Host "Arrancando stack (API + Dagster + Postgres)..."
docker compose up -d --build

Write-Host "`nEsperando servicios (30s)..."
Start-Sleep -Seconds 30

docker compose ps -a
Write-Host "`nAPI: http://localhost:8000 | Dagster: http://localhost:3000"
