"""
SuperTrend Stratejisi
ATR tabanlı trend takip stratejisi.
"""

import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal, SignalType
from config import SUPERTREND_WEIGHT


class SuperTrendStrategy(BaseStrategy):
    """SuperTrend trend-following stratejisi."""

    def __init__(self):
        super().__init__(name="SuperTrend", weight=SUPERTREND_WEIGHT)

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        required = ["supertrend", "supertrend_dir"]
        if not all(c in df.columns for c in required) or len(df) < 15:
            return self._neutral_signal(symbol, df["close"].iloc[-1])

        price = df["close"].iloc[-1]
        direction = df["supertrend_dir"].iloc[-1]
        prev_direction = df["supertrend_dir"].iloc[-2]
        supertrend_val = df["supertrend"].iloc[-1]

        # Trend değişimi: Bearish → Bullish
        if prev_direction == -1 and direction == 1:
            return Signal(
                signal_type=SignalType.BUY,
                strength=0.80,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"SuperTrend bullish dönüş (ST: {supertrend_val:.6f})",
                metadata={"supertrend": supertrend_val, "direction": direction},
            )

        # Trend değişimi: Bullish → Bearish
        if prev_direction == 1 and direction == -1:
            return Signal(
                signal_type=SignalType.SELL,
                strength=0.80,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"SuperTrend bearish dönüş (ST: {supertrend_val:.6f})",
                metadata={"supertrend": supertrend_val, "direction": direction},
            )

        # Mevcut trend devamı
        if direction == 1:
            # Fiyat supertrend'e yakınsa güçlü destek
            distance = (price - supertrend_val) / price
            if distance < 0.01:  # %1'den yakın
                return Signal(
                    signal_type=SignalType.BUY,
                    strength=0.65,
                    strategy_name=self.name,
                    symbol=symbol,
                    price=price,
                    reason="SuperTrend desteğine yakın",
                    metadata={"distance": distance},
                )

        if direction == -1:
            distance = (supertrend_val - price) / price
            if distance < 0.01:
                return Signal(
                    signal_type=SignalType.SELL,
                    strength=0.65,
                    strategy_name=self.name,
                    symbol=symbol,
                    price=price,
                    reason="SuperTrend direncine yakın",
                    metadata={"distance": distance},
                )

        return self._neutral_signal(symbol, price)
