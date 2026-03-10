from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from dagster import MaterializeResult, asset

from data_platform.config import DataPlatformConfig
from data_platform.loaders.bronze_to_duckdb import load_bronze_to_duckdb
from data_platform.pipeline import run_bronze
from scripts.sync_portfolio import sync_portfolio

REPO_ROOT = Path(__file__).resolve().parents[3]


def _db_path() -> str:
    env = os.getenv("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    return str((REPO_ROOT / env).resolve()) if not Path(env).is_absolute() else env


def _dbt_project_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "dbt"


# ---------------------------------------------------------------------------
# Bronze: fetch raw data from APIs into data lake JSONL files.
# One asset per frequency group so schedules can trigger independently.
# ---------------------------------------------------------------------------

@asset(
    group_name="bronze",
    metadata={"herramienta": "run_bronze (dlt)", "tablas": "market_snapshot_raw, derivatives_*, cross_exchange_*", "fuente": "Binance, Bybit, OKX"},
)
def bronze_high(context) -> MaterializeResult:
    """Binance (spot+futures+flow), Bybit, OKX — cada 15 min."""
    os.environ.setdefault("LAKE_ROOT", str(REPO_ROOT / "data_lake"))
    cfg = DataPlatformConfig()
    try:
        run_bronze(cfg, source_groups=["high"])
    except Exception as e:
        context.log.error(f"bronze_high failed: {e}")
        raise RuntimeError(f"bronze_high (Binance/Bybit/OKX) failed: {e}") from e
    return MaterializeResult(metadata={"group": "high", "lake_root": cfg.lake_root})


@asset(
    group_name="bronze",
    metadata={"herramienta": "run_bronze (dlt)", "tablas": "global_market_raw, fear_greed_raw, dex_snapshot_raw", "fuente": "CoinGecko, Fear&Greed, DexScreener"},
)
def bronze_medium(context) -> MaterializeResult:
    """CoinGecko, Fear & Greed, DexScreener — cada hora."""
    os.environ.setdefault("LAKE_ROOT", str(REPO_ROOT / "data_lake"))
    cfg = DataPlatformConfig()
    try:
        run_bronze(cfg, source_groups=["medium"])
    except Exception as e:
        context.log.error(f"bronze_medium failed: {e}")
        raise RuntimeError(f"bronze_medium (CoinGecko/FearGreed/DexScreener) failed: {e}") from e
    return MaterializeResult(metadata={"group": "medium", "lake_root": cfg.lake_root})


@asset(
    group_name="bronze",
    metadata={"herramienta": "run_bronze (dlt)", "tablas": "macro_rates_raw, macro_assets_raw, fed_calendar_raw", "fuente": "FRED, FED, on-chain"},
)
def bronze_low(context) -> MaterializeResult:
    """FRED macro, FED calendar, on-chain — cada 6 h."""
    os.environ.setdefault("LAKE_ROOT", str(REPO_ROOT / "data_lake"))
    cfg = DataPlatformConfig()
    try:
        run_bronze(cfg, source_groups=["low"])
    except Exception as e:
        context.log.error(f"bronze_low failed: {e}")
        raise RuntimeError(f"bronze_low (FRED/FED/on-chain) failed: {e}") from e
    return MaterializeResult(metadata={"group": "low", "lake_root": cfg.lake_root})


# ---------------------------------------------------------------------------
# Warehouse: bronze JSONL → DuckDB raw tables → dbt build (decision_features)
# dbt handles ALL silver/gold transforms; no Python silver/gold needed.
# ---------------------------------------------------------------------------

@asset(
    group_name="bronze",
    metadata={"herramienta": "yfinance + dlt", "tablas": "stock_prices, market_news", "fuente": "Yahoo Finance"},
)
def stock_market_ingest(context) -> MaterializeResult:
    """Acciones (AAPL, MSFT, etc.) + cripto (BTC-USD) + titulares de noticias."""
    db_path = _db_path()
    script = REPO_ROOT / "data_platform" / "loaders" / "stock_market_loader.py"
    if not script.exists():
        raise FileNotFoundError(f"Stock market loader not found: {script} (REPO_ROOT={REPO_ROOT})")
    cmd = [sys.executable, str(script)]
    env = {**os.environ, "DBT_DUCKDB_PATH": db_path, "PYTHONPATH": str(REPO_ROOT)}
    context.log.info(f"Running stock market ingest: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, timeout=600
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Stock ingest timed out (600s). stderr: {getattr(e, 'stderr', '') or ''}")
    if result.returncode != 0:
        err_msg = f"Stock ingest failed (exit {result.returncode}):\nstdout:\n{result.stdout or '(empty)'}\nstderr:\n{result.stderr or '(empty)'}"
        context.log.error(err_msg)
        raise RuntimeError(err_msg)
    context.log.info(f"Stock ingest complete:\n{result.stdout[-1000:]}")
    return MaterializeResult(metadata={"db_path": db_path})

@asset(
    group_name="ai_agents",
    deps=[stock_market_ingest],
    metadata={"herramienta": "sentiment_agent.py (OpenAI)", "tablas": "news_sentiment", "fuente": "Titulares market_news"},
)
def news_sentiment_analysis(context) -> MaterializeResult:
    """IA analiza titulares de noticias → score -1 a 1."""
    db_path = _db_path()
    script = REPO_ROOT / "ai" / "agents" / "sentiment_agent.py"
    
    cmd = [sys.executable, str(script)]
    env = {**os.environ, "DBT_DUCKDB_PATH": db_path, "PYTHONPATH": str(REPO_ROOT)}
    
    context.log.info(f"Running sentiment analysis: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env)
    
    if result.returncode != 0:
        raise RuntimeError(f"Sentiment analysis failed:\nstdout={result.stdout}\nstderr={result.stderr}")
        
    context.log.info(f"Sentiment analysis complete:\n{result.stderr[-1000:]}")
    return MaterializeResult(metadata={"db_path": db_path})

def _ensure_sentiment_tables_exist(db_path: str) -> None:
    """Ensure news_sentiment and x_account_sentiment exist so dbt can run (agents populate them)."""
    import duckdb
    con = duckdb.connect(db_path)
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS main.news_sentiment (
                uuid VARCHAR PRIMARY KEY, symbol VARCHAR, sentiment_score DOUBLE,
                sentiment_label VARCHAR, ai_summary VARCHAR, analyzed_at VARCHAR
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS main.x_account_sentiment (
                account_handle VARCHAR, sentiment_score DOUBLE, sentiment_label VARCHAR,
                grok_summary VARCHAR, analyzed_at VARCHAR
            )
        """)
    finally:
        con.close()


@asset(
    group_name="warehouse",
    deps=[bronze_high, bronze_medium, bronze_low, news_sentiment_analysis],
    metadata={"herramienta": "bronze_to_duckdb.py", "tablas": "Todas las *_raw en DuckDB", "fuente": "JSONL del data lake"},
)
def warehouse_raw_load(context) -> MaterializeResult:
    """Carga JSONL del data lake → tablas raw en DuckDB."""
    db_path = _db_path()
    # Asegurar env para loader (Dagster puede no tener LAKE_ROOT/DBT_DUCKDB_PATH)
    os.environ.setdefault("LAKE_ROOT", str(REPO_ROOT / "data_lake"))
    os.environ.setdefault("DBT_DUCKDB_PATH", db_path)
    cfg = DataPlatformConfig()
    counts = load_bronze_to_duckdb(cfg, db_path=db_path)
    _ensure_sentiment_tables_exist(db_path)
    context.log.info(f"Loaded {sum(counts.values())} total rows into {len(counts)} tables")
    return MaterializeResult(metadata={"db_path": db_path, "table_counts": counts})


@asset(
    group_name="ai_agents",
    deps=[warehouse_raw_load],
    metadata={"herramienta": "x_tracker_agent.py (Grok/xAI)", "tablas": "x_account_sentiment", "fuente": "X: @elonmusk, @VitalikButerin, etc."},
)
def x_account_tracking(context) -> MaterializeResult:
    """Grok analiza tweets de cuentas clave → score -1 a 1."""
    db_path = _db_path()
    script = REPO_ROOT / "ai" / "agents" / "x_tracker_agent.py"
    cmd = [sys.executable, str(script)]
    env = {**os.environ, "DBT_DUCKDB_PATH": db_path, "PYTHONPATH": str(REPO_ROOT)}
    context.log.info(f"Running X Account Tracker (Grok): {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"X Account Tracking failed:\nstdout={result.stdout}\nstderr={result.stderr}")
    context.log.info(f"X Account Tracking complete:\n{result.stderr[-1000:]}")
    return MaterializeResult(metadata={"db_path": db_path})


@asset(
    group_name="warehouse",
    deps=[x_account_tracking],
    metadata={"herramienta": "ml_metadata_loader.py", "tablas": "mlflow_*, optuna_*", "fuente": "SQLite (MLflow/Optuna)"},
)
def ml_metadata_sync(context) -> MaterializeResult:
    """Sincroniza metadatos de MLflow y Optuna (SQLite) hacia DuckDB."""
    db_path = _db_path()
    script = REPO_ROOT / "data_platform" / "loaders" / "ml_metadata_loader.py"
    cmd = [sys.executable, str(script)]
    env = {**os.environ, "DBT_DUCKDB_PATH": db_path, "PYTHONPATH": str(REPO_ROOT)}
    
    context.log.info(f"Running ML Metadata Sync: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env)
    
    if result.returncode != 0:
        raise RuntimeError(f"ML Metadata Sync failed:\nstdout={result.stdout}\nstderr={result.stderr}")
        
    context.log.info(f"ML Metadata Sync complete:\n{result.stdout}")
    return MaterializeResult(metadata={"db_path": db_path})


def _run_dbt_build(dbt_dir: Path, db_path: str, context, max_retries: int = 5, retry_delay: int = 8) -> tuple[int, str]:
    """Run dbt build, returning (return_code, full_output). Retries on DuckDB lock."""
    import subprocess
    import time

    cmd = [
        "dbt", "build",
        "--target", os.getenv("DBT_TARGET", "local"),
        "--profiles-dir", str(dbt_dir),
    ]
    env = {**os.environ, "DBT_DUCKDB_PATH": db_path}

    for attempt in range(max_retries):
        process = subprocess.Popen(cmd, cwd=str(dbt_dir), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        output = []
        for line in iter(process.stdout.readline, ""):
            if line:
                context.log.info(line.strip())
                output.append(line)
        process.stdout.close()
        return_code = process.wait()
        full_output = "".join(output)

        if return_code == 0:
            return 0, full_output
        lock_err = "Conflicting lock" in full_output or "Could not set lock" in full_output
        if lock_err and attempt < max_retries - 1:
            context.log.warning(f"DuckDB lock conflict, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(retry_delay)
        else:
            return return_code, full_output
    return 1, ""


@asset(
    group_name="warehouse",
    deps=[ml_metadata_sync],
    metadata={"herramienta": "dbt build", "tablas": "decision_features, fct_*, slv_*", "fuente": "Tablas raw + sentiment + ML metadata"},
)
def warehouse_dbt_build(context) -> MaterializeResult:
    """dbt: raw → bronze → silver → gold (decision_features)."""
    dbt_dir = _dbt_project_dir()
    db_path = _db_path()
    return_code, full_output = _run_dbt_build(dbt_dir, db_path, context)

    if return_code != 0:
        raise RuntimeError(f"dbt build failed (exit code {return_code})\n{full_output[-2000:]}")
    return MaterializeResult(metadata={"db_path": db_path, "stdout_tail": full_output[-1000:] if full_output else ""})


# ---------------------------------------------------------------------------
# ML: train model -> run agent suite (sequential via deps)
# ---------------------------------------------------------------------------

@asset(
    group_name="ml",
    deps=[warehouse_dbt_build],
    metadata={"herramienta": "auto_train_eval.py", "tablas": "MLflow (champion)", "fuente": "decision_features"},
)
def quant_model_train(context) -> MaterializeResult:
    db_path = _db_path()
    script = REPO_ROOT / "scripts" / "auto_train_eval.py"
    cmd = [
        sys.executable, str(script),
        "--set-champion",
        "--horizon", "4h",
        "--lookback-days", "1000",
        "--train-days", "180",
        "--test-days", "30",
        "--step-days", "15",
    ]
    env = {**os.environ, "DBT_DUCKDB_PATH": db_path, "PYTHONPATH": str(REPO_ROOT)}
    context.log.info(f"Running benchmark: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, timeout=7200)
    context.log.info(f"stdout (last 2000):\n{result.stdout[-2000:]}")
    if result.stderr:
        context.log.info(f"stderr (last 2000):\n{result.stderr[-2000:]}")
    if result.returncode != 0:
        raise RuntimeError(
            f"Benchmark failed (exit {result.returncode}):\nstdout={result.stdout[-2000:]}\nstderr={result.stderr[-2000:]}"
        )
    report_path = REPO_ROOT / "artifacts" / "quant_model" / "auto_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    return MaterializeResult(
        metadata={
            "benchmark_results_count": report.get("benchmark_results_count", 0),
            "best_model": report.get("best_model", "N/A"),
            "best_feature_set": report.get("best_feature_set", "N/A"),
            "best_objective": report.get("best_objective"),
            "best_net_return_pct": report.get("best_mean_net_return_percent"),
            "best_win_rate_pct": report.get("best_mean_win_rate_percent"),
            "is_profitable": report.get("is_profitable", False),
            "registered": report.get("registered", False),
            "champion": report.get("champion", False),
        }
    )


@asset(
    group_name="ml",
    deps=[quant_model_train],
    metadata={"herramienta": "run_suite_cycle.py (Optuna)", "tablas": "suite_state, research_state", "fuente": "Champion + decision_features"},
)
def quant_suite_cycle(context) -> MaterializeResult:
    db_path = _db_path()
    script = REPO_ROOT / "scripts" / "run_suite_cycle.py"
    cmd = [
        sys.executable, str(script),
        "--horizon", "4h",
        "--lookback-days", "1000",
        "--max-cycles", "10",
        "--max-trials", "500",
        "--cycles-before-explore", "2",
    ]
    env = {**os.environ, "DBT_DUCKDB_PATH": db_path, "PYTHONPATH": str(REPO_ROOT)}
    context.log.info(f"Running research loop: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, timeout=10800)
    context.log.info(f"stdout (last 2000):\n{result.stdout[-2000:]}")
    if result.stderr:
        context.log.info(f"stderr (last 2000):\n{result.stderr[-2000:]}")
    if result.returncode != 0:
        raise RuntimeError(
            f"Research loop failed (exit {result.returncode}):\nstdout={result.stdout[-2000:]}\nstderr={result.stderr[-2000:]}"
        )
    state_path = REPO_ROOT / "artifacts" / "quant_model" / "suite_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    research_path = REPO_ROOT / "artifacts" / "quant_model" / "research_state.json"
    research = json.loads(research_path.read_text(encoding="utf-8")) if research_path.exists() else {}
    return MaterializeResult(
        metadata={
            "champion_id": state.get("champion_id", "none"),
            "champion_version": state.get("version", 0),
            "champion_net_return": state.get("champion_metrics", {}).get("net_return_percent"),
            "research_mode": research.get("mode", "unknown"),
            "exploration_round": research.get("exploration_round", 0),
            "stale_cycles": research.get("cycles_without_improvement", 0),
        }
    )

@asset(
    group_name="ml",
    deps=[warehouse_dbt_build],
    metadata={"herramienta": "optimize_risk_engine.py", "tablas": "auto_report.json (risk_engine)", "fuente": "decision_features"},
)
def quant_risk_optimize(context) -> MaterializeResult:
    """Optimiza max_open_trades, max_position_size_pct vía backtest. Guarda en auto_report."""
    db_path = _db_path()
    script = REPO_ROOT / "scripts" / "optimize_risk_engine.py"
    cmd = [sys.executable, str(script), "--max-trials", "20"]
    env = {**os.environ, "DBT_DUCKDB_PATH": db_path, "PYTHONPATH": str(REPO_ROOT)}
    context.log.info(f"Running Risk Engine optimization: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, timeout=1800)
    if result.returncode != 0:
        context.log.warning(f"Risk optimize failed (non-fatal): {result.stderr[-500:]}")
        return MaterializeResult(metadata={"status": "skipped", "error": result.stderr[-200:]})
    report_path = REPO_ROOT / "artifacts" / "quant_model" / "auto_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    re = report.get("risk_engine", {})
    return MaterializeResult(
        metadata={
            "max_open_trades": re.get("max_open_trades"),
            "max_position_size_pct": re.get("max_position_size_pct"),
            "best_fitness": re.get("best_fitness"),
        }
    )


@asset(
    group_name="ml",
    deps=[quant_suite_cycle],
    metadata={"herramienta": "run_risk_engine.py", "tablas": "fct_raw_signals, fct_approved_orders", "fuente": "Modelos + Risk Engine"},
)
def quant_risk_evaluation(context) -> MaterializeResult:
    """Aplica Position Sizing y Risk Limits a las señales crudas."""
    db_path = _db_path()
    script = REPO_ROOT / "scripts" / "run_risk_engine.py"
    cmd = [sys.executable, str(script)]
    env = {**os.environ, "DBT_DUCKDB_PATH": db_path, "PYTHONPATH": str(REPO_ROOT)}
    
    context.log.info(f"Running Risk Engine: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env)
    
    if result.returncode != 0:
        raise RuntimeError(f"Risk Engine failed:\nstdout={result.stdout}\nstderr={result.stderr}")
        
    context.log.info(f"Risk Engine complete:\n{result.stderr[-1000:]}")
    return MaterializeResult(metadata={"db_path": db_path})

@asset(
    group_name="execution",
    deps=[quant_risk_evaluation],
    metadata={"herramienta": "execute_approved_orders.py", "tablas": "fct_approved_orders", "fuente": "Risk Engine + Binance API"},
)
def execute_pending_orders(context) -> MaterializeResult:
    """Envía las órdenes aprobadas al exchange vía API y actualiza el estado a EXECUTED."""
    db_path = _db_path()
    script = REPO_ROOT / "scripts" / "execute_approved_orders.py"
    cmd = [sys.executable, str(script)]
    env = {**os.environ, "DBT_DUCKDB_PATH": db_path, "PYTHONPATH": str(REPO_ROOT)}
    
    context.log.info(f"Running Order Execution: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env)
    
    if result.returncode != 0:
        raise RuntimeError(f"Order Execution failed:\nstdout={result.stdout}\nstderr={result.stderr}")
        
    context.log.info(f"Order Execution complete:\n{result.stderr[-1000:]}")
    return MaterializeResult(metadata={"db_path": db_path})


@asset(
    group_name="ml",
    deps=[execute_pending_orders],
    metadata={"herramienta": "verify_champion_performance.py", "fuente": "Backtest vs fct_order_history"},
)
def quant_performance_validation(context) -> MaterializeResult:
    """Compara el PnL del champion en backtest contra el PnL real obtenido."""
    db_path = _db_path()
    script = REPO_ROOT / "scripts" / "verify_champion_performance.py"
    cmd = [sys.executable, str(script)]
    env = {**os.environ, "DBT_DUCKDB_PATH": db_path, "PYTHONPATH": str(REPO_ROOT)}
    
    context.log.info(f"Running Performance Validation: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env)
    
    if result.returncode != 0:
        context.log.warning(f"Performance validation failed: {result.stderr}")
        return MaterializeResult(metadata={"status": "failed", "error": result.stderr})
        
    context.log.info(f"Performance Validation output:\n{result.stdout}")
    return MaterializeResult(metadata={"stdout": result.stdout[-500:]})

