"""
Veri Çekme Modülü
Exchange'lerden OHLCV ve ticker verilerini asenkron çeker.
"""

import asyncio
import pandas as pd
import ccxt.async_support as ccxt
from utils.logger import setup_logger
from config import (
    EXCHANGE_ID, BINANCE_API_KEY, BINANCE_SECRET,
    BINANCE_TESTNET, OHLCV_LIMIT
)

logger = setup_logger("DataFetcher")


class DataFetcher:
    """Borsa veri çekici."""

    def __init__(self):
        self.exchange = None
        self._initialized = False

    async def initialize(self):
        """Exchange bağlantısını başlat."""
        if self._initialized:
            return

        exchange_config = {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }

        if BINANCE_API_KEY and BINANCE_SECRET:
            exchange_config["apiKey"] = BINANCE_API_KEY
            exchange_config["secret"] = BINANCE_SECRET

        if BINANCE_TESTNET:
            exchange_config["sandbox"] = True

        exchange_class = getattr(ccxt, EXCHANGE_ID)
        self.exchange = exchange_class(exchange_config)
        self._initialized = True
        logger.info(f"Exchange başlatıldı: {EXCHANGE_ID} (testnet={BINANCE_TESTNET})")

    async def close(self):
        """Exchange bağlantısını kapat."""
        if self.exchange:
            await self.exchange.close()
            self._initialized = False

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "5m",
                          limit: int = OHLCV_LIMIT) -> pd.DataFrame:
        """OHLCV verilerini çek ve DataFrame döndür."""
        await self.initialize()
        max_retries = 3

        for attempt in range(max_retries):
            try:
                ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                df = pd.DataFrame(
                    ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
                )
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                df.set_index("timestamp", inplace=True)
                return df

            except ccxt.NetworkError as e:
                logger.warning(f"Ağ hatası ({symbol}, deneme {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
            except ccxt.ExchangeError as e:
                logger.error(f"Exchange hatası ({symbol}): {e}")
                return pd.DataFrame()
            except Exception as e:
                logger.error(f"Beklenmeyen hata ({symbol}): {e}")
                return pd.DataFrame()

        return pd.DataFrame()

    async def fetch_ticker(self, symbol: str) -> dict:
        """Anlık ticker bilgisi çek."""
        await self.initialize()
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return ticker
        except Exception as e:
            logger.error(f"Ticker hatası ({symbol}): {e}")
            return {}

    async def fetch_multiple_ohlcv(self, symbols: list, timeframe: str = "5m",
                                   limit: int = OHLCV_LIMIT) -> dict:
        """Birden fazla sembol için OHLCV çek."""
        tasks = [self.fetch_ohlcv(s, timeframe, limit) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        data = {}
        for symbol, result in zip(symbols, results):
            if isinstance(result, Exception):
                logger.error(f"Hata ({symbol}): {result}")
                data[symbol] = pd.DataFrame()
            else:
                data[symbol] = result

        return data

    async def fetch_order_book(self, symbol: str, limit: int = 20) -> dict:
        """Order book çek."""
        await self.initialize()
        try:
            return await self.exchange.fetch_order_book(symbol, limit=limit)
        except Exception as e:
            logger.error(f"Order book hatası ({symbol}): {e}")
            return {}

    async def get_balance(self) -> dict:
        """Hesap bakiyesini çek."""
        await self.initialize()
        try:
            balance = await self.exchange.fetch_balance()
            return {
                "total": balance.get("total", {}),
                "free": balance.get("free", {}),
                "used": balance.get("used", {}),
            }
        except Exception as e:
            logger.error(f"Bakiye hatası: {e}")
            return {}
