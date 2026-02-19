# Dagster Setup (Starter)

Este starter usa enfoque **asset-based**:

- `bronze_high_ingestion` (API/derivatives/cross-exchange)
- `bronze_medium_ingestion` (sentiment/DEX/global)
- `bronze_low_ingestion` (macro/FED/onchain)
- `warehouse_raw_load` (carga tablas `raw.*` en DuckDB)
- `warehouse_dbt_build` (materializa `bronze/silver/gold` con dbt)

y opcionalmente assets dbt (si existe `dbt/target/manifest.json`).

## ¿Cómo funciona Dagster?

1. Defines **assets** (datasets/features), no solo tareas.
2. Dagster calcula dependencias (`deps`) y ejecuta en orden.
3. Puedes materializar manualmente, por schedule o por sensores.
4. UI muestra lineage y estado de cada asset.

## Requisitos

Instala dependencias Dagster:

```bash
pip install -r requirements-dagster.txt
```

## Ejecutar UI local

```bash
dagster dev -w data_platform/orchestration/dagster/workspace.yaml
```

Abre: `http://127.0.0.1:3000`

## Deploy en GCP (Terraform)

El deploy de Dagster está integrado en `infra/` y usa:

- Cloud Run service: `dagster-orchestrator`
- Cloud SQL PostgreSQL para metadata
- Secret Manager para password de DB

La imagen usada es `dagster-orchestrator:${dagster_image_tag}`.

## Materializar por CLI

```bash
dagster asset materialize \
  -m data_platform.orchestration.dagster.definitions \
  --select bronze_high_ingestion,silver_high_transform,gold_high_features
```

## Schedule

- `crypto_lake_high_every_5_min`: solo ingestión bronze high
- `crypto_lake_medium_every_30_min`: solo ingestión bronze medium
- `crypto_lake_low_every_4_hours`: solo ingestión bronze low
- `crypto_lake_full_every_4_hours`: ejecuta high+medium+low + `warehouse_raw_load` + `warehouse_dbt_build`

## Integración dbt

1. Materializa vía Dagster:
   ```bash
   make dagster-materialize
   ```
2. O directo dbt local (DuckDB):
   ```bash
   cd data_platform/dbt
   dbt build --target local --profiles-dir .
   ```

DuckDB local queda en:

- `/Users/joaquincano/binance/artifacts/warehouse/crypto.duckdb`

