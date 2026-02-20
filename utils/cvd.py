"""
Cumulative Volume Delta (CVD) - Alım/Satım Baskısı Analizi
Buy pressure (yeşil mum hacmi) - sell pressure (kırmızı mum hacmi) birikimi.
CVD yükseliyorsa alım baskısı dominant → bullish confirmation.
CVD düşüyorsa satış baskısı dominant → bearish confirmation.
"""

import pandas as pd
import numpy as np
from utils.logger import setup_logger

logger = setup_logger("CVD")


def calculate_cvd(df: pd.DataFrame, lookback: int = 50) -> dict:
    """
    Cumulative Volume Delta hesapla.
    
    Args:
        df: OHLCV DataFrame (open, high, low, close, volume gerekli)
        lookback: Son N mum için hesaplama penceresi
    
    Returns:
        dict: cvd_value, cvd_delta, cvd_trend, buy_pressure, sell_pressure,
              cvd_divergence, signal_strength
    """
    if df is None or len(df) < max(lookback, 10):
        return _empty_cvd()

    try:
        df = df.tail(lookback).copy()
        
        # Her mum için alım/satım baskısı tahmini
        # Method: Yükselen mum → hacmin tamamı alım; düşen mum → hacmin tamamı satım
        # Mid candle: (close - low) / (high - low) oranında alım
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        opens = df["open"].values
        volumes = df["volume"].values

        buy_volumes = np.zeros(len(df))
        sell_volumes = np.zeros(len(df))

        for i in range(len(df)):
            h, l, c, o, v = highs[i], lows[i], closes[i], opens[i], volumes[i]
            hl_range = h - l
            if hl_range <= 0:
                buy_volumes[i] = v / 2
                sell_volumes[i] = v / 2
                continue
            
            # Bullish candle: close > open
            if c >= o:
                # Alım oranı: (close - low) / (high - low)
                buy_ratio = (c - l) / hl_range
            else:
                # Bearish candle: close < open
                # Satış oranı: (high - close) / (high - low)
                buy_ratio = (c - l) / hl_range  # Yine de alım baskısı hesapla
            
            buy_volumes[i] = v * buy_ratio
            sell_volumes[i] = v * (1 - buy_ratio)

        # Volume delta (her mum)
        delta = buy_volumes - sell_volumes
        
        # Cumulative Volume Delta
        cvd = np.cumsum(delta)
        
        # Son değer
        current_cvd = float(cvd[-1])
        prev_cvd = float(cvd[-2]) if len(cvd) > 1 else current_cvd
        cvd_delta = current_cvd - prev_cvd
        
        # Trend: son 10 bar CVD eğimi
        if len(cvd) >= 10:
            recent_cvd = cvd[-10:]
            slope = float(np.polyfit(range(10), recent_cvd, 1)[0])
            cvd_trend = "UP" if slope > 0 else "DOWN" if slope < 0 else "FLAT"
        else:
            cvd_trend = "FLAT"
            slope = 0.0
        
        # Toplam alım/satım baskısı
        total_buy = float(np.sum(buy_volumes))
        total_sell = float(np.sum(sell_volumes))
        total_vol = total_buy + total_sell
        buy_pressure_pct = (total_buy / total_vol * 100) if total_vol > 0 else 50.0
        sell_pressure_pct = 100.0 - buy_pressure_pct
        
        # Fiyat ile CVD divergence kontrolü
        price_change = closes[-1] - closes[0]
        cvd_change = current_cvd  # CVD kümülatif sıfırdan başlıyor
        
        divergence = "NONE"
        if price_change > 0 and cvd_change < 0:
            divergence = "BEARISH"  # Fiyat yüksek, CVD düşük → zayıf yükseliş
        elif price_change < 0 and cvd_change > 0:
            divergence = "BULLISH"  # Fiyat düşük, CVD yüksek → zayıf düşüş
        
        # Sinyal gücü (0-100)
        if total_vol > 0:
            signal_strength = abs(buy_pressure_pct - 50) * 2  # 0-100 scale
        else:
            signal_strength = 0.0
        
        # Trend ile uyumlu CVD signal
        price_trend_up = closes[-1] > closes[-5] if len(closes) >= 5 else None
        
        if cvd_trend == "UP" and price_trend_up:
            cvd_signal = "BULLISH_CONFIRM"
        elif cvd_trend == "DOWN" and not price_trend_up:
            cvd_signal = "BEARISH_CONFIRM"
        elif divergence != "NONE":
            cvd_signal = f"{divergence}_DIVERGENCE"
        else:
            cvd_signal = "NEUTRAL"
        
        return {
            "cvd_value": current_cvd,
            "cvd_delta": cvd_delta,
            "cvd_trend": cvd_trend,
            "cvd_slope": slope,
            "buy_pressure": buy_pressure_pct,
            "sell_pressure": sell_pressure_pct,
            "cvd_divergence": divergence,
            "cvd_signal": cvd_signal,
            "signal_strength": min(signal_strength, 100.0),
            "total_buy_vol": total_buy,
            "total_sell_vol": total_sell,
        }

    except Exception as e:
        logger.error(f"CVD hesaplama hatası: {e}")
        return _empty_cvd()


def _empty_cvd() -> dict:
    return {
        "cvd_value": 0.0,
        "cvd_delta": 0.0,
        "cvd_trend": "FLAT",
        "cvd_slope": 0.0,
        "buy_pressure": 50.0,
        "sell_pressure": 50.0,
        "cvd_divergence": "NONE",
        "cvd_signal": "NEUTRAL",
        "signal_strength": 0.0,
        "total_buy_vol": 0.0,
        "total_sell_vol": 0.0,
    }


def get_cvd_score_boost(cvd_data: dict, signal_side: str) -> float:
    """
    CVD verilerine göre sinyal skoru katkısı hesapla.
    
    Args:
        cvd_data: calculate_cvd() çıktısı
        signal_side: "buy" veya "sell"
    
    Returns:
        float: -10 ile +10 arasında skor katkısı
    """
    signal = cvd_data.get("cvd_signal", "NEUTRAL")
    strength = cvd_data.get("signal_strength", 0)
    buy_pressure = cvd_data.get("buy_pressure", 50)
    
    boost = 0.0
    
    if signal_side == "buy":
        if signal == "BULLISH_CONFIRM":
            boost = +8.0 * (strength / 100)
        elif signal == "BEARISH_CONFIRM":
            boost = -6.0 * (strength / 100)
        elif signal == "BULLISH_DIVERGENCE":
            boost = +5.0
        elif signal == "BEARISH_DIVERGENCE":
            boost = -4.0
        # Alım baskısı > %60 ise bonus
        if buy_pressure > 60:
            boost += 2.0
        elif buy_pressure < 40:
            boost -= 2.0
    
    elif signal_side == "sell":
        if signal == "BEARISH_CONFIRM":
            boost = +8.0 * (strength / 100)
        elif signal == "BULLISH_CONFIRM":
            boost = -6.0 * (strength / 100)
        elif signal == "BEARISH_DIVERGENCE":
            boost = +5.0
        elif signal == "BULLISH_DIVERGENCE":
            boost = -4.0
        # Satış baskısı > %60 ise bonus
        if buy_pressure < 40:
            boost += 2.0
        elif buy_pressure > 60:
            boost -= 2.0
    
    return round(max(-10.0, min(10.0, boost)), 2)
