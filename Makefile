.PHONY: install test run deploy-dev deploy-prod clean help

# Default target
help:
	@echo "Available commands:"
	@echo "  install     - Install dependencies"
	@echo "  test        - Run tests"
	@echo "  run         - Run locally"
	@echo "  compose-up  - Start API + Dagster + Postgres (Docker Compose)"
	@echo "  compose-down - Stop API + Dagster + Postgres (Docker Compose)"
	@echo "  local-lake-init - Create local external data lake directory"
	@echo "  local-quant-stack - Run pipeline + planner against local stack"
	@echo "  deploy-dev  - Deploy to development stage"
	@echo "  deploy-prod - Deploy to production stage"
	@echo "  clean       - Clean up generated files"
	@echo "  setup       - Initial setup"

# Install dependencies
install:
	pip install -r requirements.txt
	pip install pytest

# Run tests
test:
	python -m pytest tests/ -v

# Run locally
run:
	python run.py

# Run with uvicorn directly
run-uvicorn:
	uvicorn app:app --host 0.0.0.0 --port 8000 --reload

# Run alert engine once
alerts:
	python market_alert_engine.py --once

# Run alert engine in loop (15m)
alerts-loop:
	python market_alert_engine.py --loop-seconds 900

# Reusable model pipeline (backtest + live preview)
model-pipeline:
	python examples/reusable_model_pipeline.py

alpha-serious:
	python examples/serious_alpha_pipeline.py

quant-setup:
	python examples/quant_research_setup.py

strategy-planner:
	python examples/strategy_planner_demo.py

quant-train:
	python examples/quant_train_walkforward.py

quant-train-entry-meta:
	python examples/quant_train_entry_meta.py

quant-oos:
	python examples/quant_inference_oos.py

quant-oos-meta:
	python examples/quant_inference_oos.py --entry-meta-model artifacts/quant_model/entry_meta_model.json --entry-prob-threshold 0.45 --entry-weighting linear --allow-unknown-fed-window --dataset /Users/joaquincano/data/binance_lake/gold/signals/decision_features_backfill

quant-oos-mlflow:
	python examples/quant_inference_oos.py --allow-unknown-fed-window --dataset /Users/joaquincano/data/binance_lake/gold/signals/decision_features_backfill --mlflow-uri sqlite:///artifacts/quant_model/mlflow.db --mlflow-experiment quant-oos

quant-oos-champion:
	python examples/quant_oos_from_registry.py --dataset /Users/joaquincano/data/binance_lake/gold/signals/decision_features_backfill --model-uri models:/quant_alpha_entry_lgbm@champion --mlflow-uri sqlite:///artifacts/quant_model/mlflow.db --allow-unknown-fed-window

quant-champion-challenger:
	@venv/bin/python examples/quant_champion_challenger.py \
		--data-path $(LAKE_ROOT)/gold/signals/decision_features \
		--horizon 4h \
		--mlflow-uri sqlite:///$(PWD)/artifacts/mlflow/mlflow.db \
		--mlflow-experiment champion_challenger

backfill-all-timeframes:
	@echo "Backfilling ALL timeframes (1h, 4h, 1d) with maximum historical data..."
	@venv/bin/python data_platform/backfill_all_timeframes.py --days 1095 --intervals 1h 4h 1d

quant-exec-paper:
	python examples/quant_execute_orders.py --mode paper

quant-exec-live:
	python examples/quant_execute_orders.py --mode live

quant-review:
	python examples/quant_execution_review.py

quant-regime-report:
	python examples/quant_regime_report.py

quant-regime-opt:
	python examples/quant_regime_policy_optimizer.py --allow-unknown-fed-window --mlflow-uri sqlite:///artifacts/quant_model/mlflow.db --mlflow-experiment quant-regime-optimizer

quant-leakage-audit:
	python examples/quant_leakage_audit.py

quant-model-benchmark:
	python examples/quant_model_benchmark.py --mlflow-uri sqlite:///artifacts/quant_model/mlflow.db --mlflow-experiment quant-benchmark

quant-optuna:
	python examples/quant_optuna_tuning.py --trials 120 --mlflow-uri sqlite:///artifacts/quant_model/mlflow.db --mlflow-experiment quant-optuna --register-model-name quant_alpha_entry_lgbm --set-champion-alias

quant-optuna-robust:
	python examples/quant_optuna_tuning.py --trials 120 --optimize-time-windows --lookback-days-grid 15,30,60,90,120 --train-days-grid 45,60,90 --test-days-grid 7,14,21 --step-days-grid 7,14 --mlflow-uri sqlite:///artifacts/quant_model/mlflow.db --mlflow-experiment quant-optuna --register-model-name quant_alpha_entry_lgbm --set-champion-alias

quant-optuna-dashboard:
	optuna-dashboard sqlite:///artifacts/quant_model/optuna.db --host 0.0.0.0 --port 8081

