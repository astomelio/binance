import pytest
import os
import sys
from unittest.mock import Mock, patch

# Add the parent directory to the path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app import app

@pytest.fixture
def client():
    """Create a test client for the FastAPI app"""
    return TestClient(app)

@pytest.fixture
def mock_binance_client():
    """Mock Binance client for testing"""
    with patch("apps.api.main.get_binance_client") as mock_client:
        yield mock_client

def test_health_check(client):
    """Test the health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "binance-connector"

# ============================================================================
# SPOT TRADING TESTS
# ============================================================================

def test_get_account_info_success(client, mock_binance_client):
    """Test successful account info retrieval"""
    # Mock the account info response
    mock_account_info = {
        'makerCommission': 15,
        'takerCommission': 15,
        'buyerCommission': 0,
        'sellerCommission': 0,
        'canTrade': True,
        'canWithdraw': True,
        'canDeposit': True,
        'updateTime': 1234567890
    }
    
    mock_binance_client.return_value.get_account.return_value = mock_account_info
    
    response = client.get("/account/info")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["maker_commission"] == 15
    assert data["data"]["can_trade"] is True

def test_get_account_balance_success(client, mock_binance_client):
    """Test successful account balance retrieval"""
    # Mock the account info response with balances
    mock_account_info = {
        'balances': [
            {
                'asset': 'BTC',
                'free': '1.00000000',
                'locked': '0.00000000'
            },
            {
                'asset': 'USDT',
                'free': '1000.00000000',
                'locked': '0.00000000'
            },
            {
                'asset': 'ETH',
                'free': '0.00000000',
                'locked': '0.00000000'
            }
        ]
    }
    
    mock_binance_client.return_value.get_account.return_value = mock_account_info
    
    response = client.get("/account/balance")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    balances = data["data"]
    assert len(balances) == 2  # Only BTC and USDT have non-zero balances
    
    btc_balance = next(b for b in balances if b["asset"] == "BTC")
    assert btc_balance["free"] == "1.00000000"
    assert float(btc_balance["total"]) == 1.0

def test_get_ticker_success(client, mock_binance_client):
    """Test successful ticker retrieval"""
    # Mock the ticker response
    mock_ticker = {
        'symbol': 'BTCUSDT',
        'priceChange': '100.00',
        'priceChangePercent': '2.50',
        'weightedAvgPrice': '4000.00',
        'prevClosePrice': '3900.00',
        'lastPrice': '4000.00',
        'lastQty': '0.001',
        'bidPrice': '3999.00',
        'askPrice': '4001.00',
        'openPrice': '3900.00',
        'highPrice': '4100.00',
        'lowPrice': '3850.00',
        'volume': '1000.000',
        'quoteVolume': '4000000.00',
        'openTime': 1234567890,
        'closeTime': 1234654290,
        'count': 1000
    }
    
    mock_binance_client.return_value.get_ticker.return_value = mock_ticker
    
    response = client.get("/market/ticker/BTCUSDT")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["symbol"] == "BTCUSDT"
    assert data["data"]["last_price"] == "4000.00"

def test_create_order_success(client, mock_binance_client):
    """Test successful order creation"""
    # Mock the order response
    mock_order = {
        'symbol': 'BTCUSDT',
        'orderId': 12345,
        'clientOrderId': 'abc123',
        'transactTime': 1234567890,
        'price': '4000.00',
        'origQty': '0.001',
        'executedQty': '0.001',
        'cummulativeQuoteQty': '4.00',
        'status': 'FILLED',
        'timeInForce': 'GTC',
        'type': 'MARKET',
        'side': 'BUY'
    }
    
    mock_binance_client.return_value.create_order.return_value = mock_order
    
    order_data = {
        'symbol': 'BTCUSDT',
        'side': 'BUY',
        'order_type': 'MARKET',
        'quantity': 0.001
    }
    
    response = client.post("/order/create", json=order_data)
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["symbol"] == "BTCUSDT"
    assert data["data"]["order_id"] == 12345

# ============================================================================
# FUTURES TRADING TESTS
# ============================================================================

def test_get_futures_account_info_success(client, mock_binance_client):
    """Test successful futures account info retrieval"""
    # Mock the futures account info response
    mock_futures_account = {
        'feeTier': 0,
        'canTrade': True,
        'canDeposit': True,
        'canWithdraw': True,
        'updateTime': 1234567890,
        'totalWalletBalance': '1000.00000000',
        'totalMarginBalance': '1000.00000000',
        'totalUnrealizedProfit': '0.00000000',
        'totalMaintMargin': '0.00000000',
        'totalPositionMargin': '0.00000000',
        'totalInitialMargin': '0.00000000',
        'totalFutureOpenInterest': '0.00000000',
        'totalMarginBalanceInUSDT': '1000.00000000',
        'totalUnrealizedProfitInUSDT': '0.00000000',
        'totalWalletBalanceInUSDT': '1000.00000000',
        'availableBalanceInUSDT': '1000.00000000'
    }
    
    mock_binance_client.return_value.futures_account.return_value = mock_futures_account
    
    response = client.get("/futures/account/info")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["can_trade"] is True
    assert data["data"]["total_wallet_balance_in_usdt"] == "1000.00000000"

def test_get_futures_account_balance_success(client, mock_binance_client):
    """Test successful futures account balance retrieval"""
    # Mock the futures account response with balances
    mock_futures_account = {
        'assets': [
            {
                'asset': 'USDT',
                'walletBalance': '1000.00000000',
                'unrealizedProfit': '0.00000000',
                'marginBalance': '1000.00000000',
                'maintMargin': '0.00000000',
                'initialMargin': '0.00000000',
                'positionInitialMargin': '0.00000000',
                'openOrderInitialMargin': '0.00000000',
                'maxWithdrawAmount': '1000.00000000',
                'crossWalletBalance': '1000.00000000',
                'crossUnPnl': '0.00000000',
                'availableBalance': '1000.00000000',
                'marginAvailable': True,
                'updateTime': 1234567890
            }
        ]
    }
    
    mock_binance_client.return_value.futures_account.return_value = mock_futures_account
    
    response = client.get("/futures/account/balance")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    balances = data["data"]
    assert len(balances) == 1
    usdt_balance = balances[0]
    assert usdt_balance['asset'] == 'USDT'
    assert usdt_balance['wallet_balance'] == '1000.00000000'

def test_get_futures_positions_success(client, mock_binance_client):
    """Test successful futures positions retrieval"""
    # Mock the futures positions response
    mock_positions = [
        {
            'symbol': 'BTCUSDT',
            'initialMargin': '100.00000000',
            'maintMargin': '50.00000000',
            'unrealizedProfit': '10.00000000',
            'positionInitialMargin': '100.00000000',
            'openOrderInitialMargin': '0.00000000',
            'leverage': '10',
            'isolated': False,
            'entryPrice': '40000.00000000',
            'maxNotional': '5000000',
            'bidNotional': '0',
            'askNotional': '0',
            'positionSide': 'LONG',
            'positionAmt': '0.001',
            'updateTime': 1234567890
        }
    ]
    
    mock_binance_client.return_value.futures_position_information.return_value = mock_positions
    
    response = client.get("/futures/positions")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    positions = data["data"]
    assert len(positions) == 1
    
    position = positions[0]
    assert position['symbol'] == 'BTCUSDT'
    assert position['leverage'] == '10'
    assert position['position_side'] == 'LONG'

def test_get_futures_ticker_success(client, mock_binance_client):
    """Test successful futures ticker retrieval"""
    # Mock the futures ticker response
    mock_ticker = {
        'symbol': 'BTCUSDT',
        'priceChange': '100.00',
        'priceChangePercent': '2.50',
        'weightedAvgPrice': '4000.00',
        'prevClosePrice': '3900.00',
        'lastPrice': '4000.00',
        'lastQty': '0.001',
        'openPrice': '3900.00',
        'highPrice': '4100.00',
        'lowPrice': '3850.00',
        'volume': '1000.000',
        'quoteVolume': '4000000.00',
        'openTime': 1234567890,
        'closeTime': 1234654290,
        'firstId': 1000,
        'lastId': 2000,
        'count': 1000
    }
    
    mock_binance_client.return_value.futures_ticker.return_value = mock_ticker
    
    response = client.get("/futures/market/ticker/BTCUSDT")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["symbol"] == "BTCUSDT"
    assert data["data"]["last_price"] == "4000.00"

def test_create_futures_order_success(client, mock_binance_client):
    """Test successful futures order creation"""
    # Mock the futures order response
    mock_order = {
        'symbol': 'BTCUSDT',
        'orderId': 12345,
        'clientOrderId': 'abc123',
        'price': '4000.00',
        'origQty': '0.001',
        'executedQty': '0.001',
        'cummulativeQuoteQty': '4.00',
        'status': 'FILLED',
        'timeInForce': 'GTC',
        'type': 'MARKET',
        'side': 'BUY',
        'positionSide': 'LONG',
        'reduceOnly': False,
        'closePosition': False,
        'activatePrice': '',
        'priceRate': '',
        'updateTime': 1234567890,
        'workingType': 'CONTRACT_PRICE',
        'priceProtect': False,
        'origType': 'MARKET',
        'priceMatch': 'NONE',
        'selfTradePreventionMode': 'NONE',
        'goodTillDate': 0,
        'time': 1234567890
    }
    
    mock_binance_client.return_value.futures_create_order.return_value = mock_order
    
    order_data = {
        'symbol': 'BTCUSDT',
        'side': 'BUY',
        'order_type': 'MARKET',
        'quantity': 0.001,
        'position_side': 'LONG'
    }
    
    response = client.post("/futures/order/create", json=order_data)
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["symbol"] == "BTCUSDT"
    assert data["data"]["order_id"] == 12345
    assert data["data"]["position_side"] == "LONG"

def test_set_futures_leverage_success(client, mock_binance_client):
    """Test successful leverage setting"""
    # Mock the leverage response
    mock_leverage = {
        'leverage': 10,
        'maxNotionalValue': '5000000',
        'symbol': 'BTCUSDT'
    }
    
    mock_binance_client.return_value.futures_change_leverage.return_value = mock_leverage
    
    leverage_data = {
        'symbol': 'BTCUSDT',
        'leverage': 10
    }
    
    response = client.post("/futures/leverage", json=leverage_data)
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["leverage"] == 10
    assert data["data"]["symbol"] == "BTCUSDT"

def test_set_futures_margin_type_success(client, mock_binance_client):
    """Test successful margin type setting"""
    # Mock the margin type response
    mock_margin_type = {
        'code': 200,
        'msg': 'success'
    }
    
    mock_binance_client.return_value.futures_change_margin_type.return_value = mock_margin_type
    
    margin_data = {
        'symbol': 'BTCUSDT',
        'margin_type': 'ISOLATED'
    }
    
    response = client.post("/futures/margin_type", json=margin_data)
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["code"] == 200

# ============================================================================
# ERROR HANDLING TESTS
# ============================================================================

def test_binance_api_error_handling(client, mock_binance_client):
    """Test error handling for Binance API errors"""
    from binance.exceptions import BinanceAPIException

    mock_response = Mock(status_code=400, text='{"code": -2011, "msg": "Invalid API key"}')
    mock_binance_client.return_value.get_account.side_effect = BinanceAPIException(
        mock_response, 400, "Invalid API key"
    )

    response = client.get("/account/info")

    assert response.status_code == 400
    assert "detail" in response.json()

def test_futures_api_error_handling(client, mock_binance_client):
    """Test error handling for Binance Futures API errors"""
    from binance.exceptions import BinanceAPIException

    mock_response = Mock(status_code=400, text='{"code": -2011, "msg": "Futures trading not enabled"}')
    mock_binance_client.return_value.futures_account.side_effect = BinanceAPIException(
        mock_response, 400, "Futures trading not enabled"
    )

    response = client.get("/futures/account/info")

    assert response.status_code == 400
    assert "detail" in response.json()

def test_missing_environment_variables():
    """Test that /account/info returns 500 when Binance keys are missing"""
    with patch("apps.api.main.get_binance_client") as mock_get_client:
        mock_get_client.side_effect = ValueError("BINANCE_API_KEY and BINANCE_SECRET_KEY must be set")
        from fastapi.testclient import TestClient
        from app import app
        client = TestClient(app)
        response = client.get("/account/info")
        assert response.status_code == 500
        assert "detail" in response.json()

if __name__ == '__main__':
    pytest.main([__file__])
