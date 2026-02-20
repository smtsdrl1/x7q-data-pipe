"""
Derivatives Veri Modülü - Open Interest ve Funding Rate
Binance Futures API üzerinden OI ve FR verilerini çeker.

Kullanım Mantığı:
- OI artıyor + Fiyat artıyor → güçlü yükseliş (yeni longs giriyor)
- OI artıyor + Fiyat düşüyor → güçlü düşüş (yeni shorts giriyor)
- OI azalıyor → pozisyon kapatma (trend güçsüzleşiyor)
- Funding Rate pozitif → longs ödüyor → overbought signal
- Funding Rate negatif → shorts ödüyor → oversold signal
"""

import asyncio
import aiohttp
import time
from utils.logger import setup_logger

logger = setup_logger("Derivatives")

BINANCE_FAPI_BASE = "https://fapi.binance.com"

# Cache: sembol → (data, timestamp)
_oi_cache: dict[str, tuple[dict, float]] = {}
_fr_cache: dict[str, tuple[dict, float]] = {}
CACHE_TTL = 60  # 60 saniye cache (API rate limit koruma)


async def get_open_interest(symbol: str, session: aiohttp.ClientSession = None) -> dict:
    """
    Binance FAPI'den Open Interest verisi çek.
    Symbol format: "BTCUSDT" (slash olmadan)
    """
    clean_symbol = symbol.replace("/", "")
    
    # Cache kontrolü
    if clean_symbol in _oi_cache:
        data, ts = _oi_cache[clean_symbol]
        if time.time() - ts < CACHE_TTL:
            return data
    
    try:
        url = f"{BINANCE_FAPI_BASE}/fapi/v1/openInterest"
        params = {"symbol": clean_symbol}
        
        if session is None:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        raw = await resp.json()
                    else:
                        return _empty_oi(clean_symbol)
        else:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    raw = await resp.json()
                else:
                    return _empty_oi(clean_symbol)
        
        oi_value = float(raw.get("openInterest", 0))
        result = {
            "symbol": clean_symbol,
            "open_interest": oi_value,
            "oi_usdt": 0.0,  # Dolar değeri için fiyat gerekli
            "timestamp": int(raw.get("time", time.time() * 1000)),
            "available": True,
        }
        _oi_cache[clean_symbol] = (result, time.time())
        return result
    
    except Exception as e:
        logger.debug(f"OI veri hatası ({clean_symbol}): {e}")
        return _empty_oi(clean_symbol)


async def get_funding_rate(symbol: str, session: aiohttp.ClientSession = None) -> dict:
    """
    Binance FAPI'den Funding Rate verisi çek (son 5 funding).
    """
    clean_symbol = symbol.replace("/", "")
    
    # Cache kontrolü
    if clean_symbol in _fr_cache:
        data, ts = _fr_cache[clean_symbol]
        if time.time() - ts < CACHE_TTL:
            return data
    
    try:
        url = f"{BINANCE_FAPI_BASE}/fapi/v1/fundingRate"
        params = {"symbol": clean_symbol, "limit": 5}
        
        if session is None:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        raw = await resp.json()
                    else:
                        return _empty_fr(clean_symbol)
        else:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    raw = await resp.json()
                else:
                    return _empty_fr(clean_symbol)
        
        if not raw:
            return _empty_fr(clean_symbol)
        
        latest = raw[-1]
        current_fr = float(latest.get("fundingRate", 0))
        
        # Ortalama FR (son 5)
        rates = [float(r.get("fundingRate", 0)) for r in raw]
        avg_fr = sum(rates) / len(rates) if rates else 0.0
        
        # FR yorumu
        if current_fr > 0.001:  # > 0.1%
            fr_signal = "OVERBOUGHT"   # Longs çok fazla → short ağırlıklı fırsat
        elif current_fr < -0.001:  # < -0.1%
            fr_signal = "OVERSOLD"     # Shorts çok fazla → long ağırlıklı fırsat
        elif current_fr > 0.0003:
            fr_signal = "BULLISH_BIAS"
        elif current_fr < -0.0003:
            fr_signal = "BEARISH_BIAS"
        else:
            fr_signal = "NEUTRAL"
        
        result = {
            "symbol": clean_symbol,
            "funding_rate": current_fr,
            "funding_rate_pct": current_fr * 100,
            "avg_funding_rate": avg_fr,
            "fr_signal": fr_signal,
            "next_funding_time": int(latest.get("fundingTime", 0)),
            "available": True,
        }
        _fr_cache[clean_symbol] = (result, time.time())
        return result
    
    except Exception as e:
        logger.debug(f"FR veri hatası ({clean_symbol}): {e}")
        return _empty_fr(clean_symbol)