quant-mlflow-ui:
	mlflow ui --backend-store-uri sqlite:///artifacts/quant_model/mlflow.db --host 0.0.0.0 --port 5001

# Data platform ETL
data-bronze:
	python -m data_platform.pipeline --mode bronze

data-silver:
	python -m data_platform.pipeline --mode silver

data-gold:
	python -m data_platform.pipeline --mode gold

data-all:
	python -m data_platform.pipeline --mode all

data-backfill:
	python -m data_platform.backfill_historical --days 30 --interval 1h

# Símbolos: DP_SYMBOLS=BTCUSDT,ETHUSDT o DP_SYMBOLS=all para todas las USDT perpetual
symbols-list:
	venv/bin/python -m data_platform.scripts.list_symbols

symbols-list-all:
	venv/bin/python -m data_platform.scripts.list_symbols --all

# Warehouse backfill: years of historical data -> bronze -> DuckDB -> dbt
# 1) Backfill bronze with ~3 years of klines (market, derivatives, flow)
warehouse-backfill:
	@echo "📊 Backfilling bronze with historical data (~3 years)..."
	@venv/bin/python -m data_platform.backfill_bronze_historical --days 1095 --interval 1h

# Backfill con TODAS las USDT perpetual (~500 símbolos, tarda horas)
warehouse-backfill-all:
	@echo "📊 Backfilling ALL symbols (~500, ~3 years)..."
	@DP_SYMBOLS=all LAKE_ROOT="$(shell pwd)/data_lake" venv/bin/python -m data_platform.backfill_bronze_historical --days 1095 --interval 1h

# Backfill RÁPIDO desde data.binance.vision (1h, funding + OI)
warehouse-backfill-vision:
	@echo "📊 Backfill from data.binance.vision (1h, top ~20, funding + OI)..."
	@DP_SYMBOLS=top LAKE_ROOT="$(shell pwd)/data_lake" venv/bin/python -m data_platform.backfill_from_vision --interval 1h --months 36
	@echo "✅ Done. Next: make warehouse-load"

# Backfill TODAS las monedas (1h, ~500 símbolos). OI ~90 min.
warehouse-backfill-vision-all:
	@echo "📊 Backfill 1h TODAS las monedas (data.binance.vision)..."
	@DP_SYMBOLS=all LAKE_ROOT="$(shell pwd)/data_lake" venv/bin/python -m data_platform.backfill_from_vision --interval 1h --months 36
	@echo "✅ Done. Next: make warehouse-load"

# Backfill en PC remoto (más memoria) y sincroniza DuckDB aquí
# REMOTE_HOST=user@ip-pc-b make warehouse-remote-backfill
warehouse-remote-backfill:
	@REMOTE_HOST="$${REMOTE_HOST:?Set REMOTE_HOST=user@ip-pc-b}" \
	REMOTE_PATH="$${REMOTE_PATH:-~/binance}" \
	LOCAL_PATH="$(shell pwd)" \
	bash scripts/remote_backfill.sh

# Solo sincronizar desde remoto: make warehouse-remote-sync REMOTE_HOST=user@ip
warehouse-remote-sync:
	@REMOTE_HOST="$${REMOTE_HOST:?Set REMOTE_HOST=user@ip-pc-b}" \
	REMOTE_PATH="$${REMOTE_PATH:-~/binance}" \
	LOCAL_PATH="$(shell pwd)" \
	bash scripts/remote_sync.sh all

# Igual pero sin OI (más rápido, ~1-2h solo klines+funding)
warehouse-backfill-vision-all-fast:
	@echo "📊 Backfill 1h TODAS (sin OI, más rápido)..."
	@DP_SYMBOLS=all LAKE_ROOT="$(shell pwd)/data_lake" venv/bin/python -m data_platform.backfill_from_vision --interval 1h --months 36 --no-open-interest
	@echo "✅ Done. Next: make warehouse-load"

# 2) Load bronze into DuckDB + run dbt (populates br_*, slv_*, fct_*)
warehouse-load:
	@echo "📥 Loading bronze -> DuckDB..."
	@DB_PATH="$(shell pwd)/artifacts/warehouse/crypto.duckdb" && \
	DBT_DUCKDB_PATH=$$DB_PATH venv/bin/python -c "from data_platform.config import DataPlatformConfig; from data_platform.loaders.bronze_to_duckdb import load_bronze_to_duckdb; import os; cfg = DataPlatformConfig(); db_path = os.environ.get('DBT_DUCKDB_PATH', 'artifacts/warehouse/crypto.duckdb'); c = load_bronze_to_duckdb(cfg, db_path); print('Loaded:', c)" && \
	DBT_DUCKDB_PATH=$$DB_PATH bash -c "cd data_platform/dbt && $(shell pwd)/venv/bin/dbt run --target local --profiles-dir ."

# Full pipeline: backfill bronze + load to DuckDB + dbt
warehouse-backfill-full: warehouse-backfill warehouse-load

