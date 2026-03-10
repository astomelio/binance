"""Resolución de símbolos: lista fija o fetch de Binance."""

from __future__ import annotations

from typing import List

FUTURES_BASE = "https://fapi.binance.com"

# Top ~50 por liquidez en Futuros (Balance de volumen y seguridad)
TOP_USDT_SYMBOLS = [
    # Top 1-10
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
    # Top 11-20
    "MATICUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT", "ETCUSDT", "XLMUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "SUIUSDT",
    # Top 21-30 (Buenas altcoins de volumen)
    "NEARUSDT", "INJUSDT", "FTMUSDT", "SANDUSDT", "MANAUSDT", "GALAUSDT", "AXSUSDT", "RNDRUSDT", "TIAUSDT", "SEIUSDT",
    # Top 31-40 (Tendencias AI / Memes / Capas L1-L2)
    "WLDUSDT", "PEPEUSDT", "SHIBUSDT", "FETUSDT", "AGIXUSDT", "ORDIUSDT", "STXUSDT", "LDOUSDT", "FILUSDT", "ICPUSDT",
    # Top 41-50 (DeFi y Otras sólidas)
    "AAVEUSDT", "MKRUSDT", "RUNEUSDT", "IMXUSDT", "SNXUSDT", "GRTUSDT", "THETAUSDT", "EOSUSDT", "NEOUSDT", "KAVAUSDT"
]


def fetch_usdt_perpetual_symbols() -> List[str]:
    """Obtiene todos los símbolos USDT perpetual de Binance Futures."""
    import requests
    resp = requests.get(
        f"{FUTURES_BASE}/fapi/v1/exchangeInfo",
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    out = []
    for s in data.get("symbols", []):
        if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL":
            quote = s.get("quoteAsset", "")
            if quote == "USDT":
                out.append(s["symbol"])
    return sorted(out) if out else TOP_USDT_SYMBOLS


def resolve_symbols(raw: str) -> List[str]:
    """
    raw = "BTCUSDT,ETHUSDT" -> ["BTCUSDT", "ETHUSDT"]
    raw = "all" -> fetch_usdt_perpetual_symbols() (~500 símbolos)
    raw = "top" -> TOP_USDT_SYMBOLS (~20 más líquidos)
    """
    raw = (raw or "").strip().upper()
    if raw == "ALL":
        return fetch_usdt_perpetual_symbols()
    if raw == "TOP":
        return list(TOP_USDT_SYMBOLS)
    return [s.strip() for s in raw.split(",") if s.strip()]
