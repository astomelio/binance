"""
Informes enriquecidos de backtest: performance de champions en el tiempo,
estadísticas clave y comparación entre modelos de distintos estilos.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai.allocation.backtest import AllocationBacktestResult


@dataclass
class ChampionSnapshot:
    """Snapshot de un champion en un momento dado."""

    champion_id: str
    version: int
    timestamp: str
    net_return_percent: float
    max_drawdown_percent: float
    sharpe_ratio: float
    win_rate_percent: float
    trades_count: int
    periods: int
    equity_curve: list[float] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelComparisonRow:
    """Fila de comparación entre modelos."""

    model_id: str
    style: str  # "alpha_score", "mean_reversion", "heuristic", "ensemble"
    net_return_percent: float
    max_drawdown_percent: float
    sharpe_ratio: float
    win_rate_percent: float
    trades_count: int
    fitness: float
    virtues: list[str] = field(default_factory=list)
    flaws: list[str] = field(default_factory=list)


def _key_stats(result: AllocationBacktestResult) -> dict[str, Any]:
    """Extrae estadísticas clave de un resultado de backtest."""
    return {
        "net_return_percent": result.net_return_percent,
        "total_return_percent": result.total_return_percent,
        "max_drawdown_percent": result.max_drawdown_percent,
        "sharpe_ratio": result.sharpe_ratio,
        "win_rate_percent": result.win_rate_percent,
        "trades_count": result.trades_count,
        "periods": result.periods,
        "total_fees_percent": result.total_fees_percent,
        "total_slippage_percent": result.total_slippage_percent,
    }


def build_champion_timeline(
    snapshots: list[ChampionSnapshot],
) -> dict[str, Any]:
    """
    Construye un informe de performance de champions en el tiempo.
    Útil para ver evolución y detectar degradación.
    """
    if not snapshots:
        return {"champions": [], "summary": {}}
    rows = []
    for s in snapshots:
        rows.append({
            "champion_id": s.champion_id,
            "version": s.version,
            "timestamp": s.timestamp,
            "net_return_percent": s.net_return_percent,
            "max_drawdown_percent": s.max_drawdown_percent,
            "sharpe_ratio": s.sharpe_ratio,
            "win_rate_percent": s.win_rate_percent,
            "trades_count": s.trades_count,
            "periods": s.periods,
        })
    return {
        "champions": rows,
        "summary": {
            "count": len(snapshots),
            "best_net_return": max((s.net_return_percent for s in snapshots), default=0),
            "worst_drawdown": max((s.max_drawdown_percent for s in snapshots), default=0),
        },
    }


def build_model_comparison(
    results: list[tuple[str, AllocationBacktestResult | dict]],
    style_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Compara modelos de distintos estilos.
    results: [(model_id, result_or_dict), ...]
    style_map: model_id -> "alpha_score"|"mean_reversion"|"heuristic"|"ensemble"
    """
    style_map = style_map or {}
    rows = []
    for model_id, res in results:
        if isinstance(res, AllocationBacktestResult):
            stats = _key_stats(res)
            sharpe = res.sharpe_ratio
            mdd = res.max_drawdown_percent
            fitness = sharpe - 0.2 * mdd
        else:
            stats = res
            sharpe = res.get("sharpe_ratio", 0)
            mdd = res.get("max_drawdown_percent", 0)
            fitness = res.get("fitness", sharpe - 0.2 * mdd)
        style = style_map.get(model_id, "unknown")
        virtues = _infer_virtues(stats)
        flaws = _infer_flaws(stats)
        rows.append({
            "model_id": model_id,
            "style": style,
            "net_return_percent": stats.get("net_return_percent", 0),
            "max_drawdown_percent": stats.get("max_drawdown_percent", 0),
            "sharpe_ratio": sharpe,
            "win_rate_percent": stats.get("win_rate_percent", 0),
            "trades_count": stats.get("trades_count", 0),
            "fitness": fitness,
            "virtues": virtues,
            "flaws": flaws,
        })
    return {
        "models": rows,
        "best_by_fitness": max(rows, key=lambda r: r["fitness"]) if rows else None,
        "best_by_net_return": max(rows, key=lambda r: r["net_return_percent"]) if rows else None,
        "lowest_drawdown": min(rows, key=lambda r: r["max_drawdown_percent"]) if rows else None,
    }


def _infer_virtues(stats: dict) -> list[str]:
    """Infiere virtudes a partir de estadísticas."""
    v = []
    if stats.get("net_return_percent", 0) > 2:
        v.append("positive_returns")
    if stats.get("sharpe_ratio", 0) > 0.5:
        v.append("good_risk_adjusted")
    if stats.get("max_drawdown_percent", 99) < 5:
        v.append("low_drawdown")
    if stats.get("win_rate_percent", 0) > 55:
        v.append("high_win_rate")
    if stats.get("trades_count", 0) >= 20:
        v.append("sufficient_trades")
    return v


def _infer_flaws(stats: dict) -> list[str]:
    """Infiere defectos a partir de estadísticas."""
    f = []
    if stats.get("net_return_percent", 0) < 0:
        f.append("negative_returns")
    if stats.get("max_drawdown_percent", 0) > 15:
        f.append("high_drawdown")
    if stats.get("sharpe_ratio", 0) < 0:
        f.append("poor_risk_adjusted")
    if stats.get("trades_count", 0) < 5:
        f.append("insufficient_trades")
    if stats.get("win_rate_percent", 50) < 45:
        f.append("low_win_rate")
    return f


def write_backtest_report(
    path: Path | str,
    champion_timeline: dict[str, Any] | None = None,
    model_comparison: dict[str, Any] | None = None,
    key_stats: dict[str, Any] | None = None,
) -> None:
    """Escribe un informe JSON con champion timeline, comparación y stats."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "champion_timeline": champion_timeline or {},
        "model_comparison": model_comparison or {},
        "key_stats": key_stats or {},
    }
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
