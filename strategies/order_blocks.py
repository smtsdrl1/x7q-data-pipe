"""
Order Block Detection Strategy
ICT Order Block kavramı: Büyük kurumsal alım/satım öncesindeki son karşı mum.

- Bullish Order Block: Büyük yükselişten önceki son kırmızı mum (bearish candle)
  → Bu seviyeye geri dönünce güçlü alım beklenir
- Bearish Order Block: Büyük düşüşten önceki son yeşil mum (bullish candle)
  → Bu seviyeye yükselince güçlü satım beklenir

FVG+Fib ile birleşince: Tam ICT sniper entry sistemi
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from utils.logger import setup_logger
from strategies.base_strategy import BaseStrategy, Signal, SignalType
import config

logger = setup_logger("OrderBlock")


@dataclass
class OrderBlock:
    """Tek bir order block."""
    type: str          # BULLISH / BEARISH
    high: float
    low: float
    mid: float
    candle_idx: int
    strength: float    # 0-1 (üstüne ne kadar hareket oldu)
    mitigated: bool    # Zaten test edilip geçildi mi?
    impulse_pct: float # Ardından gelen hareketin büyüklüğü


def detect_order_blocks(df: pd.DataFrame, lookback: int = 50,
                         min_impulse_pct: float = 0.5) -> list[OrderBlock]:
    """
    Order block'ları tespit et.
    
    Args:
        df: OHLCV DataFrame
        lookback: Geriye bak mesafesi
        min_impulse_pct: Minimum impulse hareketi (%0.5)
    
    Returns:
        list[OrderBlock]: Aktif (mitigate edilmemiş) order block'lar
    """
    if df is None or len(df) < 10:
        return []
    
    df = df.tail(lookback).copy().reset_index(drop=True)
    n = len(df)
    
    opens = df["open"].values
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    
    order_blocks = []
    
    for i in range(1, n - 2):
        is_bearish = closes[i] < opens[i]  # Kırmızı mum
        is_bullish = closes[i] > opens[i]  # Yeşil mum
        
        # Bullish Order Block: kırmızı mum + sonrasında büyük yükseliş
        if is_bearish:
            # Sonraki 3 mumdaki maksimum yükseliş
            future_highs = highs[i+1:min(i+4, n)]
            future_closes = closes[i+1:min(i+4, n)]
            
            if len(future_highs) > 0:
                max_future_high = float(np.max(future_highs))
                impulse = (max_future_high - closes[i]) / closes[i] * 100
                
                if impulse >= min_impulse_pct:
                    ob_high = highs[i]
                    ob_low = lows[i]
                    ob_mid = (ob_high + ob_low) / 2
                    
                    # Mitigasyon kontrolü: fiyat bu seviyeye geri döndü mü?
                    future_lows_after = lows[i+1:]
                    mitigated = any(l <= ob_high for l in future_lows_after)
                    
                    order_blocks.append(OrderBlock(
                        type="BULLISH",
                        high=ob_high,
                        low=ob_low,
                        mid=ob_mid,
                        candle_idx=i,
                        strength=min(impulse / 3.0, 1.0),  # 3% = max strength
                        mitigated=mitigated,
                        impulse_pct=impulse,
                    ))
        
        # Bearish Order Block: yeşil mum + sonrasında büyük düşüş
        elif is_bullish:
            future_lows = lows[i+1:min(i+4, n)]
            
            if len(future_lows) > 0:
                min_future_low = float(np.min(future_lows))
                impulse = (closes[i] - min_future_low) / closes[i] * 100
                
                if impulse >= min_impulse_pct:
                    ob_high = highs[i]
                    ob_low = lows[i]
                    ob_mid = (ob_high + ob_low) / 2
                    
                    # Mitigasyon: fiyat bu seviyeye geri çıktı mı?
                    future_highs_after = highs[i+1:]
                    mitigated = any(h >= ob_low for h in future_highs_after)
                    
                    order_blocks.append(OrderBlock(
                        type="BEARISH",
                        high=ob_high,
                        low=ob_low,
                        mid=ob_mid,
                        candle_idx=i,
                        strength=min(impulse / 3.0, 1.0),
                        mitigated=mitigated,
                        impulse_pct=impulse,
                    ))
    
    # Sadece aktif (mitigate edilmemiş) OB'lar
    active_obs = [ob for ob in order_blocks if not ob.mitigated]
    
    # En son ve en güçlü 5 OB
    active_obs.sort(key=lambda x: (x.candle_idx, x.strength), reverse=True)
    return active_obs[:5]


def check_order_block_touch(price: float, order_blocks: list[OrderBlock],
                             tolerance: float = 0.003) -> dict:
    """
    Mevcut fiyat bir order block'a değiyor mu?
    
    Args:
        price: Mevcut fiyat
        order_blocks: detect_order_blocks() çıktısı
        tolerance: Fiyat toleransı (%0.3)
    
    Returns:
        dict: touching, ob_type, ob_strength, score_boost
    """
    best_ob = None
    best_score = 0
    
    for ob in order_blocks:
        tol_range = ob.high * tolerance
        
        # Fiyat OB aralığında mı?
        in_range = (ob.low - tol_range) <= price <= (ob.high + tol_range)
        
        if in_range:
            score = ob.strength * 12  # Max 12 puan
            if score > best_score:
                best_score = score
                best_ob = ob
    
    if best_ob:
        return {
            "touching": True,
            "ob_type": best_ob.type,
            "ob_high": best_ob.high,
            "ob_low": best_ob.low,
            "ob_strength": best_ob.strength,
            "impulse_pct": best_ob.impulse_pct,
            "score_boost": round(best_score, 1),
        }
    
    return {"touching": False, "ob_type": None, "score_boost": 0}


class OrderBlockStrategy(BaseStrategy):
    """Order Block tabanlı strateji."""
    
    def __init__(self):
        super().__init__("order_block", weight=getattr(config, "ORDER_BLOCK_WEIGHT", 0.20))
    
    def analyze(self, df: pd.DataFrame, symbol: str = "") -> Signal:
        """Order block sinyali üret."""
        price = float(df["close"].iloc[-1]) if df is not None and len(df) > 0 else 0.0
        if df is None or len(df) < 20:
            return Signal(SignalType.NEUTRAL, 0.0, self.name, symbol, price, "Yetersiz veri")
        
        try:
            current_price = float(df["close"].iloc[-1])
            order_blocks = detect_order_blocks(df)
            
            if not order_blocks:
                return Signal(SignalType.NEUTRAL, 0.0, self.name, symbol, current_price, "Order block yok")
            
            ob_touch = check_order_block_touch(current_price, order_blocks)
            
            if not ob_touch["touching"]:
                return Signal(SignalType.NEUTRAL, 0.0, self.name, symbol, current_price, "OB dokunması yok")
            
            ob_type = ob_touch["ob_type"]
            strength = ob_touch["ob_strength"]
            
            # Güçlü OB = strength > 0.7
            if ob_type == "BULLISH" and strength > 0.3:
                signal_type = SignalType.BUY
                strength_val = 0.55 + strength * 0.3  # 0.55 - 0.85
                reason = f"Bullish OB @ {ob_touch['ob_low']:.4f}-{ob_touch['ob_high']:.4f} ({ob_touch['impulse_pct']:.1f}%)"
            elif ob_type == "BEARISH" and strength > 0.3:
                signal_type = SignalType.SELL
                strength_val = 0.55 + strength * 0.3
                reason = f"Bearish OB @ {ob_touch['ob_low']:.4f}-{ob_touch['ob_high']:.4f} ({ob_touch['impulse_pct']:.1f}%)"
            else:
                return Signal(SignalType.NEUTRAL, 0.0, self.name, symbol, current_price, f"Zayıf OB ({strength:.2f})")
            
            return Signal(
                signal_type=signal_type,
                strength=round(min(strength_val, 0.90), 3),
                strategy_name=self.name,
                symbol=symbol,
                price=current_price,
                reason=reason,
                metadata={"score_boost": ob_touch["score_boost"]},
            )
        
        except Exception as e:
            logger.error(f"Order block analiz hatası: {e}")
            return Signal(SignalType.NEUTRAL, 0.0, self.name, symbol, price, "Hata")
