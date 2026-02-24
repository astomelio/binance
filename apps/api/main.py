import os
import logging
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    """Initialize and return Binance client (cached)"""
    global _client_cache
    if _client_cache is None:
        api_key = os.getenv('BINANCE_API_KEY')
        secret_key = os.getenv('BINANCE_SECRET_KEY')
        testnet = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'
        
        if not api_key or not secret_key:
            raise ValueError("BINANCE_API_KEY and BINANCE_SECRET_KEY must be set")
        
        _client_cache = Client(api_key, secret_key, testnet=testnet)
    
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
            if float(asset['walletBalance']) > 0 or float(asset['unrealizedProfit']) > 0:
                balances.append({
                    'asset': asset['asset'],
                    'wallet_balance': asset['walletBalance'],
                    'unrealized_profit': asset['unrealizedProfit'],
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

@app.get("/futures/positions")
async def get_futures_positions():
    """Get futures positions"""
    try:
        client = get_binance_client()
        positions = client.futures_position_information()
        
        formatted_positions = []
        for position in positions:
            if float(position['positionAmt']) != 0:  # Only show active positions
                formatted_positions.append({
                    'symbol': position['symbol'],
                    'initial_margin': position['initialMargin'],
                    'maint_margin': position['maintMargin'],
                    'unrealized_profit': position['unrealizedProfit'],
                    'position_initial_margin': position['positionInitialMargin'],
                    'open_order_initial_margin': position['openOrderInitialMargin'],
                    'leverage': position['leverage'],
                    'isolated': position['isolated'],
                    'entry_price': position['entryPrice'],
                    'max_notional': position['maxNotional'],
                    'bid_notional': position['bidNotional'],
                    'ask_notional': position['askNotional'],
                    'position_side': position['positionSide'],
                    'position_amt': position['positionAmt'],
                    'update_time': position['updateTime']
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

@app.get("/futures/market/ticker/{symbol}")
async def get_futures_ticker(symbol: str):
    """Get futures ticker information for a symbol"""
    try:
        client = get_binance_client()
        ticker = client.futures_ticker(symbol=symbol.upper())
        
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
    """Create a new futures order"""
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
        
        if order_request.position_side:
            order_params['positionSide'] = order_request.position_side.upper()
        
        if order_request.reduce_only is not None:
            order_params['reduceOnly'] = order_request.reduce_only
        
        if order_request.close_position is not None:
            order_params['closePosition'] = order_request.close_position
        
        # Create the futures order
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
        '--mlflow-uri', f'sqlite:///{project_root}/artifacts/quant_model/mlflow.db',
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
# SERVER INFO
# ============================================================================

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
            'endpoints': {
                'api_docs': f'http://{local_ip}:8000/docs',
                'warehouse': f'http://{local_ip}:8000/warehouse/tables',
                'actions': f'http://{local_ip}:8000/actions/status',
                'mlflow': f'http://{local_ip}:5001',
                'optuna': f'http://{local_ip}:8081'
            }
        }
    }

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
