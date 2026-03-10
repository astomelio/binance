# Levanta el stack COMPLETO (API + Dagster + MLflow + Optuna + dbt)
Set-Location $PSScriptRoot
docker compose -f docker-compose.server.yml up -d --remove-orphans
