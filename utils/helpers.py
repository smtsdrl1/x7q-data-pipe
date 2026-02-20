"""
Yardımcı fonksiyonlar
"""

from datetime import datetime, timezone


def format_currency(value: float, symbol: str = "$") -> str:
    """Para birimi formatla."""
    if abs(value) >= 1_000_000:
        return f"{symbol}{value:,.0f}"
    elif abs(value) >= 1000:
        return f"{symbol}{value:,.2f}"
    else:
        return f"{symbol}{value:.4f}"


def format_pct(value: float) -> str:
    """Yüzde formatla."""
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def timestamp_to_str(ts: int) -> str:
    """Unix timestamp → okunabilir tarih."""
    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def calculate_compound_growth(initial: float, daily_return: float, days: int) -> float:
    """Bileşik büyüme hesapla."""
    return initial * ((1 + daily_return / 100) ** days)


def risk_reward_ratio(entry: float, stop_loss: float, take_profit: float) -> float:
    """Risk/reward oranını hesapla."""
    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    if risk == 0:
        return 0.0
    return reward / risk
