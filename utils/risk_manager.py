"""
Risk Yönetimi Modülü
Pozisyon boyutlama, stop-loss, drawdown koruması
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from utils.logger import setup_logger
import numpy as np
from config import (
    MAX_POSITION_PCT, STOP_LOSS_PCT, TAKE_PROFIT_PCT, TRAILING_STOP_PCT,
    MAX_DAILY_LOSS_PCT, MAX_DRAWDOWN_PCT, MAX_CONCURRENT_POSITIONS,
    RISK_REWARD_MIN, CONSECUTIVE_LOSS_THRESHOLD, POSITION_REDUCE_FACTOR,
    MAKER_FEE, TAKER_FEE, SLIPPAGE_PCT,
    KELLY_SIZING_ENABLED, KELLY_FRACTION, KELLY_MAX_PCT,
    CORRELATION_ENABLED, MAX_CORRELATION_THRESHOLD, CORRELATION_LOOKBACK_HOURS,
)

logger = setup_logger("RiskManager")


@dataclass
class TradeRecord:
    """Tek bir trade kaydı."""
    symbol: str
    side: str  # "buy" veya "sell"
    entry_price: float
    exit_price: float = 0.0
    quantity: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    fee: float = 0.0
    entry_time: datetime = field(default_factory=datetime.now)
    exit_time: datetime = None
    status: str = "open"  # open, closed, stopped
    stop_loss: float = 0.0
    take_profit: float = 0.0
    trailing_stop: float = 0.0


class RiskManager:
    """Risk yönetimi ve pozisyon boyutlama."""

    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.peak_capital = initial_capital
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.today = date.today()
        self.consecutive_losses = 0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        self.total_fees = 0.0
        self.trade_history: list[TradeRecord] = []
        self.is_trading_halted = False

    def reset_daily(self):
        """Günlük metrikleri sıfırla."""
        if date.today() != self.today:
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.today = date.today()
            logger.info("Günlük metrikler sıfırlandı")

    def can_trade(self) -> tuple[bool, str]:
        """Trade yapılabilir mi kontrol et."""
        self.reset_daily()

        if self.is_trading_halted:
            return False, "Trading durduruldu"

        # Günlük kayıp limiti
        if abs(self.daily_pnl) >= self.current_capital * MAX_DAILY_LOSS_PCT and self.daily_pnl < 0:
            self.is_trading_halted = True
            return False, f"Günlük kayıp limiti aşıldı: {self.daily_pnl:.2f}"

        # Max drawdown kontrolü
        drawdown = (self.peak_capital - self.current_capital) / self.peak_capital
        if drawdown >= MAX_DRAWDOWN_PCT:
            self.is_trading_halted = True
            return False, f"Max drawdown aşıldı: {drawdown:.2%}"

        # Eşzamanlı pozisyon limiti
        open_positions = sum(1 for t in self.trade_history if t.status == "open")
        if open_positions >= MAX_CONCURRENT_POSITIONS:
            return False, f"Max pozisyon limiti: {open_positions}/{MAX_CONCURRENT_POSITIONS}"

        return True, "OK"

    def calculate_position_size(self, entry_price: float, stop_loss_price: float) -> float:
        """Pozisyon boyutunu hesapla (ATR/risk bazlı)."""
        # Temel pozisyon boyutu
        max_risk_amount = self.current_capital * MAX_POSITION_PCT

        # Ardışık kayıp sonrası küçültme
        if self.consecutive_losses >= CONSECUTIVE_LOSS_THRESHOLD:
            max_risk_amount *= POSITION_REDUCE_FACTOR
            logger.warning(
                f"Ardışık {self.consecutive_losses} kayıp - pozisyon küçültüldü"
            )

        # Risk bazlı boyutlama
        risk_per_unit = abs(entry_price - stop_loss_price)
        if risk_per_unit == 0:
            return 0.0

        position_value = max_risk_amount
        quantity = position_value / entry_price

        return quantity

    def calculate_kelly_position_size(self, win_rate: float, avg_win_pct: float,
                                      avg_loss_pct: float) -> float:
        """Kelly Criterion ile optimal pozisyon boyutu (% sermaye).

        Args:
            win_rate: Kazanma oranı 0-1
            avg_win_pct: Ortalama kazanç yüzdesi (0.04 = %4)
            avg_loss_pct: Ortalama kayıp yüzdesi (mutlak, 0.02 = %2)

        Returns:
            Sermayenin yüzdesi olarak pozisyon büyüklüğü (0.0 - KELLY_MAX_PCT)
        """
        if not KELLY_SIZING_ENABLED or avg_win_pct <= 0 or avg_loss_pct <= 0:
            return MAX_POSITION_PCT

        if win_rate <= 0 or win_rate >= 1:
            return MAX_POSITION_PCT

        # Kelly Criterion: f = (bp - q) / b
        # b = avg_win / avg_loss (odds)
        # p = win_rate
        # q = 1 - win_rate
        b = avg_win_pct / avg_loss_pct
        p = win_rate
        q = 1 - win_rate

        kelly_full = (b * p - q) / b

        if kelly_full <= 0:
            return 0.0  # Negatif Kelly → pozisyon açma

        # Half-Kelly (daha güvenli)
        kelly_f = kelly_full * KELLY_FRACTION

        # Güvenlik sınırı
        kelly_f = min(kelly_f, KELLY_MAX_PCT)

        logger.debug(
            f"Kelly: full={kelly_full:.3f} → half={kelly_f:.3f} "
            f"(WR={win_rate:.1%} W={avg_win_pct:.2%} L={avg_loss_pct:.2%})"
        )
        return kelly_f

    def get_kelly_size_from_history(self, entry_price: float,
                                    stop_loss_price: float) -> float:
        """Trade geçmişinden Kelly pozisyon boyutu hesapla."""
        if len(self.trade_history) < 20:
            # Yeterli veri yok → standart boyutlama
            return self.calculate_position_size(entry_price, stop_loss_price)

        closed = [t for t in self.trade_history if t.status == "closed"]
        if len(closed) < 10:
            return self.calculate_position_size(entry_price, stop_loss_price)

        wins = [t.pnl_pct for t in closed if t.pnl > 0]
        losses = [abs(t.pnl_pct) for t in closed if t.pnl <= 0]

        win_rate = len(wins) / len(closed)
        avg_win = sum(wins) / len(wins) / 100 if wins else 0.03
        avg_loss = sum(losses) / len(losses) / 100 if losses else 0.015

        kelly_pct = self.calculate_kelly_position_size(win_rate, avg_win, avg_loss)
        position_value = self.current_capital * kelly_pct
        quantity = position_value / entry_price
        return quantity

    def check_correlation(self, new_symbol: str, open_symbols: list[str],
                          price_histories: dict) -> tuple[bool, float]:
        """Yeni pozisyon mevcut pozisyonlarla yüksek korelasyonlu mu kontrol et.

        Args:
            new_symbol: Açılmak istenen sembol
            open_symbols: Zaten açık pozisyonların sembolleri
            price_histories: {symbol: pd.Series(close prices)} için dict

        Returns:
            (can_open: bool, max_correlation: float)
        """
        if not CORRELATION_ENABLED or not open_symbols:
            return True, 0.0

        if new_symbol not in price_histories:
            return True, 0.0

        new_prices = price_histories.get(new_symbol)
        if new_prices is None or len(new_prices) < 10:
            return True, 0.0

        max_corr = 0.0
        for sym in open_symbols:
            if sym == new_symbol or sym not in price_histories:
                continue
            existing_prices = price_histories[sym]
            if existing_prices is None or len(existing_prices) < 10:
                continue
            try:
                # Eşit uzunlukta al
                min_len = min(len(new_prices), len(existing_prices))
                p1 = np.array(new_prices[-min_len:], dtype=float)
                p2 = np.array(existing_prices[-min_len:], dtype=float)
                # Returns üzerinden korelasyon (daha anlamlı)
                r1 = np.diff(p1) / p1[:-1]
                r2 = np.diff(p2) / p2[:-1]
                corr = float(np.corrcoef(r1, r2)[0, 1])
                if abs(corr) > max_corr:
                    max_corr = abs(corr)
            except Exception:
                continue

        can_open = max_corr < MAX_CORRELATION_THRESHOLD
        if not can_open:
            logger.warning(
                f"🔗 Korelasyon engeli: {new_symbol} ile mevcut pozisyon "
                f"korelasyonu {max_corr:.2f} > {MAX_CORRELATION_THRESHOLD}"
            )
        return can_open, round(max_corr, 3)

    def calculate_stop_loss(self, entry_price: float, atr: float,
                           side: str = "buy") -> float:
        """ATR bazlı dinamik stop-loss hesapla."""
        # ATR bazlı stop-loss (1.5x ATR veya minimum %1.2)
        atr_stop = atr * 1.5
        min_stop = entry_price * STOP_LOSS_PCT

        stop_distance = max(atr_stop, min_stop)

        if side == "buy":
            return entry_price - stop_distance
        else:
            return entry_price + stop_distance

    def calculate_take_profit(self, entry_price: float, stop_loss_price: float,
                              side: str = "buy") -> float:
        """R:R bazlı take-profit hesapla."""
        risk = abs(entry_price - stop_loss_price)
        reward = risk * RISK_REWARD_MIN  # Minimum 3:1 R:R

        # Take profit en az %4, en fazla %8
        min_tp = entry_price * 0.04
        max_tp = entry_price * 0.08
        reward = max(min_tp, min(reward, max_tp))

        if side == "buy":
            return entry_price + reward
        else:
            return entry_price - reward

    def calculate_trailing_stop(self, current_price: float, entry_price: float,
                                highest_price: float, side: str = "buy") -> float:
        """Trailing stop hesapla."""
        if side == "buy":
            # Fiyat yükseldikçe stop da yükselir
            trail = highest_price * (1 - TRAILING_STOP_PCT)
            return max(trail, entry_price * (1 - STOP_LOSS_PCT))
        else:
            lowest_price = current_price  # Placeholder
            trail = lowest_price * (1 + TRAILING_STOP_PCT)
            return min(trail, entry_price * (1 + STOP_LOSS_PCT))

    def calculate_fees(self, quantity: float, price: float,
                       is_maker: bool = False) -> float:
        """İşlem ücretlerini hesapla."""
        fee_rate = MAKER_FEE if is_maker else TAKER_FEE
        trade_value = quantity * price
        fee = trade_value * fee_rate
        slippage = trade_value * SLIPPAGE_PCT
        return fee + slippage

    def record_trade(self, trade: TradeRecord):
        """Trade sonucunu kaydet."""
        self.trade_history.append(trade)

        if trade.status == "closed":
            self.total_trades += 1
            self.daily_trades += 1
            self.total_pnl += trade.pnl
            self.total_fees += trade.fee
            self.daily_pnl += trade.pnl
            self.current_capital += trade.pnl - trade.fee

            if trade.pnl > 0:
                self.winning_trades += 1
                self.consecutive_losses = 0
            else:
                self.losing_trades += 1
                self.consecutive_losses += 1

            # Peak capital güncelle
            if self.current_capital > self.peak_capital:
                self.peak_capital = self.current_capital

            logger.info(
                f"Trade kapatıldı: {trade.symbol} | P&L: ${trade.pnl:.2f} "
                f"({trade.pnl_pct:.2f}%) | Sermaye: ${self.current_capital:.2f}"
            )

    def get_stats(self) -> dict:
        """Performans istatistiklerini döndür."""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        roi = ((self.current_capital - self.initial_capital) / self.initial_capital * 100)
        drawdown = ((self.peak_capital - self.current_capital) / self.peak_capital * 100) \
            if self.peak_capital > 0 else 0

        avg_win = 0.0
        avg_loss = 0.0
        if self.winning_trades > 0:
            wins = [t.pnl_pct for t in self.trade_history if t.status == "closed" and t.pnl > 0]
            avg_win = sum(wins) / len(wins) if wins else 0
        if self.losing_trades > 0:
            losses = [t.pnl_pct for t in self.trade_history if t.status == "closed" and t.pnl < 0]
            avg_loss = sum(losses) / len(losses) if losses else 0

        return {
            "initial_capital": self.initial_capital,
            "current_capital": self.current_capital,
            "total_pnl": self.total_pnl,
            "total_fees": self.total_fees,
            "net_pnl": self.total_pnl - self.total_fees,
            "roi": roi,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "max_drawdown": drawdown,
            "consecutive_losses": self.consecutive_losses,
            "daily_pnl": self.daily_pnl,
            "daily_trades": self.daily_trades,
        }

    def resume_trading(self):
        """Trading'i yeniden başlat."""
        self.is_trading_halted = False
        logger.info("Trading yeniden başlatıldı")
