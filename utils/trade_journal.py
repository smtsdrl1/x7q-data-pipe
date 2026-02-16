"""
Profesyonel Trade Günlüğü (Trade Journal)
Her trade'in tam yaşam döngüsünü izler:
- Sinyal tespit anı ve o anki gerçek fiyat
- İşleme alınma anı ve doğrulanmış fiyat
- Pozisyon açılma detayları
- Pozisyon izleme sürecindeki fiyat hareketleri
- Kapanış anı ve sonuç
- Bildirim geçmişi
- Her adımdaki fiyat doğrulama durumu

NULL veya sahte veri KABUL ETMEZ.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional
from utils.logger import setup_logger

logger = setup_logger("TradeJournal")

JOURNAL_FILE = "data/trade_journal.json"
JOURNAL_STATS_FILE = "data/journal_stats.json"


@dataclass
class PriceSnapshot:
    """Belirli bir andaki fiyat snapshot'ı."""
    timestamp: str                  # ISO format
    timestamp_readable: str         # Okunabilir
    price: float                    # Son fiyat
    bid: float = 0.0               # Bid
    ask: float = 0.0               # Ask
    spread_pct: float = 0.0        # Spread yüzdesi
    volume_24h: float = 0.0        # 24s hacim
    source: str = ""               # Veri kaynağı
    verified: bool = False          # Doğrulandı mı
    latency_ms: float = 0.0        # Çekme süresi
    event: str = ""                 # Bu snapshot neden alındı

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class JournalEntry:
    """Tek bir trade'in tam günlük kaydı."""
    # === KİMLİK ===
    journal_id: str                     # Benzersiz günlük ID
    signal_id: str                      # İlgili sinyal ID
    symbol: str                         # İşlem çifti
    direction: str                      # BUY/SELL

    # === ZAMAN ÇİZELGESİ ===
    signal_detected_at: str = ""        # Sinyal tespit anı
    signal_detected_readable: str = ""
    trade_opened_at: str = ""           # İşlem açılma anı
    trade_opened_readable: str = ""
    trade_closed_at: str = ""           # İşlem kapanma anı
    trade_closed_readable: str = ""
    total_duration_seconds: int = 0     # Toplam süre

    # === FİYAT BİLGİLERİ ===
    # Sinyal anı
    signal_price: float = 0.0          # Strateji motorundan gelen fiyat
    signal_verified_price: float = 0.0  # Sinyal anı doğrulanmış fiyat
    signal_price_deviation_pct: float = 0.0  # Sapma yüzdesi
    signal_data_quality: str = ""       # GOOD/WARNING/FAIL

    # Giriş
    entry_price: float = 0.0           # Gerçek giriş fiyatı
    entry_slippage_pct: float = 0.0    # Giriş slippage

    # Çıkış
    exit_price: float = 0.0            # Gerçek çıkış fiyatı
    exit_verified_price: float = 0.0   # Çıkış doğrulanmış fiyat
    exit_data_quality: str = ""        # GOOD/WARNING/FAIL

    # === STRATEJİ DETAYI ===
    composite_score: float = 0.0       # Bileşik skor
    contributing_strategies: list = field(default_factory=list)  # Katkıda bulunan stratejiler
    rsi_at_entry: float = 0.0          # Girişteki RSI
    volume_ratio_at_entry: float = 0.0  # Girişteki hacim oranı
    signal_reasons: list = field(default_factory=list)  # Sinyal sebepleri

    # === POZİSYON DETAYLARI ===
    stop_loss: float = 0.0
    take_profit: float = 0.0
    trailing_stop_final: float = 0.0   # Son trailing stop değeri
    position_size_usd: float = 0.0     # Pozisyon büyüklüğü (USD)
    quantity: float = 0.0              # Miktar

    # === SONUÇ ===
    status: str = "OPEN"              # OPEN / CLOSED / REJECTED
    exit_reason: str = ""              # stop_loss/take_profit/trailing_stop
    pnl: float = 0.0                   # Brüt P&L
    pnl_pct: float = 0.0              # P&L yüzdesi
    fee_total: float = 0.0            # Toplam fee
    net_pnl: float = 0.0              # Net P&L (fee sonrası)
    result: str = ""                   # WIN / LOSS

    # === FİYAT GEÇMİŞİ ===
    price_snapshots: list = field(default_factory=list)  # PriceSnapshot listesi

    # === BİLDİRİM İZLEME ===
    notification_ids: list = field(default_factory=list)  # İlgili bildirim ID'leri
    notifications_sent: int = 0         # Gönderilen bildirim sayısı
    notifications_failed: int = 0       # Başarısız bildirim sayısı

    # === PORTFÖY DURUMU ===
    portfolio_before: float = 0.0      # İşlem öncesi portföy
    portfolio_after: float = 0.0       # İşlem sonrası portföy
    portfolio_impact_pct: float = 0.0  # Portföy etkisi yüzdesi

    # === DOĞRULAMA ===
    all_prices_verified: bool = False   # Tüm fiyatlar doğrulandı mı
    data_integrity_score: float = 0.0   # Veri bütünlük skoru (0-100)

    def to_dict(self) -> dict:
        return asdict(self)


