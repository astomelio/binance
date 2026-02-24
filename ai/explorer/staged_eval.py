"""
Evaluación por etapas: alpha solo, risk solo, mean reversion solo, sensores, combinaciones.
Cada etapa devuelve los mejores configs; la última evalúa combinaciones de los mejores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai.allocation.backtest import run_allocation_backtest
from ai.allocation.risk import apply_risk_overlay
from ai.explorer.data_filters import get_symbol_set
from ai.explorer.experiment import run_single
from ai.explorer.registry import get_strategy


@dataclass
class StageResult:
    """Resultado de una config en una etapa."""
    stage: str
    config: dict[str, Any]
    net_return_percent: float
    trades_count: int
    meta: dict[str, Any] = field(default_factory=dict)


def _run_backtest_with_risk(
    rows: list[dict],
    strategy_id: str,
    params: dict[str, Any],
    horizon: str = "4h",
    fee_percent: float = 0.04,
    symbols: list[str] | None = None,
    max_exposure: float = 1.0,
    max_per_symbol: float = 0.4,
    max_net_exposure: float | None = None,
) -> StageResult | None:
    """Backtest de una estrategia con risk overlay aplicado."""
    strategy = get_strategy(strategy_id)
    if not strategy:
        return None
    base_fn = strategy.build_compute_fn(rows, params)

    def compute_fn(features: dict, ts: str):
        alloc = base_fn(features, ts)
        return apply_risk_overlay(
            alloc,
            max_exposure=max_exposure,
            max_per_symbol=max_per_symbol,
            max_net_exposure=max_net_exposure,
        )

    r = run_allocation_backtest(
        rows,
        horizon=horizon,
        fee_percent=fee_percent,
        compute_fn=compute_fn,
        symbols=symbols,
    )
    return StageResult(
        stage="risk",
        config={
            "strategy_id": strategy_id,
            "params": params,
            "horizon": horizon,
            "max_exposure": max_exposure,
            "max_per_symbol": max_per_symbol,
            "max_net_exposure": max_net_exposure,
        },
        net_return_percent=r.net_return_percent,
        trades_count=r.trades_count,
    )


def run_stage_alpha_only(
    rows: list[dict],
    horizons: list[str] | None = None,
    symbol_sets: list[str] | None = None,
    fee_percent: float = 0.04,
    max_combos: int = 30,
) -> list[StageResult]:
    """
    Etapa 1: solo alpha (estrategia alpha_score). Varía prob_threshold, min/max_allocation.
    """
    horizons = horizons or ["4h"]
    symbol_sets = symbol_sets or ["all"]
    strategy = get_strategy("alpha_score")
    if not strategy:
        return []
    from ai.explorer.experiment import _grid_params
    param_combos = _grid_params(strategy, None)[:max_combos]
    results: list[StageResult] = []
    for params in param_combos:
        for horizon in horizons:
            for sym_key in symbol_sets:
                symbols = get_symbol_set(rows, sym_key)
                res = run_single(
                    rows,
                    "alpha_score",
                    params,
                    horizon=horizon,
                    fee_percent=fee_percent,
                    symbols=symbols,
                )
                if res:
                    results.append(StageResult(
                        stage="alpha",
                        config={"params": params, "horizon": horizon, "symbol_set": sym_key},
                        net_return_percent=res.net_return_percent,
                        trades_count=res.trades_count,
                        meta={"strategy_id": "alpha_score"},
                    ))
    results.sort(key=lambda x: x.net_return_percent, reverse=True)
    return results


def run_stage_risk_only(
    rows: list[dict],
    base_strategy_id: str = "alpha_score",
    base_params: dict[str, Any] | None = None,
    horizon: str = "4h",
    fee_percent: float = 0.04,
    risk_grid: dict[str, list[Any]] | None = None,
) -> list[StageResult]:
    """
    Etapa 2: solo risk management. Estrategia base fija; varía max_exposure, max_per_symbol, max_net_exposure.
    """
    strategy = get_strategy(base_strategy_id)
    if not strategy:
        return []
    params = base_params or strategy.default_params
    risk_grid = risk_grid or {
        "max_exposure": [0.6, 1.0],
        "max_per_symbol": [0.2, 0.3, 0.4],
        "max_net_exposure": [None, 0.5],
    }
    keys = list(risk_grid.keys())
    values = [risk_grid[k] for k in keys]
    import itertools
    results: list[StageResult] = []
    for combo in itertools.product(*values):
        rp = dict(zip(keys, combo))
        max_exp = rp.get("max_exposure", 1.0)
        max_sym = rp.get("max_per_symbol", 0.4)
        max_net = rp.get("max_net_exposure")
        res = _run_backtest_with_risk(
            rows,
            base_strategy_id,
            params,
            horizon=horizon,
            fee_percent=fee_percent,
            max_exposure=max_exp,
            max_per_symbol=max_sym,
            max_net_exposure=max_net,
        )
        if res:
            res.config["symbol_set"] = "all"
            results.append(res)
    results.sort(key=lambda x: x.net_return_percent, reverse=True)
    return results


def run_stage_mean_reversion_only(
    rows: list[dict],
    horizons: list[str] | None = None,
    symbol_sets: list[str] | None = None,
    fee_percent: float = 0.04,
    max_combos: int = 40,
) -> list[StageResult]:
    """
    Etapa 3: solo mean reversion. Varía oversold, overbought, top_volatile, vol_metric.
    """
    horizons = horizons or ["4h"]
    symbol_sets = symbol_sets or ["all"]
    strategy = get_strategy("mean_reversion")
    if not strategy:
        return []
    from ai.explorer.experiment import _grid_params
    param_combos = _grid_params(strategy, None)
    param_combos = [p for p in param_combos if p.get("oversold", -2) < p.get("overbought", 2)][:max_combos]
    results: list[StageResult] = []
    for params in param_combos:
        for horizon in horizons:
            for sym_key in symbol_sets:
                symbols = get_symbol_set(rows, sym_key)
                res = run_single(
                    rows,
                    "mean_reversion",
                    params,
                    horizon=horizon,
                    fee_percent=fee_percent,
                    symbols=symbols,
                )
                if res:
                    results.append(StageResult(
                        stage="mean_reversion",
                        config={"params": params, "horizon": horizon, "symbol_set": sym_key},
                        net_return_percent=res.net_return_percent,
                        trades_count=res.trades_count,
                        meta={"strategy_id": "mean_reversion"},
                    ))
    results.sort(key=lambda x: x.net_return_percent, reverse=True)
    return results


def run_stage_sensors(
    rows: list[dict],
    horizons: list[str] | None = None,
    symbol_sets: list[str] | None = None,
    fee_percent: float = 0.04,
) -> list[StageResult]:
    """
    Etapa 4: sensores de movimiento inminente. Heuristic (alpha_signal) y variaciones de allocation_size.
    """
    horizons = horizons or ["4h"]
    symbol_sets = symbol_sets or ["all"]
    strategy = get_strategy("heuristic")
    if not strategy:
        return []
    from ai.explorer.experiment import _grid_params
    param_combos = _grid_params(strategy, None)
    results: list[StageResult] = []
    for params in param_combos:
        for horizon in horizons:
            for sym_key in symbol_sets:
                symbols = get_symbol_set(rows, sym_key)
                res = run_single(
                    rows,
                    "heuristic",
                    params,
                    horizon=horizon,
                    fee_percent=fee_percent,
                    symbols=symbols,
                )
                if res:
                    results.append(StageResult(
                        stage="sensors",
                        config={"params": params, "horizon": horizon, "symbol_set": sym_key},
                        net_return_percent=res.net_return_percent,
                        trades_count=res.trades_count,
                        meta={"strategy_id": "heuristic"},
                    ))
    results.sort(key=lambda x: x.net_return_percent, reverse=True)
    return results


def run_stage_combinations(
    rows: list[dict],
    best_alpha: list[StageResult],
    best_risk: list[StageResult],
    best_mean_reversion: list[StageResult],
    best_sensors: list[StageResult],
    top_per_stage: int = 2,
    fee_percent: float = 0.04,
) -> list[StageResult]:
    """
    Etapa 5: combina los mejores de cada etapa. Evalúa:
    - mejor alpha + mejor risk overlay
    - mejor mean_reversion + mejor risk overlay
    - (opcional) blend o filtro por sensor
    """
    results: list[StageResult] = []
    a_list = best_alpha[:top_per_stage]
    r_list = best_risk[:top_per_stage]
    mr_list = best_mean_reversion[:top_per_stage]

    for sa in a_list:
        for sr in r_list:
            # Alpha + risk overlay
            cfg_a = sa.config
            cfg_r = sr.config
            params = cfg_a.get("params", {})
            horizon = cfg_a.get("horizon", "4h")
            res = _run_backtest_with_risk(
                rows,
                "alpha_score",
                params,
                horizon=horizon,
                fee_percent=fee_percent,
                max_exposure=cfg_r.get("max_exposure", 1.0),
                max_per_symbol=cfg_r.get("max_per_symbol", 0.4),
                max_net_exposure=cfg_r.get("max_net_exposure"),
            )
            if res:
                res.stage = "combo_alpha_risk"
                res.config = {"alpha": cfg_a, "risk": cfg_r}
                results.append(res)

    for smr in mr_list:
        for sr in r_list:
            cfg_mr = smr.config
            cfg_r = sr.config
            params = cfg_mr.get("params", {})
            horizon = cfg_mr.get("horizon", "4h")
            res = _run_backtest_with_risk(
                rows,
                "mean_reversion",
                params,
                horizon=horizon,
                fee_percent=fee_percent,
                max_exposure=cfg_r.get("max_exposure", 1.0),
                max_per_symbol=cfg_r.get("max_per_symbol", 0.4),
                max_net_exposure=cfg_r.get("max_net_exposure"),
            )
            if res:
                res.stage = "combo_mr_risk"
                res.config = {"mean_reversion": cfg_mr, "risk": cfg_r}
                results.append(res)

    results.sort(key=lambda x: x.net_return_percent, reverse=True)
    return results


def run_all_stages(
    rows: list[dict],
    horizons: list[str] | None = None,
    symbol_sets: list[str] | None = None,
    top_per_stage: int = 2,
    alpha_combos: int = 20,
    mean_rev_combos: int = 30,
) -> dict[str, Any]:
    """
    Ejecuta las 5 etapas y devuelve mejores por etapa + mejores combinaciones.
    """
    horizons = horizons or ["4h"]
    symbol_sets = symbol_sets or ["top50", "all"]

    best_alpha = run_stage_alpha_only(rows, horizons=horizons, symbol_sets=symbol_sets, max_combos=alpha_combos)
    best_risk = run_stage_risk_only(rows, horizon=horizons[0], fee_percent=0.04)
    best_mr = run_stage_mean_reversion_only(rows, horizons=horizons, symbol_sets=symbol_sets, max_combos=mean_rev_combos)
    best_sensors = run_stage_sensors(rows, horizons=horizons, symbol_sets=symbol_sets)
    best_combos = run_stage_combinations(
        rows,
        best_alpha,
        best_risk,
        best_mr,
        best_sensors,
        top_per_stage=top_per_stage,
    )

    return {
        "stage_alpha": best_alpha[:5],
        "stage_risk": best_risk[:5],
        "stage_mean_reversion": best_mr[:5],
        "stage_sensors": best_sensors[:5],
        "stage_combinations": best_combos[:10],
        "best_overall": (best_combos[0] if best_combos else None)
                         or (best_mr[0] if best_mr else None)
                         or (best_alpha[0] if best_alpha else None),
    }
