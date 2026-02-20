#!/usr/bin/env python3
"""
Mostrar vector de asignación actual para todas las monedas.
0 = nada, 0.2 = 20% long, -0.2 = 20% short.
"""
import argparse
from ai.data.loader import load_decision_features
from ai.allocation import compute_allocations


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--horizon", default="4h")
    p.add_argument("--prob-threshold", type=float, default=0.55)
    args = p.parse_args()

    rows = load_decision_features(horizon=args.horizon, label_not_null=False)
    if not rows:
        print("No data")
        return

    # Último event_time
    by_time = {}
    for r in rows:
        ts = r.get("event_time", "")
        sym = r.get("symbol", "")
        if ts and sym:
            by_time.setdefault(ts, {})[sym] = r
    last_ts = max(by_time.keys())
    features = by_time[last_ts]

    alloc = compute_allocations(
        features,
        prob_threshold=args.prob_threshold,
        min_allocation=0.1,
        max_allocation=0.4,
    )
    print(f"event_time: {last_ts}")
    print("allocations (0=nada, 0.2=20% long, -0.2=20% short):")
    for s in sorted(alloc.keys()):
        a = alloc[s]
        side = "LONG" if a > 0 else "SHORT" if a < 0 else "-"
        pct = abs(a) * 100
        print(f"  {s}: {a:+.2f} ({pct:.0f}% {side})")


if __name__ == "__main__":
    main()
