import sqlite3
import os

def list_tables(db_path):
    if not os.path.exists(db_path):
        print(f"File not found: {db_path}")
        return
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"Tables in {db_path}: {tables}")
        conn.close()
    except Exception as e:
        print(f"Error reading {db_path}: {e}")

list_tables('artifacts/quant_model/mlflow_v2.db')
list_tables('artifacts/quant_model/optuna.db')
