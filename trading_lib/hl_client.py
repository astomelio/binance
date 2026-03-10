import os
import logging
from hyperliquid.info import Info
from hyperliquid.utils import constants
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class HyperliquidTestnetClient:
    """HTTP client for Hyperliquid Testnet API"""

    def __init__(self, private_key: Optional[str] = None):
        self.is_testnet = True
        self.base_url = constants.TESTNET_API_URL
        self.info = Info(self.base_url, skip_ws=True)

        self.private_key = private_key or os.getenv("HYPERLIQUID_PRIVATE_KEY")
        self.wallet = None
        self.exchange = None

        if self.private_key:
            from eth_account import Account
            from hyperliquid.exchange import Exchange

            self.wallet = Account.from_key(self.private_key)
            self.exchange = Exchange(self.wallet, self.base_url)
            logger.info(f"Initialized Hyperliquid Testnet client for address: {self.wallet.address}")
        else:
            logger.warning("No HYPERLIQUID_PRIVATE_KEY provided. Hyperliquid client is in read-only mode.")

    def get_futures_ticker_price(self, symbol: str) -> float:
        """Get the current mark price for a symbol on Hyperliquid."""
        # Hyperliquid uses raw names like "BTC", we need to strip "USDT"
        hl_symbol = symbol.replace("USDT", "")
        
        meta = self.info.meta_and_asset_ctxs()
        asset_ctxs = meta[1]
        assets = meta[0]["universe"]
        
        for i, asset in enumerate(assets):
            if asset["name"] == hl_symbol:
                return float(asset_ctxs[i]["markPx"])
                
        raise ValueError(f"Symbol {hl_symbol} not found on Hyperliquid")

    def create_futures_order(
        self,
        symbol: str,
        side: str,  # 'BUY' or 'SELL'
        quantity: float,
        order_type: str = "MARKET",
        price: float = None,
        reduce_only: bool = False,
    ) -> Dict[str, Any]:
        """Execute order on Hyperliquid Testnet"""
        if not self.exchange:
            raise ValueError("Cannot create order: missing private key (read-only mode)")
            
        hl_symbol = symbol.replace("USDT", "")
        is_buy = True if side.upper() == 'BUY' else False
        
        try:
            if order_type.upper() == "MARKET":
                # For a market order, Hyperliquid uses MarketOrder type with a slippage price
                result = self.exchange.market_open(
                    hl_symbol,
                    is_buy,
                    quantity,
                    None, # Slippage price calculated internally or we can pass None
                    slippage=0.05 # 5% slippage
                )
            elif order_type.upper() == "LIMIT":
                if not price:
                    raise ValueError("Price is required for LIMIT orders")
                result = self.exchange.order(
                    hl_symbol,
                    is_buy,
                    quantity,
                    price,
                    {"limit": {"tif": "Gtc"}}
                )
            else:
                raise ValueError(f"Unsupported order type {order_type} on Hyperliquid wrapper")
                
            return {
                "status": "success",
                "exchange": "hyperliquid",
                "raw_response": result
            }
        except Exception as e:
            logger.error(f"Hyperliquid execution failed: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }
