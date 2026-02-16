"""
Multi-Strateji Motor
Tüm stratejilerin sinyallerini birleştirerek composite sinyal üretir.
"""

import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal, SignalType
from strategies.rsi_strategy import RSIStrategy
from strategies.macd_strategy import MACDStrategy
from strategies.bollinger_strategy import BollingerStrategy
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.volume_spike import VolumeSpikeStrategy
from strategies.supertrend import SuperTrendStrategy
from utils.indicators import TechnicalIndicators
from utils.logger import setup_logger
from config import SIGNAL_BUY_THRESHOLD, SIGNAL_SELL_THRESHOLD, MIN_STRATEGIES_AGREE

logger = setup_logger("MultiStrategy")


class MultiStrategyEngine:
    """Birden fazla stratejiyi birleştiren motor."""

    def __init__(self):
        self.strategies: list[BaseStrategy] = [
            RSIStrategy(),
            MACDStrategy(),
            BollingerStrategy(),
            EMACrossoverStrategy(),
            VolumeSpikeStrategy(),
            SuperTrendStrategy(),
        ]
        self.indicators = TechnicalIndicators()

    def analyze(self, df: pd.DataFrame, symbol: str) -> dict:
        """Tüm stratejileri çalıştır ve composite sinyal üret."""
        if df.empty or len(df) < 60:
            return {
                "signal": SignalType.NEUTRAL,
                "composite_score": 0.5,
                "signals": [],
                "reason": "Yetersiz veri",
            }

        # Göstergeleri hesapla
        df = self.indicators.calculate_all(df)

        # Her stratejiyi çalıştır
        signals: list[Signal] = []
        for strategy in self.strategies:
            try:
                signal = strategy.analyze(df, symbol)
                signals.append(signal)
            except Exception as e:
                logger.error(f"Strateji hatası ({strategy.name}): {e}")

        # Composite skor hesapla
        composite = self._calculate_composite(signals)

        # Sinyal yönü belirle
        buy_count = sum(1 for s in signals if s.signal_type == SignalType.BUY)
        sell_count = sum(1 for s in signals if s.signal_type == SignalType.SELL)

        if composite >= SIGNAL_BUY_THRESHOLD and buy_count >= MIN_STRATEGIES_AGREE:
            final_signal = SignalType.BUY
        elif composite <= SIGNAL_SELL_THRESHOLD and sell_count >= MIN_STRATEGIES_AGREE:
            final_signal = SignalType.SELL
        else:
            final_signal = SignalType.NEUTRAL

        # Açıklama oluştur
        buy_reasons = [s.reason for s in signals if s.signal_type == SignalType.BUY]
        sell_reasons = [s.reason for s in signals if s.signal_type == SignalType.SELL]

        result = {
            "signal": final_signal,
            "composite_score": composite,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "signals": signals,
            "buy_reasons": buy_reasons,
            "sell_reasons": sell_reasons,
            "price": df["close"].iloc[-1],
            "atr": df["atr"].iloc[-1] if "atr" in df.columns else 0,
            "rsi": df["rsi"].iloc[-1] if "rsi" in df.columns else 50,
            "volume_ratio": df["volume_ratio"].iloc[-1] if "volume_ratio" in df.columns else 1,
        }

        if final_signal != SignalType.NEUTRAL:
            direction = "ALIM" if final_signal == SignalType.BUY else "SATIM"
            logger.info(
                f"📊 {symbol} | {direction} sinyali | "
                f"Skor: {composite:.2f} | Onay: {buy_count}B/{sell_count}S | "
                f"Fiyat: {result['price']:.6f}"
            )

        return result

    def _calculate_composite(self, signals: list[Signal]) -> float:
        """Ağırlıklı composite skor hesapla (0-1)."""
        if not signals:
            return 0.5

        total_weight = 0.0
        weighted_score = 0.0

        for signal in signals:
            weight = 1.0
            # İlgili stratejiden ağırlığı al
            for strategy in self.strategies:
                if strategy.name == signal.strategy_name:
                    weight = strategy.weight
                    break

            total_weight += weight

            if signal.signal_type == SignalType.BUY:
                score = 0.5 + (signal.strength * 0.5)  # 0.5 - 1.0
            elif signal.signal_type == SignalType.SELL:
                score = 0.5 - (signal.strength * 0.5)  # 0.0 - 0.5
            else:
                score = 0.5

            weighted_score += score * weight

        if total_weight == 0:
            return 0.5

        return weighted_score / total_weight

    def get_strategy_names(self) -> list[str]:
        """Strateji isimlerini döndür."""
        return [s.name for s in self.strategies]
