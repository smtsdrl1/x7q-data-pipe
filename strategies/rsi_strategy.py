"""
RSI Reversal Stratejisi
Aşırı alım/satım bölgelerinde dönüş sinyalleri üretir.
"""

import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal, SignalType
from config import RSI_OVERSOLD, RSI_OVERBOUGHT, RSI_WEIGHT


class RSIStrategy(BaseStrategy):
    """RSI tabanlı mean-reversion stratejisi."""

    def __init__(self):
        super().__init__(name="RSI Reversal", weight=RSI_WEIGHT)

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        if "rsi" not in df.columns or len(df) < 20:
            return self._neutral_signal(symbol, df["close"].iloc[-1])

        current_rsi = df["rsi"].iloc[-1]
        prev_rsi = df["rsi"].iloc[-2]
        price = df["close"].iloc[-1]

        # Güçlü alım: RSI oversold bölgesinden çıkış
        if current_rsi < RSI_OVERSOLD:
            strength = min(1.0, (RSI_OVERSOLD - current_rsi) / 20)
            return Signal(
                signal_type=SignalType.BUY,
                strength=0.6 + (strength * 0.4),
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"RSI oversold: {current_rsi:.1f}",
                metadata={"rsi": current_rsi},
            )

        # RSI oversold'dan dönüş (momentum)
        if prev_rsi < RSI_OVERSOLD and current_rsi > RSI_OVERSOLD:
            return Signal(
                signal_type=SignalType.BUY,
                strength=0.75,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"RSI oversold dönüşü: {prev_rsi:.1f} → {current_rsi:.1f}",
                metadata={"rsi": current_rsi, "prev_rsi": prev_rsi},
            )

        # Güçlü satım: RSI overbought
        if current_rsi > RSI_OVERBOUGHT:
            strength = min(1.0, (current_rsi - RSI_OVERBOUGHT) / 20)
            return Signal(
                signal_type=SignalType.SELL,
                strength=0.6 + (strength * 0.4),
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"RSI overbought: {current_rsi:.1f}",
                metadata={"rsi": current_rsi},
            )

        # RSI overbought'tan dönüş
        if prev_rsi > RSI_OVERBOUGHT and current_rsi < RSI_OVERBOUGHT:
            return Signal(
                signal_type=SignalType.SELL,
                strength=0.75,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"RSI overbought dönüşü: {prev_rsi:.1f} → {current_rsi:.1f}",
                metadata={"rsi": current_rsi, "prev_rsi": prev_rsi},
            )

        # RSI divergence kontrolü
        signal = self._check_divergence(df, symbol, price, current_rsi)
        if signal:
            return signal

        return self._neutral_signal(symbol, price)

    def _check_divergence(self, df: pd.DataFrame, symbol: str,
                          price: float, current_rsi: float) -> Signal | None:
        """RSI divergence tespit et."""
        if len(df) < 30:
            return None

        # Son 20 mumda fiyat ve RSI trendini karşılaştır
        prices = df["close"].iloc[-20:]
        rsi_vals = df["rsi"].iloc[-20:]

        price_trend = prices.iloc[-1] - prices.iloc[0]
        rsi_trend = rsi_vals.iloc[-1] - rsi_vals.iloc[0]

        # Bullish divergence: Fiyat düşerken RSI yükseliyor
        if price_trend < 0 and rsi_trend > 5 and current_rsi < 45:
            return Signal(
                signal_type=SignalType.BUY,
                strength=0.65,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"Bullish RSI divergence (RSI: {current_rsi:.1f})",
                metadata={"rsi": current_rsi, "divergence": "bullish"},
            )

        # Bearish divergence: Fiyat yükselirken RSI düşüyor
        if price_trend > 0 and rsi_trend < -5 and current_rsi > 55:
            return Signal(
                signal_type=SignalType.SELL,
                strength=0.65,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=f"Bearish RSI divergence (RSI: {current_rsi:.1f})",
                metadata={"rsi": current_rsi, "divergence": "bearish"},
            )

        return None
