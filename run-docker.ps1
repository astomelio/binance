# Ejecuta el stack Docker (API + Dagster)
# Requiere: .env con BINANCE_API_KEY, BINANCE_SECRET_KEY

$ErrorActionPreference = "Stop"

Write-Host "=== Binance Pipeline Docker ===" -ForegroundColor Cyan

# Crear directorios si no existen
$dirs = @("data_lake", "artifacts", "artifacts/warehouse", "artifacts/quant_model", "artifacts/dagster")
foreach ($d in $dirs) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
        Write-Host "  Creado: $d"
    }
}

# Verificar .env
if (-not (Test-Path ".env")) {
    Write-Host "ERROR: Crea .env con BINANCE_API_KEY y BINANCE_SECRET_KEY" -ForegroundColor Red
    exit 1
}

Write-Host "`nLevantando servicios..." -ForegroundColor Yellow
docker compose -f docker-compose.run.yml up -d --build

if ($LASTEXITCODE -ne 0) {
    Write-Host "`nBuild fallo. Si ya tienes imagenes, prueba sin --build:" -ForegroundColor Yellow
    Write-Host "  docker compose -f docker-compose.run.yml up -d" -ForegroundColor Gray
    exit 1
}

Write-Host "`n=== Listo ===" -ForegroundColor Green
Write-Host "  API:     http://localhost:8000"
Write-Host "  Monitor: http://localhost:8000/monitor"
Write-Host "  Dagster: http://localhost:3000"
Write-Host "`nLogs: docker compose -f docker-compose.run.yml logs -f"
