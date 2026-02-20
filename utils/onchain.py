"""
On-Chain Veri Modülü
Blockchain verileri üzerinden akıllı para hareketlerini takip eder.

Veri kaynakları:
1. Glassnode API (API key gerekli, ücretsiz tier limited)
2. CryptoQuant API (ücretsiz tier var)
3. Whale Alert (büyük transferler)
4. CoinGecko (exchange inflows/outflows)

On-chain sinyaller:
- Exchange Outflow: Büyük çekim → hodl → bullish
- Exchange Inflow: Büyük yatırım → satış baskısı → bearish
- SOPR (Spent Output Profit Ratio) > 1 → kârdaki cüzdanlar satıyor
- MVRV Ratio yüksek → pahalı → satış bölgesi
- Realized Price → uzun vadeli destek
"""

import aiohttp
import time
from utils.logger import setup_logger

logger = setup_logger("OnChain")

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
CRYPTOQUANT_BASE = "https://api.cryptoquant.com/v1"

_cache: dict[str, tuple[dict, float]] = {}
CACHE_TTL = 1800  # 30 dakika — on-chain data yavaş değişir


async def get_exchange_flows(symbol: str = "bitcoin",
                              session: aiohttp.ClientSession = None) -> dict:
    """
    Exchange inflow/outflow verisi çek.
    CoinGecko'dan exchange'e giren/çıkan hacim verisi kullanılır.
    
    Returns:
        dict: net_flow, inflow, outflow, flow_signal, score_boost
    """
    cache_key = f"flows_{symbol}"
    if cache_key in _cache:
        data, ts = _cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return data
    
    try:
        # CoinGecko coin data
        url = f"{COINGECKO_BASE}/coins/{symbol}"
        params = {
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "false",
            "developer_data": "false",
        }
        
        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True
        
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status != 200:
                if close_session:
                    await session.close()
                return _empty_flows(symbol)
            raw = await resp.json()
        
        if close_session:
            await session.close()
        
        market_data = raw.get("market_data", {})
        
        # 24h price change kuvvetlice yukarı + yüksek hacim = sağlıklı
        price_change_24h = market_data.get("price_change_percentage_24h", 0) or 0
        volume_24h = market_data.get("total_volume", {}).get("usd", 0) or 0
        mcap = market_data.get("market_cap", {}).get("usd", 1) or 1
        
        # Volume/MCap oranı (yüksek = aktif trading)
        vol_mcap_ratio = (volume_24h / mcap) * 100 if mcap > 0 else 0
        
        # Basit on-chain proxy: Volume spike + fiyat artışı = inflow
        # Bu gerçek on-chain değil, proxy metriktir
        if price_change_24h > 5 and vol_mcap_ratio > 5:
            flow_signal = "STRONG_INFLOW"
            score_boost = 8
        elif price_change_24h > 2 and vol_mcap_ratio > 3:
            flow_signal = "MILD_INFLOW"
            score_boost = 4
        elif price_change_24h < -5 and vol_mcap_ratio > 5:
            flow_signal = "STRONG_OUTFLOW"  # Panic selling
            score_boost = -8
        elif price_change_24h < -2:
            flow_signal = "MILD_OUTFLOW"
            score_boost = -4
        else:
            flow_signal = "NEUTRAL"
            score_boost = 0
        
        result = {
            "symbol": symbol,
            "price_change_24h": price_change_24h,
            "volume_24h_usd": volume_24h,
            "vol_mcap_ratio": round(vol_mcap_ratio, 3),
            "flow_signal": flow_signal,
            "score_boost": score_boost,
            "available": True,
            "source": "coingecko_proxy",
        }
        
        _cache[cache_key] = (result, time.time())
        return result
    
    except Exception as e:
        logger.debug(f"On-chain veri hatası ({symbol}): {e}")
        return _empty_flows(symbol)


async def get_fear_greed_index() -> dict:
    """
    Kripto Fear & Greed Index çek (alternative.me API, ücretsiz).
    
    Returns:
        dict: value (0-100), sentiment, score_boost
    """
    cache_key = "fear_greed"
    if cache_key in _cache:
        data, ts = _cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return data
    
    try:
        url = "https://api.alternative.me/fng/?limit=1&format=json"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return _empty_fng()
                raw = await resp.json()
        
        fng_data = raw.get("data", [{}])[0]
        value = int(fng_data.get("value", 50))
        classification = fng_data.get("value_classification", "Neutral")
        
        # Signal
        if value <= 20:
            signal = "EXTREME_FEAR"
            score_boost = +8   # Aşırı korku → alım fırsatı
        elif value <= 35:
            signal = "FEAR"
            score_boost = +4
        elif value >= 80:
            signal = "EXTREME_GREED"
            score_boost = -8  # Aşırı açgözlülük → satım bölgesi
        elif value >= 65:
            signal = "GREED"
            score_boost = -4
        else:
            signal = "NEUTRAL"
            score_boost = 0
        
        result = {
            "value": value,
            "classification": classification,
            "signal": signal,
            "score_boost": score_boost,
            "available": True,
        }
        
        _cache[cache_key] = (result, time.time())
        return result
    
    except Exception as e:
        logger.debug(f"Fear & Greed hatası: {e}")
        return _empty_fng()


async def get_whale_activity(symbol: str = "BTC") -> dict:
    """
    Büyük transfer tespiti (proxy: exchange volume anomali).
    Whale Alert API key gerektiriyor, proxy hesaplama yapıyoruz.
    """
    # Bu fonksiyon gelecekte Whale Alert API ile genişletilecek
    # Şimdilik işaretleyici olarak dönüyor
    return {
        "symbol": symbol,
        "large_transfers_24h": 0,
        "whale_signal": "NEUTRAL",
        "available": False,
        "note": "Whale Alert API key gerekli (WHALE_ALERT_API_KEY env var)"
    }


def get_onchain_composite_score(
    flows: dict,
    fear_greed: dict,
    signal_side: str
) -> float:
    """
    On-chain bileşik skor katkısı.
    
    Returns:
        float: -15 ile +15 arasında
    """
    boost = 0.0
    
    fg_boost = fear_greed.get("score_boost", 0)
    flow_boost = flows.get("score_boost", 0)
    
    if signal_side == "buy":
        boost = fg_boost + flow_boost
    elif signal_side == "sell":
        boost = -(fg_boost + flow_boost)
    
    return round(max(-15.0, min(15.0, boost)), 2)


def _empty_flows(symbol: str) -> dict:
    return {
        "symbol": symbol, "price_change_24h": 0, "volume_24h_usd": 0,
        "vol_mcap_ratio": 0, "flow_signal": "NEUTRAL", "score_boost": 0,
        "available": False, "source": "none",
    }


def _empty_fng() -> dict:
    return {
        "value": 50, "classification": "Neutral",
        "signal": "NEUTRAL", "score_boost": 0, "available": False,
    }