# Fill ONLY empty tables (cross_exchange, dex, fear_greed) - NO toca las demás
warehouse-fill-empty:
	@LAKE_ROOT="$(shell pwd)/data_lake" venv/bin/python -m data_platform.scripts.fill_empty_tables

# Reset warehouse: delete DB, reload clean (CIERRA DBeaver antes)
warehouse-reset:
	@echo "⚠️  Cierra DBeaver antes de ejecutar"
	@LAKE_ROOT="$(shell pwd)/data_lake" venv/bin/python -m data_platform.scripts.reset_warehouse

# dbt modeling (DB_PATH = artifacts/warehouse/crypto.duckdb)
dbt-seed:
	cd data_platform/dbt && DBT_DUCKDB_PATH="$(shell pwd)/artifacts/warehouse/crypto.duckdb" $(shell pwd)/venv/bin/dbt seed --target local --profiles-dir .

dbt-run:
	cd data_platform/dbt && DBT_DUCKDB_PATH="$(shell pwd)/artifacts/warehouse/crypto.duckdb" $(shell pwd)/venv/bin/dbt run --target local --profiles-dir .

dbt-test:
	cd data_platform/dbt && DBT_DUCKDB_PATH="$(shell pwd)/artifacts/warehouse/crypto.duckdb" $(shell pwd)/venv/bin/dbt test --target local --profiles-dir .

dbt-source-freshness:
	cd data_platform/dbt && DBT_DUCKDB_PATH="$(shell pwd)/artifacts/warehouse/crypto.duckdb" $(shell pwd)/venv/bin/dbt source freshness --target local --profiles-dir .

# Freshness + schema/historical tests
dbt-validate: dbt-source-freshness dbt-test

# AI/ML (lee de DuckDB decision_features)
# Operaciones solo en event_time: datos 1h = trade cada 1h
ai-train:
	DBT_DUCKDB_PATH="$(shell pwd)/artifacts/warehouse/crypto.duckdb" venv/bin/python examples/ai_train.py

ai-infer:
	DBT_DUCKDB_PATH="$(shell pwd)/artifacts/warehouse/crypto.duckdb" venv/bin/python examples/ai_infer.py

ai-backtest:
	DBT_DUCKDB_PATH="$(shell pwd)/artifacts/warehouse/crypto.duckdb" venv/bin/python examples/ai_backtest.py

ai-registry-list:
	venv/bin/python examples/ai_registry_list.py

ai-alloc:
	DBT_DUCKDB_PATH="$(shell pwd)/artifacts/warehouse/crypto.duckdb" venv/bin/python examples/ai_alloc.py

ai-strategy-explorer:
	@echo "📊 Explorador de estrategias (script legacy)..."
	DBT_DUCKDB_PATH="$(shell pwd)/artifacts/warehouse/crypto.duckdb" venv/bin/python examples/strategy_explorer.py

ai-explorer-agent:
	@echo "📊 Agente explorador (librería ai.explorer)..."
	DBT_DUCKDB_PATH="$(shell pwd)/artifacts/warehouse/crypto.duckdb" venv/bin/python examples/ai_explorer_agent.py quick

# Dagster orchestration
install-dagster:
	pip install -r requirements-dagster.txt

dagster-dev:
	dagster dev -w data_platform/orchestration/dagster/workspace.yaml

dagster-materialize:
	dagster asset materialize \
		-m data_platform.orchestration.dagster.definitions \
		--select bronze_high_ingestion,bronze_medium_ingestion,bronze_low_ingestion,warehouse_raw_load,warehouse_dbt_build

# Deploy to development (Docker)
deploy-dev:
	docker-compose up -d

# Local full stack (API + Dagster + Postgres)
compose-up:
	docker compose up -d --build

compose-down:
	docker compose down

local-lake-init:
	mkdir -p "$${LAKE_ROOT:-/Users/joaquincano/data/binance_lake}"

local-quant-stack: local-lake-init compose-up
	. venv/bin/activate && python examples/serious_alpha_pipeline.py && python examples/strategy_planner_demo.py

# Deploy to production (Docker)
deploy-prod:
	docker-compose -f docker-compose.prod.yml up -d

# Clean up
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.pyd" -delete
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/

# Initial setup
setup: install
	@echo "Setting up Binance Connector..."
	@if [ ! -f .env ]; then \
		echo "Creating .env file from template..."; \
		cp env.example .env; \
		echo "Please edit .env file with your Binance API credentials"; \
	else \
		echo ".env file already exists"; \
	fi
	@echo "Setup complete! Don't forget to:"
	@echo "1. Edit .env file with your Binance API credentials"
	@echo "2. Test with 'make test'"
	@echo "3. Run locally with 'make run'"

# Show logs (Docker)
logs:
	docker-compose logs -f

# Show logs for production
logs-prod:
	docker-compose -f docker-compose.prod.yml logs -f

# Stop containers
stop:
	docker-compose down

# Stop production containers
stop-prod:
	docker-compose -f docker-compose.prod.yml down
