"""
Telegram Bot Entegrasyonu
Trading bot ile Telegram üzerinden etkileşim sağlar.
"""

import asyncio
import os
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

from main import TradingEngine
from utils.logger import setup_logger
from utils.helpers import format_currency, format_pct
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, INITIAL_CAPITAL

logger = setup_logger("TelegramBot")


class TradingTelegramBot:
    """Telegram bot ile trading kontrolu."""

    def __init__(self):
        self.engine = TradingEngine()
        self.app = None
        self.authorized_chat_ids = set()
        if TELEGRAM_CHAT_ID:
            self.authorized_chat_ids.add(int(TELEGRAM_CHAT_ID))

    def is_authorized(self, chat_id: int) -> bool:
        """Yetkili kullanici mi kontrol et."""
        if not self.authorized_chat_ids:
            return True  # Chat ID ayarlanmamissa herkese ac
        return chat_id in self.authorized_chat_ids

    async def send_message(self, text: str):
        """Mesaj gonder (trading engine callback)."""
        if self.app and TELEGRAM_CHAT_ID:
            try:
                await self.app.bot.send_message(
                    chat_id=int(TELEGRAM_CHAT_ID),
                    text=text,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"Mesaj gonderme hatasi: {e}")

    # ==================== KOMUTLAR ====================

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bot baslangic mesaji."""
        if not self.is_authorized(update.effective_chat.id):
            await update.message.reply_text("Yetkisiz erisim.")
            return

        keyboard = [
            [
                InlineKeyboardButton("Durum", callback_data="status"),
                InlineKeyboardButton("Bakiye", callback_data="balance"),
            ],
            [
                InlineKeyboardButton("Tradeler", callback_data="trades"),
                InlineKeyboardButton("Risk", callback_data="risk"),
            ],
            [
                InlineKeyboardButton("Baslat", callback_data="start_trading"),
                InlineKeyboardButton("Durdur", callback_data="stop_trading"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "<b>Crypto Trading Bot</b>\n\n"
            f"Sermaye: {format_currency(INITIAL_CAPITAL)}\n"
            f"Durum: {'Aktif' if self.engine.is_running else 'Durduruldu'}\n\n"
            "Bir komut secin:",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )

    async def cmd_durum(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Anlık durum raporu."""
        if not self.is_authorized(update.effective_chat.id):
            return

        status = self.engine.get_status()
        stats = status["stats"]
        positions = status["open_positions"]

        text = (
            "<b>Bot Durumu</b>\n"
            f"{'─' * 25}\n"
            f"Durum: {'Aktif' if status['is_running'] else 'Durduruldu'}\n"
            f"Uptime: {status['uptime']}\n"
            f"Tarama: #{status['scan_count']}\n\n"
            f"<b>Performans</b>\n"
            f"Sermaye: {format_currency(stats['current_capital'])}\n"
            f"ROI: {format_pct(stats['roi'])}\n"
            f"Net P&L: {format_currency(stats['net_pnl'])}\n"
            f"Fee: {format_currency(stats['total_fees'])}\n\n"
            f"<b>Trade Istatistikleri</b>\n"
            f"Toplam: {stats['total_trades']}\n"
            f"Win Rate: {stats['win_rate']:.1f}%\n"
            f"Bugun: {stats['daily_trades']} trade\n"
            f"Gunluk P&L: {format_currency(stats['daily_pnl'])}\n\n"
            f"<b>Acik Pozisyonlar</b>: {len(positions)}\n"
        )

        for pos in positions:
            text += (
                f"  {pos['symbol']} | {pos['side'].upper()} @ "
                f"{format_currency(pos['entry_price'])}\n"
            )

        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_bakiye(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bakiye bilgisi."""
        if not self.is_authorized(update.effective_chat.id):
            return

        stats = self.engine.risk_manager.get_stats()
        text = (
            "<b>Bakiye Bilgisi</b>\n"
            f"{'─' * 25}\n"
            f"Baslangic: {format_currency(stats['initial_capital'])}\n"
            f"Mevcut: {format_currency(stats['current_capital'])}\n"
            f"Net P&L: {format_currency(stats['net_pnl'])}\n"
            f"Toplam Fee: {format_currency(stats['total_fees'])}\n"
            f"ROI: {format_pct(stats['roi'])}\n"
            f"Max Drawdown: {stats['max_drawdown']:.2f}%"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Son trade'leri goster."""
        if not self.is_authorized(update.effective_chat.id):
            return

        closed_trades = [
            t for t in self.engine.risk_manager.trade_history
            if t.status == "closed"
        ][-10:]  # Son 10 trade

        if not closed_trades:
            await update.message.reply_text("Henuz kapanmis trade yok.")
            return

        text = "<b>Son Trade'ler</b>\n"
        for t in reversed(closed_trades):
            emoji = "WIN" if t.pnl > 0 else "LOSS"
            text += (
                f"\n{emoji} {t.symbol}\n"
                f"  {t.side.upper()} @ {format_currency(t.entry_price)} -> "
                f"{format_currency(t.exit_price)}\n"
                f"  P&L: {format_currency(t.pnl)} ({format_pct(t.pnl_pct)})\n"
            )

        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_sinyal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Aktif sinyalleri goster."""
        if not self.is_authorized(update.effective_chat.id):
            return

        await update.message.reply_text(
            "Sinyal taramasi yapiliyor...\n"
            "Aktif sinyaller otomatik olarak bildirilir."
        )

    async def cmd_risk(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Risk metriklerini goster."""
        if not self.is_authorized(update.effective_chat.id):
            return

        stats = self.engine.risk_manager.get_stats()
        text = (
            "<b>Risk Metrikleri</b>\n"
            f"{'─' * 25}\n"
            f"Max Drawdown: {stats['max_drawdown']:.2f}%\n"
            f"Ardisik Kayip: {stats['consecutive_losses']}\n"
            f"Gunluk P&L: {format_currency(stats['daily_pnl'])}\n"
            f"Gunluk Trade: {stats['daily_trades']}\n"
            f"Avg Win: {format_pct(stats['avg_win'])}\n"
            f"Avg Loss: {format_pct(stats['avg_loss'])}\n"
            f"Trading: {'Aktif' if not self.engine.risk_manager.is_trading_halted else 'Durduruldu'}"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_baslat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Trading'i baslat."""
        if not self.is_authorized(update.effective_chat.id):
            return

        if self.engine.is_running:
            await update.message.reply_text("Bot zaten calisiyor.")
            return

        self.engine.risk_manager.resume_trading()
        asyncio.create_task(self.engine.start())
        await update.message.reply_text("Trading baslatildi!")

    async def cmd_durdur(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Trading'i durdur."""
        if not self.is_authorized(update.effective_chat.id):
            return

        self.engine.is_running = False
        await update.message.reply_text("Trading durduruluyor...")

    async def cmd_backtest(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Son backtest sonuclarini goster."""
        if not self.is_authorized(update.effective_chat.id):
            return

        import json
        try:
            with open("data/backtest_results.json", "r") as f:
                results = json.load(f)

            text = (
                "<b>Son Backtest Sonuclari</b>\n"
                f"{'─' * 25}\n"
                f"Tarih: {results['timestamp'][:19]}\n"
                f"Baslangic: {format_currency(results['initial_capital'])}\n"
                f"Bitis: {format_currency(results['final_capital'])}\n"
                f"ROI: {format_pct(results['roi'])}\n"
                f"Trade: {results['total_trades']}\n"
                f"Win Rate: {results['win_rate']:.1f}%\n"
                f"Sharpe: {results['sharpe_ratio']:.2f}\n"
                f"Max DD: {results['max_drawdown']:.2f}%"
            )
            await update.message.reply_text(text, parse_mode="HTML")
        except FileNotFoundError:
            await update.message.reply_text("Backtest sonucu bulunamadi. Once backtest calistirin.")

    # ==================== CALLBACK HANDLER ====================

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Inline keyboard callback'leri isle."""
        query = update.callback_query
        await query.answer()

        if not self.is_authorized(query.message.chat_id):
            return

        if query.data == "status":
            await self.cmd_durum(update, context)
        elif query.data == "balance":
            await self.cmd_bakiye(update, context)
        elif query.data == "trades":
            await self.cmd_trades(update, context)
        elif query.data == "risk":
            await self.cmd_risk(update, context)
        elif query.data == "start_trading":
            await self.cmd_baslat(update, context)
        elif query.data == "stop_trading":
            await self.cmd_durdur(update, context)

    # ==================== ANA GIRIS ====================

    async def run(self):
        """Telegram bot'u baslat."""
        if not TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN ayarlanmamis!")
            logger.info("Telegram olmadan sadece trading engine calistirilacak.")
            await self.engine.start()
            return

        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Komutlari ekle
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("durum", self.cmd_durum))
        self.app.add_handler(CommandHandler("bakiye", self.cmd_bakiye))
        self.app.add_handler(CommandHandler("trades", self.cmd_trades))
        self.app.add_handler(CommandHandler("sinyal", self.cmd_sinyal))
        self.app.add_handler(CommandHandler("risk", self.cmd_risk))
        self.app.add_handler(CommandHandler("baslat", self.cmd_baslat))
        self.app.add_handler(CommandHandler("durdur", self.cmd_durdur))
        self.app.add_handler(CommandHandler("backtest", self.cmd_backtest))
        self.app.add_handler(CallbackQueryHandler(self.callback_handler))

        # Telegram callback'i ayarla
        self.engine.set_telegram_callback(self.send_message)

        logger.info("Telegram bot baslatiliyor...")

        # Bot + trading engine birlikte calistir
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

        # Trading engine'i baslat
        asyncio.create_task(self.engine.start())

        # Bekle
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()


async def main():
    bot = TradingTelegramBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
