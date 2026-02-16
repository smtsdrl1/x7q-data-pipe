"""
Volume Spike Stratejisi
Anormal hacim artışlarında fiyat yönü ile birlikte sinyal üretir.
"""

import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal, SignalType
from config import VOLUME_SPIKE_MULTIPLIER, VOLUME_WEIGHT


class VolumeSpikeStrategy(BaseStrategy):
    """Hacim spike + fiyat yönü stratejisi."""

    def __init__(self):
        super().__init__(name="Volume Spike", weight=VOLUME_WEIGHT)

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        required = ["volume_sma", "volume_ratio"]
        if not all(c in df.columns for c in required) or len(df) < 25:
            return self._neutral_signal(symbol, df["close"].iloc[-1])

        price = df["close"].iloc[-1]
        prev_price = df["close"].iloc[-2]
        volume_ratio = df["volume_ratio"].iloc[-1]
        price_change = (price - prev_price) / prev_price

        # Hacim spike + fiyat artışı → Alım
        if volume_ratio >= VOLUME_SPIKE_MULTIPLIER and price_change > 0.001:
            strength = min(0.90, 0.60 + (volume_ratio - VOLUME_SPIKE_MULTIPLIER) * 0.1)
            return Signal(
                signal_type=SignalType.BUY,
                strength=strength,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"Volume spike ({volume_ratio:.1f}x) + fiyat artışı ({price_change:.2%})",
                metadata={"volume_ratio": volume_ratio, "price_change": price_change},
            )

        # Hacim spike + fiyat düşüşü → Satım
        if volume_ratio >= VOLUME_SPIKE_MULTIPLIER and price_change < -0.001:
            strength = min(0.90, 0.60 + (volume_ratio - VOLUME_SPIKE_MULTIPLIER) * 0.1)
            return Signal(
                signal_type=SignalType.SELL,
                strength=strength,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"Volume spike ({volume_ratio:.1f}x) + fiyat düşüşü ({price_change:.2%})",
                metadata={"volume_ratio": volume_ratio, "price_change": price_change},
            )

        # Kademeli hacim artışı (3 mum üst üste artan hacim)
        if len(df) >= 5:
            recent_ratios = df["volume_ratio"].iloc[-3:]
            if all(r > 1.3 for r in recent_ratios) and recent_ratios.is_monotonic_increasing:
                recent_prices = df["close"].iloc[-3:]
                if recent_prices.is_monotonic_increasing:
                    return Signal(
                        signal_type=SignalType.BUY,
                        strength=0.65,
                        strategy_name=self.name,
                        symbol=symbol,
                        price=price,
                        reason="Kademeli hacim artışı + fiyat yükselişi",
                        metadata={"volume_ratio": volume_ratio},
                    )
                elif recent_prices.is_monotonic_decreasing:
                    return Signal(
                        signal_type=SignalType.SELL,
                        strength=0.65,
                        strategy_name=self.name,
                        symbol=symbol,
                        price=price,
                        reason="Kademeli hacim artışı + fiyat düşüşü",
                        metadata={"volume_ratio": volume_ratio},
                    )

        # Volume dry-up sonrası spike (kontraksiyon → genişleme)
        if len(df) >= 10:
            prev_5_avg = df["volume_ratio"].iloc[-6:-1].mean()
            if prev_5_avg < 0.7 and volume_ratio > 1.5:
                if price_change > 0:
                    return Signal(
                        signal_type=SignalType.BUY,
                        strength=0.70,
                        strategy_name=self.name,
                        symbol=symbol,
                        price=price,
                        reason=f"Volume dry-up breakout (ratio: {volume_ratio:.1f}x)",
                        metadata={"volume_ratio": volume_ratio, "prev_avg": prev_5_avg},
                    )

        return self._neutral_signal(symbol, price)
