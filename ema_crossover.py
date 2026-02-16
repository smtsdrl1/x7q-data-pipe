"""
EMA Crossover Stratejisi
Üçlü EMA sıralaması ile trend takibi.
"""

import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal, SignalType
from config import EMA_WEIGHT


class EMACrossoverStrategy(BaseStrategy):
    """EMA(9/21/55) crossover stratejisi."""

    def __init__(self):
        super().__init__(name="EMA Crossover", weight=EMA_WEIGHT)

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        required = ["ema_fast", "ema_mid", "ema_slow"]
        if not all(c in df.columns for c in required) or len(df) < 60:
            return self._neutral_signal(symbol, df["close"].iloc[-1])

        price = df["close"].iloc[-1]
        ema_fast = df["ema_fast"].iloc[-1]
        ema_mid = df["ema_mid"].iloc[-1]
        ema_slow = df["ema_slow"].iloc[-1]

        ema_fast_prev = df["ema_fast"].iloc[-2]
        ema_mid_prev = df["ema_mid"].iloc[-2]

        # Güçlü uptrend: EMA9 > EMA21 > EMA55
        if ema_fast > ema_mid > ema_slow:
            # Golden cross - EMA fast az önce mid'i yukarı kesti
            if ema_fast_prev <= ema_mid_prev and ema_fast > ema_mid:
                return Signal(
                    signal_type=SignalType.BUY,
                    strength=0.85,
                    strategy_name=self.name,
                    symbol=symbol,
                    price=price,
                    reason="EMA Golden Cross (9 > 21 > 55)",
                    metadata={
                        "ema_fast": ema_fast,
                        "ema_mid": ema_mid,
                        "ema_slow": ema_slow,
                    },
                )
            # Zaten trendde
            return Signal(
                signal_type=SignalType.BUY,
                strength=0.60,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason="Uptrend devam (9 > 21 > 55)",
                metadata={"ema_alignment": "bullish"},
            )

        # Güçlü downtrend: EMA9 < EMA21 < EMA55
        if ema_fast < ema_mid < ema_slow:
            # Death cross
            if ema_fast_prev >= ema_mid_prev and ema_fast < ema_mid:
                return Signal(
                    signal_type=SignalType.SELL,
                    strength=0.85,
                    strategy_name=self.name,
                    symbol=symbol,
                    price=price,
                    reason="EMA Death Cross (9 < 21 < 55)",
                    metadata={
                        "ema_fast": ema_fast,
                        "ema_mid": ema_mid,
                        "ema_slow": ema_slow,
                    },
                )
            return Signal(
                signal_type=SignalType.SELL,
                strength=0.60,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason="Downtrend devam (9 < 21 < 55)",
                metadata={"ema_alignment": "bearish"},
            )

        # EMA fast crossover (sadece fast ve mid arasında)
        if ema_fast_prev <= ema_mid_prev and ema_fast > ema_mid:
            return Signal(
                signal_type=SignalType.BUY,
                strength=0.65,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"EMA9/21 bullish cross",
            )

        if ema_fast_prev >= ema_mid_prev and ema_fast < ema_mid:
            return Signal(
                signal_type=SignalType.SELL,
                strength=0.65,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"EMA9/21 bearish cross",
            )

        # Fiyat EMA'ların altında pull-back sonrası dönüş
        if price > ema_fast and ema_fast > ema_mid:
            prev_price = df["close"].iloc[-3]
            if prev_price < ema_fast:
                return Signal(
                    signal_type=SignalType.BUY,
                    strength=0.60,
                    strategy_name=self.name,
                    symbol=symbol,
                    price=price,
                    reason="EMA pull-back dönüşü",
                )

        return self._neutral_signal(symbol, price)
