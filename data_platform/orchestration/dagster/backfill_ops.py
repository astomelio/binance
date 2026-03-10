"""
Ops y jobs de Dagster para backfill histórico y recarga de fuentes externas.
Todo el flujo que antes eran scripts sueltos (bootstrap_historical, reload_external_and_dbt)
queda orquestado aquí: lanzar desde la UI de Dagster o por schedule.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dagster import OpExecutionContext, graph, op

from data_platform.config import DataPlatformConfig
from data_platform.loaders.bronze_to_duckdb import load_bronze_to_duckdb

REPO_ROOT = Path(__file__).resolve().parents[3]


def _env() -> dict:
    env = {**os.environ}
    env.setdefault("LAKE_ROOT", str(REPO_ROOT / "data_lake"))
    env.setdefault("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
    return env


@op(description="Backfill histórico Binance (y Bybit/OKX/DEX proxy) al data lake. Escribe JSONL en data_lake/bronze/*_historical/.")
def backfill_bronze_historical_op(context) -> dict:
    """Ejecuta data_platform.backfill_bronze_historical. Config: days, interval, symbols (job config)."""
    config = context.op_config or {}
    days = int(config.get("days", 1095))
    interval = str(config.get("interval", "15m"))
    symbols = config.get("symbols")  # opcional: "top", "all", o lista CSV
    cmd = [
        sys.executable,
        "-m",
        "data_platform.backfill_bronze_historical",
        "--days", str(days),
        "--interval", interval,
    ]
    env = _env()
    if symbols:
        env["DP_SYMBOLS"] = str(symbols)
    context.log.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=7200,
    )
    if result.returncode != 0:
        context.log.error(f"stdout: {result.stdout[-2000:]}")
        context.log.error(f"stderr: {result.stderr[-2000:]}")
        raise RuntimeError(
            f"backfill_bronze_historical failed (exit {result.returncode}): {result.stderr[-500:]}"
        )
    context.log.info(result.stdout[-1500:])
    return {"days": days, "interval": interval, "symbols": symbols or "config"}


@op(description="Backfill fuentes externas (Fear&Greed, FRED, FED, CoinGecko) al data lake.")
def backfill_external_sources_op(context) -> dict:
    """Ejecuta data_platform.backfill_external_sources."""
    cmd = [sys.executable, "-m", "data_platform.backfill_external_sources"]
    env = _env()
    context.log.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if result.returncode != 0:
        context.log.error(f"stderr: {result.stderr[-2000:]}")
        raise RuntimeError(
            f"backfill_external_sources failed (exit {result.returncode}): {result.stderr[-500:]}"
        )
    context.log.info(result.stdout[-1500:])
    return {"ok": True}


@op(description="Carga todo el bronze (JSONL) del data lake a DuckDB. Mismo código que el asset warehouse_raw_load.")
def load_warehouse_op(
    context,
    _after_hist: dict | None = None,
    _after_ext: dict | None = None,
) -> dict:
    """Carga bronze → DuckDB usando load_bronze_to_duckdb."""
    cfg = DataPlatformConfig()
    db_path = os.environ.get("DBT_DUCKDB_PATH") or str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb")
    if not os.path.isabs(db_path):
        db_path = str((REPO_ROOT / db_path).resolve())
    env = _env()
    os.environ.update(env)
    context.log.info("Loading bronze to DuckDB...")
    counts = load_bronze_to_duckdb(cfg, db_path=db_path)
    context.log.info(f"Loaded: {counts}")
    return counts


@op(description="Ejecuta dbt run (Silver + Gold). Mismo resultado que el asset warehouse_dbt_build.")
def dbt_build_op(context, _after_load: dict | None = None) -> dict:
    """Ejecuta dbt run con el Python del proceso actual (evita launcher dbt.exe con rutas viejas)."""
    dbt_dir = REPO_ROOT / "data_platform" / "dbt"
    db_path = os.environ.get("DBT_DUCKDB_PATH") or str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb")
    if not os.path.isabs(db_path):
        db_path = str((REPO_ROOT / db_path).resolve())
    env = _env()
    cmd = [
        sys.executable,
        "-m",
        "dbt",
        "run",
        "--target", os.getenv("DBT_TARGET", "local"),
        "--profiles-dir", ".",
    ]
    context.log.info(f"Running: {' '.join(cmd)} in {dbt_dir}")
    result = subprocess.run(
        cmd,
        cwd=str(dbt_dir),
        env={**env, "DBT_DUCKDB_PATH": db_path},
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if result.returncode != 0:
        context.log.error(f"stdout: {result.stdout[-2000:]}")
        context.log.error(f"stderr: {result.stderr[-2000:]}")
        raise RuntimeError(f"dbt run failed (exit {result.returncode}): {result.stderr[-500:]}")
    context.log.info(result.stdout[-1000:])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Grafos y jobs
# ---------------------------------------------------------------------------

@graph(description="Backfill histórico completo: Binance+externos → load → dbt. Sustituye scripts/bootstrap_historical.py")
def backfill_full_graph():
    hist = backfill_bronze_historical_op()
    ext = backfill_external_sources_op()
    load = load_warehouse_op(hist, ext)
    dbt_build_op(load)


# Job: lanzar desde Dagster UI. Config opcional: ops.backfill_bronze_historical_op.config = { days: 1000, interval: "15m", symbols: "top" }
backfill_full_job = backfill_full_graph.to_job(
    name="backfill_full",
    description="Backfill histórico (Binance + externos) → load DuckDB → dbt. Reemplaza bootstrap_historical.py",
    tags={"origen": "backfill", "reemplaza": "scripts/bootstrap_historical.py"},
)


@graph(description="Solo fuentes externas (Fear&Greed, FRED, FED) → load → dbt. Sustituye scripts/reload_external_and_dbt.py")
def reload_external_and_warehouse_graph():
    ext = backfill_external_sources_op()
    load = load_warehouse_op(ext)
    dbt_build_op(load)


reload_external_job = reload_external_and_warehouse_graph.to_job(
    name="reload_external_and_warehouse",
    description="Recarga fuentes externas + load DuckDB + dbt. Reemplaza reload_external_and_dbt.py",
    tags={"origen": "backfill", "reemplaza": "scripts/reload_external_and_dbt.py"},
)