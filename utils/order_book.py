"""
Order Book & Likidite Seviyeleri Analizi
Binance REST/WebSocket üzerinden order book verisi çekerek
büyük bid/ask duvarlarını ve likidite boşluklarını tespit eder.

Likidite Kavramları:
- Bid Wall: Büyük alım emri → güçlü destek + kısa vadeli fiyat engeli
- Ask Wall: Büyük satım emri → güçlü direnç
- Liquidity Void: Order book'ta boşluk → hızlı fiyat hareketi beklenir
- Bid/Ask Imbalance: Yoğun bid > ask → bullish pressure
"""

import asyncio
import aiohttp
import time
from utils.logger import setup_logger

logger = setup_logger("OrderBook")

BINANCE_API_BASE = "https://api.binance.com"
_ob_cache: dict[str, tuple[dict, float]] = {}
CACHE_TTL = 15  # 15 saniye — order book hızlı değişir


async def get_order_book(symbol: str, depth: int = 20,
                          session: aiohttp.ClientSession = None) -> dict:
    """
    Binance'dan order book verisini çek.
    
    Args:
        symbol: "BTC/USDT" veya "BTCUSDT"
        depth: Gösterilecek seviye sayısı (5, 10, 20, 50, 100, 500, 1000)
    
    Returns:
        dict: bids, asks, spread, bid_wall, ask_wall, imbalance_ratio, signal
    """
    clean_symbol = symbol.replace("/", "")
    
    # Cache
    cache_key = f"{clean_symbol}_{depth}"
    if cache_key in _ob_cache:
        data, ts = _ob_cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return data
    
    try:
        url = f"{BINANCE_API_BASE}/api/v3/depth"
        params = {"symbol": clean_symbol, "limit": depth}
        
        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True
        
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return _empty_ob(clean_symbol)
                raw = await resp.json()
        finally:
            if close_session:
                await session.close()
        
        bids = [(float(p), float(q)) for p, q in raw.get("bids", [])]
        asks = [(float(p), float(q)) for p, q in raw.get("asks", [])]
        
        if not bids or not asks:
            return _empty_ob(clean_symbol)
        
        result = analyze_order_book(bids, asks, clean_symbol)
        _ob_cache[cache_key] = (result, time.time())
        return result
    
    except Exception as e:
        logger.debug(f"Order book hatası ({clean_symbol}): {e}")
        return _empty_ob(clean_symbol)


def analyze_order_book(bids: list[tuple], asks: list[tuple], symbol: str) -> dict:
    """
    Ham order book verilerini analiz et.
    
    Args:
        bids: [(price, quantity), ...] azalan sıralı
        asks: [(price, quantity), ...] artan sıralı
    """
    if not bids or not asks:
        return _empty_ob(symbol)
    
    best_bid = bids[0][0]
    best_ask = asks[0][0]
    
    spread = best_ask - best_bid
    spread_pct = (spread / best_bid) * 100 if best_bid > 0 else 0
    mid_price = (best_bid + best_ask) / 2
    
    # Toplam derinlik
    total_bid_qty = sum(q for _, q in bids)
    total_ask_qty = sum(q for _, q in asks)
    total_bid_usdt = sum(p * q for p, q in bids)
    total_ask_usdt = sum(p * q for p, q in asks)
    
    # Bid/Ask imbalance
    total_volume = total_bid_usdt + total_ask_usdt
    imbalance_ratio = (total_bid_usdt / total_volume * 100) if total_volume > 0 else 50.0
    
    # Büyük duvarları tespit (ortalamanın 5x üstü)
    avg_bid_qty = total_bid_qty / len(bids) if bids else 0
    avg_ask_qty = total_ask_qty / len(asks) if asks else 0
    
    bid_walls = [(p, q) for p, q in bids if q > avg_bid_qty * 5]
    ask_walls = [(p, q) for p, q in asks if q > avg_ask_qty * 5]
    
    # En büyük bid/ask wall
    biggest_bid_wall = max(bid_walls, key=lambda x: x[1]) if bid_walls else None
    biggest_ask_wall = max(ask_walls, key=lambda x: x[1]) if ask_walls else None
    
    # Likidite boşlukları (art arda düşük hacimli seviyeler)
    void_threshold = avg_ask_qty * 0.1
    ask_voids = []
    for i in range(1, len(asks)):
        if asks[i][1] < void_threshold and asks[i-1][1] < void_threshold:
            ask_voids.append((asks[i-1][0], asks[i][0]))
    
    # Signal
    if imbalance_ratio > 65:
        ob_signal = "BULLISH_PRESSURE"
        score_boost = 6
    elif imbalance_ratio > 55:
        ob_signal = "SLIGHT_BULLISH"
        score_boost = 3
    elif imbalance_ratio < 35:
        ob_signal = "BEARISH_PRESSURE"
        score_boost = -6
    elif imbalance_ratio < 45:
        ob_signal = "SLIGHT_BEARISH"
        score_boost = -3
    else:
        ob_signal = "BALANCED"
        score_boost = 0
    
    # Duvar yakınında mı?
    if biggest_ask_wall and abs(mid_price - biggest_ask_wall[0]) / mid_price < 0.005:
        ob_signal = "RESISTANCE_WALL"
        score_boost -= 3
    if biggest_bid_wall and abs(mid_price - biggest_bid_wall[0]) / mid_price < 0.005:
        ob_signal = "SUPPORT_WALL"
        score_boost += 3
    
    return {
        "symbol": symbol,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "spread_pct": round(spread_pct, 4),
        "mid_price": mid_price,
        "total_bid_usdt": round(total_bid_usdt, 2),
        "total_ask_usdt": round(total_ask_usdt, 2),
        "imbalance_ratio": round(imbalance_ratio, 2),
        "bid_walls": bid_walls[:3],
        "ask_walls": ask_walls[:3],
        "biggest_bid_wall": biggest_bid_wall,
        "biggest_ask_wall": biggest_ask_wall,
        "ask_voids": ask_voids[:3],
        "ob_signal": ob_signal,
        "score_boost": score_boost,
        "available": True,
    }


def get_ob_score_boost(ob_data: dict, signal_side: str) -> float:
    """Order book skor katkısı."""
    if not ob_data.get("available", False):
        return 0.0
    
    base_boost = ob_data.get("score_boost", 0)
    
    # Side'a göre yön düzelt
    if signal_side == "sell":
        base_boost = -base_boost
    
    return float(max(-8.0, min(8.0, base_boost)))


def _empty_ob(symbol: str) -> dict:
    return {
        "symbol": symbol, "best_bid": 0, "best_ask": 0, "spread": 0, "spread_pct": 0,
        "mid_price": 0, "total_bid_usdt": 0, "total_ask_usdt": 0,
        "imbalance_ratio": 50, "bid_walls": [], "ask_walls": [],
        "biggest_bid_wall": None, "biggest_ask_wall": None,
        "ask_voids": [], "ob_signal": "UNKNOWN", "score_boost": 0, "available": False,
    }
