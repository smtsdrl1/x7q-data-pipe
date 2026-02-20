"""
Liquidity Sweep (Stop Hunt) Detection Strategy
Büyük oyuncular (smart money) küçük yatırımcıların stop-loss emirlerini
toplayarak fiyatı yanlış yöne sürer, sonra asıl yöne hareket eder.

Sweep Türleri:
- Bullish Sweep (Swept Lows): Önceki swing low kırılıyor → hızla yukarı döner
  → Aslında short stop'ları toplanıp long pozisyon açılıyor
- Bearish Sweep (Swept Highs): Önceki swing high kırılıyor → hızla aşağı döner
  → Aslında long stop'ları toplanıp short pozisyon açılıyor

ICT terminolojisi: 
- Sweep önceki equal lows (EQL) veya previous day low'ları hedef alır
- Sweep + FVG/OB = sniper entry point
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from utils.logger import setup_logger
from strategies.base_strategy import BaseStrategy, Signal, SignalType
import config

logger = setup_logger("LiquiditySweep")


@dataclass
class LiquiditySweep:
    """Tespit edilen sweep olayı."""
    type: str           # BULLISH_SWEEP / BEARISH_SWEEP
    sweep_low: float    # Kırılan seviye
    sweep_high: float
    candle_idx: int
    recovery_pct: float  # Ne kadar hızlı geri döndü
    confirmed: bool      # Sweep doğrulandı mı (close geri döndü)


def detect_equal_levels(df: pd.DataFrame, lookback: int = 30,
                          tolerance: float = 0.002) -> dict:
    """
    Equal highs ve equal lows tespit et (likidite birikimi bölgeleri).
    
    Returns:
        dict: equal_highs: [(price, count)], equal_lows: [(price, count)]
    """
    if len(df) < 10:
        return {"equal_highs": [], "equal_lows": []}
    
    df_slice = df.tail(lookback)
    highs = df_slice["high"].values
    lows = df_slice["low"].values
    
    # Equal highs: birbirine yakın high seviyeleri
    equal_highs = []
    equal_lows = []
    
    for i, h in enumerate(highs):
        count = sum(1 for h2 in highs if abs(h - h2) / h < tolerance)
        if count >= 2:
            equal_highs.append((h, count))
    
    for i, l in enumerate(lows):
        count = sum(1 for l2 in lows if abs(l - l2) / l < tolerance)
        if count >= 2:
            equal_lows.append((l, count))
    
    # Duplikasyon temizle
    unique_highs = []
    seen_h = set()
    for h, c in sorted(equal_highs, key=lambda x: x[1], reverse=True):
        rounded = round(h, 4)
        if rounded not in seen_h:
            seen_h.add(rounded)
            unique_highs.append((h, c))
    
    unique_lows = []
    seen_l = set()
    for l, c in sorted(equal_lows, key=lambda x: x[1], reverse=True):
        rounded = round(l, 4)
        if rounded not in seen_l:
            seen_l.add(rounded)
            unique_lows.append((l, c))
    
    return {
        "equal_highs": unique_highs[:3],
        "equal_lows": unique_lows[:3],
    }


def detect_liquidity_sweeps(df: pd.DataFrame, lookback: int = 50,
                              min_recovery_pct: float = 0.3) -> list[LiquiditySweep]:
    """
    Son N mumda liquidity sweep ol tespiti.
    
    Sweep tespiti:
    1. Önceki swing low kırılıyor (lower low oluşuyor)
    2. AYNI veya SONRAKİ mumda close geri yukarı kapanıyor
    3. = Sweep + reversal = bullish signal
    
    Args:
        df: OHLCV DataFrame
        lookback: Tarama penceresi
        min_recovery_pct: Minimum geri dönme yüzdesi (mesafeye göre)
    
    Returns:
        list[LiquiditySweep]: Tespit edilen sweep'ler
    """
    if df is None or len(df) < 15:
        return []
    
    df = df.tail(lookback).copy().reset_index(drop=True)
    n = len(df)
    
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    opens = df["open"].values
    
    sweeps = []
    
    # Rolling min/max (önceki swing seviyeleri)
    window = 10
    
    for i in range(window, n - 1):
        prev_highs = highs[max(0, i-window):i]
        prev_lows = lows[max(0, i-window):i]
        
        recent_high = float(np.max(prev_highs))
        recent_low = float(np.min(prev_lows))
        
        current_low = lows[i]
        current_high = highs[i]
        current_close = closes[i]
        
        # Bullish Sweep: önceki low kırılıyor ama close geri geliyor
        if current_low < recent_low and current_close > recent_low:
            # Sweep derinliği
            sweep_depth = recent_low - current_low
            recovery = current_close - current_low
            
            if sweep_depth > 0:
                recovery_pct = recovery / sweep_depth
                
                if recovery_pct >= min_recovery_pct:
                    sweeps.append(LiquiditySweep(
                        type="BULLISH_SWEEP",
                        sweep_low=current_low,
                        sweep_high=recent_high,
                        candle_idx=i,
                        recovery_pct=recovery_pct,
                        confirmed=current_close > recent_low,
                    ))
        
        # Bearish Sweep: önceki high kırılıyor ama close geri geliyor
        elif current_high > recent_high and current_close < recent_high:
            sweep_height = current_high - recent_high
            recovery = current_high - current_close
            
            if sweep_height > 0:
                recovery_pct = recovery / sweep_height
                
                if recovery_pct >= min_recovery_pct:
                    sweeps.append(LiquiditySweep(
                        type="BEARISH_SWEEP",
                        sweep_low=recent_low,
                        sweep_high=current_high,
                        candle_idx=i,
                        recovery_pct=recovery_pct,
                        confirmed=current_close < recent_high,
                    ))
    
    # Son 3 sweep
    sweeps.sort(key=lambda x: x.candle_idx, reverse=True)
    return sweeps[:3]


def get_sweep_signal(sweeps: list[LiquiditySweep], recency_threshold: int = 5) -> dict:
    """
    Son sweep'lere göre sinyal üret.
    
    Args:
        sweeps: detect_liquidity_sweeps() çıktısı
        recency_threshold: Bu kadar mum öncesine kadar olan sweep geçerli
    
    Returns:
        dict: signal, score_boost, sweep_type, recovery_pct
    """
    if not sweeps:
        return {"signal": "NEUTRAL", "score_boost": 0, "sweep_type": None}
    
    # En son sweep
    latest = sweeps[0]
    
    # Yeterince yeni mi?
    # (candle_idx relative - lookback'in son elemanı)
    # Genellikle son 3-5 mum içindeyse geçerli
    # Basit yaklaşım: sadece son 3 sweep'ten birincisine bak
    
    if latest.type == "BULLISH_SWEEP" and latest.confirmed:
        boost = 10 + latest.recovery_pct * 5  # Max ~15
        return {
            "signal": "BUY",
            "score_boost": min(round(boost, 1), 15),
            "sweep_type": "BULLISH_SWEEP",
            "recovery_pct": latest.recovery_pct,
            "sweep_low": latest.sweep_low,
        }
    
    elif latest.type == "BEARISH_SWEEP" and latest.confirmed:
        boost = 10 + latest.recovery_pct * 5
        return {
            "signal": "SELL",
            "score_boost": min(round(boost, 1), 15),
            "sweep_type": "BEARISH_SWEEP",
            "recovery_pct": latest.recovery_pct,
            "sweep_high": latest.sweep_high,
        }
    
    return {"signal": "NEUTRAL", "score_boost": 0, "sweep_type": None}


class LiquiditySweepStrategy(BaseStrategy):
    """Liquidity Sweep (Stop Hunt) tabanlı strateji."""
    
    def __init__(self):
        super().__init__("liquidity_sweep", weight=getattr(config, "LIQUIDITY_SWEEP_WEIGHT", 0.20))
    
    def analyze(self, df: pd.DataFrame, symbol: str = "") -> Signal:
        """Sweep sinyali üret."""
        price = float(df["close"].iloc[-1]) if df is not None and len(df) > 0 else 0.0
        if df is None or len(df) < 20:
            return Signal(SignalType.NEUTRAL, 0.0, self.name, symbol, price, "Yetersiz veri")
        
        try:
            current_price = float(df["close"].iloc[-1])
            sweeps = detect_liquidity_sweeps(df)
            
            if not sweeps:
                return Signal(SignalType.NEUTRAL, 0.0, self.name, symbol, current_price, "Sweep tespit edilmedi")
            
            sweep_data = get_sweep_signal(sweeps)
            
            if sweep_data["signal"] == "BUY":
                strength = 0.60 + sweep_data["recovery_pct"] * 0.20
                reason = (
                    f"Bullish Sweep | Recovery: {sweep_data['recovery_pct']:.0%} | "
                    f"Low: {sweep_data.get('sweep_low', 0):.4f}"
                )
                return Signal(
                    signal_type=SignalType.BUY,
                    strength=round(min(strength, 0.90), 3),
                    strategy_name=self.name,
                    symbol=symbol,
                    price=current_price,
                    reason=reason,
                    metadata={"score_boost": sweep_data["score_boost"]},
                )
            
            elif sweep_data["signal"] == "SELL":
                strength = 0.60 + sweep_data["recovery_pct"] * 0.20
                reason = (
                    f"Bearish Sweep | Recovery: {sweep_data['recovery_pct']:.0%} | "
                    f"High: {sweep_data.get('sweep_high', 0):.4f}"
                )
                return Signal(
                    signal_type=SignalType.SELL,
                    strength=round(min(strength, 0.90), 3),
                    strategy_name=self.name,
                    symbol=symbol,
                    price=current_price,
                    reason=reason,
                    metadata={"score_boost": sweep_data["score_boost"]},
                )
            
            return Signal(SignalType.NEUTRAL, 0.0, self.name, symbol, current_price, "Sweep net değil")
        
        except Exception as e:
            logger.error(f"Sweep analiz hatası: {e}")
            return Signal(SignalType.NEUTRAL, 0.0, self.name, symbol, price, "Hata")
