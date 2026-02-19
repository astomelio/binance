"""Compatibility wrapper for fee calculator.

Primary module: `apps/automation/fee_calculator.py`
"""

from apps.automation.fee_calculator import *  # noqa: F401,F403
from apps.automation.fee_calculator import main


if __name__ == "__main__":
    main()
