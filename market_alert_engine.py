"""Compatibility wrapper for market alert engine."""

from apps.automation.market_alert_engine import *  # noqa: F401,F403
from apps.automation.market_alert_engine import main


if __name__ == "__main__":
    main()
