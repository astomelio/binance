from __future__ import annotations

from data_platform.config import DataPlatformConfig
from data_platform.pipeline import run_bronze, run_gold, run_silver
from trading_lib import FeeModel, TradingLogger, run_alpha_backtest


def main() -> None:
    cfg = DataPlatformConfig()

    logger = TradingLogger("alpha-serious")
    logger.event("PIPELINE_START", {"lake_root": cfg.lake_root, "symbols": cfg.symbols})

    run_bronze(cfg)
    run_silver(cfg)
    run_gold(cfg)

    result = run_alpha_backtest(
        decision_features_glob=f"{cfg.lake_root}/gold/signals/decision_features/**/part-*.jsonl",
        fee_model=FeeModel(),
        logger=logger,
    )

    print("=== Alpha Backtest (decision_features) ===")
    print(f"Trades: {result.trades}")
    print(f"WinRate: {result.win_rate:.2f}%")
    print(f"Gross Return: {result.gross_return_percent:.3f}%")
    print(f"Net Return: {result.net_return_percent:.3f}%")
    print(f"By Symbol: {result.by_symbol}")
    print(f"Log file: {logger.log_path}")


if __name__ == "__main__":
    main()

