"""
Sinyal Takip Sistemi
Her sinyali kaydeder, fiyat doğrulama yapar, sonucunu izler.
Tüm detaylar JSON'da kalıcı olarak saklanır.
"""

import json
import os
import asyncio
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional
from utils.logger import setup_logger

logger = setup_logger("SignalTracker")

SIGNALS_FILE = "data/signals_history.json"
STATS_FILE = "data/signal_stats.json"


@dataclass
class SignalRecord:
    """Tek bir sinyal kaydı — tüm detaylarıyla."""
    # Kimlik
    signal_id: str                   # Benzersiz ID (timestamp_symbol)
    
    # Sinyal bilgisi
    symbol: str
    direction: str                   # "BUY" veya "SELL"
    signal_time: str                 # ISO format — sinyal üretim anı
    signal_time_readable: str        # Okunabilir format
    
    # Strateji detayları
    composite_score: float
    buy_strategies: int              # Kaç strateji BUY dedi
    sell_strategies: int             # Kaç strateji SELL dedi
    rsi: float
    volume_ratio: float
    reasons: list                    # Sinyal sebepleri
    
    # Fiyat bilgisi — sinyal anı
    signal_price: float              # Strateji motorundan gelen fiyat
    verified_price: float            # Binance'den doğrulanan fiyat
    bid_price: float
    ask_price: float
    spread_pct: float
    price_deviation_pct: float       # Sinyal vs gerçek fiyat sapması
    price_verified: bool             # Fiyat doğrulandı mı
    data_quality: str                # GOOD / WARNING / FAIL
    verification_latency_ms: float   # Doğrulama süresi
    
    # Paper trading sonucu
    entry_price: float = 0.0         # Giriş fiyatı (paper)
    exit_price: float = 0.0          # Çıkış fiyatı
    stop_loss: float = 0.0
    take_profit: float = 0.0
    position_size_usd: float = 0.0   # USD pozisyon büyüklüğü
    quantity: float = 0.0
    
    # İşlem sonucu
    status: str = "PENDING"          # PENDING → ACTIVE → CLOSED / REJECTED / EXPIRED
    pnl: float = 0.0
    pnl_pct: float = 0.0
    fee: float = 0.0
    net_pnl: float = 0.0
    exit_reason: str = ""            # stop_loss / take_profit / trailing_stop / expired
    exit_time: str = ""
    exit_time_readable: str = ""
    duration_seconds: int = 0        # Pozisyon açık kalma süresi
    
    # Doğrulama
    result: str = ""                 # WIN / LOSS / PENDING
    exit_verified_price: float = 0.0 # Çıkıştaki doğrulanmış fiyat
    exit_data_quality: str = ""
    
    # 24h piyasa verisi
    volume_24h: float = 0.0
    change_24h_pct: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class SignalTracker:
    """
    Tüm sinyalleri takip eder, kaydeder ve istatistik üretir.
    - Her sinyal kaydedilir (kabul/red farketmez)
    - Fiyat doğrulaması yapılır
    - Sonuçlar izlenir
    - İstatistikler güncellenir
    """

    def __init__(self):
        self.signals: list[SignalRecord] = []
        self.active_signals: dict[str, SignalRecord] = {}  # symbol → signal
        self._load_history()

    def _load_history(self):
        """Geçmiş sinyalleri dosyadan yükle."""
        try:
            if os.path.exists(SIGNALS_FILE):
                with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.signals = [SignalRecord(**s) for s in data]
                    logger.info(f"Geçmiş yüklendi: {len(self.signals)} sinyal")
        except Exception as e:
            logger.error(f"Geçmiş yükleme hatası: {e}")
            self.signals = []

    def _save_history(self):
        """Sinyal geçmişini dosyaya kaydet."""
        try:
            os.makedirs(os.path.dirname(SIGNALS_FILE), exist_ok=True)
            with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    [s.to_dict() for s in self.signals],
                    f, ensure_ascii=False, indent=2, default=str
                )
        except Exception as e:
            logger.error(f"Geçmiş kaydetme hatası: {e}")

    def record_signal(
        self,
        symbol: str,
        direction: str,
        analysis: dict,
        verification: dict,
    ) -> SignalRecord:
        """
        Yeni sinyal kaydet.
        analysis: strateji motorundan gelen analiz sonucu
        verification: fiyat doğrulama sonucu
        """
        now = datetime.now(timezone.utc)
        signal_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{symbol.replace('/', '_')}"
        
        vp = verification.get("verified_price")
        
        record = SignalRecord(
            signal_id=signal_id,
            symbol=symbol,
            direction=direction,
            signal_time=now.isoformat(),
            signal_time_readable=now.strftime("%d.%m.%Y %H:%M:%S UTC"),
            composite_score=analysis.get("composite_score", 0),
            buy_strategies=analysis.get("buy_count", 0),
            sell_strategies=analysis.get("sell_count", 0),
            rsi=analysis.get("rsi", 0),
            volume_ratio=analysis.get("volume_ratio", 0),
            reasons=analysis.get("buy_reasons", []) if direction == "BUY" 
                    else analysis.get("sell_reasons", []),
            signal_price=analysis.get("price", 0),
            verified_price=verification.get("real_price", 0),
            bid_price=vp.bid if vp else 0,
            ask_price=vp.ask if vp else 0,
            spread_pct=vp.spread if vp else 0,
            price_deviation_pct=verification.get("deviation_pct", 0),
            price_verified=vp.verified if vp else False,
            data_quality=verification.get("data_quality", "FAIL"),
            verification_latency_ms=vp.latency_ms if vp else 0,
            volume_24h=vp.volume_24h if vp else 0,
            change_24h_pct=vp.change_24h_pct if vp else 0,
        )

        self.signals.append(record)
        self._save_history()
        
        logger.info(
            f"Sinyal kaydedildi: {signal_id} | {direction} {symbol} | "
            f"Skor: {record.composite_score:.2f} | "
            f"Doğrulama: {record.data_quality} | "
            f"Sapma: %{record.price_deviation_pct:.3f}"
        )
        
        return record

    def activate_signal(
        self, signal_id: str, entry_price: float,
        stop_loss: float, take_profit: float,
        quantity: float, position_size_usd: float
    ):
        """Sinyal aktif pozisyona dönüştü."""
        for s in self.signals:
            if s.signal_id == signal_id:
                s.status = "ACTIVE"
                s.entry_price = entry_price
                s.stop_loss = stop_loss
                s.take_profit = take_profit
                s.quantity = quantity
                s.position_size_usd = position_size_usd
                self.active_signals[s.symbol] = s
                self._save_history()
                logger.info(f"Sinyal aktifleştirildi: {signal_id}")
                return
        logger.warning(f"Sinyal bulunamadı: {signal_id}")

    def close_signal(
        self, symbol: str, exit_price: float, exit_reason: str,
        pnl: float, pnl_pct: float, fee: float,
        exit_verified_price: float = 0.0, exit_data_quality: str = ""
    ) -> Optional[SignalRecord]:
        """Aktif sinyali kapat."""
        if symbol not in self.active_signals:
            # Tüm sinyallerde ara
            for s in reversed(self.signals):
                if s.symbol == symbol and s.status == "ACTIVE":
                    self.active_signals[symbol] = s
                    break
            else:
                logger.warning(f"Aktif sinyal bulunamadı: {symbol}")
                return None

        signal = self.active_signals.pop(symbol)
        now = datetime.now(timezone.utc)

        signal.status = "CLOSED"
        signal.exit_price = exit_price
        signal.exit_reason = exit_reason
        signal.pnl = pnl
        signal.pnl_pct = pnl_pct
        signal.fee = fee
        signal.net_pnl = pnl - fee
        signal.exit_time = now.isoformat()
        signal.exit_time_readable = now.strftime("%d.%m.%Y %H:%M:%S UTC")
        signal.result = "WIN" if pnl > 0 else "LOSS"
        signal.exit_verified_price = exit_verified_price
        signal.exit_data_quality = exit_data_quality

        # Süre hesapla
        try:
            entry_time = datetime.fromisoformat(signal.signal_time)
            signal.duration_seconds = int((now - entry_time).total_seconds())
        except Exception:
            signal.duration_seconds = 0

        self._save_history()
        logger.info(
            f"Sinyal kapatıldı: {signal.signal_id} | {signal.result} | "
            f"P&L: ${pnl:.2f} ({pnl_pct:.2f}%) | Süre: {signal.duration_seconds}s"
        )
        return signal

    def reject_signal(self, signal_id: str, reason: str):
        """Sinyali reddet (risk yönetimi veya veri kalitesi sorunu)."""
        for s in self.signals:
            if s.signal_id == signal_id:
                s.status = "REJECTED"
                s.exit_reason = reason
                self._save_history()
                logger.info(f"Sinyal reddedildi: {signal_id} | {reason}")
                return

    def get_statistics(self) -> dict:
        """Kapsamlı sinyal istatistikleri."""
        closed = [s for s in self.signals if s.status == "CLOSED"]
        active = [s for s in self.signals if s.status == "ACTIVE"]
        rejected = [s for s in self.signals if s.status == "REJECTED"]
        pending = [s for s in self.signals if s.status == "PENDING"]

        wins = [s for s in closed if s.result == "WIN"]
        losses = [s for s in closed if s.result == "LOSS"]

        total_pnl = sum(s.net_pnl for s in closed)
        total_fees = sum(s.fee for s in closed)
        
        win_rate = (len(wins) / len(closed) * 100) if closed else 0
        avg_win = (sum(s.pnl_pct for s in wins) / len(wins)) if wins else 0
        avg_loss = (sum(s.pnl_pct for s in losses) / len(losses)) if losses else 0
        
        # Profit factor
        gross_profit = sum(s.net_pnl for s in wins) if wins else 0
        gross_loss = abs(sum(s.net_pnl for s in losses)) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # Ortalama trade süresi
        avg_duration = 0
        if closed:
            avg_duration = sum(s.duration_seconds for s in closed) / len(closed)

        # Veri kalitesi istatistikleri
        good_quality = len([s for s in self.signals if s.data_quality == "GOOD"])
        warning_quality = len([s for s in self.signals if s.data_quality == "WARNING"])
        fail_quality = len([s for s in self.signals if s.data_quality == "FAIL"])

        # Ardışık kazanç/kayıp
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        current_streak = 0
        streak_type = None
        for s in closed:
            if s.result == streak_type:
                current_streak += 1
            else:
                streak_type = s.result
                current_streak = 1
            if streak_type == "WIN":
                max_consecutive_wins = max(max_consecutive_wins, current_streak)
            elif streak_type == "LOSS":
                max_consecutive_losses = max(max_consecutive_losses, current_streak)

        # Sinyal dağılımı (BUY vs SELL)
        buy_signals = len([s for s in self.signals if s.direction == "BUY"])
        sell_signals = len([s for s in self.signals if s.direction == "SELL"])
        buy_wins = len([s for s in wins if s.direction == "BUY"])
        sell_wins = len([s for s in wins if s.direction == "SELL"])

        # En iyi ve en kötü trade
        best_trade = max(closed, key=lambda s: s.pnl_pct) if closed else None
        worst_trade = min(closed, key=lambda s: s.pnl_pct) if closed else None

        # Bugünkü istatistikler
        today = datetime.now(timezone.utc).date()
        today_signals = [s for s in self.signals 
                        if datetime.fromisoformat(s.signal_time).date() == today]
        today_closed = [s for s in closed
                       if s.exit_time and datetime.fromisoformat(s.exit_time).date() == today]
        today_pnl = sum(s.net_pnl for s in today_closed)

        stats = {
            "total_signals": len(self.signals),
            "active": len(active),
            "closed": len(closed),
            "rejected": len(rejected),
            "pending": len(pending),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "total_fees": total_fees,
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "profit_factor": profit_factor,
            "avg_duration_seconds": avg_duration,
            "max_consecutive_wins": max_consecutive_wins,
            "max_consecutive_losses": max_consecutive_losses,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "buy_win_rate": (buy_wins / buy_signals * 100) if buy_signals > 0 else 0,
            "sell_win_rate": (sell_wins / sell_signals * 100) if sell_signals > 0 else 0,
            "best_trade": best_trade.to_dict() if best_trade else None,
            "worst_trade": worst_trade.to_dict() if worst_trade else None,
            "data_quality": {
                "good": good_quality,
                "warning": warning_quality,
                "fail": fail_quality,
                "good_pct": (good_quality / len(self.signals) * 100) if self.signals else 0,
            },
            "today": {
                "signals": len(today_signals),
                "closed": len(today_closed),
                "pnl": today_pnl,
            },
        }

        # İstatistikleri kaydet
        try:
            os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
            with open(STATS_FILE, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.error(f"İstatistik kaydetme hatası: {e}")

        return stats

    def get_recent_signals(self, count: int = 10) -> list[SignalRecord]:
        """Son N sinyali getir."""
        return self.signals[-count:] if self.signals else []

    def get_active_count(self) -> int:
        """Aktif pozisyon sayısı."""
        return len(self.active_signals)
