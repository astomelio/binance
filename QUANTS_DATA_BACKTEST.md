# Quant Data & Backtest Design

## 1) Data sources (current)

- **Binance local API (`binance_local_api/market_snapshot`)**
  - Spot/Futures ticker + recent klines from your FastAPI connector.
  - Good for live integration tests.
  - Not enough as standalone historical source.

- **Binance public derivatives (`binance_public/derivatives_snapshot`)**
  - `mark_price`, `index_price`, `last_funding_rate`, `open_interest`, `quote_volume_24h`.
  - Useful alpha context for futures.

- **Cross-exchange futures snapshots (`bybit_public/futures_snapshot`, `okx_public/futures_snapshot`)**
  - `last_price`, `bid_price`, `ask_price`, `quote_volume_24h`.
  - Used to derive cross-venue dislocation and execution-quality features.

- **DEX snapshots (`dexscreener/dex_snapshot`)**
  - `price_usd`, `liquidity_usd`, `volume_24h_usd`, `txns_buys_24h`, `txns_sells_24h`.
  - Used to compute DEX-vs-CEX basis and DEX flow imbalance.

- **CoinGecko global (`coingecko/global_market`)**
  - `btc_dominance`, `total_market_cap_usd`, broad market context.

- **FRED macro (`fred/macro_rates`)**
  - `FEDFUNDS` when `FRED_API_KEY` exists.

- **FED calendar (`fed_calendar/decision_dates`)**
  - tries live FED page, falls back to `data_platform/config/fed_decision_dates.json`.

## 2) Time-series handling policy

- **Canonical time**: always UTC (`event_time`).
- **Dedup key**:
  - market features: `(event_time, symbol)`.
- **No look-ahead**:
  - train/test by time only (never random split).
  - use embargo between train and test.
- **Walk-forward evaluation**:
  - rolling windows (train N days, test M days, step K days).

Utilities:
- `trading_lib/timeseries.py`
  - `load_jsonl_timeseries(...)`
  - `build_walk_forward_splits(...)`

Example:
- `python examples/quant_research_setup.py`

## 3) Backtest layers

### A. Signal backtest from decision features
- `trading_lib/alpha_backtest.py`
- Input: `data_lake/gold/signals/decision_features/**/part-*.jsonl`
- Output:
  - trades, win-rate, gross/net return
  - per-symbol PnL
  - JSONL logs via `TradingLogger`

### B. Strategy backtest on candle streams
- `trading_lib/backtest.py`
- Uses same strategy object used by live executor.

## 4) Recommended quant workflow

1. Ingest (`bronze`) on schedule.
2. Build `silver/gold`.
3. Snapshot feature table per run.
4. Run walk-forward backtests per strategy configuration.
5. Track metrics:
   - net return after fees
   - max drawdown
   - hit-rate
   - turnover
   - stability across folds
6. Promote only configs that pass thresholds in out-of-sample folds.

## 5) Gaps to close next

- Add true historical backfill collector (paginated klines by interval/start/end).
- Store as Parquet for research-scale workloads.
- Add labels (`forward_return_1h`, `4h`, `24h`) for supervised alpha models with explicit slippage-aware targets.
- Add slippage model and execution latency in backtests.
- Add data quality checks (freshness, null-rate, duplicates, lag alerts).
- Add DEX pair coverage per symbol via `DEX_PAIRS_JSON` (multi-chain map).

## 6) Strategy planner module (for quants & bots)

- Config file: `configs/strategy_planner/specs.json`
- Runner: `examples/strategy_planner_demo.py`
- Command: `make strategy-planner`

Planner capabilities:
- Declarative strategy specs (thresholds, liquidity filters, event-window policy).
- Portfolio sizing multi-moneda por modelo (`allocation_pct`) con límites:
  - `max_gross_exposure_pct`
  - `max_symbol_pct`
- Walk-forward evaluation with embargo.
- Ranked leaderboard by net return / drawdown / win-rate.
- Experiment registry in `logs/strategy_planner/*.json`.

## 7) Local no-cloud setup (recommended)

- Keep the lake outside the repo:
  - `LAKE_ROOT=/Users/joaquincano/data/binance_lake`
- One-time init:
  - `make local-lake-init`
- Run local stack + pipeline + planner:
  - `make local-quant-stack`

## 8) Historical backfill for training

- Command:
  - `make data-backfill`
- Module:
  - `data_platform/backfill_historical.py`
- Output dataset:
  - `gold/signals/decision_features_backfill`

This backfill pulls historical spot/futures klines + funding + open interest and
builds training-ready feature rows per symbol and timestamp.
