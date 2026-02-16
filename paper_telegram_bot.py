"""
Paper Trading Telegram Bot
Paper trading motorunu Telegram üzerinden kontrol eder.
Tüm sinyaller, işlemler ve istatistikler detaylı raporlanır.
"""

import asyncio
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

from paper_trading import PaperTradingEngine
from utils.logger import setup_logger
from utils.helpers import format_currency, format_pct
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    INITIAL_CAPITAL, TRADING_PAIRS
)

logger = setup_logger("PaperTelegramBot")


class PaperTradingBot:
    """Paper Trading Telegram Bot."""

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
                # Telegram mesaj limiti 4096 karakter
                if len(text) > 4000:
                    # Uzun mesajları böl
                    parts = []
                    while text:
                        if len(text) <= 4000:
                            parts.append(text)
                            break
                        # Son satır sonuna kadar kes
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

    # ==================== KOMUTLAR ====================

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bot başlangıç menüsü."""
        if not self.is_authorized(update.effective_chat.id):
            await update.message.reply_text("⛔ Yetkisiz erişim.")
            return

        keyboard = [
            [
                InlineKeyboardButton("📊 Durum", callback_data="status"),
                InlineKeyboardButton("💰 Bakiye", callback_data="balance"),
            ],
            [
                InlineKeyboardButton("📈 İstatistik", callback_data="stats"),
                InlineKeyboardButton("📋 Son Sinyaller", callback_data="signals"),
            ],
            [
                InlineKeyboardButton("🏆 Son Trade'ler", callback_data="trades"),
                InlineKeyboardButton("📍 Açık Pozisyonlar", callback_data="positions"),
            ],
            [
                InlineKeyboardButton("🛡️ Risk", callback_data="risk"),
                InlineKeyboardButton("🔍 Veri Kalitesi", callback_data="quality"),
            ],
            [
                InlineKeyboardButton("▶️ Başlat", callback_data="start_trading"),
                InlineKeyboardButton("⏹ Durdur", callback_data="stop_trading"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        status_emoji = "🟢" if self.engine.is_running else "🔴"
        await update.message.reply_text(
            f"<b>📊 Crypto Paper Trading Bot</b>\n"
            f"{'─' * 30}\n"
            f"{status_emoji} Durum: {'Aktif' if self.engine.is_running else 'Durduruldu'}\n"
            f"💰 Sermaye: {format_currency(self.engine.risk_manager.current_capital)}\n"
            f"📋 Mode: DEMO (Gerçek veri, sanal para)\n"
            f"📊 {len(TRADING_PAIRS)} pair takip\n\n"
            f"Bir komut seçin:",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )

    async def cmd_durum(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Anlık durum raporu."""
        chat = update.effective_chat or update.callback_query.message.chat
        if not self.is_authorized(chat.id):
            return

        status = self.engine.get_status()
        stats = status["signal_stats"]
        risk = status["risk_stats"]
        positions = status["open_positions"]

        pos_text = ""
        for pos in positions:
            pos_text += (
                f"  📍 {pos['symbol']}: {format_currency(pos['entry_price'])} "
                f"(SL: {format_currency(pos['stop_loss'])})\n"
            )
        if not pos_text:
            pos_text = "  Açık pozisyon yok\n"

        text = (
            f"<b>📊 PAPER TRADING DURUMU</b>\n"
            f"{'─' * 30}\n"
            f"{'🟢' if status['is_running'] else '🔴'} "
            f"{'Aktif' if status['is_running'] else 'Durduruldu'}\n"
            f"⏱ Uptime: {status['uptime']}\n"
            f"🔍 Tarama: #{status['scan_count']}\n\n"
            f"<b>💰 Portföy</b>\n"
            f"  Sermaye: {format_currency(risk['current_capital'])}\n"
            f"  ROI: {format_pct(risk['roi'])}\n"
            f"  Net P&L: {format_currency(risk['net_pnl'])}\n\n"
            f"<b>📈 Sinyaller</b>\n"
            f"  Toplam: {stats['total_signals']}\n"
            f"  Aktif: {stats['active']}\n"
            f"  ✅ Win: {stats['wins']} | ❌ Loss: {stats['losses']}\n"
            f"  🎯 Win Rate: {stats['win_rate']:.1f}%\n\n"
            f"<b>📍 Açık Pozisyonlar</b> ({len(positions)})\n"
            f"{pos_text}"
        )

        if update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_istatistik(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Detaylı istatistik raporu."""
        chat = update.effective_chat or update.callback_query.message.chat
        if not self.is_authorized(chat.id):
            return

        stats = self.signal_tracker_stats()

        best = stats.get("best_trade")
        worst = stats.get("worst_trade")
        best_text = f"  {best['symbol']}: {format_pct(best['pnl_pct'])}" if best else "  -"
        worst_text = f"  {worst['symbol']}: {format_pct(worst['pnl_pct'])}" if worst else "  -"

        text = (
            f"<b>📈 DETAYLI İSTATİSTİKLER</b>\n"
            f"{'─' * 30}\n\n"
            f"<b>📊 Sinyal Özeti</b>\n"
            f"  Toplam: {stats['total_signals']}\n"
            f"  Aktif: {stats['active']}\n"
            f"  Kapalı: {stats['closed']}\n"
            f"  Reddedilen: {stats['rejected']}\n\n"
            f"<b>🎯 Performans</b>\n"
            f"  Win Rate: {stats['win_rate']:.1f}%\n"
            f"  ✅ Win: {stats['wins']} | ❌ Loss: {stats['losses']}\n"
            f"  💵 Net P&L: {format_currency(stats['total_pnl'])}\n"
            f"  💸 Toplam Fee: {format_currency(stats['total_fees'])}\n"
            f"  📊 Profit Factor: {stats['profit_factor']:.2f}\n"
            f"  🔥 Avg Win: {format_pct(stats['avg_win_pct'])}\n"
            f"  💧 Avg Loss: {format_pct(stats['avg_loss_pct'])}\n\n"
            f"<b>🏆 En İyi / En Kötü</b>\n"
            f"  🏆 En İyi:{best_text}\n"
            f"  💀 En Kötü:{worst_text}\n\n"
            f"<b>🔥 Seriler</b>\n"
            f"  Max Seri Win: {stats['max_consecutive_wins']}\n"
            f"  Max Seri Loss: {stats['max_consecutive_losses']}\n\n"
            f"<b>📊 Yön Analizi</b>\n"
            f"  BUY sinyalleri: {stats['buy_signals']}\n"
            f"  SELL sinyalleri: {stats['sell_signals']}\n"
            f"  BUY Win Rate: {stats['buy_win_rate']:.1f}%\n"
            f"  SELL Win Rate: {stats['sell_win_rate']:.1f}%\n\n"
            f"<b>📆 Bugün</b>\n"
            f"  Sinyal: {stats['today']['signals']}\n"
            f"  Kapalı: {stats['today']['closed']}\n"
            f"  P&L: {format_currency(stats['today']['pnl'])}"
        )

        if update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_sinyaller(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Son sinyalleri göster."""
        chat = update.effective_chat or update.callback_query.message.chat
        if not self.is_authorized(chat.id):
            return

        recent = self.engine.signal_tracker.get_recent_signals(10)
        if not recent:
            text = "Henüz sinyal yok."
        else:
            text = f"<b>📋 SON 10 SİNYAL</b>\n{'─' * 30}\n\n"
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
                    f"  🕐 {s.signal_time_readable}\n"
                    f"  💰 Fiyat: {format_currency(s.verified_price)} | Skor: {s.composite_score:.2f}\n"
                    f"  📊 Kalite: {s.data_quality} | Durum: {s.status}{pnl_text}\n\n"
                )

        if update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Son kapanmış trade'leri göster."""
        chat = update.effective_chat or update.callback_query.message.chat
        if not self.is_authorized(chat.id):
            return

        closed = [s for s in self.engine.signal_tracker.signals if s.status == "CLOSED"]
        last_10 = closed[-10:]

        if not last_10:
            text = "Henüz kapanmış trade yok."
        else:
            text = f"<b>🏆 SON 10 TRADE</b>\n{'─' * 30}\n\n"
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
                    f"  Giriş: {format_currency(t.entry_price)} → Çıkış: {format_currency(t.exit_price)}\n"
                    f"  P&L: {format_currency(t.net_pnl)} ({format_pct(t.pnl_pct)})\n"
                    f"  Sebep: {t.exit_reason} | Süre: {duration}\n"
                    f"  🕐 {t.signal_time_readable}\n\n"
                )

        if update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_pozisyonlar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Açık pozisyonları göster."""
        chat = update.effective_chat or update.callback_query.message.chat
        if not self.is_authorized(chat.id):
            return

        positions = self.engine.position_manager.get_open_positions()

        if not positions:
            text = "📍 Açık pozisyon bulunmuyor."
        else:
            text = f"<b>📍 AÇIK POZİSYONLAR</b> ({len(positions)})\n{'─' * 30}\n\n"

            for pos in positions:
                # Anlık fiyat çek
                try:
                    vp = await self.engine.price_verifier.verify_price(pos['symbol'])
                    current = vp.price if vp.verified else 0
                except Exception:
                    current = 0

                if current > 0:
                    unrealized_pnl = (current - pos['entry_price']) * pos['quantity']
                    unrealized_pct = ((current - pos['entry_price']) / pos['entry_price']) * 100
                    emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
                    price_text = f"  {emoji} Şu an: {format_currency(current)} ({format_pct(unrealized_pct)})\n"
                    pnl_text = f"  Unrealized P&L: {format_currency(unrealized_pnl)}\n"
                else:
                    price_text = "  ⚠️ Fiyat alınamadı\n"
                    pnl_text = ""

                text += (
                    f"📊 <b>{pos['symbol']}</b>\n"
                    f"  Giriş: {format_currency(pos['entry_price'])}\n"
                    f"{price_text}"
                    f"{pnl_text}"
                    f"  SL: {format_currency(pos['stop_loss'])}\n"
                    f"  TP: {format_currency(pos['take_profit'])}\n"
                    f"  Trail: {format_currency(pos['trailing_stop'])}\n"
                    f"  Boyut: {format_currency(pos['quantity'] * pos['entry_price'])}\n\n"
                )

        if update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_risk(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Risk metrikleri."""
        chat = update.effective_chat or update.callback_query.message.chat
        if not self.is_authorized(chat.id):
            return

        risk = self.engine.risk_manager.get_stats()
        text = (
            f"<b>🛡️ RİSK METRİKLERİ</b>\n"
            f"{'─' * 30}\n"
            f"  Max Drawdown: {risk['max_drawdown']:.2f}%\n"
            f"  Ardışık Kayıp: {risk['consecutive_losses']}\n"
            f"  Günlük P&L: {format_currency(risk['daily_pnl'])}\n"
            f"  Günlük Trade: {risk['daily_trades']}\n"
            f"  Avg Win: {format_pct(risk['avg_win'])}\n"
            f"  Avg Loss: {format_pct(risk['avg_loss'])}\n"
            f"  Trading: {'✅ Aktif' if not self.engine.risk_manager.is_trading_halted else '⛔ Durduruldu'}"
        )

        if update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_kalite(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Veri kalitesi raporu."""
        chat = update.effective_chat or update.callback_query.message.chat
        if not self.is_authorized(chat.id):
            return

        stats = self.signal_tracker_stats()
        dq = stats["data_quality"]
        
        text = (
            f"<b>🔍 VERİ KALİTESİ RAPORU</b>\n"
            f"{'─' * 30}\n"
            f"  ✅ GOOD: {dq['good']} sinyal\n"
            f"  ⚠️ WARNING: {dq['warning']} sinyal\n"
            f"  ❌ FAIL: {dq['fail']} sinyal\n"
            f"  📊 Kalite Oranı: %{dq['good_pct']:.1f}\n\n"
            f"<b>Açıklama:</b>\n"
            f"  ✅ GOOD: Fiyat doğrulandı, sapma <%0.5\n"
            f"  ⚠️ WARNING: Doğrulandı ama sapma >%0.5\n"
            f"  ❌ FAIL: Fiyat doğrulanamadı\n\n"
            f"FAIL sinyalleri otomatik reddedilir.\n"
            f"Sadece doğrulanmış verilerle işlem yapılır."
        )

        if update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_baslat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Paper trading başlat."""
        chat = update.effective_chat or update.callback_query.message.chat
        if not self.is_authorized(chat.id):
            return

        if self.engine.is_running:
            text = "⚠️ Bot zaten çalışıyor."
        else:
            self.engine.resume_trading()
            asyncio.create_task(self.engine.start())
            text = "▶️ Paper Trading başlatıldı!"

        if update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_durdur(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Paper trading durdur."""
        chat = update.effective_chat or update.callback_query.message.chat
        if not self.is_authorized(chat.id):
            return

        self.engine.is_running = False
        text = "⏹ Paper Trading durduruluyor..."

        if update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Yardım."""
        if not self.is_authorized(update.effective_chat.id):
            return

        await update.message.reply_text(
            "<b>📋 KOMUT LİSTESİ</b>\n"
            f"{'─' * 30}\n"
            "/start — Ana menü\n"
            "/durum — Anlık durum raporu\n"
            "/bakiye — Bakiye bilgisi\n"
            "/istatistik — Detaylı istatistikler\n"
            "/sinyaller — Son 10 sinyal\n"
            "/trades — Son 10 trade\n"
            "/pozisyonlar — Açık pozisyonlar\n"
            "/risk — Risk metrikleri\n"
            "/kalite — Veri kalitesi raporu\n"
            "/baslat — Trading başlat\n"
            "/durdur — Trading durdur\n"
            "/yardim — Bu mesaj",
            parse_mode="HTML",
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
            "start_trading": self.cmd_baslat,
            "stop_trading": self.cmd_durdur,
        }

        handler = handlers.get(query.data)
        if handler:
            await handler(update, context)

    async def cmd_bakiye(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bakiye bilgisi."""
        chat = update.effective_chat or update.callback_query.message.chat
        if not self.is_authorized(chat.id):
            return

        risk = self.engine.risk_manager.get_stats()
        roi = ((self.engine.risk_manager.current_capital - self.engine.initial_capital) / self.engine.initial_capital) * 100

        text = (
            f"<b>💰 BAKİYE BİLGİSİ</b>\n"
            f"{'─' * 30}\n"
            f"  Başlangıç: {format_currency(self.engine.initial_capital)}\n"
            f"  Mevcut: {format_currency(self.engine.risk_manager.current_capital)}\n"
            f"  Net P&L: {format_currency(risk['net_pnl'])}\n"
            f"  Toplam Fee: {format_currency(risk['total_fees'])}\n"
            f"  ROI: {format_pct(roi)}\n"
            f"  Max Drawdown: {risk['max_drawdown']:.2f}%\n\n"
            f"📋 Mode: DEMO (sanal bakiye)"
        )

        if update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")

    # ==================== YARDIMCI ====================

    def signal_tracker_stats(self) -> dict:
        """Signal tracker istatistiklerini al."""
        return self.engine.signal_tracker.get_statistics()

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
        self.app.add_handler(CommandHandler("baslat", self.cmd_baslat))
        self.app.add_handler(CommandHandler("durdur", self.cmd_durdur))
        self.app.add_handler(CommandHandler("yardim", self.cmd_help))
        self.app.add_handler(CallbackQueryHandler(self.callback_handler))

        # Paper trading callback
        self.engine.set_telegram_callback(self.send_message)

        logger.info("Paper Trading Telegram Bot başlatılıyor...")

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

        # Paper trading engine'i başlat
        asyncio.create_task(self.engine.start())

        logger.info("Bot çalışıyor. Ctrl+C ile durdurun.")

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
