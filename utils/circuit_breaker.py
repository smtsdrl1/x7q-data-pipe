"""
Gelişmiş Circuit Breaker
Otomatik trading durdurma mekanizmaları.

Tetikleyiciler:
1. Ardışık kayıp sayısı (3 kayıp → 1s bekle, 5 kayıp → 4s bekle, 7 kayıp → gün boyunca dur)
2. Saatlik/günlük kayıp limiti aşımı
3. Yüksek volatilite tespiti (anormal ATR/BB genişlemesi)
4. Exchange API hatası (bağlantı sorunları)
5. Anormal spread (manipülasyon / düşük likidite)
6. News Kill Zone (yüksek etkili ekonomik olay)
7. Market-wide dump (BTC %5 düştü → tüm altcoin pozisyonlarını kapat)
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from utils.logger import setup_logger

logger = setup_logger("CircuitBreaker")


@dataclass
class CircuitState:
    """Circuit breaker anlık durumu."""
    is_open: bool = False          # True = trading durduruldu
    trigger_reason: str = ""
    triggered_at: float = 0.0     # Unix timestamp
    cool_down_seconds: int = 0
    consecutive_losses: int = 0
    hourly_loss_pct: float = 0.0
    daily_loss_pct: float = 0.0
    total_trips: int = 0
    volatility_paused: bool = False
    news_paused: bool = False
    manual_paused: bool = False


class AdvancedCircuitBreaker:
    """Gelişmiş çok katmanlı circuit breaker sistemi."""
    
    # Ardışık kayıp → bekleme süresi (saniye)
    LOSS_COOLDOWN_MAP = {
        3: 3600,        # 3 kayıp → 1 saat bekle
        5: 14400,       # 5 kayıp → 4 saat bekle
        7: 86400,       # 7 kayıp → 24 saat bekle (günlük dur)
    }
    
    # Saatlik kayıp limiti
    HOURLY_LOSS_LIMIT = 0.03     # %3
    
    # Günlük kayıp limiti (config'den gelmeli ama fallback)
    DAILY_LOSS_LIMIT = 0.06      # %6
    
    # BTC dump eşiği
    BTC_DUMP_THRESHOLD = -0.05   # -5%
    
    # Anormal spread eşiği
    MAX_SPREAD_PCT = 0.10        # %0.1
    
    def __init__(self):
        self.state = CircuitState()
        self._hourly_losses: list[tuple[float, float]] = []    # (timestamp, loss_pct)
        self._daily_losses: list[tuple[float, float]] = []
    
    def check(self) -> tuple[bool, str]:
        """
        Trading yapılabilir mi?
        
        Returns:
            tuple[bool, str]: (can_trade, reason)
        """
        # Manual pause
        if self.state.manual_paused:
            return False, "⛔ Manuel durdurma aktif"
        
        # News pause
        if self.state.news_paused:
            return False, "📰 Haber kill zone aktif"
        
        # Volatility pause
        if self.state.volatility_paused:
            return False, "⚡ Yüksek volatilite duraklatması"
        
        # Circuit açık mı?
        if self.state.is_open:
            elapsed = time.time() - self.state.triggered_at
            remaining = self.state.cool_down_seconds - elapsed
            
            if remaining <= 0:
                # Soğuma süresi geçti, circuit kapat
                self._close_circuit("Soğuma süresi doldu")
                return True, "OK"
            else:
                hours_remaining = remaining / 3600
                return False, (
                    f"⛔ Circuit AÇIK | Sebep: {self.state.trigger_reason} | "
                    f"Kalan: {hours_remaining:.1f}s"
                )
        
        return True, "OK"
    
    def record_trade_result(self, pnl_pct: float):
        """Trade sonucunu kaydet ve circuit koşullarını kontrol et."""
        now = time.time()
        
        if pnl_pct < 0:
            self.state.consecutive_losses += 1
            self._hourly_losses.append((now, abs(pnl_pct)))
            self._daily_losses.append((now, abs(pnl_pct)))
        else:
            self.state.consecutive_losses = 0
        
        # Eski kayıtları temizle
        one_hour_ago = now - 3600
        one_day_ago = now - 86400
        self._hourly_losses = [(t, p) for t, p in self._hourly_losses if t > one_hour_ago]
        self._daily_losses = [(t, p) for t, p in self._daily_losses if t > one_day_ago]
        
        # Ardışık kayıp kontrolü
        for loss_count, cooldown in sorted(self.AdvancedCircuitBreaker.LOSS_COOLDOWN_MAP.items()
                                            if hasattr(self, 'AdvancedCircuitBreaker') else
                                            self.LOSS_COOLDOWN_MAP.items()):
            if self.state.consecutive_losses >= loss_count:
                self._trip(
                    f"{loss_count} ardışık kayıp",
                    cooldown_seconds=cooldown
                )
                return
        
        # Saatlik kayıp limiti
        hourly_loss = sum(p for _, p in self._hourly_losses)
        if hourly_loss > self.HOURLY_LOSS_LIMIT:
            self._trip(
                f"Saatlik kayıp limiti: {hourly_loss:.1%}",
                cooldown_seconds=3600
            )
            return
        
        # Günlük kayıp limiti
        daily_loss = sum(p for _, p in self._daily_losses)
        if daily_loss > self.DAILY_LOSS_LIMIT:
            self._trip(
                f"Günlük kayıp limiti: {daily_loss:.1%}",
                cooldown_seconds=86400
            )
    
    def check_market_wide_dump(self, btc_change_pct: float) -> bool:
        """BTC büyük dump → tüm trading durdur."""
        if btc_change_pct <= self.BTC_DUMP_THRESHOLD:
            self._trip(
                f"BTC market-wide dump: {btc_change_pct:.1%}",
                cooldown_seconds=7200  # 2 saat bekle
            )
            logger.warning(f"MARKET DUMP! BTC {btc_change_pct:.1%} düştü → Circuit trip")
            return True
        return False
    
    def check_spread(self, spread_pct: float, symbol: str) -> bool:
        """Anormal spread → bu sembolde trade durdur."""
        if spread_pct > self.MAX_SPREAD_PCT:
            logger.warning(f"Anormal spread {symbol}: {spread_pct:.3%} > {self.MAX_SPREAD_PCT:.3%}")
            return False  # Bu sembolde trade yapma
        return True
    
    def set_news_kill(self, active: bool, event_name: str = ""):
        """News Kill Zone aktifleştir/kapat."""
        self.state.news_paused = active
        if active:
            logger.info(f"News Kill Zone aktif: {event_name}")
        else:
            logger.info("News Kill Zone kalktı")
    
    def set_volatility_pause(self, active: bool, reason: str = ""):
        """Volatilite duraklatması."""
        self.state.volatility_paused = active
        if active:
            logger.warning(f"Volatilite duraklatması: {reason}")
    
    def manual_stop(self, reason: str = "Manuel durdurma"):
        """Manuel trading durdurma (Telegram komutu ile)."""
        self.state.manual_paused = True
        logger.warning(f"MANUEL DURDURMA: {reason}")
    
    def manual_resume(self):
        """Manuel trading devam (Telegram komutu ile)."""
        self.state.manual_paused = False
        self.state.consecutive_losses = 0
        self._close_circuit("Manuel devam")
        logger.info("Trading Manuel olarak devam ettirildi")
    
    def get_status(self) -> dict:
        """Mevcut circuit breaker durumu."""
        can_trade, reason = self.check()
        return {
            "can_trade": can_trade,
            "reason": reason,
            "is_open": self.state.is_open,
            "manual_paused": self.state.manual_paused,
            "news_paused": self.state.news_paused,
            "volatility_paused": self.state.volatility_paused,
            "consecutive_losses": self.state.consecutive_losses,
            "total_trips": self.state.total_trips,
            "trigger_reason": self.state.trigger_reason,
            "cool_down_remaining": max(
                0,
                self.state.cool_down_seconds - (time.time() - self.state.triggered_at)
            ) if self.state.is_open else 0,
        }
    
    def format_status(self) -> str:
        """Telegram için durum mesajı."""
        status = self.get_status()
        
        if status["can_trade"]:
            lines = [
                "✅ <b>Circuit Breaker:</b> Normal",
                f"🔴 Ardışık Kayıp: {status['consecutive_losses']}",
            ]
        else:
            remaining = status["cool_down_remaining"]
            lines = [
                "⛔ <b>Circuit Breaker:</b> AÇIK",
                f"❗ Sebep: {status['reason']}",
                f"⏱ Kalan: {remaining/3600:.1f} saat",
            ]
        
        if status["news_paused"]:
            lines.append("📰 Haber Kill Zone aktif")
        if status["volatility_paused"]:
            lines.append("⚡ Volatilite duraklatması")
        
        return "\n".join(lines)
    
    def _trip(self, reason: str, cooldown_seconds: int = 3600):
        """Circuit'a trip (aç)."""
        if self.state.is_open:
            return  # Zaten açık
        
        self.state.is_open = True
        self.state.trigger_reason = reason
        self.state.triggered_at = time.time()
        self.state.cool_down_seconds = cooldown_seconds
        self.state.total_trips += 1
        
        logger.error(
            f"🚨 CIRCUIT BREAKER TRİP! Sebep: {reason} | "
            f"Soğuma: {cooldown_seconds/3600:.1f} saat"
        )
    
    def _close_circuit(self, reason: str = ""):
        """Circuit kapat."""
        if not self.state.is_open:
            return
        
        self.state.is_open = False
        self.state.trigger_reason = ""
        logger.info(f"Circuit breaker kapatıldı: {reason}")


# Singleton
circuit_breaker = AdvancedCircuitBreaker()
# Fix self-reference issue
AdvancedCircuitBreaker.LOSS_COOLDOWN_MAP = {
    3: 3600,
    5: 14400,
    7: 86400,
}
