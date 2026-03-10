"""
Carga el champion desde MLflow y rellena alpha_score en las filas.
Conecta el pipeline de entrenamiento con el de ejecución/backtest/suite.
"""

from __future__ import annotations

from typing import Any


def load_champion_model(
    model_uri: str = "models:/quant_alpha_entry_lgbm@champion",
    mlflow_tracking_uri: str | None = None,
):
    """
    Carga el modelo champion desde MLflow.
    model_uri: ej. "models:/quant_alpha_entry_lgbm@champion" o "models:/quant_alpha_entry@champion"
    mlflow_tracking_uri: si None, usa el ya configurado (env MLFLOW_TRACKING_URI o default local).
    Soporta LightGBM, sklearn (RF, LogReg).
    """
    if mlflow_tracking_uri:
        import mlflow
        mlflow.set_tracking_uri(mlflow_tracking_uri)
    errs = []
    try:
        import mlflow.lightgbm
        return mlflow.lightgbm.load_model(model_uri)
    except Exception as e:
        errs.append(f"lightgbm:{e}")
    try:
        import mlflow.sklearn
        return mlflow.sklearn.load_model(model_uri)
    except Exception as e:
        errs.append(f"sklearn:{e}")
    try:
        import mlflow.pyfunc
        return mlflow.pyfunc.load_model(model_uri)
    except Exception as e:
        errs.append(f"pyfunc:{e}")
    raise RuntimeError(f"No se pudo cargar {model_uri}: {'; '.join(errs)}")


def enrich_rows_with_champion(
    rows: list[dict],
    model_uri: str = "models:/quant_alpha_entry_lgbm@champion",
    mlflow_tracking_uri: str | None = None,
    feature_names: list[str] | None = None,
    prob_threshold: float = 0.55,
) -> list[dict]:
    """
    Carga el champion de MLflow, rellena alpha_score en cada fila y devuelve las filas modificadas.
    Así la suite/backtest que use la estrategia alpha_score evalúa el modelo real, no una columna vacía.
    """
    model = load_champion_model(model_uri=model_uri, mlflow_tracking_uri=mlflow_tracking_uri)
    from ai.inference.model_scorer import enrich_rows_with_model
    return enrich_rows_with_model(
        rows,
        model,
        feature_names=feature_names,
        prob_threshold=prob_threshold,
    )
