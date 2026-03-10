import os
import time
import logging
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException
from dotenv import load_dotenv
from pydantic import BaseModel
import asyncio
from contextlib import asynccontextmanager

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global client cache (thread-safe for synchronous binance client)
_client_cache = None

def get_binance_client() -> Client:
    """Initialize and return Binance client (cached). Uses BINANCE_API_KEY, BINANCE_SECRET_KEY, BINANCE_TESTNET."""
    global _client_cache
    if _client_cache is None:
        api_key = os.getenv("BINANCE_API_KEY")
        secret_key = os.getenv("BINANCE_SECRET_KEY")
        testnet = os.getenv("BINANCE_TESTNET", "false").lower() == "true"

        if not api_key or not secret_key:
            raise ValueError("BINANCE_API_KEY and BINANCE_SECRET_KEY must be set")

        _client_cache = Client(api_key, secret_key, testnet=testnet)
        # Sync timestamp with Binance server (avoids -1021 in containers with wrong clock)
        try:
            res = _client_cache.futures_time() if testnet else _client_cache.get_server_time()
            server_ms = res.get("serverTime", 0) if isinstance(res, dict) else 0
            if server_ms:
                _client_cache.timestamp_offset = int(server_ms) - int(time.time() * 1000)
        except Exception as e:
            logger.warning("Could not sync Binance server time: %s", e)

    return _client_cache

# Pydantic models for request/response validation
class OrderRequest(BaseModel):
    symbol: str
    side: str  # BUY or SELL
    order_type: str  # MARKET, LIMIT, etc.
    quantity: Optional[float] = None
    price: Optional[float] = None
    time_in_force: Optional[str] = None

class FuturesOrderRequest(BaseModel):
    symbol: str
    side: str  # BUY or SELL
    order_type: str  # MARKET, LIMIT, etc.
    quantity: Optional[float] = None
    price: Optional[float] = None
    time_in_force: Optional[str] = None
    position_side: Optional[str] = None  # LONG or SHORT
    reduce_only: Optional[bool] = False
    close_position: Optional[bool] = False
    stop_price: Optional[float] = None

class SmartLimitOrderRequest(BaseModel):
    symbol: str
    side: str  # BUY or SELL
    quantity: float
    price_offset_percent: Optional[float] = 0.1

class SmartFuturesLimitOrderRequest(BaseModel):
    symbol: str
    side: str  # BUY or SELL
    quantity: float
    position_side: Optional[str] = None  # LONG or SHORT
    price_offset_percent: Optional[float] = 0.1

class LeverageRequest(BaseModel):
    symbol: str
    leverage: int

class MarginTypeRequest(BaseModel):
    symbol: str
    margin_type: str  # ISOLATED or CROSSED

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        await websocket.send_json(message)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

# FastAPI app initialization
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Binance Connector API (FastAPI)")
    yield
    # Shutdown
    logger.info("Shutting down Binance Connector API")

app = FastAPI(
    title="Binance Connector API",
    description="Conector completo para la API de Binance con FastAPI",
    version="2.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# SPOT TRADING ENDPOINTS
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        'status': 'healthy',
        'service': 'binance-connector',
        'version': '2.0.0',
        'framework': 'FastAPI'
    }

