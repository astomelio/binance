from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _resolve_symbols() -> List[str]:
    raw = os.getenv("DP_SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT")
    from data_platform.symbols import resolve_symbols
    return resolve_symbols(raw)


def _parse_dex_pairs_env() -> List[dict]:
    raw = os.getenv(
        "DEX_PAIRS_JSON",
        '[{"chain_id":"ethereum","pair_address":"0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640","symbol":"ETHUSDT"}]',
    )
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


@dataclass
class DataPlatformConfig:
    lake_root: str = os.getenv("LAKE_ROOT", "data_lake")
    api_base_url: str = os.getenv("API_BASE_URL", "http://localhost:8000")
    fed_calendar_url: str = os.getenv(
        "FED_CALENDAR_URL",
        "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    )
    fred_api_key: str = os.getenv("FRED_API_KEY", "")
    onchain_provider_url: str = os.getenv("ONCHAIN_PROVIDER_URL", "")
    strict_external_sources: bool = os.getenv("STRICT_EXTERNAL_SOURCES", "false").lower() == "true"
    symbols: List[str] = field(default_factory=_resolve_symbols)
    dex_pairs: List[dict] = field(default_factory=_parse_dex_pairs_env)

