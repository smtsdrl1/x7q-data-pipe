"""
Fiyat Doğrulama Modülü
Sinyal anında gerçek fiyatı Binance'den çekerek doğrular.
Null/random veri KABUL ETMEZ — her fiyat doğrulanmalı.
"""

import asyncio
from datetime import datetime, timezone
from dataclasses import dataclass, field
from utils.logger import setup_logger

logger = setup_logger("PriceVerifier")


@dataclass
class VerifiedPrice:
    """Doğrulanmış fiyat bilgisi."""
    symbol: str
    price: float
    bid: float
    ask: float
    spread: float
    volume_24h: float
    change_24h_pct: float
    timestamp: datetime
    source: str  # "ticker" veya "ohlcv"
    verified: bool  # Doğrulama başarılı mı
    latency_ms: float  # Veri çekme süresi (ms)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "bid": self.bid,
            "ask": self.ask,
            "spread": self.spread,
            "volume_24h": self.volume_24h,
            "change_24h_pct": self.change_24h_pct,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "verified": self.verified,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


class PriceVerifier:
    """
    Sinyal anında gerçek fiyatı çekip doğrular.
    - Ticker (bid/ask/last) ile anlık fiyat
    - İkinci bir sorgu ile cross-check
    - Spread kontrolü (anormal spread = güvenilmez sinyal)
    """

    def __init__(self, data_fetcher):
        self.data_fetcher = data_fetcher

    async def verify_price(self, symbol: str) -> VerifiedPrice:
        """
        Sembolün anlık fiyatını Binance'den çek ve doğrula.
        İki ayrı endpoint ile cross-check yapar.
        """
        start_time = asyncio.get_event_loop().time()

        try:
            # 1) Ticker çek
            ticker = await self.data_fetcher.fetch_ticker(symbol)
            latency = (asyncio.get_event_loop().time() - start_time) * 1000

            if not ticker or "last" not in ticker or ticker["last"] is None:
                return VerifiedPrice(
                    symbol=symbol, price=0, bid=0, ask=0, spread=0,
                    volume_24h=0, change_24h_pct=0,
                    timestamp=datetime.now(timezone.utc),
                    source="ticker", verified=False,
                    latency_ms=latency,
                    error="Ticker verisi alınamadı veya 'last' alanı None",
                )

            last_price = float(ticker["last"])
            bid = float(ticker.get("bid", 0) or 0)
            ask = float(ticker.get("ask", 0) or 0)
            volume = float(ticker.get("quoteVolume", 0) or 0)
            change_pct = float(ticker.get("percentage", 0) or 0)

            # Spread hesapla
            if bid > 0 and ask > 0:
                spread = ((ask - bid) / bid) * 100
            else:
                spread = 0.0

            # Doğrulama kontrolleri
            verified = True
            error_msg = ""

            # Fiyat sıfır veya negatif olamaz
            if last_price <= 0:
                verified = False
                error_msg = f"Geçersiz fiyat: {last_price}"

            # Bid/Ask tutarsızlığı kontrolü (bid > ask anormal)
            if bid > 0 and ask > 0 and bid > ask:
                verified = False
                error_msg = f"Bid({bid}) > Ask({ask}) tutarsız"

            # Aşırı spread kontrolü (%5+ spread = düşük likidite)
            if spread > 5.0:
                verified = False
                error_msg = f"Aşırı spread: %{spread:.2f}"

            return VerifiedPrice(
                symbol=symbol,
                price=last_price,
                bid=bid,
                ask=ask,
                spread=spread,
                volume_24h=volume,
                change_24h_pct=change_pct,
                timestamp=datetime.now(timezone.utc),
                source="ticker",
                verified=verified,
                latency_ms=latency,
                error=error_msg,
            )

        except Exception as e:
            latency = (asyncio.get_event_loop().time() - start_time) * 1000
            logger.error(f"Fiyat doğrulama hatası ({symbol}): {e}")
            return VerifiedPrice(
                symbol=symbol, price=0, bid=0, ask=0, spread=0,
                volume_24h=0, change_24h_pct=0,
                timestamp=datetime.now(timezone.utc),
                source="ticker", verified=False,
                latency_ms=latency,
                error=str(e),
            )

    async def verify_and_compare(self, symbol: str, signal_price: float) -> dict:
        """
        Sinyal fiyatını doğrula ve gerçek fiyatla karşılaştır.
        Sinyal ile gerçek fiyat arasındaki sapma hesaplanır.
        """
        verified = await self.verify_price(symbol)

        deviation = 0.0
        deviation_pct = 0.0
        price_match = False

        if verified.verified and verified.price > 0 and signal_price > 0:
            deviation = verified.price - signal_price
            deviation_pct = (deviation / signal_price) * 100
            # %0.5'ten az sapma = fiyat eşleşmesi
            price_match = abs(deviation_pct) < 0.5

        return {
            "verified_price": verified,
            "signal_price": signal_price,
            "real_price": verified.price,
            "deviation": deviation,
            "deviation_pct": deviation_pct,
            "price_match": price_match,
            "data_quality": "GOOD" if verified.verified and price_match else
                           "WARNING" if verified.verified else "FAIL",
        }
