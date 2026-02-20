"""
Registry de corridas AI: versiones de algoritmo, datos, métricas (Sharpe, rentabilidad, operaciones).
Todo en DuckDB para consultas SQL.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from ai.config import get_registry_path


@dataclass
class RunRecord:
    run_id: str
    created_at: str
    run_type: str  # train | backtest
    algo_version: str
    data_version: str
    config: dict
    metrics: dict
    artifacts: dict


def _get_algo_version() -> str:
    """Git hash o 'dev' si no hay repo."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=Path(__file__).resolve().parent.parent,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "dev"


def _get_data_version(rows: list[dict] | None) -> str:
    """Hash de ventana temporal (min/max event_time) o 'unknown'."""
    if not rows:
        return "unknown"
    times = [r.get("event_time") for r in rows if r.get("event_time")]
    if not times:
        return "unknown"
    s = f"{min(times)}|{max(times)}|{len(rows)}"
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def _ensure_registry(path: str) -> duckdb.DuckDBPyConnection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_runs (
            run_id VARCHAR PRIMARY KEY,
            created_at TIMESTAMP,
            run_type VARCHAR,
            algo_version VARCHAR,
            data_version VARCHAR,
            config_json VARCHAR,
            metrics_json VARCHAR,
            artifacts_json VARCHAR
        )
    """)
    return conn


def log_run(
    run_type: str,
    config: dict,
    metrics: dict,
    artifacts: dict | None = None,
    algo_version: str | None = None,
    data_version: str | None = None,
    data_rows: list[dict] | None = None,
    registry_path: str | None = None,
) -> str:
    """
    Registra una corrida. Retorna run_id.
    metrics: sharpe, net_return, trades, win_rate, etc.
    artifacts: calibration_path, model_path, etc.
    """
    path = registry_path or get_registry_path()
    conn = _ensure_registry(path)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + run_type[:4] + "_" + secrets.token_hex(3)
    created = datetime.now(timezone.utc).isoformat()
    algo = algo_version or _get_algo_version()
    data = data_version or _get_data_version(data_rows)
    artifacts = artifacts or {}

    conn.execute(
        """
        INSERT INTO ai_runs
        (run_id, created_at, run_type, algo_version, data_version, config_json, metrics_json, artifacts_json)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        [
            run_id,
            created,
            run_type,
            algo,
            data,
            json.dumps(config),
            json.dumps(metrics),
            json.dumps(artifacts),
        ],
    )
    conn.close()
    return run_id


def list_runs(
    limit: int = 50,
    run_type: str | None = None,
    registry_path: str | None = None,
) -> list[RunRecord]:
    """Lista corridas ordenadas por created_at desc."""
    path = registry_path or get_registry_path()
    if not Path(path).exists():
        return []
    conn = duckdb.connect(path, read_only=True)
    q = "SELECT * FROM ai_runs"
    params = []
    if run_type:
        q += " WHERE run_type = $1"
        params.append(run_type)
        q += " ORDER BY created_at DESC LIMIT $2"
        params.append(limit)
    else:
        q += " ORDER BY created_at DESC LIMIT $1"
        params.append(limit)
    rows = conn.execute(q, params).fetchall()
    cols = [d[0] for d in conn.execute("DESCRIBE ai_runs").fetchall()]
    conn.close()
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        out.append(
            RunRecord(
                run_id=d["run_id"],
                created_at=str(d["created_at"]),
                run_type=d["run_type"],
                algo_version=d["algo_version"],
                data_version=d["data_version"],
                config=json.loads(d["config_json"] or "{}"),
                metrics=json.loads(d["metrics_json"] or "{}"),
                artifacts=json.loads(d["artifacts_json"] or "{}"),
            )
        )
    return out


def get_run(run_id: str, registry_path: str | None = None) -> RunRecord | None:
    path = registry_path or get_registry_path()
    if not Path(path).exists():
        return None
    conn = duckdb.connect(path, read_only=True)
    rows = conn.execute("SELECT * FROM ai_runs WHERE run_id = $1", [run_id]).fetchall()
    cols = [d[0] for d in conn.execute("DESCRIBE ai_runs").fetchall()]
    conn.close()
    if not rows:
        return None
    d = dict(zip(cols, rows[0]))
    return RunRecord(
        run_id=d["run_id"],
        created_at=str(d["created_at"]),
        run_type=d["run_type"],
        algo_version=d["algo_version"],
        data_version=d["data_version"],
        config=json.loads(d["config_json"] or "{}"),
        metrics=json.loads(d["metrics_json"] or "{}"),
        artifacts=json.loads(d["artifacts_json"] or "{}"),
    )
