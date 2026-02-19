"""Compatibility wrapper for API app.

Primary API code now lives in `apps/api/main.py`.
"""

from apps.api.main import app, get_binance_client

__all__ = ["app", "get_binance_client"]
