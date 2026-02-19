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
                'symbol': ticker['symbol'],
                'price_change': ticker['priceChange'],
                'price_change_percent': ticker['priceChangePercent'],
                'weighted_avg_price': ticker['weightedAvgPrice'],
                'prev_close_price': ticker['prevClosePrice'],
                'last_price': ticker['lastPrice'],
                'last_qty': ticker['lastQty'],
                'bid_price': ticker['bidPrice'],
                'ask_price': ticker['askPrice'],
                'open_price': ticker['openPrice'],
                'high_price': ticker['highPrice'],
                'low_price': ticker['lowPrice'],
                'volume': ticker['volume'],
                'quote_volume': ticker['quoteVolume'],
                'open_time': ticker['openTime'],
                'close_time': ticker['closeTime'],
                'count': ticker['count']
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
                'symbol': ticker['symbol'],
                'price_change': ticker['priceChange'],
                'price_change_percent': ticker['priceChangePercent'],
                'weighted_avg_price': ticker['weightedAvgPrice'],
                'prev_close_price': ticker['prevClosePrice'],
                'last_price': ticker['lastPrice'],
                'last_qty': ticker['lastQty'],
                'open_price': ticker['openPrice'],
                'high_price': ticker['highPrice'],
                'low_price': ticker['lowPrice'],
                'volume': ticker['volume'],
                'quote_volume': ticker['quoteVolume'],
                'open_time': ticker['openTime'],
                'close_time': ticker['closeTime'],
                'first_id': ticker['firstId'],
                'last_id': ticker['lastId'],
                'count': ticker['count']
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

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