class TradeJournal:
    """
    Profesyonel Trade Günlüğü:
    - Her trade'in A'dan Z'ye kaydını tutar
    - Fiyat snapshot'ları ile anlık piyasa durumunu loglar
    - Bildirim geçmişini trade ile ilişkilendirir
    - Kapsamlı analiz ve raporlama sağlar
    """

    def __init__(self):
        self.entries: list[JournalEntry] = []
        self.active_entries: dict[str, JournalEntry] = {}  # symbol → entry
        self._entry_counter = 0
        self._load_journal()

    def _load_journal(self):
        """Günlüğü yükle."""
        try:
            if os.path.exists(JOURNAL_FILE):
                with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.entries = [JournalEntry(**e) for e in data]
                    self._entry_counter = len(self.entries)
                    # Aktif entry'leri yükle
                    for entry in self.entries:
                        if entry.status == "OPEN":
                            self.active_entries[entry.symbol] = entry
                    logger.info(
                        f"Trade günlüğü yüklendi: {len(self.entries)} kayıt, "
                        f"{len(self.active_entries)} aktif"
                    )
        except Exception as e:
            logger.error(f"Günlük yükleme hatası: {e}")
            self.entries = []

    def _save_journal(self):
        """Günlüğü kaydet."""
        try:
            os.makedirs(os.path.dirname(JOURNAL_FILE), exist_ok=True)
            with open(JOURNAL_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    [e.to_dict() for e in self.entries],
                    f, ensure_ascii=False, indent=2, default=str,
                )
        except Exception as e:
            logger.error(f"Günlük kaydetme hatası: {e}")

    def open_entry(
        self,
        signal_id: str,
        symbol: str,
        direction: str,
        analysis: dict,
        verification: dict,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        quantity: float,
        portfolio_value: float,
    ) -> JournalEntry:
        """Yeni trade günlük kaydı oluştur."""
        self._entry_counter += 1
        now = datetime.now(timezone.utc)

        journal_id = f"TJ_{now.strftime('%Y%m%d_%H%M%S')}_{symbol.replace('/', '_')}"

        vp = verification.get("verified_price")
        signal_price = analysis.get("price", 0)

        # Giriş slippage hesapla
        entry_slippage = 0.0
        if signal_price > 0 and entry_price > 0:
            entry_slippage = ((entry_price - signal_price) / signal_price) * 100

        entry = JournalEntry(
            journal_id=journal_id,
            signal_id=signal_id,
            symbol=symbol,
            direction=direction,
            # Zamanlama
            signal_detected_at=now.isoformat(),
            signal_detected_readable=now.strftime("%d.%m.%Y %H:%M:%S.%f")[:-3] + " UTC",
            trade_opened_at=now.isoformat(),
            trade_opened_readable=now.strftime("%d.%m.%Y %H:%M:%S.%f")[:-3] + " UTC",
            # Sinyal fiyatları
            signal_price=signal_price,
            signal_verified_price=verification.get("real_price", 0),
            signal_price_deviation_pct=verification.get("deviation_pct", 0),
            signal_data_quality=verification.get("data_quality", "FAIL"),
            # Giriş
            entry_price=entry_price,
            entry_slippage_pct=entry_slippage,
            # Strateji
            composite_score=analysis.get("composite_score", 0),
            contributing_strategies=analysis.get("buy_reasons", [])
            if direction == "BUY"
            else analysis.get("sell_reasons", []),
            rsi_at_entry=analysis.get("rsi", 0),
            volume_ratio_at_entry=analysis.get("volume_ratio", 0),
            signal_reasons=analysis.get("buy_reasons", [])
            if direction == "BUY"
            else analysis.get("sell_reasons", []),
            # Pozisyon
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_stop_final=stop_loss,
            position_size_usd=quantity * entry_price,
            quantity=quantity,
            # Durum
            status="OPEN",
            portfolio_before=portfolio_value,
        )

        # İlk fiyat snapshot
        if vp:
            snapshot = PriceSnapshot(
                timestamp=now.isoformat(),
                timestamp_readable=now.strftime("%d.%m.%Y %H:%M:%S.%f")[:-3] + " UTC",
                price=vp.price if vp.verified else 0,
                bid=vp.bid,
                ask=vp.ask,
                spread_pct=vp.spread,
                volume_24h=vp.volume_24h,
                source=vp.source,
                verified=vp.verified,
                latency_ms=vp.latency_ms,
                event="TRADE_OPEN",
            )
            entry.price_snapshots.append(snapshot.to_dict())

        self.entries.append(entry)
        self.active_entries[symbol] = entry
        self._save_journal()

        logger.info(
            f"Günlük kaydı açıldı: {journal_id} | {direction} {symbol} @ "
            f"{entry_price} | Kalite: {entry.signal_data_quality}"
        )
        return entry

    def add_price_snapshot(
        self, symbol: str, verified_price, event: str = "MONITORING"
    ):
        """Aktif trade'e fiyat snapshot'ı ekle."""
        if symbol not in self.active_entries:
            return

        entry = self.active_entries[symbol]
        now = datetime.now(timezone.utc)

        snapshot = PriceSnapshot(
            timestamp=now.isoformat(),
            timestamp_readable=now.strftime("%d.%m.%Y %H:%M:%S.%f")[:-3] + " UTC",
            price=verified_price.price if verified_price.verified else 0,
            bid=verified_price.bid,
            ask=verified_price.ask,
            spread_pct=verified_price.spread,
            volume_24h=verified_price.volume_24h,
            source=verified_price.source,
            verified=verified_price.verified,
            latency_ms=verified_price.latency_ms,
            event=event,
        )
        entry.price_snapshots.append(snapshot.to_dict())

        # Trailing stop güncelle
        if hasattr(verified_price, 'price') and verified_price.price > 0:
            if verified_price.price > entry.entry_price:
                # Fiyat yükseldi, trailing stop güncellenmiş olabilir
                pass

    def close_entry(
        self,
        symbol: str,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        pnl_pct: float,
        fee: float,
        exit_verified_price=None,
        portfolio_value: float = 0.0,
        trailing_stop_final: float = 0.0,
    ) -> Optional[JournalEntry]:
        """Trade günlük kaydını kapat."""
        if symbol not in self.active_entries:
            # Tüm entry'lerde ara
            for e in reversed(self.entries):
                if e.symbol == symbol and e.status == "OPEN":
                    self.active_entries[symbol] = e
                    break
            else:
                logger.warning(f"Aktif günlük kaydı bulunamadı: {symbol}")
                return None

        entry = self.active_entries.pop(symbol)
        now = datetime.now(timezone.utc)

        # Kapanış bilgilerini doldur
        entry.status = "CLOSED"
        entry.trade_closed_at = now.isoformat()
        entry.trade_closed_readable = (
            now.strftime("%d.%m.%Y %H:%M:%S.%f")[:-3] + " UTC"
        )
        entry.exit_price = exit_price
        entry.exit_reason = exit_reason
        entry.pnl = pnl
        entry.pnl_pct = pnl_pct
        entry.fee_total = fee
        entry.net_pnl = pnl - fee
        entry.result = "WIN" if pnl > 0 else "LOSS"
        entry.trailing_stop_final = trailing_stop_final
        entry.portfolio_after = portfolio_value

        # Portföy etkisi
        if entry.portfolio_before > 0:
            entry.portfolio_impact_pct = (
                (portfolio_value - entry.portfolio_before) / entry.portfolio_before
            ) * 100

        # Süre hesapla
        try:
            opened = datetime.fromisoformat(entry.trade_opened_at)
            entry.total_duration_seconds = int((now - opened).total_seconds())
        except Exception:
            entry.total_duration_seconds = 0

        # Çıkış fiyat doğrulama
        if exit_verified_price:
            entry.exit_verified_price = (
                exit_verified_price.price if exit_verified_price.verified else 0
            )
            entry.exit_data_quality = (
                "GOOD" if exit_verified_price.verified else "FAIL"
            )

            # Son fiyat snapshot
            snapshot = PriceSnapshot(
                timestamp=now.isoformat(),
                timestamp_readable=now.strftime("%d.%m.%Y %H:%M:%S.%f")[:-3] + " UTC",
                price=exit_verified_price.price if exit_verified_price.verified else 0,
                bid=exit_verified_price.bid,
                ask=exit_verified_price.ask,
                spread_pct=exit_verified_price.spread,
                volume_24h=exit_verified_price.volume_24h,
                source=exit_verified_price.source,
                verified=exit_verified_price.verified,
                latency_ms=exit_verified_price.latency_ms,
                event="TRADE_CLOSE",
            )
            entry.price_snapshots.append(snapshot.to_dict())

        # Veri bütünlük skoru hesapla
        entry.data_integrity_score = self._calculate_integrity_score(entry)
        entry.all_prices_verified = (
            entry.signal_data_quality in ("GOOD", "WARNING")
            and entry.exit_data_quality in ("GOOD", "WARNING", "")
        )

        self._save_journal()

        logger.info(
            f"Günlük kaydı kapatıldı: {entry.journal_id} | {entry.result} | "
            f"P&L: ${pnl:.2f} ({pnl_pct:.2f}%) | "
            f"Süre: {entry.total_duration_seconds}s | "
            f"Bütünlük: {entry.data_integrity_score:.0f}/100"
        )
        return entry

    def reject_entry(self, symbol: str, signal_id: str, reason: str):
        """Trade'i reddet."""
        # Eğer aktif entry varsa
        if symbol in self.active_entries:
            entry = self.active_entries.pop(symbol)
            entry.status = "REJECTED"
            entry.exit_reason = reason
            self._save_journal()
            return

        # Son entry'de ara
        for e in reversed(self.entries):
            if e.signal_id == signal_id and e.status == "OPEN":
                e.status = "REJECTED"
                e.exit_reason = reason
                self._save_journal()
                return

    def add_notification_id(self, symbol: str, notification_id: str, success: bool):
        """Trade'e bildirim ID'si ekle."""
        entry = self.active_entries.get(symbol)
        if not entry:
            # Kapalı entry'lerde ara (kapanış bildirimleri için)
            for e in reversed(self.entries):
                if e.symbol == symbol:
                    entry = e
                    break

        if entry:
            entry.notification_ids.append(notification_id)
            if success:
                entry.notifications_sent += 1
            else:
                entry.notifications_failed += 1
            self._save_journal()

    def _calculate_integrity_score(self, entry: JournalEntry) -> float:
        """Veri bütünlük skoru hesapla (0-100)."""
        score = 0.0

        # Sinyal fiyat doğrulama (25 puan)
        if entry.signal_data_quality == "GOOD":
            score += 25
        elif entry.signal_data_quality == "WARNING":
            score += 15

        # Çıkış fiyat doğrulama (25 puan)
        if entry.exit_data_quality == "GOOD":
            score += 25
        elif entry.exit_data_quality == "WARNING":
            score += 15
        elif entry.status == "OPEN":
            score += 25  # Henüz kapanmadı, tam puan

        # Fiyat snapshot'ları (20 puan)
        snapshots = entry.price_snapshots
        verified_snapshots = [
            s for s in snapshots if s.get("verified", False)
        ]
        if snapshots:
            snapshot_ratio = len(verified_snapshots) / len(snapshots)
            score += snapshot_ratio * 20

        # Bildirim başarısı (15 puan)
        total_notifs = entry.notifications_sent + entry.notifications_failed
        if total_notifs > 0:
            notif_success_rate = entry.notifications_sent / total_notifs
            score += notif_success_rate * 15
        elif entry.status == "OPEN":
            score += 15  # Henüz bildirim olmamış olabilir

        # Zaman bilgisi eksiksizliği (15 puan)
        if entry.signal_detected_at:
            score += 5
        if entry.trade_opened_at:
            score += 5
        if entry.trade_closed_at or entry.status == "OPEN":
            score += 5

        return min(score, 100)

    def get_statistics(self) -> dict:
        """Kapsamlı günlük istatistikleri."""
        closed = [e for e in self.entries if e.status == "CLOSED"]
        active = [e for e in self.entries if e.status == "OPEN"]
        rejected = [e for e in self.entries if e.status == "REJECTED"]

        wins = [e for e in closed if e.result == "WIN"]
        losses = [e for e in closed if e.result == "LOSS"]

        # Genel performans
        total_pnl = sum(e.net_pnl for e in closed)
        total_fees = sum(e.fee_total for e in closed)
        win_rate = (len(wins) / len(closed) * 100) if closed else 0

        # Profit factor
        gross_profit = sum(e.net_pnl for e in wins) if wins else 0
        gross_loss = abs(sum(e.net_pnl for e in losses)) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # Ortalamalar
        avg_win_pct = (sum(e.pnl_pct for e in wins) / len(wins)) if wins else 0
        avg_loss_pct = (sum(e.pnl_pct for e in losses) / len(losses)) if losses else 0
        avg_duration = (
            sum(e.total_duration_seconds for e in closed) / len(closed)
        ) if closed else 0

        # Veri bütünlük ortalaması
        integrity_scores = [e.data_integrity_score for e in closed if e.data_integrity_score > 0]
        avg_integrity = (
            sum(integrity_scores) / len(integrity_scores)
        ) if integrity_scores else 0

        # Çıkış nedeni dağılımı
        exit_reasons = {}
        for e in closed:
            r = e.exit_reason
            exit_reasons[r] = exit_reasons.get(r, 0) + 1

        # Slippage analizi
        slippages = [e.entry_slippage_pct for e in closed if e.entry_slippage_pct != 0]
        avg_slippage = (sum(abs(s) for s in slippages) / len(slippages)) if slippages else 0

        # En iyi / en kötü trade
        best = max(closed, key=lambda e: e.net_pnl) if closed else None
        worst = min(closed, key=lambda e: e.net_pnl) if closed else None

        # Strateji skor dağılımı
        win_scores = [e.composite_score for e in wins]
        loss_scores = [e.composite_score for e in losses]
        avg_win_score = (sum(win_scores) / len(win_scores)) if win_scores else 0
        avg_loss_score = (sum(loss_scores) / len(loss_scores)) if loss_scores else 0

        # Bugünkü istatistikler
        today = datetime.now(timezone.utc).date()
        today_entries = [
            e for e in self.entries
            if e.signal_detected_at
            and datetime.fromisoformat(e.signal_detected_at).date() == today
        ]
        today_closed = [e for e in today_entries if e.status == "CLOSED"]
        today_pnl = sum(e.net_pnl for e in today_closed)

        # Haftalık trend
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        weekly_entries = [
            e for e in closed
            if e.trade_closed_at
            and datetime.fromisoformat(e.trade_closed_at) > week_ago
        ]
        weekly_pnl = sum(e.net_pnl for e in weekly_entries)
        weekly_wins = [e for e in weekly_entries if e.result == "WIN"]
        weekly_win_rate = (
            len(weekly_wins) / len(weekly_entries) * 100
        ) if weekly_entries else 0

        stats = {
            "total_entries": len(self.entries),
            "active": len(active),
            "closed": len(closed),
            "rejected": len(rejected),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "total_fees": total_fees,
            "profit_factor": profit_factor,
            "avg_win_pct": avg_win_pct,
            "avg_loss_pct": avg_loss_pct,
            "avg_duration_seconds": avg_duration,
            "avg_data_integrity": avg_integrity,
            "avg_slippage_pct": avg_slippage,
            "exit_reasons": exit_reasons,
            "strategy_scores": {
                "avg_win_score": avg_win_score,
                "avg_loss_score": avg_loss_score,
            },
            "best_trade": {
                "symbol": best.symbol,
                "net_pnl": best.net_pnl,
                "pnl_pct": best.pnl_pct,
                "date": best.trade_closed_readable,
            } if best else None,
            "worst_trade": {
                "symbol": worst.symbol,
                "net_pnl": worst.net_pnl,
                "pnl_pct": worst.pnl_pct,
                "date": worst.trade_closed_readable,
            } if worst else None,
            "today": {
                "entries": len(today_entries),
                "closed": len(today_closed),
                "pnl": today_pnl,
            },
            "weekly": {
                "trades": len(weekly_entries),
                "pnl": weekly_pnl,
                "win_rate": weekly_win_rate,
            },
        }

        # İstatistikleri kaydet
        try:
            os.makedirs(os.path.dirname(JOURNAL_STATS_FILE), exist_ok=True)
            with open(JOURNAL_STATS_FILE, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.error(f"Günlük istatistik kaydetme hatası: {e}")

        return stats

    def get_recent(self, count: int = 10) -> list[JournalEntry]:
        """Son N günlük kaydını getir."""
        return self.entries[-count:] if self.entries else []

    def get_entry_by_signal(self, signal_id: str) -> Optional[JournalEntry]:
        """Signal ID ile günlük kaydını bul."""
        for e in reversed(self.entries):
            if e.signal_id == signal_id:
                return e
        return None

    def get_full_trade_report(self, journal_id: str) -> Optional[dict]:
        """Tek bir trade'in tam detaylı raporunu getir."""
        entry = None
        for e in self.entries:
            if e.journal_id == journal_id:
                entry = e
                break

        if not entry:
            return None

        # Fiyat snapshot timeline
        snapshot_timeline = []
        for s in entry.price_snapshots:
            snapshot_timeline.append({
                "time": s.get("timestamp_readable", ""),
                "price": s.get("price", 0),
                "event": s.get("event", ""),
                "verified": s.get("verified", False),
            })

        duration_text = ""
        if entry.total_duration_seconds > 0:
            hours = entry.total_duration_seconds // 3600
            mins = (entry.total_duration_seconds % 3600) // 60
            secs = entry.total_duration_seconds % 60
            if hours > 0:
                duration_text = f"{hours}s {mins}dk {secs}sn"
            else:
                duration_text = f"{mins}dk {secs}sn"

        return {
            "journal_id": entry.journal_id,
            "symbol": entry.symbol,
            "direction": entry.direction,
            "status": entry.status,
            "result": entry.result,
            "timeline": {
                "signal_detected": entry.signal_detected_readable,
                "trade_opened": entry.trade_opened_readable,
                "trade_closed": entry.trade_closed_readable,
                "duration": duration_text,
            },
            "prices": {
                "signal_price": entry.signal_price,
                "verified_entry": entry.signal_verified_price,
                "entry": entry.entry_price,
                "exit": entry.exit_price,
                "verified_exit": entry.exit_verified_price,
                "slippage": entry.entry_slippage_pct,
            },
            "strategy": {
                "score": entry.composite_score,
                "rsi": entry.rsi_at_entry,
                "volume_ratio": entry.volume_ratio_at_entry,
                "reasons": entry.signal_reasons,
            },
            "position": {
                "size_usd": entry.position_size_usd,
                "quantity": entry.quantity,
                "stop_loss": entry.stop_loss,
                "take_profit": entry.take_profit,
                "trailing_stop": entry.trailing_stop_final,
            },
            "result_detail": {
                "pnl": entry.pnl,
                "pnl_pct": entry.pnl_pct,
                "fee": entry.fee_total,
                "net_pnl": entry.net_pnl,
                "exit_reason": entry.exit_reason,
            },
            "data_quality": {
                "signal_quality": entry.signal_data_quality,
                "exit_quality": entry.exit_data_quality,
                "integrity_score": entry.data_integrity_score,
                "all_verified": entry.all_prices_verified,
            },
            "portfolio": {
                "before": entry.portfolio_before,
                "after": entry.portfolio_after,
                "impact_pct": entry.portfolio_impact_pct,
            },
            "notifications": {
                "sent": entry.notifications_sent,
                "failed": entry.notifications_failed,
                "ids": entry.notification_ids,
            },
            "price_history": snapshot_timeline,
        }