async def get_oi_history(symbol: str, period: str = "5m", limit: int = 50,
                          session: aiohttp.ClientSession = None) -> list[dict]:
    """
    OI tarihsel verisi (FAPI /futures/data/openInterestHist).
    OI trend analizi için kullanılır.
    """
    clean_symbol = symbol.replace("/", "")
    try:
        url = f"{BINANCE_FAPI_BASE}/futures/data/openInterestHist"
        params = {"symbol": clean_symbol, "period": period, "limit": limit}
        
        if session is None:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return []
        else:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    return await resp.json()
                return []
    except Exception as e:
        logger.debug(f"OI history hatası ({clean_symbol}): {e}")
        return []


def analyze_oi_trend(oi_history: list[dict]) -> dict:
    """
    OI tarihsel veriden trend analizi yap.
    
    Returns:
        dict: oi_trend, oi_change_pct, oi_signal, score_boost
    """
    if len(oi_history) < 3:
        return {"oi_trend": "UNKNOWN", "oi_change_pct": 0, "oi_signal": "NEUTRAL", "score_boost": 0}
    
    try:
        ois = [float(h.get("sumOpenInterest", 0)) for h in oi_history]
        first_oi = ois[0]
        last_oi = ois[-1]
        
        if first_oi == 0:
            return {"oi_trend": "UNKNOWN", "oi_change_pct": 0, "oi_signal": "NEUTRAL", "score_boost": 0}
        
        change_pct = ((last_oi - first_oi) / first_oi) * 100
        
        if change_pct > 5:
            oi_trend = "RISING_FAST"
        elif change_pct > 1:
            oi_trend = "RISING"
        elif change_pct < -5:
            oi_trend = "FALLING_FAST"
        elif change_pct < -1:
            oi_trend = "FALLING"
        else:
            oi_trend = "STABLE"
        
        return {
            "oi_trend": oi_trend,
            "oi_change_pct": round(change_pct, 2),
            "oi_current": last_oi,
            "oi_signal": oi_trend,
            "score_boost": 5 if "RISING" in oi_trend else (-3 if "FALLING" in oi_trend else 0),
        }
    except Exception as e:
        logger.error(f"OI trend analiz hatası: {e}")
        return {"oi_trend": "UNKNOWN", "oi_change_pct": 0, "oi_signal": "NEUTRAL", "score_boost": 0}


def get_derivatives_score_boost(oi_data: dict, fr_data: dict, signal_side: str) -> float:
    """
    OI + FR verilerine göre toplam skor katkısı.
    
    Returns:
        float: -12 ile +12 arasında skor katkısı
    """
    boost = 0.0
    
    fr_signal = fr_data.get("fr_signal", "NEUTRAL")
    oi_trend = oi_data.get("oi_trend", "STABLE") if oi_data else "STABLE"
    
    if signal_side == "buy":
        # FR
        if fr_signal == "OVERSOLD":
            boost += 6  # Shorts overpaid → squeeze olabilir
        elif fr_signal == "BEARISH_BIAS":
            boost += 3
        elif fr_signal == "OVERBOUGHT":
            boost -= 4  # Zaten çok fazla long var → overcrowded
        
        # OI
        if oi_trend in ("RISING", "RISING_FAST"):
            boost += 4  # Para giriyor
        elif oi_trend in ("FALLING", "FALLING_FAST"):
            boost -= 3  # Para çıkıyor
    
    elif signal_side == "sell":
        # FR
        if fr_signal == "OVERBOUGHT":
            boost += 6
        elif fr_signal == "BULLISH_BIAS":
            boost += 3
        elif fr_signal == "OVERSOLD":
            boost -= 4
        
        # OI
        if oi_trend in ("RISING", "RISING_FAST"):
            boost += 4
        elif oi_trend in ("FALLING", "FALLING_FAST"):
            boost -= 3
    
    return round(max(-12.0, min(12.0, boost)), 2)


def _empty_oi(symbol: str) -> dict:
    return {"symbol": symbol, "open_interest": 0, "oi_usdt": 0, "available": False,
            "oi_trend": "UNKNOWN", "oi_change_pct": 0, "score_boost": 0}


def _empty_fr(symbol: str) -> dict:
    return {"symbol": symbol, "funding_rate": 0, "funding_rate_pct": 0,
            "fr_signal": "NEUTRAL", "avg_funding_rate": 0, "available": False}
