"""
Pozisyon Yönetimi Modülü
Açık pozisyonları takip eder, stop-loss/take-profit yönetimi yapar.
"""

from dataclasses import dataclass, field
from datetime import datetime
from utils.logger import setup_logger
from utils.risk_manager import RiskManager, TradeRecord

logger = setup_logger("PositionManager")


@dataclass
class Position:
    """Açık pozisyon."""
    symbol: str
    side: str
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    trailing_stop: float
    entry_time: datetime = field(default_factory=datetime.now)
    highest_price: float = 0.0
    lowest_price: float = float("inf")


class PositionManager:
    """Pozisyon yöneticisi."""

    def __init__(self, risk_manager: RiskManager):
        self.risk_manager = risk_manager
        self.open_positions: dict[str, Position] = {}

    def open_position(self, symbol: str, side: str, entry_price: float,
                      atr: float) -> Position | None:
        """Yeni pozisyon aç."""
        can_trade, reason = self.risk_manager.can_trade()
        if not can_trade:
            logger.warning(f"Trade reddedildi ({symbol}): {reason}")
            return None

        if symbol in self.open_positions:
            logger.warning(f"Zaten açık pozisyon var: {symbol}")
            return None

        stop_loss = self.risk_manager.calculate_stop_loss(entry_price, atr, side)
        take_profit = self.risk_manager.calculate_take_profit(entry_price, stop_loss, side)
        quantity = self.risk_manager.calculate_position_size(entry_price, stop_loss)

        if quantity <= 0:
            logger.warning(f"Geçersiz pozisyon boyutu: {symbol}")
            return None

        position = Position(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_stop=stop_loss,
            highest_price=entry_price,
            lowest_price=entry_price,
        )
        self.open_positions[symbol] = position

        # Trade kaydı oluştur
        trade = TradeRecord(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status="open",
        )
        self.risk_manager.record_trade(trade)

        logger.info(
            f"Pozisyon açıldı: {side.upper()} {symbol} @ {entry_price:.6f} | "
            f"Miktar: {quantity:.6f} | SL: {stop_loss:.6f} | TP: {take_profit:.6f}"
        )
        return position

    def check_exits(self, symbol: str, current_price: float) -> dict | None:
        """Pozisyon çıkış koşullarını kontrol et."""
        if symbol not in self.open_positions:
            return None

        pos = self.open_positions[symbol]

        # Highest/lowest güncelle
        if current_price > pos.highest_price:
            pos.highest_price = current_price
        if current_price < pos.lowest_price:
            pos.lowest_price = current_price

        # Trailing stop güncelle
        new_trailing = self.risk_manager.calculate_trailing_stop(
            current_price, pos.entry_price, pos.highest_price, pos.side
        )
        if pos.side == "buy" and new_trailing > pos.trailing_stop:
            pos.trailing_stop = new_trailing
        elif pos.side == "sell" and new_trailing < pos.trailing_stop:
            pos.trailing_stop = new_trailing

        exit_reason = None

        if pos.side == "buy":
            if current_price <= pos.stop_loss:
                exit_reason = "stop_loss"
            elif current_price >= pos.take_profit:
                exit_reason = "take_profit"
            elif current_price <= pos.trailing_stop and current_price > pos.entry_price:
                exit_reason = "trailing_stop"
        else:  # sell (short)
            if current_price >= pos.stop_loss:
                exit_reason = "stop_loss"
            elif current_price <= pos.take_profit:
                exit_reason = "take_profit"
            elif current_price >= pos.trailing_stop and current_price < pos.entry_price:
                exit_reason = "trailing_stop"

        if exit_reason:
            return self.close_position(symbol, current_price, exit_reason)
        return None

    def close_position(self, symbol: str, exit_price: float,
                       reason: str = "manual") -> dict:
        """Pozisyonu kapat."""
        if symbol not in self.open_positions:
            return {"error": f"Pozisyon bulunamadı: {symbol}"}

        pos = self.open_positions.pop(symbol)

        # P&L hesapla
        if pos.side == "buy":
            pnl = (exit_price - pos.entry_price) * pos.quantity
            pnl_pct = ((exit_price - pos.entry_price) / pos.entry_price) * 100
        else:
            pnl = (pos.entry_price - exit_price) * pos.quantity
            pnl_pct = ((pos.entry_price - exit_price) / pos.entry_price) * 100

        # Fee hesapla
        entry_fee = self.risk_manager.calculate_fees(pos.quantity, pos.entry_price)
        exit_fee = self.risk_manager.calculate_fees(pos.quantity, exit_price)
        total_fee = entry_fee + exit_fee

        net_pnl = pnl - total_fee

        # Trade kaydı
        trade = TradeRecord(
            symbol=symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            quantity=pos.quantity,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            fee=total_fee,
            entry_time=pos.entry_time,
            exit_time=datetime.now(),
            status="closed",
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
        )
        self.risk_manager.record_trade(trade)

        emoji = "✅" if net_pnl > 0 else "❌"
        logger.info(
            f"{emoji} Pozisyon kapatıldı ({reason}): {symbol} | "
            f"P&L: ${net_pnl:.2f} ({pnl_pct:.2f}%) | Fee: ${total_fee:.4f}"
        )

        return {
            "symbol": symbol,
            "side": pos.side,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "quantity": pos.quantity,
            "pnl": net_pnl,
            "pnl_pct": pnl_pct,
            "fee": total_fee,
            "reason": reason,
        }

    def get_open_positions(self) -> list[dict]:
        """Açık pozisyonları döndür."""
        positions = []
        for symbol, pos in self.open_positions.items():
            positions.append({
                "symbol": symbol,
                "side": pos.side,
                "entry_price": pos.entry_price,
                "quantity": pos.quantity,
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit,
                "trailing_stop": pos.trailing_stop,
                "highest_price": pos.highest_price,
            })
        return positions