@app.get("/account/info")
async def get_account_info():
    """Get account information"""
    try:
        client = get_binance_client()
        account_info = client.get_account()
        
        return {
            'status': 'success',
            'data': {
                'maker_commission': account_info['makerCommission'],
                'taker_commission': account_info['takerCommission'],
                'buyer_commission': account_info['buyerCommission'],
                'seller_commission': account_info['sellerCommission'],
                'can_trade': account_info['canTrade'],
                'can_withdraw': account_info['canWithdraw'],
                'can_deposit': account_info['canDeposit'],
                'update_time': account_info['updateTime']
            }
        }
    except BinanceAPIException as e:
        logger.error(f"Binance API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.get("/account/balance")
async def get_account_balance():
    """Get account balance"""
    try:
        client = get_binance_client()
        account_info = client.get_account()
        
        balances = []
        for balance in account_info['balances']:
            if float(balance['free']) > 0 or float(balance['locked']) > 0:
                balances.append({
                    'asset': balance['asset'],
                    'free': balance['free'],
                    'locked': balance['locked'],
                    'total': str(float(balance['free']) + float(balance['locked']))
                })
        
        return {
            'status': 'success',
            'data': balances
        }
    except BinanceAPIException as e:
        logger.error(f"Binance API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.get("/market/ticker/{symbol}")
async def get_ticker(symbol: str):
    """Get ticker information for a symbol"""
    try:
        client = get_binance_client()
        ticker = client.get_ticker(symbol=symbol.upper())
        
        return {
            'status': 'success',
            'data': {
                'symbol': ticker.get('symbol'),
                'price_change': ticker.get('priceChange'),
                'price_change_percent': ticker.get('priceChangePercent'),
                'weighted_avg_price': ticker.get('weightedAvgPrice'),
                'prev_close_price': ticker.get('prevClosePrice'),
                'last_price': ticker.get('lastPrice'),
                'last_qty': ticker.get('lastQty'),
                'bid_price': ticker.get('bidPrice'),
                'ask_price': ticker.get('askPrice'),
                'open_price': ticker.get('openPrice'),
                'high_price': ticker.get('highPrice'),
                'low_price': ticker.get('lowPrice'),
                'volume': ticker.get('volume'),
                'quote_volume': ticker.get('quoteVolume'),
                'open_time': ticker.get('openTime'),
                'close_time': ticker.get('closeTime'),
                'count': ticker.get('count')
            }
        }
    except BinanceAPIException as e:
        logger.error(f"Binance API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.get("/market/klines/{symbol}")
async def get_klines(
    symbol: str,
    interval: str = Query(default='1d', description="Interval: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M"),
    limit: int = Query(default=100, ge=1, le=1000, description="Number of klines")
):
    """Get kline/candlestick data for a symbol"""
    try:
        client = get_binance_client()
        
        klines = client.get_klines(
            symbol=symbol.upper(),
            interval=interval,
            limit=limit
        )
        
        formatted_klines = []
        for kline in klines:
            formatted_klines.append({
                'open_time': kline[0],
                'open': kline[1],
                'high': kline[2],
                'low': kline[3],
                'close': kline[4],
                'volume': kline[5],
                'close_time': kline[6],
                'quote_asset_volume': kline[7],
                'number_of_trades': kline[8],
                'taker_buy_base_asset_volume': kline[9],
                'taker_buy_quote_asset_volume': kline[10]
            })
        
        return {
            'status': 'success',
            'data': formatted_klines
        }
    except BinanceAPIException as e:
        logger.error(f"Binance API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.post("/order/create")
async def create_order(order_request: OrderRequest):
    """Create a new order"""
    try:
        client = get_binance_client()
        
        # Prepare order parameters
        order_params = {
            'symbol': order_request.symbol.upper(),
            'side': order_request.side.upper(),
            'type': order_request.order_type.upper()
        }
        
        if order_request.quantity:
            order_params['quantity'] = order_request.quantity
        
        if order_request.price:
            order_params['price'] = order_request.price
        
        if order_request.time_in_force:
            order_params['timeInForce'] = order_request.time_in_force.upper()
        
        # Create the order
        result = client.create_order(**order_params)
        
        return {
            'status': 'success',
            'data': {
                'symbol': result['symbol'],
                'order_id': result['orderId'],
                'client_order_id': result['clientOrderId'],
                'transact_time': result['transactTime'],
                'price': result['price'],
                'orig_qty': result['origQty'],
                'executed_qty': result['executedQty'],
                'cummulative_quote_qty': result['cummulativeQuoteQty'],
                'status': result['status'],
                'time_in_force': result['timeInForce'],
                'type': result['type'],
                'side': result['side']
            }
        }
    except BinanceAPIException as e:
        logger.error(f"Binance API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except BinanceOrderException as e:
        logger.error(f"Binance order error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.get("/order/{symbol}")
async def get_orders(
    symbol: str,
    limit: int = Query(default=10, ge=1, le=1000, description="Number of orders")
):
    """Get orders for a symbol"""
    try:
        client = get_binance_client()
        
        orders = client.get_all_orders(symbol=symbol.upper(), limit=limit)
        
        formatted_orders = []
        for order in orders:
            formatted_orders.append({
                'symbol': order['symbol'],
                'order_id': order['orderId'],
                'client_order_id': order['clientOrderId'],
                'price': order['price'],
                'orig_qty': order['origQty'],
                'executed_qty': order['executedQty'],
                'cummulative_quote_qty': order['cummulativeQuoteQty'],
                'status': order['status'],
                'time_in_force': order['timeInForce'],
                'type': order['type'],
                'side': order['side'],
                'stop_price': order['stopPrice'],
                'iceberg_qty': order['icebergQty'],
                'time': order['time'],
                'update_time': order['updateTime'],
                'is_working': order['isWorking'],
                'orig_quote_order_qty': order['origQuoteOrderQty']
            })
        
        return {
            'status': 'success',
            'data': formatted_orders
        }
    except BinanceAPIException as e:
        logger.error(f"Binance API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.delete("/order/{symbol}/{order_id}")
async def cancel_order(symbol: str, order_id: int):
    """Cancel an order"""
    try:
        client = get_binance_client()
        
        result = client.cancel_order(
            symbol=symbol.upper(),
            orderId=order_id
        )
        
        return {
            'status': 'success',
            'data': {
                'symbol': result['symbol'],
                'order_id': result['orderId'],
                'client_order_id': result['clientOrderId'],
                'price': result['price'],
                'orig_qty': result['origQty'],
                'executed_qty': result['executedQty'],
                'cummulative_quote_qty': result['cummulativeQuoteQty'],
                'status': result['status'],
                'time_in_force': result['timeInForce'],
                'type': result['type'],
                'side': result['side']
            }
        }
    except BinanceAPIException as e:
        logger.error(f"Binance API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

# ============================================================================
# FUTURES TRADING ENDPOINTS
# ============================================================================

@app.get("/futures/account/info")
async def get_futures_account_info():
    """Get futures account information"""
    try:
        client = get_binance_client()
        account_info = client.futures_account()
        
        return {
            'status': 'success',
            'data': {
                'fee_tier': account_info['feeTier'],
                'can_trade': account_info['canTrade'],
                'can_deposit': account_info['canDeposit'],
                'can_withdraw': account_info['canWithdraw'],
                'update_time': account_info['updateTime'],
                'total_wallet_balance': account_info['totalWalletBalance'],
                'total_margin_balance': account_info['totalMarginBalance'],
                'total_unrealized_profit': account_info['totalUnrealizedProfit'],
                'total_maint_margin': account_info['totalMaintMargin'],
                'total_position_margin': account_info['totalPositionMargin'],
                'total_initial_margin': account_info['totalInitialMargin'],
                'total_future_open_interest': account_info['totalFutureOpenInterest'],
                'total_margin_balance_in_usdt': account_info['totalMarginBalanceInUSDT'],
                'total_unrealized_profit_in_usdt': account_info['totalUnrealizedProfitInUSDT'],
                'total_wallet_balance_in_usdt': account_info['totalWalletBalanceInUSDT'],
                'available_balance_in_usdt': account_info['availableBalanceInUSDT']
            }
        }
    except BinanceAPIException as e:
        logger.error(f"Binance Futures API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.get("/futures/account/balance")
async def get_futures_account_balance():
    """Get futures account balance"""
    try:
        client = get_binance_client()
        account_info = client.futures_account()
        
        balances = []
        for asset in account_info['assets']:
            up = asset.get('unRealizedProfit') or asset.get('unrealizedProfit') or 0
            if float(asset.get('walletBalance', 0) or 0) > 0 or float(up) > 0:
                balances.append({
                    'asset': asset['asset'],
                    'wallet_balance': asset['walletBalance'],
                    'unrealized_profit': up,
                    'margin_balance': asset['marginBalance'],
                    'maint_margin': asset['maintMargin'],
                    'initial_margin': asset['initialMargin'],
                    'position_initial_margin': asset['positionInitialMargin'],
                    'open_order_initial_margin': asset['openOrderInitialMargin'],
                    'max_withdraw_amount': asset['maxWithdrawAmount'],
                    'cross_wallet_balance': asset['crossWalletBalance'],
                    'cross_un_pnl': asset['crossUnPnl'],
                    'available_balance': asset['availableBalance'],
                    'margin_available': asset['marginAvailable'],
                    'update_time': asset['updateTime']
                })
        
        return {
            'status': 'success',
            'data': balances
        }
    except BinanceAPIException as e:
        logger.error(f"Binance Futures API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.get("/futures/exchange-info")
async def get_futures_exchange_info():
    """Get futures exchange information including symbol filters"""
    try:
        client = get_binance_client()
        info = client.futures_exchange_info()
        return {
            'status': 'success',
            'data': info
        }
    except BinanceAPIException as e:
        logger.error(f"Binance Futures API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.get("/futures/positions")
async def get_futures_positions():
    """Get futures positions"""
    try:
        client = get_binance_client()
        positions = client.futures_position_information()
        
        formatted_positions = []
        for position in positions:
            if float(position.get('positionAmt', 0)) != 0:  # Only show active positions
                formatted_positions.append({
                    'symbol': position.get('symbol', ''),
                    'initial_margin': position.get('initialMargin', '0'),
                    'maint_margin': position.get('maintMargin', '0'),
                    'unrealized_profit': position.get('unRealizedProfit') or position.get('unrealizedProfit', '0'),
                    'position_initial_margin': position.get('positionInitialMargin', '0'),
                    'open_order_initial_margin': position.get('openOrderInitialMargin', '0'),
                    'leverage': position.get('leverage', '1'),
                    'isolated': position.get('isolated', False),
                    'entry_price': position.get('entryPrice', '0'),
                    'max_notional': position.get('maxNotional', '0'),
                    'bid_notional': position.get('bidNotional', '0'),
                    'ask_notional': position.get('askNotional', '0'),
                    'position_side': position.get('positionSide', 'BOTH'),
                    'position_amt': position.get('positionAmt', '0'),
                    'update_time': position.get('updateTime', 0)
                })
        
        return {
            'status': 'success',
            'data': formatted_positions
        }
    except BinanceAPIException as e:
        logger.error(f"Binance Futures API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.get("/futures/market/orderbook/{symbol}")
async def get_futures_orderbook(
    symbol: str,
    limit: int = Query(default=5, ge=1, le=100, description="Order book depth")
):
    """Get futures order book (bids/asks) for limit order pricing."""
    try:
        client = get_binance_client()
        ob = client.futures_order_book(symbol=symbol.upper(), limit=limit)
        return {
            "status": "success",
            "data": {
                "bids": [[float(b[0]), float(b[1])] for b in ob.get("bids", [])],
                "asks": [[float(a[0]), float(a[1])] for a in ob.get("asks", [])],
            }
        }
    except BinanceAPIException as e:
        logger.error(f"Binance Futures API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/futures/market/ticker/{symbol}")
async def get_futures_ticker(symbol: str):
    """Get futures ticker information for a symbol"""
    try:
        client = await asyncio.to_thread(get_binance_client)
        ticker = await asyncio.to_thread(client.futures_ticker, symbol=symbol.upper())
        
        return {
            'status': 'success',
            'data': {
                'symbol': ticker.get('symbol'),
                'price_change': ticker.get('priceChange'),
                'price_change_percent': ticker.get('priceChangePercent'),
                'weighted_avg_price': ticker.get('weightedAvgPrice'),
                'prev_close_price': ticker.get('prevClosePrice'),
                'last_price': ticker.get('lastPrice'),
                'last_qty': ticker.get('lastQty'),
                'open_price': ticker.get('openPrice'),
                'high_price': ticker.get('highPrice'),
                'low_price': ticker.get('lowPrice'),
                'volume': ticker.get('volume'),
                'quote_volume': ticker.get('quoteVolume'),
                'open_time': ticker.get('openTime'),
                'close_time': ticker.get('closeTime'),
                'first_id': ticker.get('firstId'),
                'last_id': ticker.get('lastId'),
                'count': ticker.get('count')
            }
        }
    except BinanceAPIException as e:
        logger.error(f"Binance Futures API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.get("/futures/market/klines/{symbol}")
async def get_futures_klines(
    symbol: str,
    interval: str = Query(default='1d', description="Interval: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M"),
    limit: int = Query(default=100, ge=1, le=1000, description="Number of klines")
):
    """Get futures kline/candlestick data for a symbol"""
    try:
        client = get_binance_client()
        
        klines = client.futures_klines(
            symbol=symbol.upper(),
            interval=interval,
            limit=limit
        )
        
        formatted_klines = []
        for kline in klines:
            formatted_klines.append({
                'open_time': kline[0],
                'open': kline[1],
                'high': kline[2],
                'low': kline[3],
                'close': kline[4],
                'volume': kline[5],
                'close_time': kline[6],
                'quote_asset_volume': kline[7],
                'number_of_trades': kline[8],
                'taker_buy_base_asset_volume': kline[9],
                'taker_buy_quote_asset_volume': kline[10]
            })
        
        return {
            'status': 'success',
            'data': formatted_klines
        }
    except BinanceAPIException as e:
        logger.error(f"Binance Futures API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.post("/futures/order/create")
async def create_futures_order(order_request: FuturesOrderRequest):
    try:
        order_type = order_request.order_type.upper()
        if order_type == "MARKET" and (order_request.quantity is None or order_request.quantity <= 0):
            raise HTTPException(status_code=400, detail="quantity required and > 0 for MARKET order")

        order_params = {
            "symbol": order_request.symbol.upper(),
            "side": order_request.side.upper(),
            "type": order_type,
        }
        if order_request.quantity is not None:
            order_params["quantity"] = round(float(order_request.quantity), 8)
        if order_request.price is not None:
            order_params["price"] = order_request.price
        if order_request.time_in_force:
            order_params["timeInForce"] = order_request.time_in_force.upper()
        if order_request.position_side:
            order_params["positionSide"] = order_request.position_side.upper()
        if order_request.reduce_only is not None:
            order_params["reduceOnly"] = order_request.reduce_only
        if order_request.close_position is not None:
            order_params["closePosition"] = order_request.close_position
        if order_request.stop_price is not None:
            order_params["stopPrice"] = round(float(order_request.stop_price), 8)

        client = await asyncio.to_thread(get_binance_client)
        result = await asyncio.to_thread(client.futures_create_order, **order_params)
        r = result if isinstance(result, dict) else {}
        return {
            "status": "success",
            "data": {
                "symbol": r.get("symbol", ""),
                "order_id": r.get("orderId"),
                "client_order_id": r.get("clientOrderId", ""),
                "price": r.get("price", "0"),
                "orig_qty": r.get("origQty", "0"),
                "executed_qty": r.get("executedQty", "0"),
                "cummulative_quote_qty": r.get("cummulativeQuoteQty", "0"),
                "status": r.get("status", ""),
                "time_in_force": r.get("timeInForce", ""),
                "type": r.get("type", ""),
                "side": r.get("side", ""),
                "position_side": r.get("positionSide", ""),
                "reduce_only": r.get("reduceOnly", False),
                "close_position": r.get("closePosition", False),
                "activate_price": r.get("activatePrice", ""),
                "price_rate": r.get("priceRate", ""),
                "update_time": r.get("updateTime"),
                "working_type": r.get("workingType", ""),
                "price_protect": r.get("priceProtect", False),
                "orig_type": r.get("origType", ""),
                "price_match": r.get("priceMatch", ""),
                "self_trade_prevention_mode": r.get("selfTradePreventionMode", ""),
                "good_till_date": r.get("goodTillDate", ""),
                "time": r.get("time"),
            },
        }
    except BinanceAPIException as e:
        logger.error(f"Binance Futures API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except BinanceOrderException as e:
        logger.error(f"Binance Futures order error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.get("/futures/order/{symbol}")
async def get_futures_orders(
    symbol: str,
    limit: int = Query(default=10, ge=1, le=1000, description="Number of orders")
):
    """Get futures orders for a symbol"""
    try:
        client = get_binance_client()
        
        orders = client.futures_get_all_orders(symbol=symbol.upper(), limit=limit)
        
        formatted_orders = []
        for order in orders:
            formatted_orders.append({
                'symbol': order['symbol'],
                'order_id': order['orderId'],
                'client_order_id': order['clientOrderId'],
                'price': order['price'],
                'orig_qty': order['origQty'],
                'executed_qty': order['executedQty'],
                'cummulative_quote_qty': order['cummulativeQuoteQty'],
                'status': order['status'],
                'time_in_force': order['timeInForce'],
                'type': order['type'],
                'side': order['side'],
                'position_side': order.get('positionSide', ''),
                'reduce_only': order.get('reduceOnly', False),
                'close_position': order.get('closePosition', False),
                'activate_price': order.get('activatePrice', ''),
                'price_rate': order.get('priceRate', ''),
                'update_time': order['updateTime'],
                'working_type': order.get('workingType', ''),
                'price_protect': order.get('priceProtect', False),
                'orig_type': order.get('origType', ''),
                'price_match': order.get('priceMatch', ''),
                'self_trade_prevention_mode': order.get('selfTradePreventionMode', ''),
                'good_till_date': order.get('goodTillDate', ''),
                'time': order['time']
            })
        
        return {
            'status': 'success',
            'data': formatted_orders
        }
    except BinanceAPIException as e:
        logger.error(f"Binance Futures API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.delete("/futures/order/{symbol}/{order_id}")
async def cancel_futures_order(symbol: str, order_id: int):
    """Cancel a futures order"""
    try:
        client = get_binance_client()
        
        result = client.futures_cancel_order(
            symbol=symbol.upper(),
            orderId=order_id
        )
        
        return {
            'status': 'success',
            'data': {
                'symbol': result['symbol'],
                'order_id': result['orderId'],
                'client_order_id': result['clientOrderId'],
                'price': result['price'],
                'orig_qty': result['origQty'],
                'executed_qty': result['executedQty'],
                'cummulative_quote_qty': result['cummulativeQuoteQty'],
                'status': result['status'],
                'time_in_force': result['timeInForce'],
                'type': result['type'],
                'side': result['side'],
                'position_side': result.get('positionSide', ''),
                'reduce_only': result.get('reduceOnly', False),
                'close_position': result.get('closePosition', False),
                'activate_price': result.get('activatePrice', ''),
                'price_rate': result.get('priceRate', ''),
                'update_time': result['updateTime'],
                'working_type': result.get('workingType', ''),
                'price_protect': result.get('priceProtect', False),
                'orig_type': result.get('origType', ''),
                'price_match': result.get('priceMatch', ''),
                'self_trade_prevention_mode': result.get('selfTradePreventionMode', ''),
                'good_till_date': result.get('goodTillDate', ''),
                'time': result['time']
            }
        }
    except BinanceAPIException as e:
        logger.error(f"Binance Futures API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.post("/futures/leverage")
async def set_futures_leverage(leverage_request: LeverageRequest):
    """Set leverage for a futures symbol"""
    try:
        client = get_binance_client()
        result = client.futures_change_leverage(
            symbol=leverage_request.symbol.upper(),
            leverage=leverage_request.leverage
        )
        
        return {
            'status': 'success',
            'data': {
                'leverage': result['leverage'],
                'max_notional_value': result['maxNotionalValue'],
                'symbol': result['symbol']
            }
        }
    except BinanceAPIException as e:
        logger.error(f"Binance Futures API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.post("/futures/margin_type")
async def set_futures_margin_type(margin_request: MarginTypeRequest):
    """Set margin type for a futures symbol"""
    try:
        client = get_binance_client()
        result = client.futures_change_margin_type(
            symbol=margin_request.symbol.upper(),
            marginType=margin_request.margin_type.upper()
        )
        
        return {
            'status': 'success',
            'data': {
                'code': result['code'],
                'msg': result['msg']
            }
        }
    except BinanceAPIException as e:
        logger.error(f"Binance Futures API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

# ============================================================================
# SMART ORDER ENDPOINTS (Anti-Slippage)
# ============================================================================

@app.post("/order/smart-limit")
async def create_smart_limit_order(order_request: SmartLimitOrderRequest):
    """Create a smart limit order that avoids slippage"""
    try:
        client = get_binance_client()
        
        # Get current order book to find optimal price
        order_book = client.get_order_book(symbol=order_request.symbol.upper(), limit=5)
        
        if order_request.side.upper() == 'BUY':
            # For buy orders, use ask price (slightly above market)
            optimal_price = float(order_book['asks'][0][0])
            limit_price = optimal_price * (1 + order_request.price_offset_percent / 100)
        else:
            # For sell orders, use bid price (slightly below market)
            optimal_price = float(order_book['bids'][0][0])
            limit_price = optimal_price * (1 - order_request.price_offset_percent / 100)
        
        # Create limit order with optimal price
        order_params = {
            'symbol': order_request.symbol.upper(),
            'side': order_request.side.upper(),
            'type': 'LIMIT',
            'timeInForce': 'GTC',
            'quantity': order_request.quantity,
            'price': f"{limit_price:.8f}"
        }
        
        result = client.create_order(**order_params)
        
        return {
            'status': 'success',
            'data': {
                'symbol': result['symbol'],
                'order_id': result['orderId'],
                'client_order_id': result['clientOrderId'],
                'price': result['price'],
                'orig_qty': result['origQty'],
                'executed_qty': result['executedQty'],
                'status': result['status'],
                'time_in_force': result['timeInForce'],
                'type': result['type'],
                'side': result['side'],
                'optimal_price': optimal_price,
                'limit_price': limit_price,
                'price_offset_percent': order_request.price_offset_percent
            }
        }
    except BinanceAPIException as e:
        logger.error(f"Binance API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.post("/futures/order/smart-limit")
async def create_smart_futures_limit_order(order_request: SmartFuturesLimitOrderRequest):
    """Create a smart futures limit order that avoids slippage"""
    try:
        client = get_binance_client()
        
        # Get current futures order book
        order_book = client.futures_order_book(symbol=order_request.symbol.upper(), limit=5)
        
        if order_request.side.upper() == 'BUY':
            # For buy orders, use ask price (slightly above market)
            optimal_price = float(order_book['asks'][0][0])
            limit_price = optimal_price * (1 + order_request.price_offset_percent / 100)
        else:
            # For sell orders, use bid price (slightly below market)
            optimal_price = float(order_book['bids'][0][0])
            limit_price = optimal_price * (1 - order_request.price_offset_percent / 100)
        
        # Create futures limit order with optimal price
        order_params = {
            'symbol': order_request.symbol.upper(),
            'side': order_request.side.upper(),
            'type': 'LIMIT',
            'timeInForce': 'GTC',
            'quantity': order_request.quantity,
            'price': f"{limit_price:.8f}"
        }
        
        if order_request.position_side:
            order_params['positionSide'] = order_request.position_side.upper()
        
        result = client.futures_create_order(**order_params)
        
        return {
            'status': 'success',
            'data': {
                'symbol': result['symbol'],
                'order_id': result['orderId'],
                'client_order_id': result['clientOrderId'],
                'price': result['price'],
                'orig_qty': result['origQty'],
                'executed_qty': result['executedQty'],
                'status': result['status'],
                'time_in_force': result['timeInForce'],
                'type': result['type'],
                'side': result['side'],
                'position_side': result.get('positionSide', ''),
                'optimal_price': optimal_price,
                'limit_price': limit_price,
                'price_offset_percent': order_request.price_offset_percent
            }
        }
    except BinanceAPIException as e:
        logger.error(f"Binance Futures API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.get("/order/optimal-price/{symbol}")
async def get_optimal_price(
    symbol: str,
    side: str = Query(default='BUY', description="BUY or SELL"),
    price_offset_percent: float = Query(default=0.1, description="Price offset percentage")
):
    """Get optimal price for limit orders to avoid slippage"""
    try:
        client = get_binance_client()
        
        # Get current order book
        order_book = client.get_order_book(symbol=symbol.upper(), limit=5)
        
        if side.upper() == 'BUY':
            optimal_price = float(order_book['asks'][0][0])
            limit_price = optimal_price * (1 + price_offset_percent / 100)
            price_type = 'ask'
        else:
            optimal_price = float(order_book['bids'][0][0])
            limit_price = optimal_price * (1 - price_offset_percent / 100)
            price_type = 'bid'
        
        return {
            'status': 'success',
            'data': {
                'symbol': symbol.upper(),
                'side': side.upper(),
                'market_price': optimal_price,
                'suggested_limit_price': limit_price,
                'price_offset_percent': price_offset_percent,
                'price_type': price_type,
                'order_book_depth': {
                    'bids': order_book['bids'][:3],
                    'asks': order_book['asks'][:3]
                }
            }
        }
    except BinanceAPIException as e:
        logger.error(f"Binance API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

@app.get("/futures/order/optimal-price/{symbol}")
async def get_futures_optimal_price(
    symbol: str,
    side: str = Query(default='BUY', description="BUY or SELL"),
    price_offset_percent: float = Query(default=0.1, description="Price offset percentage")
):
    """Get optimal price for futures limit orders to avoid slippage"""
    try:
        client = get_binance_client()
        
        # Get current futures order book
        order_book = client.futures_order_book(symbol=symbol.upper(), limit=5)
        
        if side.upper() == 'BUY':
            optimal_price = float(order_book['asks'][0][0])
            limit_price = optimal_price * (1 + price_offset_percent / 100)
            price_type = 'ask'
        else:
            optimal_price = float(order_book['bids'][0][0])
            limit_price = optimal_price * (1 - price_offset_percent / 100)
            price_type = 'bid'
        
        return {
            'status': 'success',
            'data': {
                'symbol': symbol.upper(),
                'side': side.upper(),
                'market_price': optimal_price,
                'suggested_limit_price': limit_price,
                'price_offset_percent': price_offset_percent,
                'price_type': price_type,
                'order_book_depth': {
                    'bids': order_book['bids'][:3],
                    'asks': order_book['asks'][:3]
                }
            }
        }
    except BinanceAPIException as e:
        logger.error(f"Binance Futures API error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail='Internal server error')

# ============================================================================
# WEBSOCKET ENDPOINTS (NEW - Order Book Streaming)
# ============================================================================

@app.websocket("/ws/orderbook/{symbol}")
async def websocket_orderbook(websocket: WebSocket, symbol: str):
    """WebSocket endpoint for real-time order book streaming"""
    await manager.connect(websocket)
    logger.info(f"WebSocket connected for {symbol}")
    
    try:
        client = get_binance_client()
        
        while True:
            try:
                # Get current order book
                order_book = client.get_order_book(symbol=symbol.upper(), limit=20)
                
                # Format order book data
                orderbook_data = {
                    'symbol': symbol.upper(),
                    'bids': [[float(bid[0]), float(bid[1])] for bid in order_book['bids'][:10]],
                    'asks': [[float(ask[0]), float(ask[1])] for ask in order_book['asks'][:10]],
                    'timestamp': order_book.get('lastUpdateId', 0)
                }
                
                await websocket.send_json(orderbook_data)
                
                # Update every 500ms for real-time feel
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error in order book stream: {e}")
                await websocket.send_json({'error': str(e)})
                await asyncio.sleep(1)
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info(f"WebSocket disconnected for {symbol}")

@app.websocket("/ws/ticker/{symbol}")
async def websocket_ticker(websocket: WebSocket, symbol: str):
    """WebSocket endpoint for real-time ticker streaming"""
    await manager.connect(websocket)
    logger.info(f"Ticker WebSocket connected for {symbol}")
    
    try:
        client = get_binance_client()
        
        while True:
            try:
                ticker = client.get_ticker(symbol=symbol.upper())
                
                ticker_data = {
                    'symbol': ticker['symbol'],
                    'price': ticker['lastPrice'],
                    'bid': ticker['bidPrice'],
                    'ask': ticker['askPrice'],
                    'volume': ticker['volume'],
                    'price_change_percent': ticker['priceChangePercent'],
                    'timestamp': ticker['closeTime']
                }
                
                await websocket.send_json(ticker_data)
                
                # Update every 1 second
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Error in ticker stream: {e}")
                await websocket.send_json({'error': str(e)})
                await asyncio.sleep(1)
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info(f"Ticker WebSocket disconnected for {symbol}")

# ============================================================================
# FEE CALCULATION ENDPOINTS
# ============================================================================

@app.get("/fees/account")
async def get_account_fees():
    """Get real fees from your Binance account"""
    try:
        client = get_binance_client()
        account_info = client.get_account()
        
        # Binance returns fees as integers (10 = 0.1%)
        maker_commission = account_info['makerCommission'] / 10000
        taker_commission = account_info['takerCommission'] / 10000
        
        return {
            'status': 'success',
            'data': {
                'maker_fee': maker_commission,
                'taker_fee': taker_commission,
                'maker_percent': maker_commission * 100,
                'taker_percent': taker_commission * 100
            }
        }
    except Exception as e:
        logger.error(f"Error getting account fees: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/fees/calculate")
async def calculate_fees(
    amount: float = Query(..., description="Amount in USD"),
    is_maker: bool = Query(default=True, description="True for limit orders (maker), False for market (taker)"),
    market_type: str = Query(default='spot', description="'spot' or 'futures'")
):
    """Calculate fees for a trade"""
    try:
        from apps.automation.fee_calculator import FeeCalculator
        calc = FeeCalculator()
        
        if market_type == 'spot':
            fees = calc.calculate_spot_fees(amount, is_maker)
        else:
            fees = calc.calculate_futures_fees(amount, is_maker)
        
        return {
            'status': 'success',
            'data': fees
        }
    except Exception as e:
        logger.error(f"Error calculating fees: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/fees/round-trip")
async def calculate_round_trip_fees(
    amount: float = Query(..., description="Amount in USD"),
    is_maker: bool = Query(default=True, description="True for limit orders"),
    market_type: str = Query(default='spot', description="'spot' or 'futures'")
):
    """Calculate round trip fees (buy + sell)"""
    try:
        from apps.automation.fee_calculator import FeeCalculator
        calc = FeeCalculator()
        
        round_trip = calc.calculate_round_trip_fees(amount, is_maker, market_type)
        
        return {
            'status': 'success',
            'data': round_trip
        }
    except Exception as e:
        logger.error(f"Error calculating round trip fees: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/fees/min-profit")
async def calculate_min_profit_needed(
    amount: float = Query(..., description="Amount in USD"),
    target_profit_percent: float = Query(default=0, description="Target profit percentage"),
    market_type: str = Query(default='spot', description="'spot' or 'futures'"),
    is_maker: bool = Query(default=True, description="True for limit orders")
):
    """Calculate minimum profit needed to cover fees and achieve target"""
    try:
        from apps.automation.fee_calculator import FeeCalculator
        calc = FeeCalculator()
        
        min_profit = calc.calculate_min_profit_needed(amount, target_profit_percent, market_type, is_maker)
        
        return {
            'status': 'success',
            'data': min_profit
        }
    except Exception as e:
        logger.error(f"Error calculating min profit: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/fees/analyze-strategy")
async def analyze_strategy_profitability(strategy: Dict):
    """Analyze if a strategy is profitable after fees"""
    try:
        from apps.automation.fee_calculator import FeeCalculator
        calc = FeeCalculator()
        
        analysis = calc.analyze_strategy_profitability(
            strategy,
            strategy.get('market_type', 'spot')
        )
        
        return {
            'status': 'success',
            'data': analysis
        }
    except Exception as e:
        logger.error(f"Error analyzing strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/fees/compare")
async def compare_maker_vs_taker(
    amount: float = Query(..., description="Amount in USD"),
    market_type: str = Query(default='spot', description="'spot' or 'futures'")
):
    """Compare maker vs taker fees"""
    try:
        from apps.automation.fee_calculator import FeeCalculator
        calc = FeeCalculator()
        
        comparison = calc.compare_maker_vs_taker(amount, market_type)
        
        return {
            'status': 'success',
            'data': comparison
        }
    except Exception as e:
        logger.error(f"Error comparing fees: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# WAREHOUSE ENDPOINTS (DuckDB Data Lake)
# ============================================================================

import duckdb
import subprocess
import threading

# Global process tracker for background jobs
_background_jobs: Dict[str, Dict[str, Any]] = {}
_job_lock = threading.Lock()

def get_duckdb_path() -> str:
    """Get DuckDB path from environment or default"""
    return os.getenv('DBT_DUCKDB_PATH', 
                     os.path.join(os.path.dirname(__file__), '..', '..', 'artifacts', 'warehouse', 'crypto.duckdb'))

class SQLQuery(BaseModel):
    sql: str
    limit: Optional[int] = 1000

@app.get("/warehouse/tables")
async def list_warehouse_tables():
    """List all tables in the DuckDB warehouse"""
    try:
        db_path = get_duckdb_path()
        if not os.path.exists(db_path):
            return {
                'status': 'success',
                'data': {
                    'tables': [],
                    'message': 'Warehouse database not found. Run backfill first.'
                }
            }
        
        conn = duckdb.connect(db_path, read_only=True)
        tables = conn.execute("SHOW TABLES").fetchall()
        
        table_info = []
        for (table_name,) in tables:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                table_info.append({'name': table_name, 'row_count': count})
            except Exception:
                table_info.append({'name': table_name, 'row_count': 'error'})
        
        conn.close()
        
        return {
            'status': 'success',
            'data': {
                'tables': table_info,
                'db_path': db_path
            }
        }
    except Exception as e:
        logger.error(f"Error listing tables: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/warehouse/query")
async def execute_warehouse_query(query: SQLQuery):
    """Execute a SQL query on the DuckDB warehouse"""
    try:
        db_path = get_duckdb_path()
        if not os.path.exists(db_path):
            raise HTTPException(status_code=404, detail="Warehouse database not found")
        
        # Basic SQL injection protection
        sql_lower = query.sql.lower().strip()
        if any(keyword in sql_lower for keyword in ['drop', 'delete', 'update', 'insert', 'alter', 'create']):
            raise HTTPException(status_code=400, detail="Only SELECT queries are allowed")
        
        conn = duckdb.connect(db_path, read_only=True)
        
        # Add LIMIT if not present
        if 'limit' not in sql_lower:
            sql = f"{query.sql} LIMIT {query.limit}"
        else:
            sql = query.sql
        
        result = conn.execute(sql).fetchdf()
        conn.close()
        
        return {
            'status': 'success',
            'data': {
                'columns': list(result.columns),
                'rows': result.to_dict(orient='records'),
                'row_count': len(result)
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/warehouse/symbols")
async def list_warehouse_symbols():
    """List all symbols with data in the warehouse"""
    try:
        db_path = get_duckdb_path()
        if not os.path.exists(db_path):
            return {'status': 'success', 'data': {'symbols': []}}
        
        conn = duckdb.connect(db_path, read_only=True)
        
        # Try to get symbols from market_snapshot_raw or similar table
        symbols = []
        try:
            result = conn.execute("""
                SELECT DISTINCT symbol, COUNT(*) as records
                FROM market_snapshot_raw 
                GROUP BY symbol 
                ORDER BY records DESC
            """).fetchdf()
            symbols = result.to_dict(orient='records')
        except Exception:
            # Try alternative table
            try:
                tables = conn.execute("SHOW TABLES").fetchall()
                for (table_name,) in tables:
                    if 'symbol' in [col[0] for col in conn.execute(f"DESCRIBE {table_name}").fetchall()]:
                        result = conn.execute(f"SELECT DISTINCT symbol FROM {table_name} LIMIT 100").fetchdf()
                        symbols = [{'symbol': s, 'table': table_name} for s in result['symbol'].tolist()]
                        break
            except Exception:
                pass
        
        conn.close()
        
        return {
            'status': 'success',
            'data': {'symbols': symbols}
        }
    except Exception as e:
        logger.error(f"Error listing symbols: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/warehouse/features/{symbol}")
async def get_symbol_features(
    symbol: str,
    limit: int = Query(default=100, ge=1, le=10000)
):
    """Get decision features for a symbol"""
    try:
        db_path = get_duckdb_path()
        if not os.path.exists(db_path):
            raise HTTPException(status_code=404, detail="Warehouse database not found")
        
        conn = duckdb.connect(db_path, read_only=True)
        
        # Try decision_features table first
        try:
            result = conn.execute(f"""
                SELECT * FROM decision_features 
                WHERE symbol = '{symbol.upper()}'
                ORDER BY event_time DESC
                LIMIT {limit}
            """).fetchdf()
        except Exception:
            # Fallback to market data
            result = conn.execute(f"""
                SELECT * FROM market_snapshot_raw 
                WHERE symbol = '{symbol.upper()}'
                ORDER BY event_time DESC
                LIMIT {limit}
            """).fetchdf()
        
        conn.close()
        
        return {
            'status': 'success',
            'data': {
                'symbol': symbol.upper(),
                'columns': list(result.columns),
                'rows': result.to_dict(orient='records'),
                'row_count': len(result)
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting features: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/warehouse/stats")
async def get_warehouse_stats():
    """Get warehouse statistics"""
    try:
        db_path = get_duckdb_path()
        lake_root = os.getenv('LAKE_ROOT', os.path.join(os.path.dirname(__file__), '..', '..', 'data_lake'))
        
        stats = {
            'db_exists': os.path.exists(db_path),
            'db_path': db_path,
            'lake_root': lake_root,
            'lake_exists': os.path.exists(lake_root),
            'tables': []
        }
        
        if stats['db_exists']:
            stats['db_size_mb'] = round(os.path.getsize(db_path) / (1024 * 1024), 2)
            
            conn = duckdb.connect(db_path, read_only=True)
            tables = conn.execute("SHOW TABLES").fetchall()
            
            for (table_name,) in tables:
                try:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                    stats['tables'].append({'name': table_name, 'rows': count})
                except Exception:
                    pass
            
            conn.close()
        
        return {'status': 'success', 'data': stats}
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ACTIONS ENDPOINTS (Remote Command Execution)
# ============================================================================

class BackfillRequest(BaseModel):
    symbols: str = "top"  # "top", "all", or comma-separated symbols
    months: int = 36
    interval: str = "1h"

class TrainRequest(BaseModel):
    experiment_name: Optional[str] = "remote-train"
    trials: int = 50


class ExplorerAgentRequest(BaseModel):
    mode: str = "quick"  # quick, grid, full
    strategy: Optional[str] = "mean_reversion"  # for grid mode
    horizon: str = "4h"
    max_combos: int = 30


class ModelEvaluationRequest(BaseModel):
    train_days: int = 60
    test_days: int = 14
    step_days: int = 14


def run_background_job(job_id: str, command: List[str], cwd: str):
    """Run a command in background and track its status"""
    try:
        with _job_lock:
            _background_jobs[job_id]['status'] = 'running'
            _background_jobs[job_id]['started_at'] = asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0
        
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            env={**os.environ, 'LAKE_ROOT': os.path.join(cwd, 'data_lake')}
        )
        
        with _job_lock:
            _background_jobs[job_id]['status'] = 'completed' if result.returncode == 0 else 'failed'
            _background_jobs[job_id]['exit_code'] = result.returncode
            _background_jobs[job_id]['stdout'] = result.stdout[-5000:] if result.stdout else ''
            _background_jobs[job_id]['stderr'] = result.stderr[-2000:] if result.stderr else ''
    except Exception as e:
        with _job_lock:
            _background_jobs[job_id]['status'] = 'error'
            _background_jobs[job_id]['error'] = str(e)

@app.post("/actions/backfill")
async def start_backfill(request: BackfillRequest):
    """Start a backfill job in background"""
    import uuid
    from datetime import datetime
    
    job_id = str(uuid.uuid4())[:8]
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    venv_python = os.path.join(project_root, 'venv', 'Scripts', 'python.exe')
    
    if not os.path.exists(venv_python):
        venv_python = os.path.join(project_root, 'venv', 'bin', 'python')
    
    command = [
        venv_python, '-m', 'data_platform.backfill_from_vision',
        '--interval', request.interval,
        '--months', str(request.months)
    ]
    
    with _job_lock:
        _background_jobs[job_id] = {
            'type': 'backfill',
            'status': 'starting',
            'symbols': request.symbols,
            'months': request.months,
            'interval': request.interval,
            'created_at': datetime.now().isoformat()
        }
    
    # Set environment and start thread
    os.environ['DP_SYMBOLS'] = request.symbols
    thread = threading.Thread(target=run_background_job, args=(job_id, command, project_root))
    thread.start()
    
    return {
        'status': 'success',
        'data': {
            'job_id': job_id,
            'message': f'Backfill started for {request.symbols} symbols',
            'check_status': f'/actions/status/{job_id}'
        }
    }

@app.post("/actions/warehouse-load")
async def start_warehouse_load():
    """Load bronze data into DuckDB"""
    import uuid
    from datetime import datetime
    
    job_id = str(uuid.uuid4())[:8]
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    venv_python = os.path.join(project_root, 'venv', 'Scripts', 'python.exe')
    
    if not os.path.exists(venv_python):
        venv_python = os.path.join(project_root, 'venv', 'bin', 'python')
    
    load_script = '''
from data_platform.config import DataPlatformConfig
from data_platform.loaders.bronze_to_duckdb import load_bronze_to_duckdb
import os
cfg = DataPlatformConfig()
db_path = os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
count = load_bronze_to_duckdb(cfg, db_path)
print(f"Loaded {count} records")
'''
    
    command = [venv_python, '-c', load_script]
    
    with _job_lock:
        _background_jobs[job_id] = {
            'type': 'warehouse-load',
            'status': 'starting',
            'created_at': datetime.now().isoformat()
        }
    
    thread = threading.Thread(target=run_background_job, args=(job_id, command, project_root))
    thread.start()
    
    return {
        'status': 'success',
        'data': {
            'job_id': job_id,
            'message': 'Warehouse load started',
            'check_status': f'/actions/status/{job_id}'
        }
    }

@app.post("/actions/train")
async def start_training(request: TrainRequest):
    """Start ML training job"""
    import uuid
    from datetime import datetime
    
    job_id = str(uuid.uuid4())[:8]
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    venv_python = os.path.join(project_root, 'venv', 'Scripts', 'python.exe')
    
    if not os.path.exists(venv_python):
        venv_python = os.path.join(project_root, 'venv', 'bin', 'python')
    
    command = [
        venv_python, 'examples/quant_optuna_tuning.py',
        '--trials', str(request.trials),
        '--mlflow-uri', os.environ.get('MLFLOW_TRACKING_URI', f'sqlite:///{project_root}/artifacts/quant_model/mlflow_v2.db'),
        '--mlflow-experiment', request.experiment_name
    ]
    
    with _job_lock:
        _background_jobs[job_id] = {
            'type': 'train',
            'status': 'starting',
            'experiment': request.experiment_name,
            'trials': request.trials,
            'created_at': datetime.now().isoformat()
        }
    
    thread = threading.Thread(target=run_background_job, args=(job_id, command, project_root))
    thread.start()
    
    return {
        'status': 'success',
        'data': {
            'job_id': job_id,
            'message': f'Training started with {request.trials} trials',
            'check_status': f'/actions/status/{job_id}'
        }
    }


@app.post("/actions/explorer-agent")
async def start_explorer_agent(request: ExplorerAgentRequest):
    """Start ExplorationAgent in background (quick/grid/full)"""
    import uuid
    from datetime import datetime

    job_id = str(uuid.uuid4())[:8]
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    venv_python = os.path.join(project_root, 'venv', 'Scripts', 'python.exe')
    if not os.path.exists(venv_python):
        venv_python = os.path.join(project_root, 'venv', 'bin', 'python')

    cmd = [
        venv_python, 'examples/ai_explorer_agent.py', request.mode,
        '--horizon', request.horizon, '--max-combos', str(request.max_combos),
    ]
    if request.mode == 'grid':
        cmd.extend(['--strategy', request.strategy or 'mean_reversion'])

    with _job_lock:
        _background_jobs[job_id] = {
            'type': 'explorer-agent',
            'status': 'starting',
            'mode': request.mode,
            'strategy': request.strategy,
            'created_at': datetime.now().isoformat()
        }

    env = dict(os.environ)
    env['DBT_DUCKDB_PATH'] = env.get('DBT_DUCKDB_PATH', 'artifacts/warehouse/crypto.duckdb')
    if not os.path.isabs(env['DBT_DUCKDB_PATH']):
        env['DBT_DUCKDB_PATH'] = os.path.join(project_root, env['DBT_DUCKDB_PATH'])

    def _run():
        try:
            with _job_lock:
                _background_jobs[job_id]['status'] = 'running'
            result = subprocess.run(
                cmd, cwd=project_root, capture_output=True, text=True, env=env
            )
            with _job_lock:
                _background_jobs[job_id]['status'] = 'completed' if result.returncode == 0 else 'failed'
                _background_jobs[job_id]['exit_code'] = result.returncode
                _background_jobs[job_id]['stdout'] = (result.stdout or '')[-5000:]
                _background_jobs[job_id]['stderr'] = (result.stderr or '')[-2000:]
        except Exception as e:
            with _job_lock:
                _background_jobs[job_id]['status'] = 'error'
                _background_jobs[job_id]['error'] = str(e)

    thread = threading.Thread(target=_run)
    thread.start()

    return {
        'status': 'success',
        'data': {
            'job_id': job_id,
            'message': f'Explorer agent ({request.mode}) started',
            'check_status': f'/actions/status/{job_id}'
        }
    }


@app.post("/actions/model-evaluation")
async def start_model_evaluation(request: ModelEvaluationRequest):
    """Start model evaluation (LightGBM vs XGBoost vs mean reversion)"""
    import uuid
    from datetime import datetime

    job_id = str(uuid.uuid4())[:8]
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    venv_python = os.path.join(project_root, 'venv', 'Scripts', 'python.exe')
    if not os.path.exists(venv_python):
        venv_python = os.path.join(project_root, 'venv', 'bin', 'python')

    cmd = [
        venv_python, 'examples/quant_model_evaluation.py',
        '--train-days', str(request.train_days),
        '--test-days', str(request.test_days),
        '--step-days', str(request.step_days),
    ]

    with _job_lock:
        _background_jobs[job_id] = {
            'type': 'model-evaluation',
            'status': 'starting',
            'created_at': datetime.now().isoformat()
        }

    def _run():
        try:
            with _job_lock:
                _background_jobs[job_id]['status'] = 'running'
            result = subprocess.run(
                cmd, cwd=project_root, capture_output=True, text=True,
                env={**os.environ, 'LAKE_ROOT': os.path.join(project_root, 'data_lake')}
            )
            with _job_lock:
                _background_jobs[job_id]['status'] = 'completed' if result.returncode == 0 else 'failed'
                _background_jobs[job_id]['exit_code'] = result.returncode
                _background_jobs[job_id]['stdout'] = (result.stdout or '')[-5000:]
                _background_jobs[job_id]['stderr'] = (result.stderr or '')[-2000:]
        except Exception as e:
            with _job_lock:
                _background_jobs[job_id]['status'] = 'error'
                _background_jobs[job_id]['error'] = str(e)

    thread = threading.Thread(target=_run)
    thread.start()

    return {
        'status': 'success',
        'data': {
            'job_id': job_id,
            'message': 'Model evaluation started',
            'check_status': f'/actions/status/{job_id}'
        }
    }


@app.post("/actions/backfill-external")
async def start_backfill_external():
    """Backfill external sources (FRED, Fear&Greed, CoinGecko, FED Calendar, Glassnode)"""
    import uuid
    from datetime import datetime

    job_id = str(uuid.uuid4())[:8]
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    venv_python = os.path.join(project_root, 'venv', 'Scripts', 'python.exe')
    if not os.path.exists(venv_python):
        venv_python = os.path.join(project_root, 'venv', 'bin', 'python')

    cmd = [venv_python, '-m', 'data_platform.backfill_external_sources']

    with _job_lock:
        _background_jobs[job_id] = {
            'type': 'backfill-external',
            'status': 'starting',
            'created_at': datetime.now().isoformat()
        }

    def _run():
        try:
            with _job_lock:
                _background_jobs[job_id]['status'] = 'running'
            result = subprocess.run(
                cmd, cwd=project_root, capture_output=True, text=True,
                env={**os.environ, 'LAKE_ROOT': os.path.join(project_root, 'data_lake')}
            )
            with _job_lock:
                _background_jobs[job_id]['status'] = 'completed' if result.returncode == 0 else 'failed'
                _background_jobs[job_id]['exit_code'] = result.returncode
                _background_jobs[job_id]['stdout'] = (result.stdout or '')[-5000:]
                _background_jobs[job_id]['stderr'] = (result.stderr or '')[-2000:]
        except Exception as e:
            with _job_lock:
                _background_jobs[job_id]['status'] = 'error'
                _background_jobs[job_id]['error'] = str(e)

    thread = threading.Thread(target=_run)
    thread.start()

    return {
        'status': 'success',
        'data': {
            'job_id': job_id,
            'message': 'Backfill external sources started',
            'check_status': f'/actions/status/{job_id}'
        }
    }


@app.get("/actions/status")
async def list_all_jobs():
    """List all background jobs"""
    with _job_lock:
        return {
            'status': 'success',
            'data': {
                'jobs': dict(_background_jobs)
            }
        }

@app.get("/actions/status/{job_id}")
async def get_job_status(job_id: str):
    """Get status of a specific job"""
    with _job_lock:
        if job_id not in _background_jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return {
            'status': 'success',
            'data': _background_jobs[job_id]
        }

@app.delete("/actions/{job_id}")
async def cancel_job(job_id: str):
    """Cancel/remove a job from tracking"""
    with _job_lock:
        if job_id in _background_jobs:
            del _background_jobs[job_id]
            return {'status': 'success', 'message': 'Job removed'}
        raise HTTPException(status_code=404, detail="Job not found")

# ============================================================================
# AGENTS — quant agent suite endpoints
# ============================================================================

class SuiteCycleRequest(BaseModel):
    horizon: str = "4h"
    lookback_days: int = 0
    optimize: bool = False
    use_champion: bool = True
    max_trials: int = 400

class ResearchLoopRequest(BaseModel):
    horizon: str = "4h"
    lookback_days: int = 0
    max_cycles: int = 30
    cycles_before_explore: int = 3
    stop_on_promote: bool = False
    optimize: bool = True
    use_champion: bool = True
    max_trials: int = 400


def _get_project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _load_suite_data(db_path: str, horizon: str, lookback_days: int, use_champion: bool):
    """Load decision_features and optionally enrich with champion alpha_score."""
    import sys
    project_root = _get_project_root()
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from ai.data.loader import load_decision_features
    from datetime import datetime, timedelta, timezone

    end_dt = datetime.now(timezone.utc)
    if lookback_days <= 0:
        start_str = end_str = None
    else:
        start_str = (end_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")

    rows = load_decision_features(
        db_path=db_path, horizon=horizon,
        label_not_null=True, start=start_str, end=end_str,
    )
    if not rows or len(rows) < 200:
        raise ValueError(f"Insufficient data: {len(rows) if rows else 0} rows (need >=200)")

    if use_champion:
        mlflow_uri = os.environ.get('MLFLOW_TRACKING_URI', f"sqlite:///{os.path.join(_get_project_root(), 'artifacts', 'quant_model', 'mlflow_v2.db')}")
        from ai.inference.champion_loader import enrich_rows_with_champion
        rows = enrich_rows_with_champion(
            rows, model_uri="models:/quant_alpha_entry_lgbm@champion",
            mlflow_tracking_uri=mlflow_uri,
        )
    return rows


@app.post("/agents/suite-cycle")
async def run_suite_cycle_endpoint(request: SuiteCycleRequest):
    """Run one agent suite cycle (tuning -> decision -> report -> evolution)."""
    import uuid
    from datetime import datetime as dt

    job_id = str(uuid.uuid4())[:8]
    project_root = _get_project_root()
    db_path = os.path.abspath(get_duckdb_path())

    with _job_lock:
        _background_jobs[job_id] = {
            'type': 'suite-cycle', 'status': 'starting',
            'horizon': request.horizon, 'optimize': request.optimize,
            'created_at': dt.now().isoformat(),
        }

    def _run():
        import sys
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        try:
            with _job_lock:
                _background_jobs[job_id]['status'] = 'loading_data'

            rows = _load_suite_data(db_path, request.horizon, request.lookback_days, request.use_champion)

            with _job_lock:
                _background_jobs[job_id]['status'] = 'running'
                _background_jobs[job_id]['rows'] = len(rows)

            from ai.suite import (
                QuantAgentSuite, ExplorationTuningAgent, OptimizerTuningAgent,
                BacktestDecisionAgent, DefaultReportAgent, DefaultEvolutionAgent,
            )

            if request.optimize:
                tuning = OptimizerTuningAgent(
                    horizons=["1h", "4h"], symbol_sets=["top20", "top50", "all"],
                    max_total_trials=request.max_trials, max_candidates=15, fee_percent=0.04,
                )
            else:
                tuning = ExplorationTuningAgent(horizon=request.horizon, fee_percent=0.04, max_candidates=10)

            suite = QuantAgentSuite(
                tuning_agent=tuning,
                decision_agent=BacktestDecisionAgent(horizon=request.horizon, fee_percent=0.04, db_path=db_path),
                report_agent=DefaultReportAgent(promote_min_net_return=0.0, promote_min_trades=1),
                evolution_agent=DefaultEvolutionAgent(),
                state_path=os.path.join(project_root, 'artifacts', 'quant_model', 'suite_state.json'),
                report_dir=os.path.join(project_root, 'artifacts', 'quant_model'),
            )

            state, report, decision = suite.run_cycle(rows)

            with _job_lock:
                _background_jobs[job_id]['status'] = 'completed'
                _background_jobs[job_id]['result'] = {
                    'recommendation': report.recommendation,
                    'reason': report.recommendation_reason,
                    'champion_id': state.champion_id,
                    'version': state.version,
                    'net_return': getattr(decision, 'net_return_percent', None),
                    'trades': getattr(decision, 'trades_count', None),
                }
        except Exception as e:
            with _job_lock:
                _background_jobs[job_id]['status'] = 'error'
                _background_jobs[job_id]['error'] = str(e)

    thread = threading.Thread(target=_run)
    thread.start()
    return {'status': 'success', 'data': {'job_id': job_id, 'check_status': f'/actions/status/{job_id}'}}


@app.post("/agents/research-loop")
async def run_research_loop_endpoint(request: ResearchLoopRequest):
    """Run research loop: cycles until good result or stagnation, then explores."""
    import uuid
    from datetime import datetime as dt

    job_id = str(uuid.uuid4())[:8]
    project_root = _get_project_root()
    db_path = os.path.abspath(get_duckdb_path())

    with _job_lock:
        _background_jobs[job_id] = {
            'type': 'research-loop', 'status': 'starting',
            'max_cycles': request.max_cycles,
            'created_at': dt.now().isoformat(),
        }

    def _run():
        import sys
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        try:
            with _job_lock:
                _background_jobs[job_id]['status'] = 'loading_data'

            rows = _load_suite_data(db_path, request.horizon, request.lookback_days, request.use_champion)

            with _job_lock:
                _background_jobs[job_id]['status'] = 'running'
                _background_jobs[job_id]['rows'] = len(rows)

            from ai.suite import (
                QuantAgentSuite, ExplorationTuningAgent, OptimizerTuningAgent,
                BacktestDecisionAgent, DefaultReportAgent, DefaultEvolutionAgent,
                run_research_loop,
            )

            if request.optimize:
                tuning = OptimizerTuningAgent(
                    horizons=["1h", "4h"], symbol_sets=["top20", "top50", "all"],
                    max_total_trials=request.max_trials, max_candidates=15, fee_percent=0.04,
                )
            else:
                tuning = ExplorationTuningAgent(horizon=request.horizon, fee_percent=0.04, max_candidates=10)

            suite = QuantAgentSuite(
                tuning_agent=tuning,
                decision_agent=BacktestDecisionAgent(horizon=request.horizon, fee_percent=0.04, db_path=db_path),
                report_agent=DefaultReportAgent(promote_min_net_return=0.0, promote_min_trades=1),
                evolution_agent=DefaultEvolutionAgent(),
                state_path=os.path.join(project_root, 'artifacts', 'quant_model', 'suite_state.json'),
                report_dir=os.path.join(project_root, 'artifacts', 'quant_model'),
            )

            def on_explore(suite_ref, state, report, research_state):
                if not request.optimize:
                    return
                r = research_state.exploration_round
                from ai.suite import OptimizerTuningAgent as OTA
                suite_ref.tuning_agent = OTA(
                    horizons=["1h", "4h", "24h"] if r >= 1 else ["1h", "4h"],
                    symbol_sets=["top20", "top50", "all"],
                    max_total_trials=min(request.max_trials * (r + 2), 1200),
                    max_candidates=20, fee_percent=0.04,
                )
                with _job_lock:
                    _background_jobs[job_id]['exploration_round'] = r

            state, report, research_state, cycles = run_research_loop(
                suite, rows,
                max_cycles=request.max_cycles,
                cycles_before_explore=request.cycles_before_explore,
                stop_on_promote=request.stop_on_promote,
                on_explore=on_explore if request.optimize else None,
                state_path=os.path.join(project_root, 'artifacts', 'quant_model', 'suite_state.json'),
                research_state_path=os.path.join(project_root, 'artifacts', 'quant_model', 'research_state.json'),
            )

            with _job_lock:
                _background_jobs[job_id]['status'] = 'completed'
                _background_jobs[job_id]['result'] = {
                    'cycles_executed': cycles,
                    'recommendation': report.recommendation,
                    'reason': report.recommendation_reason,
                    'champion_id': state.champion_id,
                    'version': state.version,
                    'research_mode': research_state.mode,
                    'cycles_without_improvement': research_state.cycles_without_improvement,
                    'exploration_round': research_state.exploration_round,
                }
        except Exception as e:
            with _job_lock:
                _background_jobs[job_id]['status'] = 'error'
                _background_jobs[job_id]['error'] = str(e)

    thread = threading.Thread(target=_run)
    thread.start()
    return {'status': 'success', 'data': {'job_id': job_id, 'check_status': f'/actions/status/{job_id}'}}


@app.get("/agents/state")
async def get_agent_state():
    """Current suite state + research state (from disk)."""
    import json as _json
    project_root = _get_project_root()
    artifacts = os.path.join(project_root, 'artifacts', 'quant_model')

    suite_state = {}
    suite_path = os.path.join(artifacts, 'suite_state.json')
    if os.path.exists(suite_path):
        with open(suite_path, 'r') as f:
            suite_state = _json.load(f)

    research_state = {}
    research_path = os.path.join(artifacts, 'research_state.json')
    if os.path.exists(research_path):
        with open(research_path, 'r') as f:
            research_state = _json.load(f)

    report = {}
    report_path = os.path.join(artifacts, 'suite_report.json')
    if os.path.exists(report_path):
        with open(report_path, 'r') as f:
            report = _json.load(f)

    return {
        'status': 'success',
        'data': {
            'suite_state': suite_state,
            'research_state': research_state,
            'latest_report': report,
        }
    }


@app.get("/agents/champion")
async def get_champion_info():
    """Current MLflow champion model info."""
    try:
        import sys
        import mlflow
        project_root = _get_project_root()
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
            
        mlflow_uri = os.environ.get('MLFLOW_TRACKING_URI', f"sqlite:///{os.path.join(project_root, 'artifacts', 'quant_model', 'mlflow_v2.db')}")
        mlflow.set_tracking_uri(mlflow_uri)
        client = mlflow.MlflowClient()
        mv = client.get_model_version_by_alias("quant_alpha_entry_lgbm", "champion")
        run = client.get_run(mv.run_id)
        return {
            'status': 'success',
            'data': {
                'champion': {
                    'version': mv.version,
                    'status': mv.status,
                    'run_id': mv.run_id,
                    'creation_timestamp': mv.creation_timestamp,
                    'metrics': dict(list(run.data.metrics.items())[:10]),
                    'params': dict(list(run.data.params.items())[:10]),
                }
            }
        }
    except Exception as e:
        return {'status': 'success', 'data': {'champion': None, 'message': str(e)}}


# ============================================================================
# SERVER INFO
# ============================================================================

class ChatQuery(BaseModel):
    query: str

@app.post("/agent/chat")
async def agent_chat(request: ChatQuery):
    """Chat with the system AI Agent"""
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage
        import duckdb
        import mlflow
        
        # Use a dummy response if no key is found, so it "works" for testing
        api_key = os.getenv('OPENAI_API_KEY')
        
        # Gather basic context
        db_path = get_duckdb_path()
        stats_msg = "Database not found."
        if os.path.exists(db_path):
            conn = duckdb.connect(db_path, read_only=True)
            tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
            stats_msg = f"Database has {len(tables)} tables: {', '.join(tables[:5])}..."
            conn.close()
            
        project_root = _get_project_root()
        mlflow_uri = os.environ.get('MLFLOW_TRACKING_URI', f"sqlite:///{os.path.join(project_root, 'artifacts', 'quant_model', 'mlflow_v2.db')}")
        champion_msg = "No MLflow DB found."
        
        try:
            mlflow.set_tracking_uri(mlflow_uri)
            client = mlflow.MlflowClient()
            try:
                mv = client.get_model_version_by_alias("quant_alpha_entry_lgbm", "champion")
                run = client.get_run(mv.run_id)
                ret = run.data.metrics.get('mean_net_return_percent', 'N/A')
                champion_msg = f"El mejor modelo actual es la versión {mv.version} con un retorno esperado de {ret}%."
            except:
                champion_msg = "Aún no se ha encontrado un modelo campeón."
        except Exception as e:
            logger.warning(f"No se pudo acceder a MLflow: {e}")
                
        if not api_key:
            # Fallback local response if no OpenAI key is configured yet
            if "mejor modelo" in request.query.lower() or "retorno" in request.query.lower():
                response_text = champion_msg
            elif "tablas" in request.query.lower() or "datos" in request.query.lower():
                response_text = stats_msg
            else:
                response_text = "Modo de simulación del agente (OPENAI_API_KEY no configurada). Contexto actual: " + champion_msg
        else:
            system_prompt = f"""You are the Binance Quant AI Assistant. 
Respond in Spanish.
System state:
- Database: {stats_msg}
- Models: {champion_msg}

Answer the user's query concisely and helpfully based on this context."""

            chat = ChatOpenAI(temperature=0, openai_api_key=api_key)
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=request.query)
            ]
            response = chat.invoke(messages)
            response_text = response.content
        
        return {
            'status': 'success',
            'data': {
                'response': response_text
            }
        }
    except Exception as e:
        logger.error(f"Error in AI agent: {e}")
        return {"status": "error", "message": str(e)}

# ============================================================================
# TESTNET MONITOR (balance + posiciones en tiempo real)
# ============================================================================

def _get_bot_operations(db_path: str) -> dict:
    """Agregados de operaciones del bot: fct_order_history (ejecutadas) + fct_approved_orders (pendientes)."""
    if not os.path.exists(db_path):
        return {"total": 0, "by_status": {}, "by_signal_type": {}, "by_model": {}, "last_10": [], "last_failures": [], "total_pnl_usdt": 0.0, "win_rate_pct": 0.0, "risk_rejected_total": 0}
    try:
        conn = duckdb.connect(db_path, read_only=True)
        tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
        # fct_order_history: operaciones ya ejecutadas/fallidas (no se borran)
        # fct_approved_orders: pendientes actuales (se sobrescribe cada ciclo)
        by_status: dict = {}
        by_signal: dict = {}
        by_model: dict = {}
        total_history = 0
        total_pnl_usdt = 0.0
        win_rate_pct = 0.0
        risk_rejected_total = 0

        if "fct_risk_cycle_stats" in tables:
            try:
                row = conn.execute("SELECT COALESCE(SUM(rejected_count), 0) FROM fct_risk_cycle_stats").fetchone()
                risk_rejected_total = int(row[0]) if row else 0
            except Exception:
                pass

        if "fct_order_history" in tables:
            total_history = conn.execute("SELECT COUNT(*) FROM fct_order_history").fetchone()[0]
            for row in conn.execute("SELECT status, COUNT(*) FROM fct_order_history GROUP BY status").fetchall():
                by_status[row[0] or "NULL"] = by_status.get(row[0], 0) + row[1]
            for row in conn.execute("SELECT signal_type, COUNT(*) FROM fct_order_history GROUP BY signal_type").fetchall():
                by_signal[row[0] or "NULL"] = by_signal.get(row[0], 0) + row[1]
            try:
                for row in conn.execute(
                    "SELECT COALESCE(model_id, 'champion') as m, COUNT(*) FROM fct_order_history GROUP BY m"
                ).fetchall():
                    by_model[row[0]] = by_model.get(row[0], 0) + row[1]
            except Exception:
                by_model["quant_alpha_entry_lgbm@champion"] = total_history
            try:
                row = conn.execute("SELECT COALESCE(SUM(realized_pnl), 0) FROM fct_order_history WHERE realized_pnl IS NOT NULL").fetchone()
                total_pnl_usdt = float(row[0]) if row and row[0] is not None else 0.0
            except Exception:
                pass
            try:
                rows = conn.execute(
                    "SELECT COUNT(*), SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) FROM fct_order_history WHERE realized_pnl IS NOT NULL AND status = 'EXECUTED'"
                ).fetchone()
                if rows and rows[0] and rows[0] > 0:
                    win_rate_pct = round(100.0 * (rows[1] or 0) / rows[0], 1)
            except Exception:
                pass
        total_pending = 0
        if "fct_approved_orders" in tables:
            total_pending = conn.execute("SELECT COUNT(*) FROM fct_approved_orders WHERE status = 'PENDING'").fetchone()[0]
            by_status["PENDING"] = by_status.get("PENDING", 0) + total_pending
        total = total_history + total_pending
        last_10 = []
        last_failures = []
        try:
            if "fct_order_history" in tables:
                cols = [d[0] for d in conn.execute("DESCRIBE fct_order_history").fetchall()]
                last_10 = [
                    dict(zip(cols, r))
                    for r in conn.execute(
                        "SELECT * FROM fct_order_history ORDER BY event_time DESC LIMIT 10"
                    ).fetchall()
                ]
                try:
                    last_failures = [
                        dict(zip(cols, r))
                        for r in conn.execute(
                            "SELECT * FROM fct_order_history WHERE status IN ('FAILED','FAILED_INVALID_QTY','FAILED_BELOW_MIN') ORDER BY event_time DESC LIMIT 5"
                        ).fetchall()
                    ]
                except Exception:
                    pass
            if not last_10 and "fct_approved_orders" in tables:
                cols = [d[0] for d in conn.execute("DESCRIBE fct_approved_orders").fetchall()]
                last_10 = [
                    dict(zip(cols, r))
                    for r in conn.execute(
                        "SELECT * FROM fct_approved_orders ORDER BY event_time DESC LIMIT 10"
                    ).fetchall()
                ]
            for r in last_10 + last_failures:
                for k, v in list(r.items()):
                    if hasattr(v, "isoformat"):
                        r[k] = v.isoformat() if v else ""
        except Exception:
            pass
        conn.close()
        return {
            "total": total,
            "by_status": by_status,
            "by_signal_type": by_signal,
            "by_model": by_model,
            "last_10": last_10,
            "last_failures": last_failures,
            "total_pnl_usdt": total_pnl_usdt,
            "win_rate_pct": win_rate_pct,
            "risk_rejected_total": risk_rejected_total,
        }
    except Exception:
        return {"total": 0, "by_status": {}, "by_signal_type": {}, "by_model": {}, "last_10": [], "last_failures": [], "total_pnl_usdt": 0.0, "win_rate_pct": 0.0, "risk_rejected_total": 0}


@app.get("/monitor/data")
async def get_monitor_data():
    """Datos para el monitor testnet: balance, posiciones, champion, operaciones del bot."""
    testnet = os.getenv("BINANCE_TESTNET", "false").lower() == "true"
    data = {"testnet": testnet, "balance": None, "positions": [], "champion": None, "bot_operations": None}
    try:
        client = get_binance_client()
        account = client.futures_account()
        usdt = next((a for a in account["assets"] if a["asset"] == "USDT"), None)
        if usdt:
            up = usdt.get("unRealizedProfit") or usdt.get("unrealizedProfit") or 0
            data["balance"] = {
                "wallet_balance": float(usdt.get("walletBalance", 0) or 0),
                "unrealized_profit": float(up),
            }
        data["positions"] = []
        for p in client.futures_position_information():
            amt = float(p["positionAmt"])
            if amt == 0:
                continue
            side_display = "LONG" if amt > 0 else "SHORT"
            up = p.get("unRealizedProfit") or p.get("unrealizedProfit") or 0
            data["positions"].append({
                "symbol": p["symbol"],
                "position_side": side_display,
                "position_amt": amt,
                "entry_price": p["entryPrice"],
                "unrealized_profit": float(up),
            })
    except Exception as e:
        data["error"] = str(e)
    try:
        champ = await get_champion_info()
        if champ.get("status") == "success" and champ.get("data", {}).get("champion"):
            data["champion"] = champ["data"]["champion"]
    except Exception:
        pass
    try:
        db_path = get_duckdb_path()
        if not os.path.isabs(db_path):
            db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", db_path))
        data["bot_operations"] = _get_bot_operations(db_path)
    except Exception:
        data["bot_operations"] = {"total": 0, "by_status": {}, "by_signal_type": {}, "by_model": {}, "last_10": [], "last_failures": [], "total_pnl_usdt": 0.0, "win_rate_pct": 0.0, "risk_rejected_total": 0}
    return data


@app.get("/monitor", response_class=HTMLResponse)
async def monitor_page():
    """Monitor testnet: balance y posiciones en tiempo real. Auto-refresh cada 5s."""
    return HTMLResponse(content=_MONITOR_HTML)


_MONITOR_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <title>Monitor Testnet</title>
  <style>
    body { font-family: system-ui; margin: 2rem; background: #0f0f12; color: #e4e4e7; }
    h1 { color: #a78bfa; }
    .card { background: #18181b; border-radius: 8px; padding: 1rem; margin: 1rem 0; }
    .error { color: #f87171; }
    .ok { color: #34d399; }
    .metric { display: inline-block; margin-right: 1.5rem; }
    .metric-val { font-size: 1.5rem; font-weight: 600; color: #a78bfa; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 0.5rem; text-align: left; }
    th { color: #a78bfa; }
    #ts { color: #71717a; font-size: 0.9rem; }
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    @media (max-width: 768px) { .grid2 { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <h1>Monitor Testnet Binance</h1>
  <p id="ts">Cargando...</p>
  <div id="content"></div>
  <script>
    function esc(s) { return (s == null || s === undefined) ? '' : String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;'); }
    async function load() {
      try {
        const r = await fetch('/monitor/data');
        const d = await r.json();
        document.getElementById('ts').textContent = 'Última actualización: ' + new Date().toLocaleTimeString() + ' (refresh cada 5s)';
        let html = '';
        if (d.error) {
          html = '<div class="card error">' + esc(d.error) + '</div>';
        } else {
          html += '<div class="card"><strong>Modo:</strong> ' + (d.testnet ? '<span class="ok">TESTNET</span>' : 'PRODUCCIÓN') + '</div>';
          if (d.balance) {
            var wb = (d.balance.wallet_balance != null) ? Number(d.balance.wallet_balance).toFixed(2) : '0.00';
            var up = (d.balance.unrealized_profit != null) ? Number(d.balance.unrealized_profit).toFixed(2) : '0.00';
            html += '<div class="card"><h3>Balance USDT</h3><p>Wallet: ' + wb + ' | PnL no realizado: ' + up + '</p></div>';
          }
          html += '<div class="card"><h3>Posiciones (' + (d.positions ? d.positions.length : 0) + ')</h3>';
          if (d.positions && d.positions.length) {
            html += '<table><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>PnL</th></tr>';
            d.positions.forEach(p => {
              var up = (p.unrealized_profit != null) ? Number(p.unrealized_profit).toFixed(2) : esc(p.unrealized_profit);
              html += '<tr><td>' + esc(p.symbol) + '</td><td>' + esc(p.position_side) + '</td><td>' + esc(p.position_amt) + '</td><td>' + esc(p.entry_price) + '</td><td>' + up + '</td></tr>';
            });
            html += '</table>';
          } else html += '<p>Sin posiciones abiertas</p>';
          html += '</div>';

          var bot = d.bot_operations || {};
          html += '<div class="card"><h3>Operaciones del bot</h3>';
          var pnl = (bot.total_pnl_usdt != null && !isNaN(bot.total_pnl_usdt)) ? Number(bot.total_pnl_usdt).toFixed(2) : '0.00';
          var wr = (bot.win_rate_pct != null && !isNaN(bot.win_rate_pct)) ? Number(bot.win_rate_pct).toFixed(1) : '0.0';
          var rej = (bot.risk_rejected_total != null) ? Number(bot.risk_rejected_total) : 0;
          html += '<p style="margin-bottom:1rem;"><strong>Métricas:</strong> <span class="metric"><span class="metric-val">' + pnl + '</span> USDT PnL total</span>';
          html += '<span class="metric"><span class="metric-val">' + wr + '%</span> ops positivas</span>';
          html += '<span class="metric"><span class="metric-val">' + rej + '</span> rechazadas Risk</span></p>';
          html += '<p><span class="metric"><span class="metric-val">' + (bot.total || 0) + '</span> total</span>';
          if (bot.by_status && Object.keys(bot.by_status).length) {
            Object.entries(bot.by_status).forEach(function(e) {
              html += '<span class="metric"><span class="metric-val">' + e[1] + '</span> ' + esc(e[0]) + '</span>';
            });
          }
          html += '</p>';
          if (bot.by_model && Object.keys(bot.by_model).length) {
            html += '<p><strong>Por modelo:</strong> ';
            html += Object.entries(bot.by_model).map(function(e) { return esc(e[0]) + ': ' + e[1]; }).join(' | ');
            html += '</p>';
          }
          if (bot.by_signal_type && Object.keys(bot.by_signal_type).length) {
            html += '<p><strong>Por tipo:</strong> ';
            html += Object.entries(bot.by_signal_type).map(function(e) { return esc(e[0]) + ': ' + e[1]; }).join(' | ');
            html += '</p>';
          }
          if (bot.last_10 && bot.last_10.length) {
            html += '<h4>Últimas 10 operaciones</h4><table><tr><th>Fecha</th><th>Symbol</th><th>Tipo</th><th>Size USD</th><th>PnL</th><th>Order</th><th>Status</th><th>Modelo</th></tr>';
            bot.last_10.forEach(function(op) {
              var ord = esc(op.order_type || 'MARKET') + (op.limit_price ? ' @' + op.limit_price : '');
              var rpnl = (op.realized_pnl != null && op.realized_pnl !== 0) ? Number(op.realized_pnl).toFixed(2) : '-';
              html += '<tr><td>' + esc(op.event_time) + '</td><td>' + esc(op.symbol) + '</td><td>' + esc(op.signal_type) + '</td><td>' + esc(op.size_usd) + '</td><td>' + rpnl + '</td><td>' + ord + '</td><td>' + esc(op.status) + '</td><td>' + esc(op.model_id || 'champion') + '</td></tr>';
            });
            html += '</table>';
          }
          if (bot.last_failures && bot.last_failures.length) {
            html += '<h4 class="error">Últimas fallidas (motivo)</h4><table><tr><th>Fecha</th><th>Symbol</th><th>Tipo</th><th>Size USD</th><th>Status</th><th>Motivo</th></tr>';
            bot.last_failures.forEach(function(op) {
              html += '<tr><td>' + esc(op.event_time) + '</td><td>' + esc(op.symbol) + '</td><td>' + esc(op.signal_type) + '</td><td>' + esc(op.size_usd) + '</td><td>' + esc(op.status) + '</td><td style="max-width:300px;word-break:break-all">' + esc(op.error_message || '-') + '</td></tr>';
            });
            html += '</table>';
          }
          html += '</div>';

          if (d.champion) html += '<div class="card"><h3>Champion</h3><p>v' + esc(d.champion.version) + ' (modelo que genera señales)</p></div>';
        }
        document.getElementById('content').innerHTML = html;
      } catch (e) {
        document.getElementById('content').innerHTML = '<div class="card error">Error: ' + esc(e.message) + '</div>';
      }
    }
    load();
    setInterval(load, 5000);
  </script>
</body>
</html>
"""


@app.get("/server/info")
async def get_server_info():
    """Get server information for remote access"""
    import socket
    
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "unknown"
    
    return {
        'status': 'success',
        'data': {
            'hostname': hostname,
            'local_ip': local_ip,
            'api_port': 8000,
            'mlflow_port': 5001,
            'optuna_port': 8081,
            'dagster_port': 3000,
            'endpoints': {
                'api_docs': f'http://{local_ip}:8000/docs',
                'monitor': f'http://{local_ip}:8000/monitor',
                'warehouse': f'http://{local_ip}:8000/warehouse/tables',
                'actions': f'http://{local_ip}:8000/actions/status',
                'agents': f'http://{local_ip}:8000/agents/state',
                'mlflow': f'http://{local_ip}:5001',
                'optuna': f'http://{local_ip}:8081',
                'dagster': f'http://{local_ip}:3000',
            }
        }
    }

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
