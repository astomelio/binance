from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from data_platform.config import DataPlatformConfig
from data_platform.ingestion.collectors import (
    BinanceDerivativesPublicCollector,
    BinanceDerivativesFlowCollector,
    BinanceLocalCollector,
    CoinGeckoGlobalCollector,
    DexScreenerCollector,
    FearGreedCollector,
    FREDMacroCollector,
    FedCalendarCollector,
    OKXFuturesCollector,
    OnChainCollector,
    BybitFuturesCollector,
)
from data_platform.storage.lake_writer import LakeWriter
from data_platform.transforms.gold import build_decision_features
from data_platform.transforms.silver import (
    normalize_cross_exchange_snapshot,
    normalize_dex_snapshot,
    normalize_derivatives_snapshot,
    normalize_derivatives_flow,
    normalize_fed_calendar,
    normalize_fear_greed,
    normalize_global_market,
    normalize_macro_rates,
    normalize_market_snapshot,
)


def _read_jsonl(path_pattern: str) -> List[Dict]:
    rows: List[Dict] = []
    for file in glob.glob(path_pattern, recursive=True):
        with open(file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    rows.sort(key=lambda x: x.get("event_time", ""))
    return rows


def run_bronze(cfg: DataPlatformConfig, source_groups: Sequence[str] | None = None) -> None:
    writer = LakeWriter(cfg.lake_root)
    collectors_with_groups = [
        ("high", BinanceLocalCollector(cfg.api_base_url, cfg.symbols)),
        ("high", BinanceDerivativesPublicCollector(cfg.symbols)),
        ("high", BinanceDerivativesFlowCollector(cfg.symbols)),
        ("high", BybitFuturesCollector(cfg.symbols)),
        ("high", OKXFuturesCollector(cfg.symbols)),
        ("medium", CoinGeckoGlobalCollector()),
        ("medium", FearGreedCollector()),
        ("medium", DexScreenerCollector(cfg.dex_pairs)),
        ("low", FREDMacroCollector(cfg.fred_api_key)),
        ("low", FedCalendarCollector(live_url=cfg.fed_calendar_url)),
        ("low", OnChainCollector(cfg.onchain_provider_url)),
    ]
    selected_groups = set(source_groups or ["high", "medium", "low"])
    failures: List[Tuple[str, str, str]] = []

    for group, collector in collectors_with_groups:
        if group not in selected_groups:
            continue
        try:
            events = collector.collect()
            if not events:
                print(f"[bronze][SKIP] {collector.source}/{collector.dataset}: no rows")
                continue
            out = writer.write_events("bronze", collector.source, collector.dataset, events)
            print(f"[bronze] {collector.source}/{collector.dataset}: {len(events)} rows -> {out}")
        except Exception as exc:  # noqa: BLE001
            print(f"[bronze][WARN] {collector.source}/{collector.dataset}: {exc}")
            failures.append((collector.source, collector.dataset, str(exc)))

    if cfg.strict_external_sources and failures:
        raise RuntimeError(f"Bronze failed collectors: {failures}")


def run_silver(cfg: DataPlatformConfig) -> None:
    writer = LakeWriter(cfg.lake_root)

    market_events = _read_jsonl(f"{cfg.lake_root}/bronze/binance_local_api/market_snapshot/**/part-*.jsonl")
    derivatives_events = _read_jsonl(f"{cfg.lake_root}/bronze/binance_public/derivatives_snapshot/**/part-*.jsonl")
    derivatives_flow_events = _read_jsonl(f"{cfg.lake_root}/bronze/binance_public/derivatives_flow/**/part-*.jsonl")
    bybit_events = _read_jsonl(f"{cfg.lake_root}/bronze/bybit_public/futures_snapshot/**/part-*.jsonl")
    okx_events = _read_jsonl(f"{cfg.lake_root}/bronze/okx_public/futures_snapshot/**/part-*.jsonl")
    dex_events = _read_jsonl(f"{cfg.lake_root}/bronze/dexscreener/dex_snapshot/**/part-*.jsonl")
    global_events = _read_jsonl(f"{cfg.lake_root}/bronze/coingecko/global_market/**/part-*.jsonl")
    fear_greed_events = _read_jsonl(f"{cfg.lake_root}/bronze/alternative_me/fear_greed_index/**/part-*.jsonl")
    macro_events = _read_jsonl(f"{cfg.lake_root}/bronze/fred/macro_rates/**/part-*.jsonl")
    fed_events = _read_jsonl(f"{cfg.lake_root}/bronze/fed_calendar/decision_dates/**/part-*.jsonl")

    if market_events:
        out = writer.write_events(
            "silver",
            "market",
            "market_snapshot_normalized",
            normalize_market_snapshot(market_events),
        )
        print(f"[silver] market_snapshot_normalized -> {out}")
    if derivatives_events:
        out = writer.write_events(
            "silver",
            "market",
            "derivatives_snapshot_normalized",
            normalize_derivatives_snapshot(derivatives_events),
        )
        print(f"[silver] derivatives_snapshot_normalized -> {out}")
    if derivatives_flow_events:
        out = writer.write_events(
            "silver",
            "market",
            "derivatives_flow_normalized",
            normalize_derivatives_flow(derivatives_flow_events),
        )
        print(f"[silver] derivatives_flow_normalized -> {out}")
    if bybit_events or okx_events:
        out = writer.write_events(
            "silver",
            "market",
            "cross_exchange_snapshot_normalized",
            normalize_cross_exchange_snapshot(bybit_events + okx_events),
        )
        print(f"[silver] cross_exchange_snapshot_normalized -> {out}")
    if dex_events:
        out = writer.write_events(
            "silver",
            "market",
            "dex_snapshot_normalized",
            normalize_dex_snapshot(dex_events),
        )
        print(f"[silver] dex_snapshot_normalized -> {out}")
    if global_events:
        out = writer.write_events(
            "silver",
            "global",
            "global_market_normalized",
            normalize_global_market(global_events),
        )
        print(f"[silver] global_market_normalized -> {out}")
    if fear_greed_events:
        out = writer.write_events(
            "silver",
            "global",
            "fear_greed_normalized",
            normalize_fear_greed(fear_greed_events),
        )
        print(f"[silver] fear_greed_normalized -> {out}")
    if macro_events:
        out = writer.write_events(
            "silver",
            "macro",
            "macro_rates_normalized",
            normalize_macro_rates(macro_events),
        )
        print(f"[silver] macro_rates_normalized -> {out}")
    if fed_events:
        out = writer.write_events(
            "silver",
            "macro",
            "fed_calendar_normalized",
            normalize_fed_calendar(fed_events),
        )
        print(f"[silver] fed_calendar_normalized -> {out}")


def run_gold(cfg: DataPlatformConfig) -> None:
    writer = LakeWriter(cfg.lake_root)
    market_rows = _read_jsonl(f"{cfg.lake_root}/silver/market/market_snapshot_normalized/**/part-*.jsonl")
    derivatives_rows = _read_jsonl(f"{cfg.lake_root}/silver/market/derivatives_snapshot_normalized/**/part-*.jsonl")
    derivatives_flow_rows = _read_jsonl(f"{cfg.lake_root}/silver/market/derivatives_flow_normalized/**/part-*.jsonl")
    cross_exchange_rows = _read_jsonl(f"{cfg.lake_root}/silver/market/cross_exchange_snapshot_normalized/**/part-*.jsonl")
    dex_rows = _read_jsonl(f"{cfg.lake_root}/silver/market/dex_snapshot_normalized/**/part-*.jsonl")
    global_rows = _read_jsonl(f"{cfg.lake_root}/silver/global/global_market_normalized/**/part-*.jsonl")
    fear_greed_rows = _read_jsonl(f"{cfg.lake_root}/silver/global/fear_greed_normalized/**/part-*.jsonl")
    macro_rows = _read_jsonl(f"{cfg.lake_root}/silver/macro/macro_rates_normalized/**/part-*.jsonl")
    fed_rows = _read_jsonl(f"{cfg.lake_root}/silver/macro/fed_calendar_normalized/**/part-*.jsonl")

    features = build_decision_features(
        market_rows,
        derivatives_rows,
        derivatives_flow_rows,
        cross_exchange_rows,
        dex_rows,
        global_rows,
        fear_greed_rows,
        macro_rows,
        fed_rows,
    )
    if not features:
        print("[gold] no features produced (missing silver inputs)")
        return
    out = writer.write_events("gold", "signals", "decision_features", features)
    print(f"[gold] decision_features -> {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Data Lake ETL pipeline (bronze/silver/gold)")
    parser.add_argument("--mode", choices=["bronze", "silver", "gold", "all"], default="all")
    args = parser.parse_args()

    cfg = DataPlatformConfig()
    Path(cfg.lake_root).mkdir(parents=True, exist_ok=True)

    if args.mode in ("bronze", "all"):
        run_bronze(cfg)
    if args.mode in ("silver", "all"):
        run_silver(cfg)
    if args.mode in ("gold", "all"):
        run_gold(cfg)


if __name__ == "__main__":
    main()

