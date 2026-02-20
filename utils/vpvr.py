"""
Volume Profile / VPVR (Volume Profile Visible Range)
Fiyat seviyelerine göre hacim dağılımını hesaplayarak
yüksek hacimli destek/direnç seviyelerini tespit eder.

Kavramlar:
- POC (Point of Control): En fazla hacmin işlem gördüğü fiyat seviyesi
- VAH (Value Area High): Hacmin %70'inin işlem gördüğü alanın üst sınırı
- VAL (Value Area Low): Hacmin %70'inin işlem gördüğü alanın alt sınırı
- HVN (High Volume Node): Güçlü destek/direnç → fiyat burada yavaşlar
- LVN (Low Volume Node): Hızlı geçiş noktası → fiyat hızla geçer
"""

import numpy as np
import pandas as pd
from utils.logger import setup_logger

logger = setup_logger("VPVR")


def calculate_vpvr(df: pd.DataFrame, num_bins: int = 50, value_area_pct: float = 0.70) -> dict:
    """
    Volume Profile hesapla.
    
    Args:
        df: OHLCV DataFrame (high, low, close, volume gerekli)
        num_bins: Fiyat seviyesi sayısı
        value_area_pct: Value Area yüzdesi (default %70)
    
    Returns:
        dict: poc, vah, val, hvn_levels, lvn_levels, current_zone, signal, score_boost
    """
    if df is None or len(df) < 20:
        return _empty_vpvr()
    
    try:
        highs = df["high"].values.astype(float)
        lows = df["low"].values.astype(float)
        volumes = df["volume"].values.astype(float)
        closes = df["close"].values.astype(float)
        
        price_range_high = float(np.max(highs))
        price_range_low = float(np.min(lows))
        
        if price_range_high <= price_range_low:
            return _empty_vpvr()
        
        # Fiyat bin'leri oluştur
        bins = np.linspace(price_range_low, price_range_high, num_bins + 1)
        bin_centers = (bins[:-1] + bins[1:]) / 2
        bin_volumes = np.zeros(num_bins)
        
        # Her mum'un hacmini kapsadığı fiyat seviyelerine dağıt
        for i in range(len(df)):
            h, l, v = highs[i], lows[i], volumes[i]
            candle_range = h - l
            
            if candle_range <= 0:
                # Doji: hacmi close bin'ine ver
                bin_idx = np.digitize(closes[i], bins) - 1
                bin_idx = max(0, min(bin_idx, num_bins - 1))
                bin_volumes[bin_idx] += v
                continue
            
            # Hacmi fiyat aralığına orantısal dağıt
            for j in range(num_bins):
                bin_low = bins[j]
                bin_high = bins[j + 1]
                
                overlap_low = max(bin_low, l)
                overlap_high = min(bin_high, h)
                
                if overlap_high > overlap_low:
                    overlap_pct = (overlap_high - overlap_low) / candle_range
                    bin_volumes[j] += v * overlap_pct
        
        # POC: En yüksek hacimli seviye
        poc_idx = int(np.argmax(bin_volumes))
        poc = float(bin_centers[poc_idx])
        
        # Value Area (%70 hacim)
        total_volume = float(np.sum(bin_volumes))
        target_volume = total_volume * value_area_pct
        
        # POC'tan dışa doğru genişlet
        va_volume = bin_volumes[poc_idx]
        va_low_idx = poc_idx
        va_high_idx = poc_idx
        
        while va_volume < target_volume and (va_low_idx > 0 or va_high_idx < num_bins - 1):
            expand_up = bin_volumes[va_high_idx + 1] if va_high_idx < num_bins - 1 else 0
            expand_down = bin_volumes[va_low_idx - 1] if va_low_idx > 0 else 0
            
            if expand_up >= expand_down:
                va_high_idx = min(va_high_idx + 1, num_bins - 1)
                va_volume += expand_up
            else:
                va_low_idx = max(va_low_idx - 1, 0)
                va_volume += expand_down
        
        vah = float(bin_centers[va_high_idx])
        val = float(bin_centers[va_low_idx])
        
        # HVN: Ortalamanın 1.5x üstü hacimli seviyeler
        avg_vol = float(np.mean(bin_volumes))
        hvn_levels = [
            float(bin_centers[i]) for i in range(num_bins)
            if bin_volumes[i] > avg_vol * 1.5
        ]
        
        # LVN: Ortalamanın 0.4x altı hacimli seviyeler
        lvn_levels = [
            float(bin_centers[i]) for i in range(num_bins)
            if bin_volumes[i] < avg_vol * 0.4 and bin_volumes[i] > 0
        ]
        
        # Mevcut fiyata göre konum
        current_price = float(closes[-1])
        
        if current_price > vah:
            current_zone = "ABOVE_VALUE_AREA"
            signal = "NEUTRAL"  # Aşırı satın alınmış
            score_boost = -3
        elif current_price < val:
            current_zone = "BELOW_VALUE_AREA"
            signal = "NEUTRAL"
            score_boost = +3
        elif abs(current_price - poc) / poc < 0.002:
            current_zone = "AT_POC"
            signal = "SUPPORT"  # POC güçlü destek/direnç
            score_boost = +2
        else:
            current_zone = "INSIDE_VALUE_AREA"
            signal = "NEUTRAL"
            score_boost = 0
        
        # En yakın HVN seviyesi
        nearest_hvn = None
        if hvn_levels:
            distances = [abs(p - current_price) for p in hvn_levels]
            nearest_hvn = hvn_levels[int(np.argmin(distances))]
        
        # POC'a yakınlık ek sinyal
        poc_distance_pct = abs(current_price - poc) / current_price * 100
        
        return {
            "poc": round(poc, 6),
            "vah": round(vah, 6),
            "val": round(val, 6),
            "hvn_levels": [round(p, 6) for p in sorted(hvn_levels)[-5:]],
            "lvn_levels": [round(p, 6) for p in sorted(lvn_levels)[-5:]],
            "current_zone": current_zone,
            "nearest_hvn": round(nearest_hvn, 6) if nearest_hvn else None,
            "poc_distance_pct": round(poc_distance_pct, 3),
            "total_bins": num_bins,
            "signal": signal,
            "score_boost": score_boost,
            "price_range_high": round(price_range_high, 6),
            "price_range_low": round(price_range_low, 6),
            "available": True,
        }
    
    except Exception as e:
        logger.error(f"VPVR hesaplama hatası: {e}")
        return _empty_vpvr()


