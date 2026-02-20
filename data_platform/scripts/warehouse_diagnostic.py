#!/usr/bin/env python3
"""
Diagnóstico: qué esquemas y tablas tiene tu DuckDB, cuáles tienen datos.

Uso:
    python -m data_platform.scripts.warehouse_diagnostic
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import duckdb


def main() -> None:
    db_env = os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    repo_root = Path(__file__).resolve().parents[2]
    db_path = db_env if Path(db_env).is_absolute() else str(repo_root / db_env)

    if not Path(db_path).exists():
        print(f"[diagnostic] No existe: {db_path}")
        return

    con = duckdb.connect(db_path, read_only=True)
    schemas = con.execute(
        """
        SELECT DISTINCT schema_name
        FROM information_schema.schemata
        WHERE schema_name NOT IN ('information_schema', 'pg_catalog')
        ORDER BY 1
    """
    ).fetchall()

    print(f"=== DuckDB: {db_path} ===\n")
    print(f"Esquemas: {[s[0] for s in schemas]}\n")

    for (sch,) in schemas:
        tabs = con.execute(
            f"""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = ?
            ORDER BY 1
        """,
            [sch],
        ).fetchall()
        if not tabs:
            continue
        print(f"--- {sch} ---")
        for (name,) in tabs:
            try:
                n = con.execute(f'SELECT count(*) FROM "{sch}"."{name}"').fetchone()[0]
                status = "✓" if n > 0 else "vacía"
                print(f"  {name}: {n} rows {status}")
            except Exception as e:
                print(f"  {name}: error {e}")
        print()

    print("--- Tabla principal ---")
    print("  decision_features o fct_decision_features (features + labels para ML)")
    print("\n--- Para llenar tablas vacías (cross_exchange, dex, fear_greed) ---")
    print("  make warehouse-fill-empty")
    print("  (Si tus raw están en otro esquema: WAREHOUSE_SCHEMA=raw make warehouse-fill-empty)")


if __name__ == "__main__":
    main()
