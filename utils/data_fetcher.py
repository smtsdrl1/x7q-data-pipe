"""
Veri Çekme Modülü
Exchange'lerden OHLCV ve ticker verilerini asenkron çeker.
WebSocket candle cache ile anlık sinyal için düşük gecikme.
"""

import asyncio
import pandas as pd
import ccxt.async_support as ccxt
from utils.logger import setup_logger
from config import (
    EXCHANGE_ID, BINANCE_API_KEY, BINANCE_SECRET,
    BINANCE_TESTNET, OHLCV_LIMIT, TREND_TIMEFRAME, PRIMARY_TIMEFRAME
)

logger = setup_logger("DataFetcher")


class DataFetcher:
    """
    Borsa veri çekici.
    - REST API: başlangıç yüklemesi ve fallback
    - WebSocket: anlık mum güncellemesi (REST polling yerine)
    - Multi-timeframe: 5m + 1h verisi önbellekte tutulur
    """

    def __init__(self):
        self.exchange = None
        self._initialized = False
        # WebSocket candle cache: {symbol: {timeframe: DataFrame}}
        self._candle_cache: dict[str, dict[str, pd.DataFrame]] = {}
        self._ws_tasks: list[asyncio.Task] = []
        self._ws_running = False
        self._ws_supported = False  # WebSocket desteklenip desteklenmediği

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
        self._ws_running = False
        for task in self._ws_tasks:
            task.cancel()
        self._ws_tasks.clear()
        if self.exchange:
            await self.exchange.close()
            self._initialized = False

    # ==================== WEBSOCKET STREAMING ====================

    async def start_websocket_stream(self, symbols: list, timeframes: list = None):
        """
        WebSocket stream başlat — REST polling yerine anlık veri.
        Önce REST ile history yükler, sonra WS ile günceller.
        """
        if timeframes is None:
            timeframes = [PRIMARY_TIMEFRAME, TREND_TIMEFRAME]

        await self.initialize()

        # Önce REST ile history yükle
        logger.info(f"WebSocket için {len(symbols)} sembol başlangıç verisi yükleniyor...")
        for symbol in symbols:
            self._candle_cache[symbol] = {}
            for tf in timeframes:
                try:
                    df = await self.fetch_ohlcv(symbol, tf, limit=250)
                    self._candle_cache[symbol][tf] = df
                    logger.info(f"  ✓ {symbol} {tf}: {len(df)} mum yüklendi")
                except Exception as e:
                    logger.warning(f"  ✗ {symbol} {tf}: {e}")
                    self._candle_cache[symbol][tf] = pd.DataFrame()

        # WebSocket watch denemesi
        try:
            if not hasattr(self.exchange, "watch_ohlcv"):
                raise AttributeError("watch_ohlcv yok")
            # Test et
            test_candle = await asyncio.wait_for(
                self.exchange.watch_ohlcv(symbols[0], PRIMARY_TIMEFRAME), timeout=5.0
            )
            self._ws_supported = True
            logger.info("WebSocket destekleniyor — anlık mum stream aktif")

            self._ws_running = True
            # Her sembol için ayrı watch task başlat
            for symbol in symbols:
                for tf in timeframes:
                    task = asyncio.create_task(
                        self._ws_watch_symbol(symbol, tf),
                        name=f"ws_{symbol}_{tf}"
                    )
                    self._ws_tasks.append(task)

        except Exception as e:
            logger.warning(f"WebSocket başlatılamadı ({e}) — REST polling kullanılıyor")
            self._ws_supported = False

    async def _ws_watch_symbol(self, symbol: str, timeframe: str):
        """Tek bir sembol için WebSocket dinleme döngüsü."""
        retry_count = 0
        while self._ws_running:
            try:
                candles = await self.exchange.watch_ohlcv(symbol, timeframe)
                if candles:
                    self._update_cache(symbol, timeframe, candles)
                retry_count = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                retry_count += 1
                wait = min(30, 2 ** retry_count)
                logger.warning(f"WS hatası ({symbol} {timeframe}): {e} — {wait}s sonra retry")
                await asyncio.sleep(wait)

    def _update_cache(self, symbol: str, timeframe: str, new_candles: list):
        """WebSocket'ten gelen mumu cache'e uygula."""
        if symbol not in self._candle_cache or timeframe not in self._candle_cache[symbol]:
            return
        df = self._candle_cache[symbol][timeframe]
        if df.empty:
            return

        for candle in new_candles:
            ts, o, h, l, c, v = candle[0], candle[1], candle[2], candle[3], candle[4], candle[5]
            timestamp = pd.Timestamp(ts, unit="ms")
            row = {"open": float(o), "high": float(h), "low": float(l),
                   "close": float(c), "volume": float(v)}
            if timestamp in df.index:
                df.loc[timestamp] = row  # Mevcut mumu güncelle
            else:
                new_row = pd.DataFrame([row], index=[timestamp])
                df = pd.concat([df, new_row])

        # Son 300 mumu tut
        if len(df) > 300:
            df = df.iloc[-300:]
        self._candle_cache[symbol][timeframe] = df.sort_index()

    async def get_ohlcv(self, symbol: str, timeframe: str = PRIMARY_TIMEFRAME,
                        limit: int = OHLCV_LIMIT) -> pd.DataFrame:
        """
        OHLCV al — WebSocket cache öncelikli, yoksa REST fallback.
        """
        if (self._ws_supported and
                symbol in self._candle_cache and
                timeframe in self._candle_cache[symbol] and
                not self._candle_cache[symbol][timeframe].empty):
            df = self._candle_cache[symbol][timeframe]
            return df.iloc[-limit:] if len(df) > limit else df

        # REST fallback
        return await self.fetch_ohlcv(symbol, timeframe, limit)

    async def fetch_trend_context(self, symbol: str) -> dict:
        """
        Multi-timeframe trend bağlamı çek.
        Returns: {"trend": "BULLISH"|"BEARISH"|"NEUTRAL", "ema_fast": ..., "ema_slow": ...}
        """
        try:
            df_1h = await self.get_ohlcv(symbol, TREND_TIMEFRAME, limit=100)
            if df_1h.empty or len(df_1h) < 60:
                return {"trend": "NEUTRAL", "ema_fast": 0, "ema_slow": 0}

            close = df_1h["close"]
            ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
            ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
            ema55 = close.ewm(span=55, adjust=False).mean().iloc[-1]
            price = close.iloc[-1]

            # 3-EMA trend filtresi
            if price > ema9 > ema21 > ema55:
                trend = "BULLISH"
            elif price < ema9 < ema21 < ema55:
                trend = "BEARISH"
            elif price > ema21 and ema9 > ema55:
                trend = "BULLISH"
            elif price < ema21 and ema9 < ema55:
                trend = "BEARISH"
            else:
                trend = "NEUTRAL"

            return {"trend": trend, "ema9": ema9, "ema21": ema21, "ema55": ema55, "price_1h": price}
        except Exception as e:
            logger.warning(f"Trend context hatası ({symbol}): {e}")
            return {"trend": "NEUTRAL"}

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
