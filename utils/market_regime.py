"""
Market Regime Detector
Piyasanın mevcut durumunu (trending/ranging/volatile/quiet) tespit eder.
Farklı piyasa rejimlerinde farklı stratejiler çalışır:
- TRENDING: EMA cross, momentum, FVG+Fib iyi çalışır
- RANGING: RSI, Bollinger Bands iyi çalışır
- VOLATILE: Pozisyon boyutunu küçült, daha geniş SL/TP
- QUIET: Sinyal üretme, spread yüksek
"""

import numpy as np
import pandas as pd
from utils.logger import setup_logger

logger = setup_logger("MarketRegime")


class MarketRegimeDetector:
    """Piyasa rejimini ATR, ADX, volatilite ve trend analiziyle tespit eder."""
    
    def __init__(self):
        self._cache: dict[str, tuple[dict, int]] = {}  # symbol → (regime, candle_idx)
    
    def detect(self, df: pd.DataFrame, symbol: str = "") -> dict:
        """
        Mevcut piyasa rejimini tespit et.
        
        Args:
            df: OHLCV DataFrame (en az 50 mum)
            symbol: Loglama için sembol adı
        
        Returns:
            dict: regime, sub_regime, adx, atr_pct, trend_strength,
                  is_trending, is_ranging, is_volatile, multiplier, summary
        """
        if df is None or len(df) < 30:
            return self._default_regime()
        
        try:
            closes = df["close"].values.astype(float)
            highs = df["high"].values.astype(float)
            lows = df["low"].values.astype(float)
            
            # ADX hesapla (trend gücü)
            adx = self._calc_adx(highs, lows, closes, period=14)
            
            # ATR hesapla (volatilite)
            atr = self._calc_atr(highs, lows, closes, period=14)
            atr_pct = (atr / closes[-1] * 100) if closes[-1] > 0 else 0
            
            # Lineer regresyon: eğim = trend gücü
            x = np.arange(min(20, len(closes)))
            y = closes[-len(x):]
            slope, _ = np.polyfit(x, y, 1)
            trend_pct = abs(slope / closes[-1] * 100) if closes[-1] > 0 else 0
            
            # Bollinger Band genişliği (ranging tespiti)
            bb_period = 20
            if len(closes) >= bb_period:
                sma = np.mean(closes[-bb_period:])
                std = np.std(closes[-bb_period:])
                bb_width_pct = (std * 2 / sma * 100) if sma > 0 else 0
            else:
                bb_width_pct = 0
            
            # Rejim belirleme
            is_trending  = adx > 25
            is_ranging   = adx < 20
            is_volatile  = atr_pct > 2.5
            is_quiet     = atr_pct < 0.12  # 0.5→0.12: 5m için gerçekçi eşik (~$115 ATR/BTC)
            
            if is_trending and is_volatile:
                regime = "VOLATILE_TREND"
                multiplier = 0.7  # Büyük hareketler, dikkatli ol
                sub = "Güçlü + Yüksek Volatilite → %70 pozisyon"
            elif is_trending:
                regime = "TRENDING"
                multiplier = 1.0  # Normal
                sub = "Trend sürüyor → tam pozisyon"
            elif is_volatile:
                regime = "VOLATILE"
                multiplier = 0.6  # Volatil ranging
                sub = "Yüksek volatilite → %60 pozisyon"
            elif is_quiet:
                regime = "QUIET"
                multiplier = 0.5  # Az hacim
                sub = "Düşük aktivite → sinyal üretme"
            elif is_ranging:
                regime = "RANGING"
                multiplier = 0.8  # Range
                sub = "Yatay piyasa → mean-reversion stratejileri"
            else:
                regime = "TRANSITION"
                multiplier = 0.85
                sub = "Geçiş dönemi"
            
            # Trend yönü
            slope_direction = "UP" if slope > 0 else "DOWN"
            
            return {
                "regime": regime,
                "sub_regime": sub,
                "adx": round(float(adx), 2),
                "atr": round(float(atr), 6),
                "atr_pct": round(float(atr_pct), 3),
                "trend_strength": round(float(trend_pct), 3),
                "bb_width_pct": round(float(bb_width_pct), 3),
                "slope_direction": slope_direction,
                "is_trending": is_trending,
                "is_ranging": is_ranging,
                "is_volatile": is_volatile,
                "is_quiet": is_quiet,
                "position_multiplier": multiplier,
                "summary": f"{regime} | ADX:{adx:.1f} | ATR%:{atr_pct:.2f}",
            }
        
        except Exception as e:
            logger.error(f"Market regime hatası ({symbol}): {e}")
            return self._default_regime()
    
    def _calc_adx(self, highs, lows, closes, period=14) -> float:
        """ADX (Average Directional Index) hesapla."""
        n = len(closes)
        if n < period + 1:
            return 20.0  # Default
        
        tr = np.zeros(n)
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        
        for i in range(1, n):
            hl = highs[i] - lows[i]
            hpc = abs(highs[i] - closes[i-1])
            lpc = abs(lows[i] - closes[i-1])
            tr[i] = max(hl, hpc, lpc)
            
            up = highs[i] - highs[i-1]
            down = lows[i-1] - lows[i]
            
            plus_dm[i] = up if up > down and up > 0 else 0
            minus_dm[i] = down if down > up and down > 0 else 0
        
        # Wilder smoothing
        atr_s = np.zeros(n)
        pdm_s = np.zeros(n)
        mdm_s = np.zeros(n)
        
        atr_s[period] = np.sum(tr[1:period+1])
        pdm_s[period] = np.sum(plus_dm[1:period+1])
        mdm_s[period] = np.sum(minus_dm[1:period+1])
        
        for i in range(period+1, n):
            atr_s[i] = atr_s[i-1] - atr_s[i-1]/period + tr[i]
            pdm_s[i] = pdm_s[i-1] - pdm_s[i-1]/period + plus_dm[i]
            mdm_s[i] = mdm_s[i-1] - mdm_s[i-1]/period + minus_dm[i]
        
        with np.errstate(divide="ignore", invalid="ignore"):
            pdi  = np.where(atr_s > 0, 100 * pdm_s / atr_s, 0)
            mdi  = np.where(atr_s > 0, 100 * mdm_s / atr_s, 0)
            dx   = np.where((pdi + mdi) > 0, 100 * np.abs(pdi - mdi) / (pdi + mdi), 0)
        
        # ADX = SMA of DX
        if n < period * 2:
            return float(np.mean(dx[period:]))
        
        return float(np.mean(dx[-period:]))
    
    def _calc_atr(self, highs, lows, closes, period=14) -> float:
        """ATR hesapla."""
        n = len(closes)
        if n < 2:
            return 0.0
        
        tr_values = []
        for i in range(1, n):
            hl = highs[i] - lows[i]
            hpc = abs(highs[i] - closes[i-1])
            lpc = abs(lows[i] - closes[i-1])
            tr_values.append(max(hl, hpc, lpc))
        
        if not tr_values:
            return 0.0
        return float(np.mean(tr_values[-period:]))
    
    def get_strategy_weights(self, regime: dict) -> dict:
        """
        Piyasa rejimine göre strateji ağırlıklarını döndür.
        TRENDING rejimde momentum ağırlıklı, RANGING'de mean-reversion.
        """
        r = regime.get("regime", "TRANSITION")
        
        base_weights = {
            "TRENDING": {
                "rsi": 0.10, "macd": 0.20, "bollinger": 0.10,
                "ema_crossover": 0.25, "volume": 0.15, "supertrend": 0.20,
            },
            "RANGING": {
                "rsi": 0.25, "macd": 0.15, "bollinger": 0.25,
                "ema_crossover": 0.10, "volume": 0.15, "supertrend": 0.10,
            },
            "VOLATILE_TREND": {
                "rsi": 0.10, "macd": 0.15, "bollinger": 0.15,
                "ema_crossover": 0.25, "volume": 0.20, "supertrend": 0.15,
            },
            "VOLATILE": {
                "rsi": 0.15, "macd": 0.15, "bollinger": 0.20,
                "ema_crossover": 0.15, "volume": 0.20, "supertrend": 0.15,
            },
        }
        
        return base_weights.get(r, base_weights["TRENDING"])
    
    def _default_regime(self) -> dict:
        return {
            "regime": "TRANSITION",
            "sub_regime": "Yeterli veri yok",
            "adx": 20.0, "atr": 0.0, "atr_pct": 1.0,
            "trend_strength": 0.0, "bb_width_pct": 0.0,
            "slope_direction": "FLAT",
            "is_trending": False, "is_ranging": True,
            "is_volatile": False, "is_quiet": False,
            "position_multiplier": 0.85,
            "summary": "TRANSITION | Veri yetersiz",
        }


# Singleton instance
market_regime_detector = MarketRegimeDetector()
