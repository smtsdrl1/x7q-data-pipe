"""
Bildirim Yönetim Sistemi
Her bildirimi takip eder: gönderim zamanı, teslimat durumu, o anki fiyat,
sinyal referansı ve tüm metadata.
Hiçbir bildirim kayıp olmaz, her detay loglanır.
"""

import json
import os
import asyncio
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable, Awaitable
from enum import Enum
from utils.logger import setup_logger

logger = setup_logger("NotificationManager")

NOTIFICATIONS_FILE = "data/notifications_history.json"
NOTIFICATION_STATS_FILE = "data/notification_stats.json"


class NotificationType(str, Enum):
    """Bildirim tipleri."""
    SIGNAL_NEW = "SIGNAL_NEW"               # Yeni sinyal tespit edildi
    SIGNAL_REJECTED = "SIGNAL_REJECTED"     # Sinyal reddedildi
    TRADE_OPENED = "TRADE_OPENED"           # Paper trade açıldı
    TRADE_CLOSED = "TRADE_CLOSED"           # Paper trade kapandı
    PERIODIC_REPORT = "PERIODIC_REPORT"     # 15dk periyodik rapor
    DAILY_SUMMARY = "DAILY_SUMMARY"         # Günlük özet
    RISK_ALERT = "RISK_ALERT"              # Risk uyarısı
    SYSTEM_START = "SYSTEM_START"           # Sistem başlatıldı
    SYSTEM_STOP = "SYSTEM_STOP"            # Sistem durduruldu
    PRICE_ALERT = "PRICE_ALERT"            # Fiyat uyarısı
    ERROR_ALERT = "ERROR_ALERT"            # Hata bildirimi


class DeliveryStatus(str, Enum):
    """Teslimat durumları."""
    PENDING = "PENDING"         # Gönderilmedi henüz
    SENT = "SENT"               # Başarıyla gönderildi
    FAILED = "FAILED"           # Gönderim başarısız
    RETRY = "RETRY"             # Yeniden deneniyor


@dataclass
class NotificationRecord:
    """Tek bir bildirim kaydı — eksiksiz audit trail."""
    # Kimlik
    notification_id: str                    # Benzersiz bildirim ID
    notification_type: str                  # NotificationType

    # Zamanlama
    created_at: str                         # Bildirim oluşturulma anı (ISO)
    created_at_readable: str                # Okunabilir format
    sent_at: str = ""                       # Gönderim anı (ISO)
    sent_at_readable: str = ""              # Okunabilir gönderim
    delivery_latency_ms: float = 0.0        # Oluşturma → gönderim süresi

    # Teslimat
    delivery_status: str = "PENDING"        # DeliveryStatus
    retry_count: int = 0                    # Yeniden deneme sayısı
    error_message: str = ""                 # Hata mesajı (varsa)

    # Sinyal referansı
    signal_id: str = ""                     # İlgili sinyal ID
    symbol: str = ""                        # İşlem çifti
    direction: str = ""                     # BUY/SELL

    # Bildirim anındaki fiyat bilgisi
    price_at_notification: float = 0.0      # Bildirim gönderildiğinde fiyat
    price_verified: bool = False            # Fiyat doğrulandı mı
    price_source: str = ""                  # Fiyat kaynağı (ticker/ohlcv)
    price_fetch_latency_ms: float = 0.0     # Fiyat çekme süresi
    bid_at_notification: float = 0.0        # Bildirim anı bid
    ask_at_notification: float = 0.0        # Bildirim anı ask
    spread_at_notification: float = 0.0     # Bildirim anı spread

    # İçerik
    message_length: int = 0                 # Mesaj uzunluğu (karakter)
    message_parts: int = 1                  # Kaç parçaya bölündü

    # Ek metadata
    trade_pnl: float = 0.0                 # İlgili trade P&L (kapanışta)
    trade_result: str = ""                  # WIN/LOSS (kapanışta)
    portfolio_value: float = 0.0           # O anki portföy değeri
    open_positions_count: int = 0          # O anki açık pozisyon sayısı

    def to_dict(self) -> dict:
        return asdict(self)


