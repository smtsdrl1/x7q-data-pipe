"""
Ana Trading Motoru
Canlı piyasa verilerini izler, strateji sinyallerini değerlendirir ve trade execute eder.
"""

import asyncio
import signal
import sys
from datetime import datetime

from strategies.multi_strategy import MultiStrategyEngine
from strategies.base_strategy import SignalType
from utils.data_fetcher import DataFetcher
from utils.risk_manager import RiskManager
from utils.position_manager import PositionManager
from utils.indicators import TechnicalIndicators
from utils.logger import setup_logger
from utils.helpers import format_currency, format_pct
from config import (
    INITIAL_CAPITAL, TRADING_PAIRS, PRIMARY_TIMEFRAME,
    CONFIRM_TIMEFRAME, SCAN_INTERVAL_SECONDS, HEARTBEAT_INTERVAL,
    OHLCV_LIMIT
)

logger = setup_logger("TradingEngine")


class TradingEngine:
    """Ana trading motoru."""

    def __init__(self):
        self.data_fetcher = DataFetcher()
        self.risk_manager = RiskManager(INITIAL_CAPITAL)
        self.position_manager = PositionManager(self.risk_manager)
        self.strategy_engine = MultiStrategyEngine()
        self.indicators = TechnicalIndicators()
        self.is_running = False
        self.scan_count = 0
        self.start_time = None
        self._telegram_callback = None

    def set_telegram_callback(self, callback):
        """Telegram bildirim callback'i ayarla."""
        self._telegram_callback = callback

    async def notify(self, message: str):
        """Telegram bildirimi gönder (varsa)."""
        if self._telegram_callback:
            try:
                await self._telegram_callback(message)
            except Exception as e:
                logger.error(f"Telegram bildirim hatası: {e}")

    async def start(self):
        """Trading motorunu başlat."""
        logger.info("=" * 50)
        logger.info("Trading Motoru Baslatiliyor...")
        logger.info(f"  Sermaye: {format_currency(INITIAL_CAPITAL)}")
        logger.info(f"  Pair sayisi: {len(TRADING_PAIRS)}")
        logger.info(f"  Timeframe: {PRIMARY_TIMEFRAME}")
        logger.info(f"  Tarama araligi: {SCAN_INTERVAL_SECONDS}s")
        logger.info("=" * 50)

        await self.data_fetcher.initialize()
        self.is_running = True
        self.start_time = datetime.now()

        await self.notify(
            "Trading Bot Baslatildi\n"
            f"Sermaye: {format_currency(INITIAL_CAPITAL)}\n"
            f"{len(TRADING_PAIRS)} pair takip ediliyor\n"
            f"Tarama: her {SCAN_INTERVAL_SECONDS}s"
        )

        try:
            tasks = [
                self._scan_loop(),
                self._position_monitor_loop(),
                self._heartbeat_loop(),
            ]
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Trading motoru durduruluyor...")
        finally:
            await self.stop()

    async def stop(self):
        """Trading motorunu durdur."""
        self.is_running = False
        await self.data_fetcher.close()

        stats = self.risk_manager.get_stats()
        summary = (
            f"Trading Bot Durduruldu\n"
            f"Sermaye: {format_currency(stats['current_capital'])}\n"
            f"ROI: {format_pct(stats['roi'])}\n"
            f"Toplam Trade: {stats['total_trades']}\n"
            f"Win Rate: {stats['win_rate']:.1f}%"
        )
        logger.info(summary)
        await self.notify(summary)

    async def _scan_loop(self):
        """Piyasa tarama dongusu."""
        while self.is_running:
            try:
                self.scan_count += 1
                await self._scan_markets()
                await asyncio.sleep(SCAN_INTERVAL_SECONDS)
            except Exception as e:
                logger.error(f"Tarama hatasi: {e}")
                await asyncio.sleep(SCAN_INTERVAL_SECONDS * 2)

    async def _scan_markets(self):
        """Tum pairleri tara ve sinyalleri degerlendir."""
        can_trade, reason = self.risk_manager.can_trade()
        if not can_trade:
            if self.scan_count % 60 == 0:
                logger.warning(f"Trading durdu: {reason}")
            return

        for pair in TRADING_PAIRS:
            if pair in self.position_manager.open_positions:
                continue

            try:
                df = await self.data_fetcher.fetch_ohlcv(pair, PRIMARY_TIMEFRAME, OHLCV_LIMIT)
                if df.empty or len(df) < 60:
                    continue

                analysis = self.strategy_engine.analyze(df, pair)

                if analysis["signal"] == SignalType.BUY:
                    await self._execute_buy(pair, analysis)

            except Exception as e:
                logger.error(f"Analiz hatasi ({pair}): {e}")

    async def _execute_buy(self, symbol: str, analysis: dict):
        """Alim emri yurut."""
        price = analysis["price"]
        atr = analysis["atr"]

        position = self.position_manager.open_position(symbol, "buy", price, atr)
        if position:
            reasons = ", ".join(analysis.get("buy_reasons", [])[:3])
            message = (
                f"ALIM SINYALI\n"
                f"Symbol: #{symbol.replace('/', '')}\n"
                f"Fiyat: {format_currency(price)}\n"
                f"Skor: {analysis['composite_score']:.2f}\n"
                f"RSI: {analysis['rsi']:.1f}\n"
                f"Vol: {analysis['volume_ratio']:.1f}x\n"
                f"SL: {format_currency(position.stop_loss)}\n"
                f"TP: {format_currency(position.take_profit)}\n"
                f"Sebepler: {reasons}"
            )
            await self.notify(message)

    async def _position_monitor_loop(self):
        """Acik pozisyonlari surekli izle."""
        while self.is_running:
            try:
                for symbol in list(self.position_manager.open_positions.keys()):
                    ticker = await self.data_fetcher.fetch_ticker(symbol)
                    if not ticker:
                        continue

                    current_price = ticker.get("last", 0)
                    if current_price <= 0:
                        continue

                    result = self.position_manager.check_exits(symbol, current_price)
                    if result and "error" not in result:
                        emoji = "WIN" if result["pnl"] > 0 else "LOSS"
                        message = (
                            f"{emoji} POZISYON KAPANDI\n"
                            f"Symbol: #{symbol.replace('/', '')}\n"
                            f"Giris: {format_currency(result['entry_price'])}\n"
                            f"Cikis: {format_currency(result['exit_price'])}\n"
                            f"P&L: {format_currency(result['pnl'])} ({format_pct(result['pnl_pct'])})\n"
                            f"Fee: {format_currency(result['fee'])}\n"
                            f"Sebep: {result['reason']}\n"
                            f"Sermaye: {format_currency(self.risk_manager.current_capital)}"
                        )
                        await self.notify(message)

                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Pozisyon izleme hatasi: {e}")
                await asyncio.sleep(5)

    async def _heartbeat_loop(self):
        """Periyodik durum raporu."""
        while self.is_running:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            stats = self.risk_manager.get_stats()
            open_pos = self.position_manager.get_open_positions()
            uptime = datetime.now() - self.start_time

            message = (
                f"Durum Raporu\n"
                f"Uptime: {str(uptime).split('.')[0]}\n"
                f"Sermaye: {format_currency(stats['current_capital'])}\n"
                f"ROI: {format_pct(stats['roi'])}\n"
                f"Trade: {stats['total_trades']} (Bugun: {stats['daily_trades']})\n"
                f"Win Rate: {stats['win_rate']:.1f}%\n"
                f"Acik Pozisyon: {len(open_pos)}\n"
                f"Tarama: #{self.scan_count}"
            )
            logger.info(message.replace('\n', ' | '))

    def get_status(self) -> dict:
        """Bot durumunu dondur."""
        stats = self.risk_manager.get_stats()
        open_pos = self.position_manager.get_open_positions()
        return {
            "is_running": self.is_running,
            "uptime": str(datetime.now() - self.start_time).split('.')[0] if self.start_time else "N/A",
            "scan_count": self.scan_count,
            "stats": stats,
            "open_positions": open_pos,
        }


async def main():
    """Ana giris noktasi."""
    engine = TradingEngine()

    loop = asyncio.get_event_loop()

    def shutdown_handler():
        logger.info("Kapatma sinyali alindi...")
        engine.is_running = False

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_handler)
        except NotImplementedError:
            pass

    await engine.start()


if __name__ == "__main__":
    asyncio.run(main())
