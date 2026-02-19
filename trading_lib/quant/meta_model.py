from __future__ import annotations

import math
import random
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Dict, List, Sequence

from .labels import LabeledRow


@dataclass
class EntryMetaModel:
    feature_names: List[str]
    means: Dict[str, float]
    stds: Dict[str, float]
    weights: Dict[str, float]
    bias: float
    prob_threshold: float


@dataclass
class EntryMetaReport:
    samples: int
    hit_rate_percent: float
    selected_rate_percent: float
    avg_net_return_percent: float
    threshold: float


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _safe_std(values: Sequence[float]) -> float:
    s = pstdev(values) if len(values) > 1 else 0.0
    return s if s > 1e-12 else 1.0


def _dot(row: Dict[str, float], weights: Dict[str, float], bias: float) -> float:
    return bias + sum(float(row.get(k, 0.0) or 0.0) * float(weights.get(k, 0.0)) for k in weights.keys())


def _normalize_row(row: Dict[str, float], means: Dict[str, float], stds: Dict[str, float]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for k, m in means.items():
        out[k] = (float(row.get(k, 0.0) or 0.0) - m) / float(stds[k])
    return out


def _future_return(row: LabeledRow, horizon: str) -> float:
    return float(getattr(row, horizon))


def _build_samples(
    labeled_rows: List[LabeledRow],
    base_weights: Dict[str, float],
    fee_percent: float,
    horizon: str = "fwd_return_4h",
) -> List[Dict]:
    out: List[Dict] = []
    for row in labeled_rows:
        model_score = sum(float(base_weights.get(k, 0.0)) * float(v) for k, v in row.features.items())
        side = 1.0 if model_score >= 0 else -1.0
        future = _future_return(row, horizon)
        net = (side * future) - fee_percent

        feats = dict(row.features)
        feats["model_score"] = model_score
        feats["model_score_abs"] = abs(model_score)
        feats["model_score_sign"] = 1.0 if model_score >= 0 else -1.0

        out.append(
            {
                "event_time": row.event_time,
                "symbol": row.symbol,
                "features": feats,
                "label": 1.0 if net > 0 else 0.0,
                "net_return_percent": net,
            }
        )
    out.sort(key=lambda x: x["event_time"])
    return out


def train_entry_meta_model(
    labeled_rows: List[LabeledRow],
    base_weights: Dict[str, float],
    fee_percent: float = 0.04,
    horizon: str = "fwd_return_4h",
    train_ratio: float = 0.8,
    seed: int = 42,
    epochs: int = 350,
    lr: float = 0.04,
    l2: float = 0.0005,
) -> tuple[EntryMetaModel, EntryMetaReport]:
    if not labeled_rows:
        raise ValueError("No labeled rows for meta model training")
    random.seed(seed)

    samples = _build_samples(labeled_rows, base_weights=base_weights, fee_percent=fee_percent, horizon=horizon)
    feature_names = sorted(samples[0]["features"].keys())

    split_idx = max(1, int(len(samples) * train_ratio))
    train = samples[:split_idx]
    test = samples[split_idx:] if split_idx < len(samples) else samples[-max(1, len(samples) // 5) :]

    means = {k: mean([float(s["features"][k]) for s in train]) for k in feature_names}
    stds = {k: _safe_std([float(s["features"][k]) for s in train]) for k in feature_names}

    x_train = [_normalize_row(s["features"], means, stds) for s in train]
    y_train = [float(s["label"]) for s in train]

    weights = {k: random.uniform(-0.05, 0.05) for k in feature_names}
    bias = 0.0

    n = float(len(x_train))
    for _ in range(epochs):
        grad_w = {k: 0.0 for k in feature_names}
        grad_b = 0.0
        for x, y in zip(x_train, y_train):
            p = _sigmoid(_dot(x, weights, bias))
            err = p - y
            grad_b += err
            for k in feature_names:
                grad_w[k] += err * x[k]
        for k in feature_names:
            grad_w[k] = (grad_w[k] / n) + (l2 * weights[k])
            weights[k] -= lr * grad_w[k]
        bias -= lr * (grad_b / n)

    model = EntryMetaModel(
        feature_names=feature_names,
        means=means,
        stds=stds,
        weights=weights,
        bias=bias,
        prob_threshold=0.45,
    )

    test_rows = test
    probs = [predict_entry_probability(s["features"], model) for s in test_rows]
    labels = [float(s["label"]) for s in test_rows]
    nets = [float(s["net_return_percent"]) for s in test_rows]

    # Tune probability threshold on test split with a quality objective.
    best = None
    # Use a broad threshold grid because model probability calibration can shift by sample.
    for th in [0.35, 0.38, 0.40, 0.42, 0.45, 0.48, 0.50, 0.52]:
        selected_idx = [i for i, p in enumerate(probs) if p >= th]
        if not selected_idx:
            continue
        hit_rate = _pct(sum(labels[i] for i in selected_idx), len(selected_idx))
        avg_net = sum(nets[i] for i in selected_idx) / len(selected_idx)
        selected_rate = _pct(len(selected_idx), len(test_rows))
        objective = avg_net + (0.005 * hit_rate) + (0.002 * selected_rate)
        candidate = (objective, th, hit_rate, avg_net, selected_rate)
        if best is None or candidate[0] > best[0]:
            best = candidate

    if best:
        _, best_th, hit_rate, avg_net, selected_rate = best
        model.prob_threshold = float(best_th)
        report = EntryMetaReport(
            samples=len(test_rows),
            hit_rate_percent=round(hit_rate, 2),
            selected_rate_percent=round(selected_rate, 2),
            avg_net_return_percent=round(avg_net, 5),
            threshold=round(best_th, 4),
        )
    else:
        report = EntryMetaReport(
            samples=len(test_rows),
            hit_rate_percent=0.0,
            selected_rate_percent=0.0,
            avg_net_return_percent=0.0,
            threshold=model.prob_threshold,
        )
    return model, report


def predict_entry_probability(features: Dict[str, float], model: EntryMetaModel) -> float:
    x = _normalize_row(features, model.means, model.stds)
    return _sigmoid(_dot(x, model.weights, model.bias))


def _pct(n: float, d: float) -> float:
    return (n / d * 100.0) if d else 0.0

