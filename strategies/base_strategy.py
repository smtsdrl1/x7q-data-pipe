"""
Temel Strateji Sınıfı
Tüm stratejiler bu sınıftan türetilir.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import pandas as pd


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    NEUTRAL = "neutral"


@dataclass
class Signal:
    """Strateji sinyali."""
    signal_type: SignalType
    strength: float  # 0.0 - 1.0 arası sinyal gücü
    strategy_name: str
    symbol: str
    price: float
    reason: str
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class BaseStrategy(ABC):
    """Tüm stratejiler için temel sınıf."""

    def __init__(self, name: str, weight: float = 1.0):
        self.name = name
        self.weight = weight

    @abstractmethod
    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        """Veriyi analiz et ve sinyal üret."""
        pass

    def _neutral_signal(self, symbol: str, price: float) -> Signal:
        """Nötr sinyal döndür."""
        return Signal(
            signal_type=SignalType.NEUTRAL,
            strength=0.5,
            strategy_name=self.name,
            symbol=symbol,
            price=price,
            reason="Sinyal yok",
        )
