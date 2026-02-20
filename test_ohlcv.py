"""Quick test for OHLCV fetch"""
import asyncio
from utils.data_fetcher import DataFetcher

async def test():
    df = DataFetcher()
    await df.initialize()
    print("Fetching BTC/USDT OHLCV...")
    data = await df.fetch_ohlcv("BTC/USDT", "5m", 100)
    print(f"Got {len(data)} rows")
    if not data.empty:
        print(data.tail(3))
    else:
        print("EMPTY DataFrame!")
    await df.close()

asyncio.run(test())
