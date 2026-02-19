# Orchestration: Dagster + dbt

Orquestador oficial del repo: **Dagster**.

## Por qué Dagster aquí

- Enfoque **asset-based** (bronze/silver/gold como assets nativos).
- Lineage y observabilidad muy claros para equipo pequeño/mediano.
- Integración directa con dbt (`dagster-dbt`).

## Starter incluido

- `dagster/workspace.yaml`
- `dagster/definitions.py`
- `dagster/assets.py`
- `dagster/dbt_assets.py`
- `dagster/README.md`

## Flujo recomendado

1. `bronze` (ingesta cruda)
2. `silver` (normalización)
3. `gold` (features de decisión)
4. `dbt test` (calidad mínima)