class NotificationManager:
    """
    Bildirim yöneticisi:
    - Her bildirimi ID ile kayıt altına alır
    - Gönderim zamanını milisaniye hassasiyetle loglar
    - O andaki gerçek fiyatı kaydeder
    - Teslimat durumunu izler
    - Hataları ve yeniden denemeleri takip eder
    - İstatistik ve analiz üretir
    """

    def __init__(self):
        self.notifications: list[NotificationRecord] = []
        self._notification_counter = 0
        self._load_history()

    def _load_history(self):
        """Geçmiş bildirimleri yükle."""
        try:
            if os.path.exists(NOTIFICATIONS_FILE):
                with open(NOTIFICATIONS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.notifications = [NotificationRecord(**n) for n in data]
                    self._notification_counter = len(self.notifications)
                    logger.info(f"Bildirim geçmişi yüklendi: {len(self.notifications)} kayıt")
        except Exception as e:
            logger.error(f"Bildirim geçmişi yükleme hatası: {e}")
            self.notifications = []

    def _save_history(self):
        """Bildirim geçmişini kaydet."""
        try:
            os.makedirs(os.path.dirname(NOTIFICATIONS_FILE), exist_ok=True)
            with open(NOTIFICATIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    [n.to_dict() for n in self.notifications],
                    f, ensure_ascii=False, indent=2, default=str
                )
        except Exception as e:
            logger.error(f"Bildirim kaydetme hatası: {e}")

    def create_notification(
        self,
        notification_type: NotificationType,
        symbol: str = "",
        direction: str = "",
        signal_id: str = "",
        portfolio_value: float = 0.0,
        open_positions_count: int = 0,
        trade_pnl: float = 0.0,
        trade_result: str = "",
    ) -> NotificationRecord:
        """Yeni bildirim kaydı oluştur."""
        self._notification_counter += 1
        now = datetime.now(timezone.utc)

        notification_id = (
            f"NTF_{now.strftime('%Y%m%d_%H%M%S')}_{self._notification_counter:04d}"
        )

        record = NotificationRecord(
            notification_id=notification_id,
            notification_type=notification_type.value,
            created_at=now.isoformat(),
            created_at_readable=now.strftime("%d.%m.%Y %H:%M:%S.%f")[:-3] + " UTC",
            symbol=symbol,
            direction=direction,
            signal_id=signal_id,
            portfolio_value=portfolio_value,
            open_positions_count=open_positions_count,
            trade_pnl=trade_pnl,
            trade_result=trade_result,
        )

        self.notifications.append(record)
        return record

    def record_price_at_notification(
        self,
        record: NotificationRecord,
        verified_price,  # VerifiedPrice object
    ):
        """Bildirim anındaki fiyatı kaydet."""
        if verified_price and verified_price.verified:
            record.price_at_notification = verified_price.price
            record.price_verified = True
            record.price_source = verified_price.source
            record.price_fetch_latency_ms = verified_price.latency_ms
            record.bid_at_notification = verified_price.bid
            record.ask_at_notification = verified_price.ask
            record.spread_at_notification = verified_price.spread
        else:
            record.price_verified = False
            record.error_message = (
                verified_price.error if verified_price else "Fiyat verisi alınamadı"
            )

    def mark_sent(
        self,
        record: NotificationRecord,
        message_length: int = 0,
        message_parts: int = 1,
    ):
        """Bildirimi başarıyla gönderildi olarak işaretle."""
        now = datetime.now(timezone.utc)
        record.delivery_status = DeliveryStatus.SENT.value
        record.sent_at = now.isoformat()
        record.sent_at_readable = now.strftime("%d.%m.%Y %H:%M:%S.%f")[:-3] + " UTC"
        record.message_length = message_length
        record.message_parts = message_parts

        # Oluşturma → gönderim gecikme süresi hesapla
        try:
            created = datetime.fromisoformat(record.created_at)
            record.delivery_latency_ms = (now - created).total_seconds() * 1000
        except Exception:
            record.delivery_latency_ms = 0.0

        self._save_history()
        logger.info(
            f"Bildirim gönderildi: {record.notification_id} | "
            f"Tip: {record.notification_type} | "
            f"Gecikme: {record.delivery_latency_ms:.0f}ms"
        )

    def mark_failed(self, record: NotificationRecord, error: str):
        """Bildirimi başarısız olarak işaretle."""
        record.delivery_status = DeliveryStatus.FAILED.value
        record.error_message = error
        record.retry_count += 1
        self._save_history()
        logger.error(
            f"Bildirim başarısız: {record.notification_id} | "
            f"Hata: {error} | Deneme: {record.retry_count}"
        )

    def get_statistics(self) -> dict:
        """Kapsamlı bildirim istatistikleri."""
        total = len(self.notifications)
        sent = [n for n in self.notifications if n.delivery_status == "SENT"]
        failed = [n for n in self.notifications if n.delivery_status == "FAILED"]
        pending = [n for n in self.notifications if n.delivery_status == "PENDING"]

        # Tip bazlı dağılım
        type_distribution = {}
        for n in self.notifications:
            t = n.notification_type
            type_distribution[t] = type_distribution.get(t, 0) + 1

        # Ortalama gecikme
        latencies = [n.delivery_latency_ms for n in sent if n.delivery_latency_ms > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        max_latency = max(latencies) if latencies else 0
        min_latency = min(latencies) if latencies else 0

        # Fiyat doğrulama oranı
        price_checks = [n for n in self.notifications if n.symbol]
        price_verified = [n for n in price_checks if n.price_verified]
        price_verify_rate = (
            len(price_verified) / len(price_checks) * 100
        ) if price_checks else 0

        # Ortalama fiyat çekme süresi
        price_latencies = [
            n.price_fetch_latency_ms for n in price_verified
            if n.price_fetch_latency_ms > 0
        ]
        avg_price_latency = (
            sum(price_latencies) / len(price_latencies)
        ) if price_latencies else 0

        # Başarı oranı
        delivery_rate = (len(sent) / total * 100) if total > 0 else 0

        # Bugünkü istatistikler
        today = datetime.now(timezone.utc).date()
        today_notifications = [
            n for n in self.notifications
            if datetime.fromisoformat(n.created_at).date() == today
        ]
        today_sent = [n for n in today_notifications if n.delivery_status == "SENT"]
        today_failed = [n for n in today_notifications if n.delivery_status == "FAILED"]

        # Saatlik dağılım (bugün)
        hourly = {}
        for n in today_notifications:
            hour = datetime.fromisoformat(n.created_at).hour
            hourly[hour] = hourly.get(hour, 0) + 1

        # Son 24 saat trade bildirimleri
        last_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        trade_notifications_24h = [
            n for n in self.notifications
            if n.notification_type in ("TRADE_OPENED", "TRADE_CLOSED")
            and datetime.fromisoformat(n.created_at) > last_24h
        ]
        trade_opens_24h = [
            n for n in trade_notifications_24h
            if n.notification_type == "TRADE_OPENED"
        ]
        trade_closes_24h = [
            n for n in trade_notifications_24h
            if n.notification_type == "TRADE_CLOSED"
        ]
        wins_24h = [n for n in trade_closes_24h if n.trade_result == "WIN"]
        losses_24h = [n for n in trade_closes_24h if n.trade_result == "LOSS"]

        stats = {
            "total_notifications": total,
            "sent": len(sent),
            "failed": len(failed),
            "pending": len(pending),
            "delivery_rate": delivery_rate,
            "type_distribution": type_distribution,
            "latency": {
                "avg_ms": avg_latency,
                "max_ms": max_latency,
                "min_ms": min_latency,
            },
            "price_verification": {
                "total_checks": len(price_checks),
                "verified": len(price_verified),
                "verify_rate": price_verify_rate,
                "avg_price_latency_ms": avg_price_latency,
            },
            "today": {
                "total": len(today_notifications),
                "sent": len(today_sent),
                "failed": len(today_failed),
                "hourly_distribution": hourly,
            },
            "last_24h_trades": {
                "opened": len(trade_opens_24h),
                "closed": len(trade_closes_24h),
                "wins": len(wins_24h),
                "losses": len(losses_24h),
                "win_rate": (
                    len(wins_24h) / len(trade_closes_24h) * 100
                ) if trade_closes_24h else 0,
            },
        }

        # İstatistikleri kaydet
        try:
            os.makedirs(os.path.dirname(NOTIFICATION_STATS_FILE), exist_ok=True)
            with open(NOTIFICATION_STATS_FILE, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.error(f"Bildirim istatistik kaydetme hatası: {e}")

        return stats

    def get_recent(self, count: int = 20) -> list[NotificationRecord]:
        """Son N bildirimi getir."""
        return self.notifications[-count:] if self.notifications else []

    def get_by_signal(self, signal_id: str) -> list[NotificationRecord]:
        """Bir sinyale ait tüm bildirimleri getir."""
        return [n for n in self.notifications if n.signal_id == signal_id]

    def get_by_type(
        self, notification_type: NotificationType, count: int = 50
    ) -> list[NotificationRecord]:
        """Belirli tipteki bildirimleri getir."""
        filtered = [
            n for n in self.notifications
            if n.notification_type == notification_type.value
        ]
        return filtered[-count:]

    def get_failed_notifications(self) -> list[NotificationRecord]:
        """Başarısız bildirimleri getir."""
        return [
            n for n in self.notifications
            if n.delivery_status == "FAILED"
        ]

    def get_trade_notification_audit(self, signal_id: str) -> dict:
        """
        Bir trade'in tam bildirim audit trail'i.
        Signal ID ile ilgili tüm bildirimleri kronolojik sırayla döndürür.
        """
        related = sorted(
            [n for n in self.notifications if n.signal_id == signal_id],
            key=lambda n: n.created_at,
        )

        if not related:
            return {"signal_id": signal_id, "notifications": [], "timeline": []}

        timeline = []
        for n in related:
            timeline.append({
                "notification_id": n.notification_id,
                "type": n.notification_type,
                "time": n.created_at_readable,
                "status": n.delivery_status,
                "price": n.price_at_notification,
                "price_verified": n.price_verified,
                "latency_ms": n.delivery_latency_ms,
            })

        return {
            "signal_id": signal_id,
            "symbol": related[0].symbol if related else "",
            "total_notifications": len(related),
            "all_delivered": all(
                n.delivery_status == "SENT" for n in related
            ),
            "timeline": timeline,
            "notifications": [n.to_dict() for n in related],
        }
