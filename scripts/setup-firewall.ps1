# Configure Windows Firewall for remote access
# MUST be run as Administrator
# Usage: Right-click PowerShell -> Run as Administrator -> .\scripts\setup-firewall.ps1

param(
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

# Check if running as admin
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: This script must be run as Administrator!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Right-click PowerShell and select 'Run as Administrator', then run this script again."
    exit 1
}

$rules = @(
    @{Name="Binance-API-8000"; Port=8000; Description="FastAPI Server for Binance Trading"},
    @{Name="Binance-MLflow-5001"; Port=5001; Description="MLflow UI for ML Experiments"},
    @{Name="Binance-Optuna-8081"; Port=8081; Description="Optuna Dashboard for Hyperparameter Tuning"}
)

if ($Remove) {
    Write-Host "Removing firewall rules..." -ForegroundColor Yellow
    foreach ($rule in $rules) {
        $existing = Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
        if ($existing) {
            Remove-NetFirewallRule -DisplayName $rule.Name
            Write-Host "  Removed: $($rule.Name)" -ForegroundColor Green
        } else {
            Write-Host "  Not found: $($rule.Name)" -ForegroundColor Gray
        }
    }
    Write-Host "Done." -ForegroundColor Green
    exit 0
}

Write-Host "=== Configuring Windows Firewall ===" -ForegroundColor Cyan
Write-Host ""

foreach ($rule in $rules) {
    Write-Host "Port $($rule.Port): $($rule.Description)" -ForegroundColor Yellow
    
    # Check if rule exists
    $existing = Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
    
    if ($existing) {
        Write-Host "  Rule already exists, updating..." -ForegroundColor Gray
        Set-NetFirewallRule -DisplayName $rule.Name -Enabled True -Profile Private,Domain
    } else {
        # Create inbound rule
        New-NetFirewallRule `
            -DisplayName $rule.Name `
            -Description $rule.Description `
            -Direction Inbound `
            -Protocol TCP `
            -LocalPort $rule.Port `
            -Action Allow `
            -Profile Private,Domain `
            -Enabled True | Out-Null
        
        Write-Host "  Created inbound rule" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "=== Firewall Configuration Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Ports opened for Private and Domain networks:"
foreach ($rule in $rules) {
    Write-Host "  - Port $($rule.Port): $($rule.Name)"
}
Write-Host ""
Write-Host "NOTE: Rules are for Private/Domain networks only (not Public) for security." -ForegroundColor Yellow
Write-Host "      If you need Public network access, modify the rules manually." -ForegroundColor Yellow
Write-Host ""
Write-Host "To remove these rules later: .\scripts\setup-firewall.ps1 -Remove" -ForegroundColor Gray
