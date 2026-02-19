"""Compatibility wrapper for strategy demo module."""

from apps.automation.trading_strategy_500usd import *  # noqa: F401,F403
from apps.automation.trading_strategy_500usd import main


if __name__ == "__main__":
    main()
