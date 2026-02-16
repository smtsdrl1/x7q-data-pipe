"""
Paper Trading Telegram Bot v2.0 — Profesyonel Bildirim ve Analiz Sistemi
Paper trading motorunu Telegram üzerinden kontrol eder.
Tüm sinyaller, işlemler, bildirimler ve istatistikler detaylı raporlanır.
Her bildirim izlenir, fiyat doğrulanır, teslimat onaylanır.

KOMUTLAR:
/start          — Ana menü (inline butonlar)
/durum          — Anlık durum raporu
/bakiye         — Bakiye ve ROI bilgisi
/istatistik     — Detaylı sinyal istatistikleri
/sinyaller      — Son 10 sinyal
/trades         — Son 10 trade
/pozisyonlar    — Açık pozisyonlar (anlık fiyatla)
/risk           — Risk metrikleri
/kalite         — Veri kalitesi raporu
/bildirimler    — Bildirim geçmişi ve güvenilirlik
/journal        — Trade journal detayları
/analiz         — Performans analiz raporu
/pairler        — Pair bazlı performans
/saatlik        — Saatlik performans kırılımı
/audit          — Sinyal audit trail (ID ile)
/baslat         — Trading başlat
/durdur         — Trading durdur
/yardim         — Komut listesi
"""

import asyncio
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

from paper_trading import PaperTradingEngine
from utils.performance_analytics import PerformanceAnalytics
from utils.logger import setup_logger
from utils.helpers import format_currency, format_pct
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    INITIAL_CAPITAL, TRADING_PAIRS
)

logger = setup_logger("PaperTelegramBot")


