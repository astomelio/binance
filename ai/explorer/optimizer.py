"""
Optimizador: busca mejores estrategias × parámetros × horizontes × activos × sesión.
Usa todo el dataset (o un lookback grande) y explora grid/sample de combinaciones.
"""

from __future__ import annotations

import random
from typing import Any

from ai.explorer.data_filters import filter_rows_by_session, get_symbol_set
from ai.explorer.experiment import run_grid, run_single
from ai.explorer.registry import get_registry, get_strategy
from ai.explorer.types import ExperimentResult


def run_optimization(
    rows: list[dict],
    strategy_ids: list[str] | None = None,
    horizons: list[str] | None = None,
    symbol_sets: list[str] | None = None,
    session_hours: tuple[int, int] | None = None,
    max_combos_per_strategy: int = 50,
    max_total_trials: int = 500,
    fee_percent: float = 0.04,
    slippage_percent: float = 0.0,
    param_overrides: dict[str, list[Any]] | None = None,
    random_seed: int = 42,
) -> list[ExperimentResult]:
    """
    Explora estrategias × params × horizon × conjuntos de activos × (opcional) sesión.
    - strategy_ids: ej. ["mean_reversion", "alpha_score"]; None = todas.
    - horizons: ej. ["1h", "4h"]; None = ["4h"].
    - symbol_sets: ej. ["top20", "top50", "all"]; None = ["all"].
    - session_hours: (start_hour_utc, end_hour_utc) para filtrar barras; None = todas las horas.
    - max_combos_per_strategy: máx combinaciones de params por estrategia (grid muestreado).
    - max_total_trials: tope global de backtests para no disparar tiempos.
    Devuelve lista de ExperimentResult ordenada por net_return_percent descendente.
    """
    if not rows:
        return []
    random.seed(random_seed)
    registry = get_registry()
    ids = strategy_ids or list(registry.keys())
    horizons = horizons or ["4h"]
    symbol_sets = symbol_sets or ["all"]

    # Filtrar por sesión si se pide
    if session_hours is not None:
        rows = filter_rows_by_session(rows, session_hours[0], session_hours[1])
    if not rows:
        return []

    all_results: list[ExperimentResult] = []
    total_trials = 0

    for sid in ids:
        strategy = get_strategy(sid)
        if not strategy:
            continue
        for horizon in horizons:
            for sym_set_key in symbol_sets:
                symbols = get_symbol_set(rows, sym_set_key)
                for params in _sample_param_combos(strategy, max_combos_per_strategy, param_overrides):
                    if total_trials >= max_total_trials:
                        break
                    if sid == "mean_reversion" and params.get("oversold", 0) >= params.get("overbought", 0):
                        continue
                    res = run_single(
                        rows,
                        sid,
                        params,
                        horizon=horizon,
                        fee_percent=fee_percent,
                        slippage_percent=slippage_percent,
                        symbols=symbols,
                    )
                    if res:
                        res.meta = dict(res.meta)
                        res.meta["symbol_set"] = sym_set_key
                        all_results.append(res)
                        total_trials += 1
                if total_trials >= max_total_trials:
                    break
            if total_trials >= max_total_trials:
                break
        if total_trials >= max_total_trials:
            break

    # Ordenar por fitness (risk-adjusted)
    all_results.sort(key=lambda r: r.fitness, reverse=True)
    return all_results


def _sample_param_combos(
    strategy,
    max_combos: int,
    param_overrides: dict[str, list[Any]] | None,
) -> list[dict]:
    """Genera combinaciones de params (grid o sample) para la estrategia."""
    from ai.explorer.experiment import _grid_params
    combos = _grid_params(strategy, param_overrides)
    if len(combos) <= max_combos:
        return combos
    return random.sample(combos, max_combos)


def run_optimization_grid(
    rows: list[dict],
    strategy_id: str,
    horizons: list[str] | None = None,
    symbol_sets: list[str] | None = None,
    session_hours: tuple[int, int] | None = None,
    max_combos: int = 100,
    fee_percent: float = 0.04,
    param_overrides: dict[str, list[Any]] | None = None,
) -> list[ExperimentResult]:
    """
    Grid completo sobre una sola estrategia (más combinaciones que run_optimization).
    Útil para mean_reversion u otra con muchos params.
    """
    if not rows:
        return []
    if session_hours is not None:
        rows = filter_rows_by_session(rows, session_hours[0], session_hours[1])
    if not rows:
        return []
    horizons = horizons or ["4h"]
    symbol_sets = symbol_sets or ["all"]
    all_results: list[ExperimentResult] = []
    for horizon in horizons:
        for sym_set_key in symbol_sets:
            symbols = get_symbol_set(rows, sym_set_key)
            results = run_grid(
                rows,
                strategy_id,
                horizon=horizon,
                fee_percent=fee_percent,
                param_overrides=param_overrides,
                max_combos=max_combos,
                symbols=symbols,
            )
            for res in results:
                res.meta = dict(res.meta)
                res.meta["symbol_set"] = sym_set_key
                all_results.append(res)
    all_results.sort(key=lambda r: r.fitness, reverse=True)
    return all_results
