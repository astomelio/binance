"""
Rellena alpha_score en filas de decision_features usando un modelo registrado.
El backtest usa ese score para entradas/salidas; sin modelo (o sin alpha en DB) no hay trades.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# Mismo set que quant_oos_from_registry / quant_optuna_tuning para modelos LightGBM
DEFAULT_FEATURE_NAMES = [
    "alpha_microstructure_score",
    "momentum_score",
    "basis_bps",
    "funding_rate_8h",
    "long_short_account_ratio",
    "buy_sell_ratio",
    "fear_greed_value",
    "btc_dominance",
    "fed_funds_rate",
    "session_overlap_score",
    "liquidity_event_score",
    "cross_exchange_spread_bps",
    "cross_exchange_mean_diff_bps",
    "cross_exchange_bid_ask_bps_mean",
    "bybit_okx_delta_bps",
    "cross_exchange_score",
    "dex_cex_basis_bps",
    "dex_liquidity_usd",
    "dex_volume_24h_usd",
    "dex_txn_imbalance_24h",
    "dex_alpha_score",
]


def enrich_rows_with_model(
    rows: list[dict],
    model: Any,
    feature_names: list[str] | None = None,
    prob_threshold: float = 0.55,
) -> list[dict]:
    """
    Para cada fila predice con el modelo y asigna alpha_score (y model_score).
    score en [-1, 1] para compatibilidad con compute_allocations.
    """
    names = feature_names or DEFAULT_FEATURE_NAMES
    # Matriz con las columnas en el orden que espera el modelo (faltantes = 0)
    X = pd.DataFrame(
        [{k: float(r.get(k, 0.0) or 0.0) for k in names} for r in rows],
        columns=names,
    )

    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(X)
        p_up = proba[:, 1] if proba.shape[1] > 1 else proba.ravel()
    else:
        pred = model.predict(X)
        p_up = pred if hasattr(pred, "__len__") else [pred]
    # Mapear prob [0,1] -> score [-1, 1] para allocation
    p_up = np.asarray(p_up).ravel()
    score = (2.0 * p_up) - 1.0

    out = []
    for i, row in enumerate(rows):
        r = dict(row)
        p = float(p_up[i]) if i < len(p_up) else 0.5
        s = float(score[i]) if i < len(score) else 0.0
        if p >= prob_threshold:
            r["alpha_score"] = s
        elif p <= (1.0 - prob_threshold):
            r["alpha_score"] = s
        else:
            r["alpha_score"] = 0.0
        r["model_score"] = s
        r["entry_probability"] = p
        out.append(r)
    return out
