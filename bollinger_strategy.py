"""
Bollinger Bands Stratejisi
Band dokunuşları ve squeeze breakout sinyalleri.
"""

import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal, SignalType
from config import BB_WEIGHT


class BollingerStrategy(BaseStrategy):
    """Bollinger Bands squeeze ve bounce stratejisi."""

    def __init__(self):
        super().__init__(name="Bollinger Bands", weight=BB_WEIGHT)

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        required = ["bb_upper", "bb_lower", "bb_middle", "bb_width", "bb_pct"]
        if not all(c in df.columns for c in required) or len(df) < 25:
            return self._neutral_signal(symbol, df["close"].iloc[-1])

        price = df["close"].iloc[-1]
        bb_pct = df["bb_pct"].iloc[-1]
        bb_width = df["bb_width"].iloc[-1]
        bb_width_prev = df["bb_width"].iloc[-5]  # 5 mum önceki genişlik
        bb_upper = df["bb_upper"].iloc[-1]
        bb_lower = df["bb_lower"].iloc[-1]
        bb_middle = df["bb_middle"].iloc[-1]

        # Squeeze tespit (bantlar daralma)
        is_squeeze = bb_width < bb_width_prev * 0.7

        # Fiyat alt banda dokundu/altına düştü → Alım
        if bb_pct <= 0.05:
            strength = 0.75 if is_squeeze else 0.65
            return Signal(
                signal_type=SignalType.BUY,
                strength=strength,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"Alt banda dokunuş (BB%: {bb_pct:.2f})",
                metadata={"bb_pct": bb_pct, "bb_width": bb_width, "squeeze": is_squeeze},
            )

        # Fiyat alt banddan sıçrama
        prev_pct = df["bb_pct"].iloc[-2]
        if prev_pct <= 0.05 and bb_pct > 0.10:
            return Signal(
                signal_type=SignalType.BUY,
                strength=0.70,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"Alt banddan sıçrama ({prev_pct:.2f} → {bb_pct:.2f})",
                metadata={"bb_pct": bb_pct},
            )

        # Fiyat üst banda dokundu/üstüne çıktı → Satım
        if bb_pct >= 0.95:
            strength = 0.75 if is_squeeze else 0.65
            return Signal(
                signal_type=SignalType.SELL,
                strength=strength,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"Üst banda dokunuş (BB%: {bb_pct:.2f})",
                metadata={"bb_pct": bb_pct, "bb_width": bb_width, "squeeze": is_squeeze},
            )

        # Squeeze breakout - bantlar genişlemeye başladı
        if is_squeeze and bb_width > bb_width_prev:
            # Yukarı breakout
            if price > bb_middle and bb_pct > 0.6:
                return Signal(
                    signal_type=SignalType.BUY,
                    strength=0.80,
                    strategy_name=self.name,
                    symbol=symbol,
                    price=price,
                    reason=f"Squeeze breakout yukarı (width: {bb_width:.4f})",
                    metadata={"bb_pct": bb_pct, "squeeze_breakout": True},
                )
            # Aşağı breakout
            elif price < bb_middle and bb_pct < 0.4:
                return Signal(
                    signal_type=SignalType.SELL,
                    strength=0.80,
                    strategy_name=self.name,
                    symbol=symbol,
                    price=price,
                    reason=f"Squeeze breakout aşağı (width: {bb_width:.4f})",
                    metadata={"bb_pct": bb_pct, "squeeze_breakout": True},
                )

        return self._neutral_signal(symbol, price)
