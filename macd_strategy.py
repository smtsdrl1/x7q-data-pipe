"""
MACD Crossover Stratejisi
MACD çizgisi ve sinyal çizgisi kesişim noktalarında sinyal üretir.
"""

import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal, SignalType
from config import MACD_WEIGHT


class MACDStrategy(BaseStrategy):
    """MACD crossover ve histogram stratejisi."""

    def __init__(self):
        super().__init__(name="MACD Crossover", weight=MACD_WEIGHT)

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        required = ["macd", "macd_signal", "macd_histogram"]
        if not all(c in df.columns for c in required) or len(df) < 30:
            return self._neutral_signal(symbol, df["close"].iloc[-1])

        price = df["close"].iloc[-1]
        macd = df["macd"].iloc[-1]
        macd_prev = df["macd"].iloc[-2]
        signal_line = df["macd_signal"].iloc[-1]
        signal_prev = df["macd_signal"].iloc[-2]
        histogram = df["macd_histogram"].iloc[-1]
        histogram_prev = df["macd_histogram"].iloc[-2]

        # Bullish crossover: MACD sinyal çizgisini yukarı kesiyor
        if macd_prev <= signal_prev and macd > signal_line:
            strength = 0.70
            # Sıfır çizgisinin altında crossover daha güçlü
            if macd < 0:
                strength = 0.80
            return Signal(
                signal_type=SignalType.BUY,
                strength=strength,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"MACD bullish crossover (MACD: {macd:.6f})",
                metadata={"macd": macd, "signal": signal_line, "histogram": histogram},
            )

        # Bearish crossover: MACD sinyal çizgisini aşağı kesiyor
        if macd_prev >= signal_prev and macd < signal_line:
            strength = 0.70
            if macd > 0:
                strength = 0.80
            return Signal(
                signal_type=SignalType.SELL,
                strength=strength,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"MACD bearish crossover (MACD: {macd:.6f})",
                metadata={"macd": macd, "signal": signal_line, "histogram": histogram},
            )

        # Histogram momentum artışı
        if histogram > 0 and histogram > histogram_prev and histogram_prev > 0:
            hist_accel = (histogram - histogram_prev) / abs(histogram_prev) if histogram_prev != 0 else 0
            if hist_accel > 0.5:
                return Signal(
                    signal_type=SignalType.BUY,
                    strength=0.60,
                    strategy_name=self.name,
                    symbol=symbol,
                    price=price,
                    reason=f"MACD histogram hızlanması (+{hist_accel:.1%})",
                    metadata={"macd": macd, "histogram": histogram},
                )

        if histogram < 0 and histogram < histogram_prev and histogram_prev < 0:
            hist_accel = (histogram - histogram_prev) / abs(histogram_prev) if histogram_prev != 0 else 0
            if hist_accel > 0.5:
                return Signal(
                    signal_type=SignalType.SELL,
                    strength=0.60,
                    strategy_name=self.name,
                    symbol=symbol,
                    price=price,
                    reason=f"MACD histogram düşüş hızlanması",
                    metadata={"macd": macd, "histogram": histogram},
                )

        # Zero line crossover
        if macd_prev < 0 and macd > 0:
            return Signal(
                signal_type=SignalType.BUY,
                strength=0.65,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason="MACD sıfır çizgisi üstüne geçti",
                metadata={"macd": macd},
            )

        if macd_prev > 0 and macd < 0:
            return Signal(
                signal_type=SignalType.SELL,
                strength=0.65,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason="MACD sıfır çizgisi altına düştü",
                metadata={"macd": macd},
            )

        return self._neutral_signal(symbol, price)
