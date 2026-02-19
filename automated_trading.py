"""Compatibility wrapper for automated trading module."""

from apps.automation.automated_trading import *  # noqa: F401,F403
from apps.automation.automated_trading import main


if __name__ == "__main__":
    main()
