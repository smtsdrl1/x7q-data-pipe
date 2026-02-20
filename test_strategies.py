"""
Strateji Testleri
Temel strateji mantigi testleri.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock ccxt before importing anything that depends on it
import types
ccxt_mock = types.ModuleType("ccxt")
ccxt_async_mock = types.ModuleType("ccxt.async_support")
ccxt_mock.async_support = ccxt_async_mock
ccxt_mock.NetworkError = Exception
ccxt_mock.ExchangeError = Exception
ccxt_async_mock.NetworkError = Exception
ccxt_async_mock.ExchangeError = Exception
sys.modules["ccxt"] = ccxt_mock
sys.modules["ccxt.async_support"] = ccxt_async_mock

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from strategies.rsi_strategy import RSIStrategy
from strategies.macd_strategy import MACDStrategy
from strategies.bollinger_strategy import BollingerStrategy
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.volume_spike import VolumeSpikeStrategy
from strategies.supertrend import SuperTrendStrategy
from strategies.multi_strategy import MultiStrategyEngine
from strategies.base_strategy import SignalType
from utils.indicators import TechnicalIndicators
from utils.risk_manager import RiskManager


def generate_test_data(n: int = 200, trend: str = "up") -> pd.DataFrame:
    """Test verisi olustur."""
    np.random.seed(42)
    dates = pd.date_range(start="2025-01-01", periods=n, freq="5min")

    if trend == "up":
        base_price = 100 + np.cumsum(np.random.randn(n) * 0.5 + 0.05)
    elif trend == "down":
        base_price = 100 + np.cumsum(np.random.randn(n) * 0.5 - 0.05)
    else:
        base_price = 100 + np.cumsum(np.random.randn(n) * 0.3)

    high = base_price + np.abs(np.random.randn(n) * 0.3)
    low = base_price - np.abs(np.random.randn(n) * 0.3)
    volume = np.random.randint(1000, 10000, n).astype(float)

    df = pd.DataFrame({
        "open": base_price + np.random.randn(n) * 0.1,
        "high": high,
        "low": low,
        "close": base_price,
        "volume": volume,
    }, index=dates)

    return df


def test_indicators():
    """Gosterge hesaplama testi."""
    print("Testing: Indicators...")
    df = generate_test_data(200)
    ti = TechnicalIndicators()
    result = ti.calculate_all(df)

    assert "rsi" in result.columns, "RSI eksik"
    assert "macd" in result.columns, "MACD eksik"
    assert "bb_upper" in result.columns, "BB eksik"
    assert "ema_fast" in result.columns, "EMA eksik"
    assert "atr" in result.columns, "ATR eksik"
    assert "supertrend" in result.columns, "SuperTrend eksik"
    assert "volume_ratio" in result.columns, "Volume ratio eksik"
    assert "adx" in result.columns, "ADX eksik"

    # RSI 0-100 arasinda mi
    rsi_valid = result["rsi"].dropna()
    assert (rsi_valid >= 0).all() and (rsi_valid <= 100).all(), "RSI aralik hatasi"

    print("  PASSED: Tum gostergeler dogru hesaplandi")


def test_rsi_strategy():
    """RSI stratejisi testi."""
    print("Testing: RSI Strategy...")
    strategy = RSIStrategy()

    # Oversold durumu icin veri
    df = generate_test_data(200, "down")
    ti = TechnicalIndicators()
    df = ti.calculate_all(df)

    signal = strategy.analyze(df, "TEST/USDT")
    assert signal is not None, "Sinyal uretilmedi"
    assert signal.strategy_name == "RSI Reversal"
    print(f"  Signal: {signal.signal_type.value}, Strength: {signal.strength:.2f}, Reason: {signal.reason}")
    print("  PASSED")


def test_macd_strategy():
    """MACD stratejisi testi."""
    print("Testing: MACD Strategy...")
    strategy = MACDStrategy()

    df = generate_test_data(200, "up")
    ti = TechnicalIndicators()
    df = ti.calculate_all(df)

    signal = strategy.analyze(df, "TEST/USDT")
    assert signal is not None
    print(f"  Signal: {signal.signal_type.value}, Strength: {signal.strength:.2f}, Reason: {signal.reason}")
    print("  PASSED")


def test_bollinger_strategy():
    """Bollinger Bands stratejisi testi."""
    print("Testing: Bollinger Strategy...")
    strategy = BollingerStrategy()

    df = generate_test_data(200)
    ti = TechnicalIndicators()
    df = ti.calculate_all(df)

    signal = strategy.analyze(df, "TEST/USDT")
    assert signal is not None
    print(f"  Signal: {signal.signal_type.value}, Strength: {signal.strength:.2f}, Reason: {signal.reason}")
    print("  PASSED")


def test_ema_crossover():
    """EMA crossover testi."""
    print("Testing: EMA Crossover...")
    strategy = EMACrossoverStrategy()

    df = generate_test_data(200, "up")
    ti = TechnicalIndicators()
    df = ti.calculate_all(df)

    signal = strategy.analyze(df, "TEST/USDT")
    assert signal is not None
    print(f"  Signal: {signal.signal_type.value}, Strength: {signal.strength:.2f}, Reason: {signal.reason}")
    print("  PASSED")


def test_multi_strategy():
    """Multi-strateji motoru testi."""
    print("Testing: Multi Strategy Engine...")
    engine = MultiStrategyEngine()

    df = generate_test_data(200, "up")
    result = engine.analyze(df, "TEST/USDT")

    assert "signal" in result
    assert "composite_score" in result
    assert "buy_count" in result
    assert "sell_count" in result
    assert 0 <= result["composite_score"] <= 1

    print(f"  Signal: {result['signal'].value}")
    print(f"  Composite Score: {result['composite_score']:.3f}")
    print(f"  Buy/Sell: {result['buy_count']}/{result['sell_count']}")
    print("  PASSED")


def test_risk_manager():
    """Risk yonetimi testi."""
    print("Testing: Risk Manager...")
    rm = RiskManager(1000.0)

    # Trade yapilabilir mi
    can, reason = rm.can_trade()
    assert can is True, f"Trade engellenmemeli: {reason}"

    # Pozisyon boyutu
    size = rm.calculate_position_size(100.0, 98.8)
    assert size > 0, "Pozisyon boyutu 0"

    # Stop-loss
    sl = rm.calculate_stop_loss(100.0, 1.5, "buy")
    assert sl < 100.0, "Stop-loss giris fiyatinin altinda olmali"

    # Take-profit
    tp = rm.calculate_take_profit(100.0, sl, "buy")
    assert tp > 100.0, "Take-profit giris fiyatinin ustunde olmali"

    # R:R kontrolu
    rr = (tp - 100.0) / (100.0 - sl)
    assert rr >= 2.0, f"R:R orani dusuk: {rr:.1f}"

    print(f"  Position Size: {size:.4f}")
    print(f"  Stop-Loss: {sl:.2f}")
    print(f"  Take-Profit: {tp:.2f}")
    print(f"  R:R Ratio: {rr:.1f}")
    print("  PASSED")


def run_all_tests():
    """Tum testleri calistir."""
    print("=" * 50)
    print("  STRATEJI TESTLERI")
    print("=" * 50 + "\n")

    tests = [
        test_indicators,
        test_rsi_strategy,
        test_macd_strategy,
        test_bollinger_strategy,
        test_ema_crossover,
        test_multi_strategy,
        test_risk_manager,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAILED: {e}")
            failed += 1
        print()

    print("=" * 50)
    print(f"  Sonuc: {passed} passed, {failed} failed")
    print("=" * 50)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
