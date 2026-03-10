import os
import dlt
import yfinance as yf
from datetime import datetime, timedelta
import pandas as pd
import logging

logger = logging.getLogger(__name__)

@dlt.source
def stock_market_source(symbols: list[str], start_date: str = None, end_date: str = None):
    """
    Source for fetching stock market data and news using yfinance.
    """
    return [
        stock_prices(symbols, start_date, end_date),
        stock_news(symbols)
    ]

@dlt.resource(name="stock_prices", write_disposition="merge", primary_key=["symbol", "event_time"])
def stock_prices(symbols: list[str], start_date: str = None, end_date: str = None):
    """Fetches historical prices (daily/hourly)."""
    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')
        
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            # Fetch hourly data for the last 30 days or daily for longer
            # Let's use 1h to match our crypto pipeline style if possible
            # yfinance allows 1h data for max 730 days
            df = ticker.history(start=start_date, end=end_date, interval="1h")
            if df.empty:
                logger.warning(f"No data for {symbol}")
                continue
                
            df = df.reset_index()
            # Rename columns to match our style
            col_map = {
                'Datetime': 'event_time',
                'Date': 'event_time',
                'Open': 'open_price',
                'High': 'high_price',
                'Low': 'low_price',
                'Close': 'close_price',
                'Volume': 'volume'
            }
            df = df.rename(columns=col_map)
            df['symbol'] = symbol
            
            # Convert timezone to UTC and then to string for duckdb
            if df['event_time'].dt.tz is not None:
                df['event_time'] = df['event_time'].dt.tz_convert('UTC')
            df['event_time'] = df['event_time'].dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # Select relevant columns
            cols = ['event_time', 'symbol', 'open_price', 'high_price', 'low_price', 'close_price', 'volume']
            df = df[cols]
            
            for record in df.to_dict(orient='records'):
                yield record
        except Exception as e:
            logger.error(f"Error fetching prices for {symbol}: {e}")

@dlt.resource(name="market_news", write_disposition="merge", primary_key=["uuid"])
def stock_news(symbols: list[str]):
    """Fetches latest news for symbols."""
    import hashlib
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            news = ticker.news
            for item in news:
                # Generate a deterministic UUID if none is provided by Yahoo Finance
                item_uuid = item.get('uuid')
                if not item_uuid:
                    title = item.get('title', '')
                    link = item.get('link', '')
                    if not title and not link:
                        continue
                    item_uuid = hashlib.md5(f"{symbol}-{title}-{link}".encode('utf-8')).hexdigest()
                
                # Default publish time if not provided
                pub_time = item.get('providerPublishTime')
                if pub_time:
                    pub_time_str = datetime.fromtimestamp(pub_time).strftime('%Y-%m-%d %H:%M:%S')
                else:
                    pub_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                yield {
                    'uuid': item_uuid,
                    'symbol': symbol,
                    'title': item.get('title'),
                    'publisher': item.get('publisher'),
                    'link': item.get('link'),
                    'provider_publish_time': pub_time_str,
                    'type': item.get('type')
                }
        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {e}")

if __name__ == "__main__":
    import time
    db_path = os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    pipeline = dlt.pipeline(
        pipeline_name='stock_market_pipeline',
        destination=dlt.destinations.duckdb(db_path),
        dataset_name='main'
    )

    test_symbols = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'TSLA', 'META', 'BTC-USD', 'ETH-USD']

    for attempt in range(12):
        try:
            load_info = pipeline.run(stock_market_source(symbols=test_symbols))
            print(load_info)
            break
        except Exception as e:
            if "Could not set lock on file" in str(e) or "Conflicting lock" in str(e):
                logger.warning(f"DuckDB lock held, waiting 5s... (attempt {attempt+1}/12)")
                time.sleep(5)
            else:
                raise
    else:
        raise RuntimeError("Failed to acquire DuckDB lock after 1 minute.")
