# Start all server services for remote access
# Usage: .\scripts\start-server.ps1
# Services: FastAPI (8000), MLflow (5001), Optuna (8081)

param(
    [switch]$StopAll,
    [switch]$StatusOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$VenvActivate = Join-Path $ProjectRoot "venv\Scripts\Activate.ps1"
$LakeRoot = Join-Path $ProjectRoot "data_lake"
$DbPath = Join-Path $ProjectRoot "artifacts\warehouse\crypto.duckdb"
$MlflowDb = Join-Path $ProjectRoot "artifacts\quant_model\mlflow.db"
$OptunaDb = Join-Path $ProjectRoot "artifacts\quant_model\optuna.db"

$env:LAKE_ROOT = $LakeRoot
$env:DBT_DUCKDB_PATH = $DbPath

function Get-LocalIP {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "Loopback" -and $_.IPAddress -notmatch "^169" } | Select-Object -First 1).IPAddress
    if (-not $ip) { $ip = "localhost" }
    return $ip
}

function Show-Status {
    Write-Host "`n=== Server Status ===" -ForegroundColor Cyan
    
    $processes = @(
        @{Name="FastAPI"; Port=8000; Process="uvicorn"},
        @{Name="MLflow"; Port=5001; Process="mlflow"},
        @{Name="Optuna"; Port=8081; Process="optuna"}
    )
    
    foreach ($svc in $processes) {
        $running = Get-NetTCPConnection -LocalPort $svc.Port -ErrorAction SilentlyContinue
        if ($running) {
            Write-Host "  $($svc.Name) (port $($svc.Port)): " -NoNewline
            Write-Host "RUNNING" -ForegroundColor Green
        } else {
            Write-Host "  $($svc.Name) (port $($svc.Port)): " -NoNewline
            Write-Host "STOPPED" -ForegroundColor Red
        }
    }
    
    $ip = Get-LocalIP
    Write-Host "`n=== Access URLs ===" -ForegroundColor Cyan
    Write-Host "  API Docs:   http://${ip}:8000/docs"
    Write-Host "  Warehouse:  http://${ip}:8000/warehouse/tables"
    Write-Host "  MLflow:     http://${ip}:5001"
    Write-Host "  Optuna:     http://${ip}:8081"
    Write-Host ""
}

function Stop-AllServices {
    Write-Host "Stopping all services..." -ForegroundColor Yellow
    
    # Find and stop processes on our ports
    @(8000, 5001, 8081) | ForEach-Object {
        $port = $_
        $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
        if ($conn) {
            $pid = $conn.OwningProcess | Select-Object -First 1
            if ($pid) {
                Write-Host "  Stopping process on port $port (PID: $pid)"
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            }
        }
    }
    
    Write-Host "All services stopped." -ForegroundColor Green
}

function Start-AllServices {
    $ip = Get-LocalIP
    
    Write-Host "=== Starting Binance Data Server ===" -ForegroundColor Cyan
    Write-Host "Project: $ProjectRoot"
    Write-Host "Local IP: $ip"
    Write-Host ""
    
    # Check if venv exists
    if (-not (Test-Path $VenvPython)) {
        Write-Host "ERROR: Virtual environment not found at $VenvPython" -ForegroundColor Red
        Write-Host "Run: py -3.10 -m venv venv && .\venv\Scripts\pip.exe install -r requirements.txt"
        exit 1
    }
    
    # Create directories if needed
    $dirs = @(
        (Join-Path $ProjectRoot "artifacts\warehouse"),
        (Join-Path $ProjectRoot "artifacts\quant_model"),
        $LakeRoot
    )
    foreach ($dir in $dirs) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }
    
    # Start FastAPI
    Write-Host "[1/3] Starting FastAPI on port 8000..." -ForegroundColor Yellow
    $fastApiRunning = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
    if (-not $fastApiRunning) {
        Start-Process -FilePath $VenvPython -ArgumentList "-m", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000" -WorkingDirectory $ProjectRoot -WindowStyle Hidden
        Start-Sleep -Seconds 2
        Write-Host "  FastAPI started: http://${ip}:8000/docs" -ForegroundColor Green
    } else {
        Write-Host "  FastAPI already running" -ForegroundColor Green
    }
    
    # Start MLflow with visible console (Hidden made it exit; PowerShell wrapper treated stderr as error)
    Write-Host "[2/3] Starting MLflow on port 5001..." -ForegroundColor Yellow
    $mlflowRunning = Get-NetTCPConnection -LocalPort 5001 -ErrorAction SilentlyContinue
    if (-not $mlflowRunning) {
        $mlflowExe = Join-Path $ProjectRoot "venv\Scripts\mlflow.exe"
        $mlflowUri = "sqlite:///" + ($MlflowDb -replace '\\', '/')
        Start-Process -FilePath $mlflowExe -ArgumentList "ui", "--backend-store-uri", $mlflowUri, "--host", "0.0.0.0", "--port", "5001" -WorkingDirectory $ProjectRoot -WindowStyle Normal
        Start-Sleep -Seconds 5
        Write-Host "  MLflow started: http://${ip}:5001 (close the MLflow console window to stop)" -ForegroundColor Green
    } else {
        Write-Host "  MLflow already running" -ForegroundColor Green
    }

    # Start Optuna Dashboard with visible console (only if optuna.db exists)
    Write-Host "[3/3] Starting Optuna Dashboard on port 8081..." -ForegroundColor Yellow
    $optunaRunning = Get-NetTCPConnection -LocalPort 8081 -ErrorAction SilentlyContinue
    if (-not $optunaRunning) {
        if (Test-Path $OptunaDb) {
            $optunaExe = Join-Path $ProjectRoot "venv\Scripts\optuna-dashboard.exe"
            $optunaUri = "sqlite:///" + ($OptunaDb -replace '\\', '/')
            Start-Process -FilePath $optunaExe -ArgumentList $optunaUri, "--host", "0.0.0.0", "--port", "8081" -WorkingDirectory $ProjectRoot -WindowStyle Normal
            Start-Sleep -Seconds 5
            Write-Host "  Optuna Dashboard started: http://${ip}:8081 (close the Optuna window to stop)" -ForegroundColor Green
        } else {
            Write-Host "  Optuna Dashboard skipped (no optuna.db yet)" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  Optuna Dashboard already running" -ForegroundColor Green
    }
    
    Write-Host ""
    Write-Host "=== Server Ready ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "Access from another PC:" -ForegroundColor Cyan
    Write-Host "  API:     http://${ip}:8000/docs"
    Write-Host "  MLflow:  http://${ip}:5001"
    Write-Host "  Optuna:  http://${ip}:8081"
    Write-Host ""
    Write-Host "Quick commands from remote:" -ForegroundColor Cyan
    Write-Host "  curl http://${ip}:8000/warehouse/tables"
    Write-Host "  curl http://${ip}:8000/server/info"
    Write-Host "  curl -X POST http://${ip}:8000/actions/backfill -H 'Content-Type: application/json' -d '{\"symbols\":\"top\",\"months\":36}'"
    Write-Host ""
    Write-Host "To stop all services: .\scripts\start-server.ps1 -StopAll" -ForegroundColor Yellow
}

# Main
if ($StatusOnly) {
    Show-Status
} elseif ($StopAll) {
    Stop-AllServices
} else {
    Start-AllServices
    Show-Status
}
