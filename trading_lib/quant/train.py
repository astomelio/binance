from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Dict, List, Tuple

from ..fees import FeeModel
from ..timeseries import build_walk_forward_splits
from .labels import LabeledRow


@dataclass
class QuantModelConfig:
    weights: Dict[str, float]
    threshold: float


@dataclass
class QuantFoldMetric:
    split_index: int
    net_return_percent: float
    win_rate: float
    trades: int
    sharpe_like: float


@dataclass
class QuantTrainResult:
    config: QuantModelConfig
    mean_net_return_percent: float
    std_net_return_percent: float
    mean_win_rate: float
    mean_sharpe_like: float
    mean_trades: float
    folds: List[QuantFoldMetric]


def _score(features: Dict[str, float], weights: Dict[str, float]) -> float:
    return sum(weights.get(k, 0.0) * float(v) for k, v in features.items())


def _simulate(rows: List[LabeledRow], cfg: QuantModelConfig, fee_model: FeeModel, target_horizon: str) -> Tuple[float, float, int, float]:
    rt_fee = fee_model.round_trip_fee_percent("futures", is_maker=True)
    returns: List[float] = []
    wins = 0
    trades = 0
    for row in rows:
        s = _score(row.features, cfg.weights)
        if s >= cfg.threshold:
            signal = 1.0
        elif s <= -cfg.threshold:
            signal = -1.0
        else:
            signal = 0.0

        if signal == 0:
            continue
        trades += 1
        future_ret = getattr(row, target_horizon)
        net = (signal * future_ret) - rt_fee
        returns.append(net)
        if net > 0:
            wins += 1

    if not returns:
        return 0.0, 0.0, 0, 0.0
    avg = mean(returns)
    vol = pstdev(returns) if len(returns) > 1 else 0.0
    sharpe_like = (avg / vol) if vol > 0 else 0.0
    return sum(returns), (wins / trades) * 100 if trades else 0.0, trades, sharpe_like


def optimize_quant_model(
    labeled_rows: List[LabeledRow],
    target_horizon: str = "fwd_return_4h",
    random_trials: int = 120,
    train_days: int = 60,
    test_days: int = 14,
    step_days: int = 14,
    embargo_hours: int = 12,
    seed: int = 42,
) -> QuantTrainResult:
    if not labeled_rows:
        raise ValueError("No labeled rows provided")

    random.seed(seed)
    rows = sorted(labeled_rows, key=lambda x: x.event_time)
    row_dicts = [{"event_time": r.event_time} for r in rows]
    splits = build_walk_forward_splits(
        rows=row_dicts,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        embargo_hours=embargo_hours,
    )
    if not splits:
        # fallback single split using all rows
        splits = []

    feature_names = list(rows[0].features.keys())
    fee_model = FeeModel()

    def eval_cfg(cfg: QuantModelConfig) -> QuantTrainResult:
        fold_metrics: List[QuantFoldMetric] = []
        if not splits:
            net, wr, tr, sh = _simulate(rows, cfg, fee_model, target_horizon)
            fold_metrics.append(QuantFoldMetric(1, net, wr, tr, sh))
        else:
            from datetime import datetime

            def p(ts: str):
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))

            for idx, split in enumerate(splits, start=1):
                a, b = p(split.test_start), p(split.test_end)
                test_rows = [r for r in rows if a <= p(r.event_time) < b]
                net, wr, tr, sh = _simulate(test_rows, cfg, fee_model, target_horizon)
                fold_metrics.append(QuantFoldMetric(idx, net, wr, tr, sh))

        nets = [f.net_return_percent for f in fold_metrics]
        wrs = [f.win_rate for f in fold_metrics]
        shs = [f.sharpe_like for f in fold_metrics]
        trs = [f.trades for f in fold_metrics]
        return QuantTrainResult(
            config=cfg,
            mean_net_return_percent=mean(nets) if nets else 0.0,
            std_net_return_percent=pstdev(nets) if len(nets) > 1 else 0.0,
            mean_win_rate=mean(wrs) if wrs else 0.0,
            mean_sharpe_like=mean(shs) if shs else 0.0,
            mean_trades=mean(trs) if trs else 0.0,
            folds=fold_metrics,
        )

    best = None
    for _ in range(random_trials):
        weights = {k: random.uniform(-1.0, 1.0) for k in feature_names}
        # Keep threshold in a practical tradable range to avoid overly sparse models.
        cfg = QuantModelConfig(weights=weights, threshold=random.uniform(0.05, 0.4))
        result = eval_cfg(cfg)
        objective = result.mean_net_return_percent - (0.5 * result.std_net_return_percent) + (0.2 * result.mean_sharpe_like)
        if best is None:
            best = (objective, result)
        else:
            if objective > best[0]:
                best = (objective, result)

    return best[1] if best else eval_cfg(QuantModelConfig(weights={k: 0.0 for k in feature_names}, threshold=0.4))