def get_vpvr_score_boost(vpvr_data: dict, signal_side: str, current_price: float) -> float:
    """
    VPVR verilerine göre skor katkısı.
    
    - POC yakınında buy → +skore (güçlü destek onayı)
    - VAH üstünde buy → -score (aşırı satın alınmış)
    - LVN üstünde price → hızlı hareket → +score
    """
    if not vpvr_data.get("available", False):
        return 0.0
    
    zona = vpvr_data.get("current_zone", "INSIDE_VALUE_AREA")
    poc = vpvr_data.get("poc", 0)
    poc_dist = vpvr_data.get("poc_distance_pct", 100)
    
    boost = 0.0
    
    if signal_side == "buy":
        if zona == "BELOW_VALUE_AREA":
            boost = +4  # Ucuz bölge
        elif zona == "AT_POC":
            boost = +3  # POC destek
        elif zona == "ABOVE_VALUE_AREA":
            boost = -3  # Pahalı bölge
        
        # LVN üstünde fiyat → yukarıya kolay hareket
        for lvn in vpvr_data.get("lvn_levels", []):
            if abs(current_price - lvn) / current_price < 0.01:
                boost += 2
                break
    
    elif signal_side == "sell":
        if zona == "ABOVE_VALUE_AREA":
            boost = +4
        elif zona == "AT_POC":
            boost = +3
        elif zona == "BELOW_VALUE_AREA":
            boost = -3
    
    return float(max(-6.0, min(6.0, boost)))


def _empty_vpvr() -> dict:
    return {
        "poc": 0, "vah": 0, "val": 0,
        "hvn_levels": [], "lvn_levels": [],
        "current_zone": "UNKNOWN", "nearest_hvn": None,
        "poc_distance_pct": 100, "total_bins": 0,
        "signal": "NEUTRAL", "score_boost": 0,
        "price_range_high": 0, "price_range_low": 0,
        "available": False,
    }