class PaperTradingBot:
    """Paper Trading Telegram Bot v2.0 — Profesyonel."""

    def __init__(self, capital: float = INITIAL_CAPITAL):
        self.engine = PaperTradingEngine(initial_capital=capital)
        self.app = None
        self.authorized_chat_ids = set()
        if TELEGRAM_CHAT_ID:
            self.authorized_chat_ids.add(int(TELEGRAM_CHAT_ID))

    def is_authorized(self, chat_id: int) -> bool:
        if not self.authorized_chat_ids:
            return True
        return chat_id in self.authorized_chat_ids

    async def send_message(self, text: str):
        """Mesaj gönder (paper trading callback)."""
        if self.app and TELEGRAM_CHAT_ID:
            try:
                if len(text) > 4000:
                    parts = []
                    while text:
                        if len(text) <= 4000:
                            parts.append(text)
                            break
                        cut = text[:4000].rfind('\n')
                        if cut == -1:
                            cut = 4000
                        parts.append(text[:cut])
                        text = text[cut:]

                    for part in parts:
                        await self.app.bot.send_message(
                            chat_id=int(TELEGRAM_CHAT_ID),
                            text=part,
                            parse_mode="HTML",
                        )
                        await asyncio.sleep(0.3)
                else:
                    await self.app.bot.send_message(
                        chat_id=int(TELEGRAM_CHAT_ID),
                        text=text,
                        parse_mode="HTML",
                    )
            except Exception as e:
                logger.error(f"Mesaj gönderme hatası: {e}")
                raise  # Re-raise to track in notification manager

    def _get_reply_target(self, update: Update):
        """Update'den reply hedefini al."""
        if update.callback_query:
            return update.callback_query.message
        return update.message

    async def _reply(self, update: Update, text: str):
        """Mesajı doğru hedefe gönder."""
        target = self._get_reply_target(update)
        if target:
            # Uzun mesajları böl
            if len(text) > 4000:
                parts = []
                remaining = text
                while remaining:
                    if len(remaining) <= 4000:
                        parts.append(remaining)
                        break
                    cut = remaining[:4000].rfind('\n')
                    if cut == -1:
                        cut = 4000
                    parts.append(remaining[:cut])
                    remaining = remaining[cut:]

                for part in parts:
                    await target.reply_text(part, parse_mode="HTML")
                    await asyncio.sleep(0.3)
            else:
                await target.reply_text(text, parse_mode="HTML")

    # ==================== KOMUTLAR ====================

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bot başlangıç menüsü."""
        if not self.is_authorized(update.effective_chat.id):
            await update.message.reply_text("Yetkisiz erişim.")
            return

        keyboard = [
            [
                InlineKeyboardButton("Durum", callback_data="status"),
                InlineKeyboardButton("Bakiye", callback_data="balance"),
            ],
            [
                InlineKeyboardButton("İstatistik", callback_data="stats"),
                InlineKeyboardButton("Sinyaller", callback_data="signals"),
            ],
            [
                InlineKeyboardButton("Trade'ler", callback_data="trades"),
                InlineKeyboardButton("Pozisyonlar", callback_data="positions"),
            ],
            [
                InlineKeyboardButton("Risk", callback_data="risk"),
                InlineKeyboardButton("Kalite", callback_data="quality"),
            ],
            [
                InlineKeyboardButton("Bildirimler", callback_data="notifications"),
                InlineKeyboardButton("Journal", callback_data="journal"),
            ],
            [
                InlineKeyboardButton("Analiz", callback_data="analytics"),
                InlineKeyboardButton("Pair'ler", callback_data="pairs"),
            ],
            [
                InlineKeyboardButton("Saatlik", callback_data="hourly"),
                InlineKeyboardButton("Yardim", callback_data="help"),
            ],
            [
                InlineKeyboardButton("Baslat", callback_data="start_trading"),
                InlineKeyboardButton("Durdur", callback_data="stop_trading"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        status_emoji = "🟢" if self.engine.is_running else "🔴"
        notif_count = len(self.engine.notification_manager.notifications)

        await update.message.reply_text(
            f"<b>Crypto Paper Trading Bot v2.0</b>\n"
            f"{'─' * 30}\n"
            f"{status_emoji} Durum: {'Aktif' if self.engine.is_running else 'Durduruldu'}\n"
            f"Sermaye: {format_currency(self.engine.risk_manager.current_capital)}\n"
            f"Mode: DEMO (Gerçek veri, sanal para)\n"
            f"{len(TRADING_PAIRS)} pair | Bildirim izleme AKTİF\n"
            f"Toplam bildirim: {notif_count}\n\n"
            f"Bir komut seçin:",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )

    async def cmd_durum(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Anlık durum raporu."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        status = self.engine.get_status()
        stats = status["signal_stats"]
        risk = status["risk_stats"]
        positions = status["open_positions"]
        notif = status["notification_stats"]
        journal = status["journal_stats"]

        pos_text = ""
        for pos in positions:
            pos_text += (
                f"  {pos['symbol']}: {format_currency(pos['entry_price'])} "
                f"(SL: {format_currency(pos['stop_loss'])})\n"
            )
        if not pos_text:
            pos_text = "  Açık pozisyon yok\n"

        text = (
            f"<b>PAPER TRADING DURUMU</b>\n"
            f"{'─' * 30}\n"
            f"{'🟢' if status['is_running'] else '🔴'} "
            f"{'Aktif' if status['is_running'] else 'Durduruldu'} | {status['mode']}\n"
            f"Uptime: {status['uptime']}\n"
            f"Tarama: #{status['scan_count']}\n\n"
            f"<b>Portföy</b>\n"
            f"  Sermaye: {format_currency(risk['current_capital'])}\n"
            f"  ROI: {format_pct(risk['roi'])}\n"
            f"  Net P&L: {format_currency(risk['net_pnl'])}\n\n"
            f"<b>Sinyaller</b>\n"
            f"  Toplam: {stats['total_signals']}\n"
            f"  Aktif: {stats['active']}\n"
            f"  Win: {stats['wins']} | Loss: {stats['losses']}\n"
            f"  Win Rate: {stats['win_rate']:.1f}%\n\n"
            f"<b>Bildirimler</b>\n"
            f"  Gönderilen: {notif['sent']}\n"
            f"  Teslimat: %{notif['delivery_rate']:.1f}\n\n"
            f"<b>Journal</b>\n"
            f"  Kayıt: {journal['total_entries']}\n"
            f"  Bütünlük: {journal['avg_data_integrity']:.0f}/100\n\n"
            f"<b>Açık Pozisyonlar</b> ({len(positions)})\n"
            f"{pos_text}"
        )

        await self._reply(update, text)

    async def cmd_bakiye(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bakiye bilgisi."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        risk = self.engine.risk_manager.get_stats()
        roi = ((self.engine.risk_manager.current_capital - self.engine.initial_capital) / self.engine.initial_capital) * 100

        text = (
            f"<b>BAKİYE BİLGİSİ</b>\n"
            f"{'─' * 30}\n"
            f"  Başlangıç: {format_currency(self.engine.initial_capital)}\n"
            f"  Mevcut: {format_currency(self.engine.risk_manager.current_capital)}\n"
            f"  Net P&L: {format_currency(risk['net_pnl'])}\n"
            f"  Toplam Fee: {format_currency(risk['total_fees'])}\n"
            f"  ROI: {format_pct(roi)}\n"
            f"  Max Drawdown: {risk['max_drawdown']:.2f}%\n\n"
            f"Mode: DEMO (sanal bakiye)"
        )

        await self._reply(update, text)

    async def cmd_istatistik(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Detaylı istatistik raporu."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        stats = self.engine.signal_tracker.get_statistics()

        best = stats.get("best_trade")
        worst = stats.get("worst_trade")
        best_text = f"  {best['symbol']}: {format_pct(best['pnl_pct'])}" if best else "  -"
        worst_text = f"  {worst['symbol']}: {format_pct(worst['pnl_pct'])}" if worst else "  -"

        text = (
            f"<b>DETAYLI İSTATİSTİKLER</b>\n"
            f"{'─' * 30}\n\n"
            f"<b>Sinyal Özeti</b>\n"
            f"  Toplam: {stats['total_signals']}\n"
            f"  Aktif: {stats['active']}\n"
            f"  Kapalı: {stats['closed']}\n"
            f"  Reddedilen: {stats['rejected']}\n\n"
            f"<b>Performans</b>\n"
            f"  Win Rate: {stats['win_rate']:.1f}%\n"
            f"  Win: {stats['wins']} | Loss: {stats['losses']}\n"
            f"  Net P&L: {format_currency(stats['total_pnl'])}\n"
            f"  Toplam Fee: {format_currency(stats['total_fees'])}\n"
            f"  Profit Factor: {stats['profit_factor']:.2f}\n"
            f"  Avg Win: {format_pct(stats['avg_win_pct'])}\n"
            f"  Avg Loss: {format_pct(stats['avg_loss_pct'])}\n\n"
            f"<b>En İyi / En Kötü</b>\n"
            f"  En İyi:{best_text}\n"
            f"  En Kötü:{worst_text}\n\n"
            f"<b>Seriler</b>\n"
            f"  Max Seri Win: {stats['max_consecutive_wins']}\n"
            f"  Max Seri Loss: {stats['max_consecutive_losses']}\n\n"
            f"<b>Yön Analizi</b>\n"
            f"  BUY sinyalleri: {stats['buy_signals']}\n"
            f"  SELL sinyalleri: {stats['sell_signals']}\n"
            f"  BUY Win Rate: {stats['buy_win_rate']:.1f}%\n"
            f"  SELL Win Rate: {stats['sell_win_rate']:.1f}%\n\n"
            f"<b>Bugün</b>\n"
            f"  Sinyal: {stats['today']['signals']}\n"
            f"  Kapalı: {stats['today']['closed']}\n"
            f"  P&L: {format_currency(stats['today']['pnl'])}"
        )

        await self._reply(update, text)

    async def cmd_sinyaller(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Son sinyalleri göster."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        recent = self.engine.signal_tracker.get_recent_signals(10)
        if not recent:
            await self._reply(update, "Henüz sinyal yok.")
            return

        text = f"<b>SON 10 SİNYAL</b>\n{'─' * 30}\n\n"
        for s in reversed(recent):
            status_emoji = {
                "ACTIVE": "🟡",
                "CLOSED": "✅" if s.result == "WIN" else "❌",
                "REJECTED": "⛔",
                "PENDING": "⏳",
            }.get(s.status, "❓")

            pnl_text = ""
            if s.status == "CLOSED":
                pnl_text = f" | P&L: {format_currency(s.net_pnl)} ({format_pct(s.pnl_pct)})"

            text += (
                f"{status_emoji} <b>{s.symbol}</b> {s.direction}\n"
                f"  {s.signal_time_readable}\n"
                f"  Fiyat: {format_currency(s.verified_price)} | Skor: {s.composite_score:.2f}\n"
                f"  Kalite: {s.data_quality} | Durum: {s.status}{pnl_text}\n"
                f"  <code>{s.signal_id}</code>\n\n"
            )

        await self._reply(update, text)

    async def cmd_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Son kapanmış trade'leri göster."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        closed = [s for s in self.engine.signal_tracker.signals if s.status == "CLOSED"]
        last_10 = closed[-10:]

        if not last_10:
            await self._reply(update, "Henüz kapanmış trade yok.")
            return

        text = f"<b>SON 10 TRADE</b>\n{'─' * 30}\n\n"
        for t in reversed(last_10):
            emoji = "✅" if t.result == "WIN" else "❌"

            duration = ""
            if t.duration_seconds > 0:
                mins = t.duration_seconds // 60
                if mins > 60:
                    hours = mins // 60
                    mins = mins % 60
                    duration = f"{hours}s {mins}dk"
                else:
                    duration = f"{mins}dk"

            text += (
                f"{emoji} <b>{t.symbol}</b> | {t.result}\n"
                f"  Giriş: {format_currency(t.entry_price)} -> Çıkış: {format_currency(t.exit_price)}\n"
                f"  P&L: {format_currency(t.net_pnl)} ({format_pct(t.pnl_pct)})\n"
                f"  Sebep: {t.exit_reason} | Süre: {duration}\n"
                f"  {t.signal_time_readable}\n\n"
            )

        await self._reply(update, text)

    async def cmd_pozisyonlar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Açık pozisyonları göster."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        positions = self.engine.position_manager.get_open_positions()

        if not positions:
            await self._reply(update, "Açık pozisyon bulunmuyor.")
            return

        text = f"<b>AÇIK POZİSYONLAR</b> ({len(positions)})\n{'─' * 30}\n\n"

        for pos in positions:
            try:
                vp = await self.engine.price_verifier.verify_price(pos['symbol'])
                current = vp.price if vp.verified else 0
                latency = vp.latency_ms if vp.verified else 0
            except Exception:
                current = 0
                latency = 0

            if current > 0:
                unrealized_pnl = (current - pos['entry_price']) * pos['quantity']
                unrealized_pct = ((current - pos['entry_price']) / pos['entry_price']) * 100
                emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
                price_text = (
                    f"  {emoji} Şu an: {format_currency(current)} "
                    f"({format_pct(unrealized_pct)}) [{latency:.0f}ms]\n"
                )
                pnl_text = f"  Unrealized P&L: {format_currency(unrealized_pnl)}\n"
            else:
                price_text = "  Fiyat alınamadı\n"
                pnl_text = ""

            text += (
                f"<b>{pos['symbol']}</b>\n"
                f"  Giriş: {format_currency(pos['entry_price'])}\n"
                f"{price_text}"
                f"{pnl_text}"
                f"  SL: {format_currency(pos['stop_loss'])}\n"
                f"  TP: {format_currency(pos['take_profit'])}\n"
                f"  Trail: {format_currency(pos['trailing_stop'])}\n"
                f"  Boyut: {format_currency(pos['quantity'] * pos['entry_price'])}\n\n"
            )

        await self._reply(update, text)

    async def cmd_risk(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Risk metrikleri."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        risk = self.engine.risk_manager.get_stats()
        text = (
            f"<b>RİSK METRİKLERİ</b>\n"
            f"{'─' * 30}\n"
            f"  Max Drawdown: {risk['max_drawdown']:.2f}%\n"
            f"  Ardışık Kayıp: {risk['consecutive_losses']}\n"
            f"  Günlük P&L: {format_currency(risk['daily_pnl'])}\n"
            f"  Günlük Trade: {risk['daily_trades']}\n"
            f"  Avg Win: {format_pct(risk['avg_win'])}\n"
            f"  Avg Loss: {format_pct(risk['avg_loss'])}\n"
            f"  Trading: {'Aktif' if not self.engine.risk_manager.is_trading_halted else 'Durduruldu'}"
        )

        await self._reply(update, text)

    async def cmd_kalite(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Veri kalitesi raporu."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        stats = self.engine.signal_tracker.get_statistics()
        dq = stats["data_quality"]

        text = (
            f"<b>VERİ KALİTESİ RAPORU</b>\n"
            f"{'─' * 30}\n"
            f"  GOOD: {dq['good']} sinyal\n"
            f"  WARNING: {dq['warning']} sinyal\n"
            f"  FAIL: {dq['fail']} sinyal\n"
            f"  Kalite Oranı: %{dq['good_pct']:.1f}\n\n"
            f"<b>Açıklama:</b>\n"
            f"  GOOD: Fiyat doğrulandı, sapma <%0.5\n"
            f"  WARNING: Doğrulandı ama sapma >%0.5\n"
            f"  FAIL: Fiyat doğrulanamadı\n\n"
            f"FAIL sinyalleri otomatik reddedilir.\n"
            f"Sadece doğrulanmış verilerle işlem yapılır."
        )

        await self._reply(update, text)

    # ==================== YENİ KOMUTLAR ====================

    async def cmd_bildirimler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bildirim geçmişi ve güvenilirlik raporu."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        notif_stats = self.engine.notification_manager.get_statistics()
        recent = self.engine.notification_manager.get_recent(10)

        text = (
            f"<b>BİLDİRİM YÖNETİM RAPORU</b>\n"
            f"{'─' * 30}\n\n"
            f"<b>Genel</b>\n"
            f"  Toplam: {notif_stats['total_notifications']}\n"
            f"  Gönderilen: {notif_stats['sent']}\n"
            f"  Başarısız: {notif_stats['failed']}\n"
            f"  Bekleyen: {notif_stats['pending']}\n"
            f"  Teslimat Oranı: %{notif_stats['delivery_rate']:.1f}\n\n"
            f"<b>Gecikme</b>\n"
            f"  Ortalama: {notif_stats['latency']['avg_ms']:.0f}ms\n"
            f"  Minimum: {notif_stats['latency']['min_ms']:.0f}ms\n"
            f"  Maksimum: {notif_stats['latency']['max_ms']:.0f}ms\n\n"
            f"<b>Fiyat Doğrulama</b>\n"
            f"  Kontrol: {notif_stats['price_verification']['total_checks']}\n"
            f"  Doğrulanmış: {notif_stats['price_verification']['verified']}\n"
            f"  Oran: %{notif_stats['price_verification']['verify_rate']:.1f}\n"
            f"  Ort. Fiyat Gecikme: {notif_stats['price_verification']['avg_price_latency_ms']:.0f}ms\n\n"
        )

        # Tip dağılımı
        if notif_stats.get("type_distribution"):
            text += "<b>Tip Dağılımı</b>\n"
            for ntype, count in sorted(
                notif_stats["type_distribution"].items(),
                key=lambda x: x[1],
                reverse=True
            ):
                text += f"  {ntype}: {count}\n"
            text += "\n"

        # Son 24s trade bildirimleri
        last24 = notif_stats.get("last_24h_trades", {})
        if last24:
            text += (
                f"<b>Son 24 Saat Trade</b>\n"
                f"  Açılan: {last24.get('opened', 0)}\n"
                f"  Kapanan: {last24.get('closed', 0)}\n"
                f"  Win: {last24.get('wins', 0)} | Loss: {last24.get('losses', 0)}\n"
                f"  Win Rate: %{last24.get('win_rate', 0):.1f}\n\n"
            )

        # Son 5 bildirim
        if recent:
            text += "<b>Son 5 Bildirim</b>\n"
            for n in reversed(recent[-5:]):
                status_emoji = "✅" if n.delivery_status == "SENT" else "❌"
                price_text = f"${n.price_at_notification:.2f}" if n.price_verified else "N/A"
                text += (
                    f"  {status_emoji} {n.notification_type}\n"
                    f"    {n.created_at_readable}\n"
                    f"    Fiyat: {price_text} | Gecikme: {n.delivery_latency_ms:.0f}ms\n"
                )

        await self._reply(update, text)

    async def cmd_journal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Trade journal detayları."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        journal_stats = self.engine.trade_journal.get_statistics()
        recent = self.engine.trade_journal.get_recent(5)

        text = (
            f"<b>TRADE JOURNAL RAPORU</b>\n"
            f"{'─' * 30}\n\n"
            f"<b>Özet</b>\n"
            f"  Toplam Kayıt: {journal_stats['total_entries']}\n"
            f"  Aktif: {journal_stats['active']}\n"
            f"  Kapalı: {journal_stats['closed']}\n"
            f"  Reddedilen: {journal_stats['rejected']}\n\n"
            f"<b>Performans</b>\n"
            f"  Win: {journal_stats['wins']} | Loss: {journal_stats['losses']}\n"
            f"  Win Rate: %{journal_stats['win_rate']:.1f}\n"
            f"  Net P&L: {format_currency(journal_stats['total_pnl'])}\n"
            f"  Toplam Fee: {format_currency(journal_stats['total_fees'])}\n"
            f"  Profit Factor: {journal_stats['profit_factor']:.2f}\n\n"
            f"<b>Kalite Metrikleri</b>\n"
            f"  Ort. Bütünlük: {journal_stats['avg_data_integrity']:.0f}/100\n"
            f"  Ort. Slippage: %{journal_stats['avg_slippage_pct']:.4f}\n"
        )

        # Strateji skoru
        strat = journal_stats.get("strategy_scores", {})
        if strat:
            text += (
                f"\n<b>Strateji Skoru</b>\n"
                f"  Avg Win Skor: {strat.get('avg_win_score', 0):.2f}\n"
                f"  Avg Loss Skor: {strat.get('avg_loss_score', 0):.2f}\n"
            )

        # En iyi / en kötü
        best = journal_stats.get("best_trade")
        worst = journal_stats.get("worst_trade")
        if best:
            text += (
                f"\n<b>En İyi Trade</b>\n"
                f"  {best['symbol']}: {format_currency(best['net_pnl'])} "
                f"({format_pct(best['pnl_pct'])})\n"
                f"  {best['date']}\n"
            )
        if worst:
            text += (
                f"\n<b>En Kötü Trade</b>\n"
                f"  {worst['symbol']}: {format_currency(worst['net_pnl'])} "
                f"({format_pct(worst['pnl_pct'])})\n"
                f"  {worst['date']}\n"
            )

        # Çıkış sebepleri
        exits = journal_stats.get("exit_reasons", {})
        if exits:
            text += "\n<b>Çıkış Sebepleri</b>\n"
            for reason, count in sorted(exits.items(), key=lambda x: x[1], reverse=True):
                text += f"  {reason}: {count}\n"

        # Haftalık trend
        weekly = journal_stats.get("weekly", {})
        if weekly:
            text += (
                f"\n<b>Bu Hafta</b>\n"
                f"  Trade: {weekly.get('trades', 0)}\n"
                f"  P&L: {format_currency(weekly.get('pnl', 0))}\n"
                f"  Win Rate: %{weekly.get('win_rate', 0):.1f}\n"
            )

        # Son journal kayıtları
        if recent:
            text += f"\n<b>Son 5 Kayıt</b>\n"
            for e in reversed(recent):
                emoji = {"WIN": "✅", "LOSS": "❌", "": "🟡"}.get(e.result, "❓")
                text += (
                    f"  {emoji} {e.symbol} | {e.direction} | "
                    f"{e.status}\n"
                    f"    Bütünlük: {e.data_integrity_score:.0f}/100 | "
                    f"Bildirim: {e.notifications_sent}/{e.notifications_sent + e.notifications_failed}\n"
                )

        await self._reply(update, text)

    async def cmd_analiz(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Kapsamlı performans analiz raporu."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        analytics = PerformanceAnalytics(
            self.engine.trade_journal,
            self.engine.notification_manager,
            self.engine.signal_tracker,
        )

        text = analytics.format_telegram_summary()
        await self._reply(update, text)

    async def cmd_pairler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Pair bazlı performans raporu."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        analytics = PerformanceAnalytics(
            self.engine.trade_journal,
            self.engine.notification_manager,
            self.engine.signal_tracker,
        )

        text = analytics.format_telegram_pair_report()
        await self._reply(update, text)

    async def cmd_saatlik(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Saatlik performans kırılımı."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        analytics = PerformanceAnalytics(
            self.engine.trade_journal,
            self.engine.notification_manager,
            self.engine.signal_tracker,
        )

        text = analytics.format_telegram_hourly_report()
        await self._reply(update, text)

    async def cmd_audit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Sinyal audit trail — belirli bir sinyal ID ile."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        # Argüman olarak signal_id bekleniyor
        args = context.args
        if not args:
            await self._reply(
                update,
                "<b>AUDIT TRAIL</b>\n\n"
                "Kullanım: /audit [sinyal_id]\n\n"
                "Örnek:\n"
                "<code>/audit 20260216_143022_BTC_USDT</code>\n\n"
                "Sinyal ID'lerini /sinyaller veya /trades "
                "komutlarından alabilirsiniz.",
            )
            return

        signal_id = args[0]

        # Bildirim audit trail
        audit = self.engine.notification_manager.get_trade_notification_audit(signal_id)

        # Journal kaydı
        journal_entry = self.engine.trade_journal.get_entry_by_signal(signal_id)

        if not audit["timeline"] and not journal_entry:
            await self._reply(
                update, f"Sinyal bulunamadı: <code>{signal_id}</code>"
            )
            return

        text = (
            f"<b>AUDIT TRAIL</b>\n"
            f"{'─' * 30}\n"
            f"Sinyal: <code>{signal_id}</code>\n"
        )

        if audit.get("symbol"):
            text += f"Sembol: {audit['symbol']}\n"
        text += f"Bildirim: {audit.get('total_notifications', 0)}\n"
        text += f"Hepsi teslim: {'Evet' if audit.get('all_delivered') else 'Hayır'}\n\n"

        # Bildirim zaman çizelgesi
        if audit.get("timeline"):
            text += "<b>Bildirim Zaman Çizelgesi</b>\n"
            for t in audit["timeline"]:
                status_emoji = "✅" if t["status"] == "SENT" else "❌"
                price = f"${t['price']:.2f}" if t['price'] > 0 else "N/A"
                text += (
                    f"  {status_emoji} {t['type']}\n"
                    f"    Zaman: {t['time']}\n"
                    f"    Fiyat: {price} | Gecikme: {t['latency_ms']:.0f}ms\n"
                    f"    Doğrulandı: {'Evet' if t['price_verified'] else 'Hayır'}\n\n"
                )

        # Journal detayları
        if journal_entry:
            report = self.engine.trade_journal.get_full_trade_report(
                journal_entry.journal_id
            )
            if report:
                text += (
                    f"<b>Journal Detayı</b>\n"
                    f"  Durum: {report['status']}\n"
                    f"  Sonuç: {report['result'] or 'DEVAM EDİYOR'}\n"
                )
                tl = report.get("timeline", {})
                if tl:
                    text += (
                        f"  Sinyal: {tl.get('signal_detected', '')}\n"
                        f"  Açılış: {tl.get('trade_opened', '')}\n"
                        f"  Kapanış: {tl.get('trade_closed', '') or 'Devam ediyor'}\n"
                        f"  Süre: {tl.get('duration', '') or 'N/A'}\n\n"
                    )
                prices = report.get("prices", {})
                if prices:
                    text += (
                        f"<b>Fiyat İzleme</b>\n"
                        f"  Sinyal: {format_currency(prices.get('signal_price', 0))}\n"
                        f"  Doğ. Giriş: {format_currency(prices.get('verified_entry', 0))}\n"
                        f"  Giriş: {format_currency(prices.get('entry', 0))}\n"
                        f"  Çıkış: {format_currency(prices.get('exit', 0))}\n"
                        f"  Doğ. Çıkış: {format_currency(prices.get('verified_exit', 0))}\n"
                        f"  Slippage: %{prices.get('slippage', 0):.4f}\n\n"
                    )
                quality = report.get("data_quality", {})
                if quality:
                    text += (
                        f"<b>Veri Kalitesi</b>\n"
                        f"  Sinyal: {quality.get('signal_quality', 'N/A')}\n"
                        f"  Çıkış: {quality.get('exit_quality', 'N/A')}\n"
                        f"  Bütünlük: {quality.get('integrity_score', 0):.0f}/100\n"
                        f"  Tümü Doğru: {'Evet' if quality.get('all_verified') else 'Hayır'}\n\n"
                    )
                result_d = report.get("result_detail", {})
                if result_d and result_d.get("pnl"):
                    text += (
                        f"<b>Sonuç</b>\n"
                        f"  Brüt P&L: {format_currency(result_d.get('pnl', 0))}\n"
                        f"  Fee: {format_currency(result_d.get('fee', 0))}\n"
                        f"  Net P&L: {format_currency(result_d.get('net_pnl', 0))}\n"
                        f"  P&L %: {format_pct(result_d.get('pnl_pct', 0))}\n"
                        f"  Çıkış Sebep: {result_d.get('exit_reason', '')}\n"
                    )

                # Fiyat geçmişi
                ph = report.get("price_history", [])
                if ph:
                    text += f"\n<b>Fiyat Geçmişi ({len(ph)} kayıt)</b>\n"
                    for snap in ph[-5:]:
                        v = "✓" if snap.get("verified") else "✗"
                        text += (
                            f"  [{v}] {snap.get('time', '')} | "
                            f"${snap.get('price', 0):.2f} | "
                            f"{snap.get('event', '')}\n"
                        )

        await self._reply(update, text)

    async def cmd_baslat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Paper trading başlat."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        if self.engine.is_running:
            await self._reply(update, "Bot zaten çalışıyor.")
        else:
            self.engine.resume_trading()
            asyncio.create_task(self.engine.start())
            await self._reply(update, "Paper Trading v2.0 başlatıldı!")

    async def cmd_durdur(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Paper trading durdur."""
        chat = update.effective_chat
        if not self.is_authorized(chat.id):
            return

        self.engine.is_running = False
        await self._reply(update, "Paper Trading durduruluyor...")

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Yardım."""
        if not self.is_authorized(update.effective_chat.id):
            return

        await self._reply(
            update,
            "<b>KOMUT LİSTESİ v2.0</b>\n"
            f"{'─' * 30}\n\n"
            "<b>Temel</b>\n"
            "/start — Ana menü\n"
            "/durum — Anlık durum\n"
            "/bakiye — Bakiye bilgisi\n"
            "/baslat — Trading başlat\n"
            "/durdur — Trading durdur\n\n"
            "<b>İzleme</b>\n"
            "/sinyaller — Son 10 sinyal\n"
            "/trades — Son 10 trade\n"
            "/pozisyonlar — Açık pozisyonlar\n\n"
            "<b>Analiz</b>\n"
            "/istatistik — Detaylı istatistikler\n"
            "/risk — Risk metrikleri\n"
            "/kalite — Veri kalitesi\n"
            "/analiz — Performans analizi\n"
            "/pairler — Pair bazlı performans\n"
            "/saatlik — Saatlik kırılım\n\n"
            "<b>Profesyonel</b>\n"
            "/bildirimler — Bildirim güvenilirlik raporu\n"
            "/journal — Trade journal detayları\n"
            "/audit [id] — Sinyal audit trail\n\n"
            "/yardim — Bu mesaj",
        )

    # ==================== CALLBACK ====================

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Inline buton callback'leri."""
        query = update.callback_query
        await query.answer()

        if not self.is_authorized(query.message.chat_id):
            return

        handlers = {
            "status": self.cmd_durum,
            "balance": self.cmd_bakiye,
            "stats": self.cmd_istatistik,
            "signals": self.cmd_sinyaller,
            "trades": self.cmd_trades,
            "positions": self.cmd_pozisyonlar,
            "risk": self.cmd_risk,
            "quality": self.cmd_kalite,
            "notifications": self.cmd_bildirimler,
            "journal": self.cmd_journal,
            "analytics": self.cmd_analiz,
            "pairs": self.cmd_pairler,
            "hourly": self.cmd_saatlik,
            "help": self.cmd_help,
            "start_trading": self.cmd_baslat,
            "stop_trading": self.cmd_durdur,
        }

        handler = handlers.get(query.data)
        if handler:
            await handler(update, context)

    # ==================== ANA GİRİŞ ====================

    async def run(self):
        """Telegram bot'u başlat."""
        if not TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN ayarlanmamış!")
            logger.info("Telegram olmadan paper trading engine çalıştırılacak.")
            await self.engine.start()
            return

        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Komutları ekle
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("durum", self.cmd_durum))
        self.app.add_handler(CommandHandler("bakiye", self.cmd_bakiye))
        self.app.add_handler(CommandHandler("istatistik", self.cmd_istatistik))
        self.app.add_handler(CommandHandler("sinyaller", self.cmd_sinyaller))
        self.app.add_handler(CommandHandler("trades", self.cmd_trades))
        self.app.add_handler(CommandHandler("pozisyonlar", self.cmd_pozisyonlar))
        self.app.add_handler(CommandHandler("risk", self.cmd_risk))
        self.app.add_handler(CommandHandler("kalite", self.cmd_kalite))
        self.app.add_handler(CommandHandler("bildirimler", self.cmd_bildirimler))
        self.app.add_handler(CommandHandler("journal", self.cmd_journal))
        self.app.add_handler(CommandHandler("analiz", self.cmd_analiz))
        self.app.add_handler(CommandHandler("pairler", self.cmd_pairler))
        self.app.add_handler(CommandHandler("saatlik", self.cmd_saatlik))
        self.app.add_handler(CommandHandler("audit", self.cmd_audit))
        self.app.add_handler(CommandHandler("baslat", self.cmd_baslat))
        self.app.add_handler(CommandHandler("durdur", self.cmd_durdur))
        self.app.add_handler(CommandHandler("yardim", self.cmd_help))
        self.app.add_handler(CallbackQueryHandler(self.callback_handler))

        # Paper trading callback
        self.engine.set_telegram_callback(self.send_message)

        logger.info("Paper Trading Telegram Bot v2.0 başlatılıyor...")

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

        # Paper trading engine'i başlat
        asyncio.create_task(self.engine.start())

        logger.info("Bot v2.0 çalışıyor. Ctrl+C ile durdurun.")

        try:
            await asyncio.Event().wait()
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            self.engine.is_running = False
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()


async def main():
    bot = PaperTradingBot(capital=INITIAL_CAPITAL)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
