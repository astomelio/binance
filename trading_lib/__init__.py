"""Reusable trading library for backtesting and live execution via local API."""

from .api_client import BinanceConnectorClient
from .alpha_backtest import AlphaBacktestResult, run_alpha_backtest
from .backtest import Backtester, BacktestResult
from .fees import FeeModel
from .live import FuturesLiveExecutor
from .models import Candle, FeatureSet, Regime, TradeSignal
from .planner import (
    AllocationDecision,
    PlannerFoldResult,
    PlannerResult,
    PlannerTrade,
    StrategySpec,
    compute_model_allocations,
    evaluate_strategy_walk_forward,
    load_specs_from_dicts,
    rank_results,
    write_experiment,
)
from .quant import (
    BenchmarkFoldMetric,
    BenchmarkResult,
    EntryMetaModel,
    EntryMetaReport,
    LabeledRow,
    QuantFoldMetric,
    QuantModelConfig,
    QuantTrainResult,
    benchmark_models_walk_forward,
    build_labeled_rows,
    optimize_quant_model,
    predict_entry_probability,
    train_entry_meta_model,
)
from .strategies import RegimeFuturesStrategy, Strategy
from .timeseries import WalkForwardSplit, build_walk_forward_splits, load_jsonl_timeseries
from .trade_logger import TradingLogger
from .zones import ZoneClassifier

__all__ = [
    "Backtester",
    "BacktestResult",
    "AlphaBacktestResult",
    "BinanceConnectorClient",
    "Candle",
    "FeatureSet",
    "FeeModel",
    "FuturesLiveExecutor",
    "AllocationDecision",
    "PlannerFoldResult",
    "PlannerResult",
    "PlannerTrade",
    "RegimeFuturesStrategy",
    "Regime",
    "StrategySpec",
    "Strategy",
    "TradeSignal",
    "TradingLogger",
    "WalkForwardSplit",
    "ZoneClassifier",
    "BenchmarkFoldMetric",
    "BenchmarkResult",
    "LabeledRow",
    "EntryMetaModel",
    "EntryMetaReport",
    "QuantFoldMetric",
    "QuantModelConfig",
    "QuantTrainResult",
    "compute_model_allocations",
    "build_walk_forward_splits",
    "benchmark_models_walk_forward",
    "build_labeled_rows",
    "predict_entry_probability",
    "train_entry_meta_model",
    "evaluate_strategy_walk_forward",
    "load_jsonl_timeseries",
    "load_specs_from_dicts",
    "optimize_quant_model",
    "rank_results",
    "run_alpha_backtest",
    "write_experiment",
]

