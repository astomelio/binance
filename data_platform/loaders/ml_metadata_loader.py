import sqlite3
import duckdb
import os
from pathlib import Path


def _create_empty_mlflow_tables(con):
    """Create empty MLflow tables so dbt int_mlflow_runs can run."""
    con.execute("""
        CREATE OR REPLACE TABLE mlflow_runs AS
        SELECT CAST(NULL AS VARCHAR) as run_uuid, CAST(NULL AS INTEGER) as experiment_id,
               CAST(NULL AS VARCHAR) as name, CAST(NULL AS VARCHAR) as status,
               CAST(NULL AS BIGINT) as start_time, CAST(NULL AS BIGINT) as end_time
        WHERE 1=0
    """)
    con.execute("""
        CREATE OR REPLACE TABLE mlflow_metrics AS
        SELECT CAST(NULL AS VARCHAR) as run_uuid, CAST(NULL AS VARCHAR) as key,
               CAST(NULL AS DOUBLE) as value WHERE 1=0
    """)
    con.execute("""
        CREATE OR REPLACE TABLE mlflow_params AS
        SELECT CAST(NULL AS VARCHAR) as run_uuid, CAST(NULL AS VARCHAR) as key,
               CAST(NULL AS VARCHAR) as value WHERE 1=0
    """)
    con.execute("""
        CREATE OR REPLACE TABLE mlflow_tags AS
        SELECT CAST(NULL AS VARCHAR) as run_uuid, CAST(NULL AS VARCHAR) as key,
               CAST(NULL AS VARCHAR) as value WHERE 1=0
    """)
    con.execute("""
        CREATE OR REPLACE TABLE mlflow_experiments AS
        SELECT CAST(NULL AS INTEGER) as experiment_id, CAST(NULL AS VARCHAR) as name
        WHERE 1=0
    """)


def _create_empty_optuna_tables(con):
    """Create empty Optuna tables so dbt int_optuna_trials can run."""
    con.execute("""
        CREATE OR REPLACE TABLE optuna_studies AS
        SELECT CAST(NULL AS INTEGER) as study_id, CAST(NULL AS VARCHAR) as study_name
        WHERE 1=0
    """)
    con.execute("""
        CREATE OR REPLACE TABLE optuna_trials AS
        SELECT CAST(NULL AS INTEGER) as trial_id, CAST(NULL AS INTEGER) as study_id,
               CAST(NULL AS VARCHAR) as state, CAST(NULL AS VARCHAR) as datetime_start,
               CAST(NULL AS VARCHAR) as datetime_complete WHERE 1=0
    """)
    con.execute("""
        CREATE OR REPLACE TABLE optuna_trial_params AS
        SELECT CAST(NULL AS INTEGER) as trial_id, CAST(NULL AS VARCHAR) as param_name,
               CAST(NULL AS VARCHAR) as param_value WHERE 1=0
    """)
    con.execute("""
        CREATE OR REPLACE TABLE optuna_trial_values AS
        SELECT CAST(NULL AS INTEGER) as trial_id, CAST(NULL AS VARCHAR) as objective,
               CAST(NULL AS DOUBLE) as value WHERE 1=0
    """)


def sync_ml_metadata(mlflow_db_path, optuna_db_path, duckdb_path):
    print(f"Syncing ML metadata to {duckdb_path}...")
    
    # Connect to DuckDB
    con = duckdb.connect(duckdb_path)
    
    # Install and load sqlite extension if needed
    con.execute("INSTALL sqlite; LOAD sqlite;")
    
    # Sync MLflow tables
    if os.path.exists(mlflow_db_path) and os.path.getsize(mlflow_db_path) > 0:
        print(f"Syncing MLflow from {mlflow_db_path}")
        con.execute(f"ATTACH '{mlflow_db_path}' AS mlflow_db (TYPE SQLITE);")
        try:
            mlflow_tables = ['runs', 'metrics', 'params', 'tags', 'experiments']
            for table in mlflow_tables:
                print(f"  Mirroring mlflow_db.{table} -> mlflow_{table}")
                con.execute(f"CREATE OR REPLACE TABLE mlflow_{table} AS SELECT * FROM mlflow_db.{table};")
        except Exception as e:
            print(f"Error reading MLflow DB, creating empty tables: {e}")
            _create_empty_mlflow_tables(con)
        finally:
            con.execute("DETACH mlflow_db;")
    else:
        print(f"MLflow DB not found or empty at {mlflow_db_path}. Creating empty tables for dbt.")
        _create_empty_mlflow_tables(con)

    # Sync Optuna tables
    if os.path.exists(optuna_db_path) and os.path.getsize(optuna_db_path) > 0:
        print(f"Syncing Optuna from {optuna_db_path}")
        con.execute(f"ATTACH '{optuna_db_path}' AS optuna_db (TYPE SQLITE);")
        try:
            optuna_tables = ['studies', 'trials', 'trial_params', 'trial_values']
            for table in optuna_tables:
                print(f"  Mirroring optuna_db.{table} -> optuna_{table}")
                con.execute(f"CREATE OR REPLACE TABLE optuna_{table} AS SELECT * FROM optuna_db.{table};")
        except Exception as e:
            print(f"Error reading Optuna DB, creating empty tables: {e}")
            _create_empty_optuna_tables(con)
        finally:
            con.execute("DETACH optuna_db;")
    else:
        print(f"Optuna DB not found or empty at {optuna_db_path}. Creating empty tables for dbt.")
        _create_empty_optuna_tables(con)
        
    con.close()
    print("Sync complete.")

if __name__ == "__main__":
    REPO_ROOT = Path(__file__).resolve().parents[2]
    mlflow_db = REPO_ROOT / "artifacts" / "quant_model" / "mlflow_v2.db"
    optuna_db = REPO_ROOT / "artifacts" / "quant_model" / "optuna.db"
    
    # Get duckdb path from env or default
    duckdb_path = os.getenv("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
    
    sync_ml_metadata(str(mlflow_db), str(optuna_db), duckdb_path)
