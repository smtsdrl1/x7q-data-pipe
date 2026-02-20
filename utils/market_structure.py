"""
Market Structure Analizi - Break of Structure (BOS) ve Change of Character (CHoCH)
ICT (Inner Circle Trader) Market Structure teorisi implementasyonu.

- BOS (Break of Structure): Son swing high kırılırsa → trend devam
- CHoCH (Change of Character): İlk zıt swing kırılırsa → trend dönüşü başlıyor
FVG+Fibonacci ile birleşince tam ICT sistemi oluşur.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from utils.logger import setup_logger

logger = setup_logger("MarketStructure")


@dataclass
class SwingPoint:
    """Swing High veya Swing Low noktası."""
    index: int
    price: float
    type: str        # "HH", "HL", "LH", "LL"
    candle_idx: int


@dataclass 
class StructureBreak:
    """Yapı kırılması olayı."""
    type: str        # "BOS_BULLISH", "BOS_BEARISH", "CHOCH_BULLISH", "CHOCH_BEARISH"
    price: float
    candle_idx: int
    swing_ref: float  # Kırılan swing price


def detect_swing_points(df: pd.DataFrame, lookback: int = 5) -> list[SwingPoint]:
    """
    Swing high/low noktalarını tespit et.
    
    Args:
        df: OHLCV DataFrame
        lookback: Her iki yanda kontrol edilecek mum sayısı
    
    Returns:
        list[SwingPoint]: Sıralı swing noktaları
    """
    swings = []
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    
    for i in range(lookback, n - lookback):
        # Swing High: solundaki ve sağındaki tüm high'lardan büyük
        is_sh = all(highs[i] > highs[i-j] for j in range(1, lookback+1)) and \
                all(highs[i] > highs[i+j] for j in range(1, lookback+1))
        
        # Swing Low: solundaki ve sağındaki tüm low'lardan küçük
        is_sl = all(lows[i] < lows[i-j] for j in range(1, lookback+1)) and \
                all(lows[i] < lows[i+j] for j in range(1, lookback+1))
        
        if is_sh:
            swings.append(SwingPoint(
                index=len(swings), price=highs[i], type="SH", candle_idx=i
            ))
        elif is_sl:
            swings.append(SwingPoint(
                index=len(swings), price=lows[i], type="SL", candle_idx=i
            ))
    
    return swings


def classify_swing_structure(swings: list[SwingPoint]) -> list[SwingPoint]:
    """
    Swing noktalarını HH, HL, LH, LL olarak sınıflandır.
    
    HH = Higher High (önceki SH'dan yüksek)
    HL = Higher Low (önceki SL'den yüksek)  
    LH = Lower High (önceki SH'dan düşük)
    LL = Lower Low (önceki SL'den düşük)
    """
    if len(swings) < 2:
        return swings
    
    last_sh_price = None
    last_sl_price = None
    
    for sw in swings:
        if sw.type == "SH":
            if last_sh_price is None:
                sw.type = "SH"
            elif sw.price > last_sh_price:
                sw.type = "HH"
            else:
                sw.type = "LH"
            last_sh_price = sw.price
        
        elif sw.type == "SL":
            if last_sl_price is None:
                sw.type = "SL"
            elif sw.price > last_sl_price:
                sw.type = "HL"
            else:
                sw.type = "LL"
            last_sl_price = sw.price
    
    return swings


def detect_structure_breaks(df: pd.DataFrame, swings: list[SwingPoint]) -> list[StructureBreak]:
    """
    BOS ve CHoCH noktalarını tespit et.
    
    BOS: Trend devam - mevcut trend yönündeki son swing kırılır
    CHoCH: Trend dönüşü - ilk zıt swing kırılır
    """
    breaks = []
    closes = df["close"].values
    n = len(closes)
    
    if len(swings) < 3:
        return breaks
    
    # Son 20 swing'e bak
    recent_swings = swings[-20:]
    
    # Trend tespiti: son 3-4 swap yapısına bak
    sh_points = [s for s in recent_swings if s.type in ("SH", "HH", "LH")]
    sl_points = [s for s in recent_swings if s.type in ("SL", "HL", "LL")]
    
    if not sh_points or not sl_points:
        return breaks
    
    last_sh = sh_points[-1]
    last_sl = sl_points[-1]
    
    # Mevcut trend: HH+HL varsa bullish, LH+LL varsa bearish
    hh_count = sum(1 for s in recent_swings if s.type == "HH")
    hl_count = sum(1 for s in recent_swings if s.type == "HL")
    lh_count = sum(1 for s in recent_swings if s.type == "LH")
    ll_count = sum(1 for s in recent_swings if s.type == "LL")
    
    current_trend = "BULLISH" if (hh_count + hl_count) > (lh_count + ll_count) else "BEARISH"
    
    # Son N mum içinde kırılma kontrolü
    check_candles = min(10, n)
    recent_closes = closes[-check_candles:]
    
    max_recent = float(np.max(recent_closes))
    min_recent = float(np.min(recent_closes))
    
    # BOS Bullish: Bearish trendde last SH kırılırsa → trend dönüşü / güçlü devam
    if max_recent > last_sh.price and last_sh.candle_idx < n - check_candles:
        break_type = "BOS_BULLISH" if current_trend == "BULLISH" else "CHOCH_BULLISH"
        breaks.append(StructureBreak(
            type=break_type,
            price=last_sh.price,
            candle_idx=n - 1,
            swing_ref=last_sh.price,
        ))
    
    # BOS Bearish: Bullish trendde last SL kırılırsa → trend dönüşü / güçlü devam
    if min_recent < last_sl.price and last_sl.candle_idx < n - check_candles:
        break_type = "BOS_BEARISH" if current_trend == "BEARISH" else "CHOCH_BEARISH"
        breaks.append(StructureBreak(
            type=break_type,
            price=last_sl.price,
            candle_idx=n - 1,
            swing_ref=last_sl.price,
        ))
    
    return breaks


def analyze_market_structure(df: pd.DataFrame, swing_lookback: int = 5) -> dict:
    """
    Tam market structure analizi.
    
    Returns:
        dict: trend, bos_detected, choch_detected, structure_breaks,
              last_hh, last_hl, last_lh, last_ll, score_boost, signal, summary
    """
    if df is None or len(df) < 30:
        return _empty_structure()
    
    try:
        swings = detect_swing_points(df, lookback=swing_lookback)
        swings = classify_swing_structure(swings)
        breaks = detect_structure_breaks(df, swings)
        
        # Swing sınıflandırma sayısı
        hh = [s for s in swings if s.type == "HH"]
        hl = [s for s in swings if s.type == "HL"]
        lh = [s for s in swings if s.type == "LH"]
        ll = [s for s in swings if s.type == "LL"]
        
        # Trend
        bull_score = len(hh) + len(hl)
        bear_score = len(lh) + len(ll)
        
        if bull_score > bear_score * 1.5:
            trend = "BULLISH"
        elif bear_score > bull_score * 1.5:
            trend = "BEARISH"
        else:
            trend = "RANGING"
        
        # BOS/CHoCH tespiti
        bos_bullish = [b for b in breaks if b.type == "BOS_BULLISH"]
        bos_bearish = [b for b in breaks if b.type == "BOS_BEARISH"]
        choch_bullish = [b for b in breaks if b.type == "CHOCH_BULLISH"]
        choch_bearish = [b for b in breaks if b.type == "CHOCH_BEARISH"]
        
        bos_detected = bool(bos_bullish or bos_bearish)
        choch_detected = bool(choch_bullish or choch_bearish)
        
        # Signal
        signal = "NEUTRAL"
        score_boost = 0
        
        if choch_bullish:
            signal = "STRONG_BUY"  # CHoCH → beklenen trend dönüşü
            score_boost = 15
        elif bos_bullish and trend == "BULLISH":
            signal = "BUY"
            score_boost = 10
        elif choch_bearish:
            signal = "STRONG_SELL"
            score_boost = -15
        elif bos_bearish and trend == "BEARISH":
            signal = "SELL"
            score_boost = -10
        
        # Summary text
        breaklines = []
        for b in breaks[-3:]:
            breaklines.append(f"  • {b.type} @ {b.price:.4f}")
        summary = f"Trend: {trend} | BOS: {'✅' if bos_detected else '❌'} | CHoCH: {'✅' if choch_detected else '❌'}"
        
        return {
            "trend": trend,
            "bull_score": bull_score,
            "bear_score": bear_score,
            "hh_count": len(hh),
            "hl_count": len(hl),
            "lh_count": len(lh),
            "ll_count": len(ll),
            "bos_detected": bos_detected,
            "choch_detected": choch_detected,
            "bos_bullish": bool(bos_bullish),
            "bos_bearish": bool(bos_bearish),
            "choch_bullish": bool(choch_bullish),
            "choch_bearish": bool(choch_bearish),
            "structure_breaks": [b.type for b in breaks],
            "signal": signal,
            "score_boost": score_boost,
            "summary": summary,
            "swing_count": len(swings),
        }
    
    except Exception as e:
        logger.error(f"Market structure analiz hatası: {e}")
        return _empty_structure()


def _empty_structure() -> dict:
    return {
        "trend": "UNKNOWN",
        "bull_score": 0, "bear_score": 0,
        "hh_count": 0, "hl_count": 0, "lh_count": 0, "ll_count": 0,
        "bos_detected": False, "choch_detected": False,
        "bos_bullish": False, "bos_bearish": False,
        "choch_bullish": False, "choch_bearish": False,
        "structure_breaks": [],
        "signal": "NEUTRAL",
        "score_boost": 0,
        "summary": "Analiz mevcut değil",
        "swing_count": 0,
    }
