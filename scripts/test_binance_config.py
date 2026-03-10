import os
from binance.client import Client
from dotenv import load_dotenv

def test_binance_connection():
    load_dotenv()
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_SECRET_KEY")
    testnet = os.getenv("BINANCE_TESTNET", "true").lower() == "true"
    
    print(f"Testing Binance Connection (Testnet: {testnet})")
    print(f"API Key: {api_key[:5]}...{api_key[-5:] if api_key else ''}")
    
    try:
        client = Client(api_key, api_secret, testnet=testnet)
        # Test Futures (what we use for orders)
        acc = client.futures_account()
        print("OK: Futures account connected (Testnet)")
        usdt = next((a for a in acc.get("assets", []) if a["asset"] == "USDT"), None)
        if usdt:
            print(f"  USDT balance: {usdt.get('walletBalance')}")
        return
    except Exception as e:
        pass
    try:
        client = Client(api_key, api_secret, testnet=testnet)
        info = client.get_account()
        print("OK: Spot account connected (Testnet)")
        print(f"  Account: {info.get('accountType')}")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    test_binance_connection()
