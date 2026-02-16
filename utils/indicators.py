"""
Teknik Göstergeler Modülü
RSI, MACD, Bollinger Bands, EMA, SuperTrend, ATR, Volume analizi
"""

import pandas as pd
import numpy as np
from config import (
    RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_PERIOD, BB_STD_DEV, EMA_FAST, EMA_MID, EMA_SLOW,
    SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER, VOLUME_MA_PERIOD
)


class TechnicalIndicators:
    """Teknik gösterge hesaplayıcı."""

    @staticmethod
    def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
        """Tüm göstergeleri hesapla ve DataFrame'e ekle."""
        df = df.copy()
        df = TechnicalIndicators.add_rsi(df)
        df = TechnicalIndicators.add_macd(df)
        df = TechnicalIndicators.add_bollinger_bands(df)
        df = TechnicalIndicators.add_ema(df)
        df = TechnicalIndicators.add_atr(df)
        df = TechnicalIndicators.add_supertrend(df)
        df = TechnicalIndicators.add_volume_indicators(df)
        df = TechnicalIndicators.add_adx(df)
        return df

    @staticmethod
    def add_rsi(df: pd.DataFrame, period: int = RSI_PERIOD) -> pd.DataFrame:
        """RSI (Relative Strength Index) hesapla - Wilder smoothing."""
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        # Wilder smoothing
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))
        return df

    @staticmethod
    def add_macd(df: pd.DataFrame, fast: int = MACD_FAST,
                 slow: int = MACD_SLOW, signal: int = MACD_SIGNAL) -> pd.DataFrame:
        """MACD hesapla."""
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
        df["macd"] = ema_fast - ema_slow
        df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
        df["macd_histogram"] = df["macd"] - df["macd_signal"]
        return df

    @staticmethod
    def add_bollinger_bands(df: pd.DataFrame, period: int = BB_PERIOD,
                            std_dev: float = BB_STD_DEV) -> pd.DataFrame:
        """Bollinger Bands hesapla."""
        sma = df["close"].rolling(window=period).mean()
        std = df["close"].rolling(window=period).std()
        df["bb_upper"] = sma + (std * std_dev)
        df["bb_middle"] = sma
        df["bb_lower"] = sma - (std * std_dev)
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]
        df["bb_pct"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
        return df

    @staticmethod
    def add_ema(df: pd.DataFrame, fast: int = EMA_FAST,
                mid: int = EMA_MID, slow: int = EMA_SLOW) -> pd.DataFrame:
        """EMA'ları hesapla."""
        df["ema_fast"] = df["close"].ewm(span=fast, adjust=False).mean()
        df["ema_mid"] = df["close"].ewm(span=mid, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=slow, adjust=False).mean()
        return df

    @staticmethod
    def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """ATR (Average True Range) hesapla."""
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = true_range.ewm(alpha=1 / period, min_periods=period).mean()
        return df

    @staticmethod
    def add_supertrend(df: pd.DataFrame, period: int = SUPERTREND_PERIOD,
                       multiplier: float = SUPERTREND_MULTIPLIER) -> pd.DataFrame:
        """SuperTrend göstergesi."""
        if "atr" not in df.columns:
            df = TechnicalIndicators.add_atr(df, period)

        hl2 = (df["high"] + df["low"]) / 2
        upper_band = hl2 + (multiplier * df["atr"])
        lower_band = hl2 - (multiplier * df["atr"])

        supertrend = pd.Series(index=df.index, dtype=float)
        direction = pd.Series(index=df.index, dtype=int)

        supertrend.iloc[0] = upper_band.iloc[0]
        direction.iloc[0] = -1

        for i in range(1, len(df)):
            if df["close"].iloc[i] > upper_band.iloc[i - 1]:
                direction.iloc[i] = 1
            elif df["close"].iloc[i] < lower_band.iloc[i - 1]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = direction.iloc[i - 1]

            if direction.iloc[i] == 1:
                supertrend.iloc[i] = lower_band.iloc[i]
                if i > 0 and direction.iloc[i - 1] == 1:
                    supertrend.iloc[i] = max(supertrend.iloc[i], supertrend.iloc[i - 1])
            else:
                supertrend.iloc[i] = upper_band.iloc[i]
                if i > 0 and direction.iloc[i - 1] == -1:
                    supertrend.iloc[i] = min(supertrend.iloc[i], supertrend.iloc[i - 1])

        df["supertrend"] = supertrend
        df["supertrend_dir"] = direction
        return df

    @staticmethod
    def add_volume_indicators(df: pd.DataFrame,
                              ma_period: int = VOLUME_MA_PERIOD) -> pd.DataFrame:
        """Volume göstergeleri."""
        df["volume_sma"] = df["volume"].rolling(window=ma_period).mean()
        df["volume_ratio"] = df["volume"] / df["volume_sma"]

        # OBV (On-Balance Volume)
        obv = pd.Series(index=df.index, dtype=float)
        obv.iloc[0] = 0
        for i in range(1, len(df)):
            if df["close"].iloc[i] > df["close"].iloc[i - 1]:
                obv.iloc[i] = obv.iloc[i - 1] + df["volume"].iloc[i]
            elif df["close"].iloc[i] < df["close"].iloc[i - 1]:
                obv.iloc[i] = obv.iloc[i - 1] - df["volume"].iloc[i]
            else:
                obv.iloc[i] = obv.iloc[i - 1]
        df["obv"] = obv
        return df

    @staticmethod
    def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """ADX (Average Directional Index) hesapla."""
        plus_dm = df["high"].diff()
        minus_dm = -df["low"].diff()

        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        if "atr" not in df.columns:
            df = TechnicalIndicators.add_atr(df, period)

        plus_di = 100 * (plus_dm.ewm(alpha=1 / period, min_periods=period).mean() /
                         df["atr"].replace(0, np.nan))
        minus_di = 100 * (minus_dm.ewm(alpha=1 / period, min_periods=period).mean() /
                          df["atr"].replace(0, np.nan))

        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        df["adx"] = dx.ewm(alpha=1 / period, min_periods=period).mean()
        df["plus_di"] = plus_di
        df["minus_di"] = minus_di
        return df
