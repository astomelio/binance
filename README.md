# Binance Data Platform + AI Strategies

Historical data platform, API connector, and ML strategy exploration for quantitative trading with Binance Futures (USDT perpetual).

## Overview

This repo combines:

- **FastAPI** – Binance API connector (spot/futures, orders, smart limit, WebSockets, fee calculator)
- **Data platform** – Backfill from data.binance.vision, bronze/silver/gold pipeline, DuckDB + dbt
- **ML pipeline** – Walk-forward training, calibration, allocation vectors, backtest
- **Strategy explorer** – `ai.explorer` library for exploring strategies (alpha_score, heuristic, mean reversion)
- **Trading lib** – Backtest, planner, allocation logic, fee models

## API (FastAPI)

REST API for Binance spot and futures.

**Run:** `make run` or `uvicorn app:app --host 0.0.0.0 --port 8000`

**Endpoints:**
- Account: `/account/info`, `/account/balance`, `/futures/account/balance`, `/futures/positions`
- Market: `/market/ticker/{symbol}`, `/market/klines/{symbol}`, `/futures/market/ticker/{symbol}`
- Orders: `POST /order/create`, `POST /futures/order/create`, `POST /order/smart-limit`, `POST /futures/order/smart-limit`
- WebSockets: `/ws/orderbook/{symbol}`, `/ws/ticker/{symbol}`
- Fees: `/fees/account`, `/fees/calculate`, `/fees/round-trip`, `/fees/analyze-strategy`

Requires `BINANCE_API_KEY` and `BINANCE_SECRET_KEY` in `.env`.

## Data platform

**Flow:** data.binance.vision (zips) + Open Interest API → bronze (JSONL) → DuckDB → dbt → `decision_features`

**Backfill:** `backfill_from_vision.py` downloads klines, funding rate, and fetches open interest via API. Writes to `bronze/binance_vision/` (market_snapshot, derivatives_snapshot, derivatives_flow).

**Loaders:** `bronze_to_duckdb.py` loads raw tables. dbt models build `br_*`, `slv_*`, `fct_*` and final `decision_features` (basis, momentum, alpha_signal, fwd_returns).

## ML pipeline

**Training:** `ai/training/pipeline.py` – walk-forward splits, train model, calibrate probabilities, save calibration. Uses `decision_features` from DuckDB.

**Inference:** `ai/inference/predictor.py` – loads calibration, predicts allocation for latest event_time per symbol.

**Backtest:** `ai/allocation/backtest.py` – runs allocation vectors over time, computes net return and fees.

**Explorer:** `ai/explorer` – strategy registry (alpha_score, heuristic, mean_reversion), grid search, `ExplorationAgent` for run_quick/run_grid/run_full.

## Trading lib

- **Backtest:** `trading_lib/backtest.py`, `trading_lib/alpha_backtest.py`
- **Planner:** `trading_lib/planner/engine.py` – runs strategy specs over folds, computes trades and PnL
- **Allocation:** `trading_lib/planner/allocation.py` – computes model allocations with constraints
- **Quant:** `trading_lib/quant/` – calibration, benchmarks, real model wrapper, meta models

## Automation & integrations

- **Market alerts:** `apps/automation/market_alert_engine.py`
- **Fee calculator:** `apps/automation/fee_calculator.py`
- **Trading strategy:** `apps/automation/trading_strategy_500usd.py`
- **Bot integrator:** `apps/integrations/bot_integrator.py` – Flask API for bot rebalance
- **Trading signals:** `apps/integrations/trading_signals.py` – signal processing

## Quick start

```bash
pip install -r requirements.txt
make warehouse-backfill-vision    # ~20 min, top 20 symbols
make warehouse-load              # DuckDB + dbt
make ai-explorer-agent           # Explore strategies
```

## Commands

| Command | Description |
|---------|-------------|
| `make run` | Start FastAPI (port 8000) |
| `make warehouse-backfill-vision` | Backfill 1h, top ~20 symbols |
| `make warehouse-backfill-vision-all` | All coins (~500). ~30 GB disk, ~15 GB RAM |
| `make warehouse-load` | Bronze → DuckDB + dbt |
| `make ai-explorer-agent` | Explore strategies |
| `make ai-backtest` | Backtest allocation vectors |
| `make ai-train` | Train model + calibration |
| `make ai-alloc` | View allocation vector |
| `make strategy-planner` | Planner demo |
| `make quant-train` | Quant walk-forward training |
| `make quant-oos` | Out-of-sample inference |

## Structure

```
├── apps/
│   ├── api/
│   │   └── main.py          # FastAPI Binance connector
│   ├── automation/          # Alerts, fee calc, trading strategy
│   └── integrations/       # Bot integrator, trading signals
├── data_platform/
│   ├── backfill_from_vision.py
│   ├── loaders/             # Bronze → DuckDB
│   ├── dbt/                 # Models
│   └── transforms/         # Silver, gold
├── ai/
│   ├── explorer/            # Strategy registry, grid search
│   ├── allocation/          # Backtest
│   ├── training/
│   └── inference/
├── trading_lib/
│   ├── planner/             # Engine, allocation, specs
│   ├── quant/               # Calibration, benchmarks
│   └── backtest.py
├── data_lake/               # Bronze (JSONL)
└── artifacts/warehouse/     # DuckDB
```

## Environment variables

```bash
LAKE_ROOT=data_lake
DP_SYMBOLS=top               # top (~20), all (~500), or list
BINANCE_API_KEY=...
BINANCE_SECRET_KEY=...
```

## Remote PC (more memory)

For backfilling all coins on a machine with more RAM:

```bash
REMOTE_HOST=user@ip-pc make warehouse-remote-backfill
REMOTE_HOST=user@ip-pc make warehouse-remote-sync
```

## Requirements

Python 3.10+, DuckDB, dbt
