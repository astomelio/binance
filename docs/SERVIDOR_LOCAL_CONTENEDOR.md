# Servidor local: contenedor con DAGs y procesos

Tu idea: **dejar corriendo en este PC un contenedor** que ya tenga los DAGs (Dagster) y los procesos (datos + training). Así no dependes de cron en el host; todo lo orquesta Dagster dentro del contenedor.

---

## 1. Qué levanta el contenedor

Con **docker-compose** (perfil `full` para incluir Dagster):

- **API** (puerto 8000): endpoints de warehouse y acciones.
- **MLflow** (5001): UI de experimentos y modelos.
- **dbt-docs** (8080): documentación de modelos dbt (opcional).
- **Dagster** (3000): orquestación con DAGs y schedules.
- **PostgreSQL**: metadata de Dagster.

Los **DAGs** en Dagster ya incluyen:

- **Bronze:** ingestión high (cada 5 min), medium (cada 30 min), low (cada 4 h).
- **Warehouse:** carga bronze → DuckDB y **dbt run** (decision_features).
- **Schedules:** 
  - `crypto_lake_full_every_hour`: cada hora, datos completos (bronze + warehouse + dbt).
  - `crypto_lake_full_plus_train_weekly`: **cada domingo 23:00**, datos + **entrenamiento** + **suite de agentes** (modelo + un ciclo tuning→decisión→informe→evolución).
  - **`quant_suite_daily`**: **cada día a las 04:00**, un ciclo de la **suite de agentes** (tuning → decisión → informe → evolución del champion). Usa los datos ya cargados en DuckDB.

Es decir: si levantas el contenedor con Dagster, los procesos de datos corren solos por schedule; una vez a la semana se entrena el modelo y se ejecuta la suite; y **cada día a las 04:00** la suite de agentes corre sola y actualiza el champion.

---

## 2. Cómo levantar el servidor en tu PC

### Requisitos

- Docker y Docker Compose.
- En la raíz del repo: `data_lake`, `artifacts/warehouse`, `artifacts/quant_model` (se crean si no existen al montar).

### Comando (perfil `full` = con Dagster)

```bash
cd /ruta/al/repo
docker compose -f docker-compose.server.yml --profile full up -d
```

Esto levanta API, MLflow, Dagster y Postgres. Para ver logs de Dagster:

```bash
docker compose -f docker-compose.server.yml --profile full logs -f dagster
```

### URLs

- **Dagster UI:** http://localhost:3000 (schedules, jobs, materializar assets a mano).
- **API:** http://localhost:8000.
- **MLflow:** http://localhost:5001.

---

## 3. DAGs y jobs útiles

| Job / Schedule | Qué hace |
|----------------|----------|
| **crypto_lake_high_job** | Solo bronze high (APIs Binance/Bybit/OKX, etc.). |
| **crypto_lake_full_job** | Bronze high + medium + low → warehouse_raw_load → warehouse_dbt_build (DuckDB + dbt). |
| **crypto_lake_full_plus_train_job** | Lo mismo que full + **quant_model_train** + **quant_suite_cycle** (entrena, suite de agentes). |
| **quant_suite_job** | Un ciclo de la **suite de agentes** (tuning → decisión → informe → evolución). |
| **crypto_lake_full_every_hour** (schedule) | Ejecuta `crypto_lake_full_job` cada hora. |
| **crypto_lake_full_plus_train_weekly** (schedule) | Ejecuta `crypto_lake_full_plus_train_job` cada domingo a las 23:00. |
| **quant_suite_daily** (schedule) | Ejecuta **quant_suite_job** cada día a las 04:00 (el “agente” que sigue corriendo la suite). |

En la UI de Dagster (http://localhost:3000) puedes:

- Activar/desactivar schedules.
- Lanzar un job a mano (p. ej. `crypto_lake_full_plus_train_job` para datos + training ya).
- Ver el lineage de assets (bronze → warehouse → quant_model_train).

---

## 4. Volúmenes (persistencia en tu PC)

En `docker-compose.server.yml`, Dagster monta:

- `.:/app` (código).
- `./data_lake:/data/lake` (lake).
- `./artifacts/warehouse:/app/artifacts/warehouse` (DuckDB).
- `./artifacts/quant_model:/app/artifacts/quant_model` (MLflow, reportes, modelo).

Así, la base DuckDB y los modelos viven en tu máquina; al reiniciar el contenedor se siguen usando.

---

## 5. Resumen

| Objetivo | Cómo |
|----------|------|
| Servidor con DAGs y procesos en este PC | `docker compose -f docker-compose.server.yml --profile full up -d`. |
| Datos en tiempo (casi) real | Schedules cada hora (`crypto_lake_full_every_hour`) o cada 5/30 min (high/medium). |
| Modelo nuevo cada semana | Schedule `crypto_lake_full_plus_train_weekly` (domingo 23:00) o lanzar a mano `crypto_lake_full_plus_train_job`. |
| Revisar runs / MLflow | Dagster en :3000, MLflow en :5001. |

Con el contenedor corriendo, ya tienes los DAGs y los procesos (datos + training) ejecutándose solos según los schedules; solo hace falta dejar el PC encendido (o un servidor donde corra el mismo compose).
