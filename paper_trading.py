"""
Paper Trading Motor — Profesyonel Demo Simülasyon v2.0
Gerçek piyasa verileriyle sanal bakiye üzerinden trade simülasyonu.
Her işlem sinyal tracker'a, trade journal'a ve bildirim yöneticisine kaydedilir.
Her bildirimde O ANDAKİ GERÇEK FİYAT doğrulanır ve kaydedilir.
NULL/random veri KABUL ETMEZ — kusursuz audit trail.
"""

import asyncio
from datetime import datetime, timezone
from utils.data_fetcher import DataFetcher
from utils.risk_manager import RiskManager, TradeRecord
from utils.position_manager import PositionManager
from utils.price_verifier import PriceVerifier
from utils.signal_tracker import SignalTracker
from utils.notification_manager import NotificationManager, NotificationType
from utils.trade_journal import TradeJournal
from utils.logger import setup_logger
from utils.helpers import format_currency, format_pct
from strategies.multi_strategy import MultiStrategyEngine
from strategies.base_strategy import SignalType
from config import (
    TRADING_PAIRS, PRIMARY_TIMEFRAME, OHLCV_LIMIT,
    SCAN_INTERVAL_SECONDS, MAX_CONCURRENT_POSITIONS,
)

logger = setup_logger("PaperTrading")


class PaperTradingEngine:
    """
    Paper Trading Motoru v2.0:
    - Gerçek Binance verileriyle piyasa taranır
    - Sinyal üretildiğinde fiyat ANI doğrulanır
    - Sanal bakiye üzerinden pozisyon açılır
    - Pozisyon izlenir (SL/TP/trailing)
    - Çıkışta fiyat tekrar doğrulanır
    - Her detay sinyal tracker'a kaydedilir
    - Her bildirim notification manager ile izlenir
    - Her trade, trade journal'a tam detayla yazılır
    - Bildirim gönderildiği anda GERÇEK fiyat kaydedilir
    """

    def __init__(self, initial_capital: float = 1000.0):
        self.initial_capital = initial_capital
        self.data_fetcher = DataFetcher()
        self.risk_manager = RiskManager(initial_capital)
        self.position_manager = PositionManager(self.risk_manager)
        self.strategy_engine = MultiStrategyEngine()
        self.price_verifier = PriceVerifier(self.data_fetcher)
        self.signal_tracker = SignalTracker()

        # === YENİ: Bildirim ve Journal sistemi ===
        self.notification_manager = NotificationManager()
        self.trade_journal = TradeJournal()

        self.is_running = False
        self.scan_count = 0
        self.start_time = None
        self._telegram_callback = None
        self._signal_id_map: dict[str, str] = {}  # symbol → signal_id

    def set_telegram_callback(self, callback):
        self._telegram_callback = callback

    async def _tracked_notify(
        self,
        message: str,
        notification_type: NotificationType,
        symbol: str = "",
        direction: str = "",
        signal_id: str = "",
        trade_pnl: float = 0.0,
        trade_result: str = "",
    ) -> str:
        """
        İZLENEN bildirim gönderimi.
        Her bildirim:
        1. NotificationRecord oluşturulur (created_at kaydedilir)
        2. Symbol varsa O ANDAKİ GERÇEK FİYAT çekilir ve kaydedilir
        3. Telegram'a gönderilir
        4. Gönderim durumu (başarı/hata) kaydedilir
        5. Bildirim ID trade journal'a eklenir
        Dönüş: notification_id
        """
        # 1) Bildirim kaydı oluştur
        record = self.notification_manager.create_notification(
            notification_type=notification_type,
            symbol=symbol,
            direction=direction,
            signal_id=signal_id,
            portfolio_value=self.risk_manager.current_capital,
            open_positions_count=len(self.position_manager.open_positions),
            trade_pnl=trade_pnl,
            trade_result=trade_result,
        )

        # 2) Symbol varsa bildirim anındaki gerçek fiyatı çek
        if symbol:
            try:
                price_at_notif = await self.price_verifier.verify_price(symbol)
                self.notification_manager.record_price_at_notification(
                    record, price_at_notif
                )
            except Exception as e:
                logger.error(f"Bildirim fiyat çekme hatası ({symbol}): {e}")
                record.price_verified = False
                record.error_message = f"Fiyat çekme hatası: {e}"

        # 3) Telegram'a gönder
        if self._telegram_callback:
            try:
                await self._telegram_callback(message)
                # 4a) Başarılı gönderim
                parts = 1
                if len(message) > 4000:
                    parts = (len(message) // 4000) + 1
                self.notification_manager.mark_sent(
                    record,
                    message_length=len(message),
                    message_parts=parts,
                )
            except Exception as e:
                # 4b) Başarısız gönderim
                self.notification_manager.mark_failed(record, str(e))
                logger.error(f"Telegram bildirim hatası: {e}")
        else:
            # Telegram callback yok, yine de kaydedilir
            self.notification_manager.mark_failed(
                record, "Telegram callback ayarlanmamış"
            )

        # 5) Trade journal'a bildirim ID ekle
        if signal_id or symbol:
            self.trade_journal.add_notification_id(
                symbol=symbol,
                notification_id=record.notification_id,
                success=record.delivery_status == "SENT",
            )

        return record.notification_id

    async def notify(self, message: str, parse_mode: str = "HTML"):
        """Basit bildirim (geriye uyumluluk)."""
        if self._telegram_callback:
            try:
                await self._telegram_callback(message)
            except Exception as e:
                logger.error(f"Telegram bildirim hatası: {e}")

    async def start(self):
        """Paper trading motorunu başlat."""
        logger.info("=" * 60)
        logger.info("PAPER TRADING MOTORU v2.0 BAŞLATILIYOR")
        logger.info(f"  Sanal Sermaye: {format_currency(self.initial_capital)}")
        logger.info(f"  Pair sayısı: {len(TRADING_PAIRS)}")
        logger.info(f"  Timeframe: {PRIMARY_TIMEFRAME}")
        logger.info(f"  Tarama aralığı: {SCAN_INTERVAL_SECONDS}s")
        logger.info(f"  Bildirim izleme: AKTİF")
        logger.info(f"  Trade journal: AKTİF")
        logger.info("=" * 60)

        await self.data_fetcher.initialize()
        self.is_running = True
        self.start_time = datetime.now(timezone.utc)

        await self._tracked_notify(
            "🟢 <b>PAPER TRADING v2.0 BAŞLATILDI</b>\n"
            f"{'─' * 30}\n"
            f"💰 Sanal Sermaye: {format_currency(self.initial_capital)}\n"
            f"📊 {len(TRADING_PAIRS)} pair takip ediliyor\n"
            f"⏱ Tarama: her {SCAN_INTERVAL_SECONDS}s\n"
            f"📋 Mode: DEMO (gerçek veri, sanal para)\n"
            f"📱 Bildirim İzleme: AKTİF\n"
            f"📓 Trade Journal: AKTİF\n"
            f"🕐 Başlangıç: {self.start_time.strftime('%d.%m.%Y %H:%M:%S.%f')[:-3]} UTC",
            notification_type=NotificationType.SYSTEM_START,
        )

        try:
            tasks = [
                self._scan_loop(),
                self._position_monitor_loop(),
                self._periodic_report_loop(),
                self._daily_summary_loop(),
            ]
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Paper trading durduruluyor...")
        finally:
            await self.stop()

    async def stop(self):
        """Motoru durdur ve özet gönder."""
        self.is_running = False
        stats = self.signal_tracker.get_statistics()
        notif_stats = self.notification_manager.get_statistics()
        journal_stats = self.trade_journal.get_statistics()

        await self._tracked_notify(
            "🔴 <b>PAPER TRADING DURDURULDU</b>\n"
            f"{'─' * 30}\n"
            f"💰 Sermaye: {format_currency(self.risk_manager.current_capital)}\n"
            f"📈 ROI: {format_pct(((self.risk_manager.current_capital - self.initial_capital) / self.initial_capital) * 100)}\n\n"
            f"📊 <b>Sinyal Özeti</b>\n"
            f"  Toplam: {stats['total_signals']}\n"
            f"  ✅ Win: {stats['wins']} | ❌ Loss: {stats['losses']}\n"
            f"  🎯 Win Rate: {stats['win_rate']:.1f}%\n"
            f"  💵 Net P&L: {format_currency(stats['total_pnl'])}\n\n"
            f"📱 <b>Bildirim Özeti</b>\n"
            f"  Gönderilen: {notif_stats['sent']}\n"
            f"  Başarısız: {notif_stats['failed']}\n"
            f"  Teslimat: %{notif_stats['delivery_rate']:.1f}\n\n"
            f"📓 <b>Journal</b>\n"
            f"  Kayıtlı Trade: {journal_stats['total_entries']}\n"
            f"  Ort. Bütünlük: {journal_stats['avg_data_integrity']:.0f}/100",
            notification_type=NotificationType.SYSTEM_STOP,
        )

        await self.data_fetcher.close()

    # ==================== TARAMA ====================

    async def _scan_loop(self):
        """Piyasa tarama döngüsü."""
        while self.is_running:
            try:
                self.scan_count += 1
                await self._scan_markets()
                await asyncio.sleep(SCAN_INTERVAL_SECONDS)
            except Exception as e:
                logger.error(f"Tarama hatası: {e}")
                await asyncio.sleep(SCAN_INTERVAL_SECONDS * 2)

    async def _scan_markets(self):
        """Tüm pairleri tara, sinyal üret, fiyat doğrula, paper trade aç."""
        can_trade, reason = self.risk_manager.can_trade()
        if not can_trade:
            if self.scan_count % 60 == 0:
                logger.warning(f"Trading durdu: {reason}")
                # Risk uyarısı bildirimi
                await self._tracked_notify(
                    f"⚠️ <b>TRADE DURDURULDU</b>\n"
                    f"{'─' * 30}\n"
                    f"Sebep: {reason}\n"
                    f"🕐 {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M:%S.%f')[:-3]} UTC",
                    notification_type=NotificationType.RISK_ALERT,
                )
            return

        for pair in TRADING_PAIRS:
            if pair in self.position_manager.open_positions:
                continue

            try:
                # 1) OHLCV verisini çek
                df = await self.data_fetcher.fetch_ohlcv(
                    pair, PRIMARY_TIMEFRAME, OHLCV_LIMIT
                )
                if df.empty or len(df) < 60:
                    continue

                # 2) Strateji analizi
                analysis = self.strategy_engine.analyze(df, pair)

                if analysis["signal"] == SignalType.NEUTRAL:
                    continue

                direction = "BUY" if analysis["signal"] == SignalType.BUY else "SELL"

                # 3) ANLIK fiyat doğrulama (gerçek zamanlı Binance ticker)
                verification = await self.price_verifier.verify_and_compare(
                    pair, analysis["price"]
                )

                # 4) Sinyali kaydet (her durumda)
                signal = self.signal_tracker.record_signal(
                    symbol=pair,
                    direction=direction,
                    analysis=analysis,
                    verification=verification,
                )

                # 5) Veri kalitesi kontrolü — FAIL ise reddet
                if verification["data_quality"] == "FAIL":
                    self.signal_tracker.reject_signal(
                        signal.signal_id,
                        f"Veri kalitesi FAIL: {verification['verified_price'].error}",
                    )
                    await self._tracked_notify(
                        f"⚠️ <b>SİNYAL REDDEDİLDİ</b> — Veri Hatası\n"
                        f"{'─' * 30}\n"
                        f"📊 {pair} | {direction}\n"
                        f"❌ Sebep: {verification['verified_price'].error}\n"
                        f"🕐 {signal.signal_time_readable}\n"
                        f"🔢 Sinyal ID: <code>{signal.signal_id}</code>",
                        notification_type=NotificationType.SIGNAL_REJECTED,
                        symbol=pair,
                        direction=direction,
                        signal_id=signal.signal_id,
                    )
                    continue

                # 6) Sadece BUY sinyallerini işleme al (spot paper trading)
                if direction != "BUY":
                    signal.status = "REJECTED"
                    signal.exit_reason = "Sadece BUY sinyalleri işleniyor (spot mode)"
                    self.signal_tracker._save_history()
                    continue

                # 7) Doğrulanmış fiyatla paper trade aç
                real_price = verification["real_price"]
                atr = analysis.get("atr", 0)

                position = self.position_manager.open_position(
                    pair, "buy", real_price, atr
                )
                if not position:
                    self.signal_tracker.reject_signal(
                        signal.signal_id,
                        "Risk yönetimi tarafından reddedildi",
                    )
                    await self._tracked_notify(
                        f"⛔ <b>POZİSYON REDDEDİLDİ</b> — Risk Yönetimi\n"
                        f"{'─' * 30}\n"
                        f"📊 {pair} | {direction}\n"
                        f"🕐 {signal.signal_time_readable}\n"
                        f"🔢 Sinyal ID: <code>{signal.signal_id}</code>",
                        notification_type=NotificationType.SIGNAL_REJECTED,
                        symbol=pair,
                        direction=direction,
                        signal_id=signal.signal_id,
                    )
                    continue

                # 8) Sinyal tracker'ı güncelle
                self.signal_tracker.activate_signal(
                    signal_id=signal.signal_id,
                    entry_price=real_price,
                    stop_loss=position.stop_loss,
                    take_profit=position.take_profit,
                    quantity=position.quantity,
                    position_size_usd=position.quantity * real_price,
                )
                self._signal_id_map[pair] = signal.signal_id

                # 9) Trade Journal'a kaydet
                journal_entry = self.trade_journal.open_entry(
                    signal_id=signal.signal_id,
                    symbol=pair,
                    direction=direction,
                    analysis=analysis,
                    verification=verification,
                    entry_price=real_price,
                    stop_loss=position.stop_loss,
                    take_profit=position.take_profit,
                    quantity=position.quantity,
                    portfolio_value=self.risk_manager.current_capital,
                )

                # 10) DETAYLI Telegram bildirimi (izlenen)
                vp = verification["verified_price"]
                now_str = datetime.now(timezone.utc).strftime(
                    "%d.%m.%Y %H:%M:%S.%f"
                )[:-3]

                await self._tracked_notify(
                    f"🟢 <b>PAPER TRADE AÇILDI</b>\n"
                    f"{'─' * 30}\n"
                    f"📊 <b>{pair}</b> | {direction}\n"
                    f"🕐 Sinyal: {signal.signal_time_readable}\n"
                    f"📨 Bildirim: {now_str} UTC\n\n"
                    f"💰 <b>Fiyat Bilgisi</b>\n"
                    f"  Sinyal Fiyatı: {format_currency(analysis['price'])}\n"
                    f"  Doğrulanan: {format_currency(real_price)}\n"
                    f"  Bid: {format_currency(vp.bid)} | Ask: {format_currency(vp.ask)}\n"
                    f"  Spread: %{vp.spread:.3f}\n"
                    f"  Sapma: %{verification['deviation_pct']:.3f}\n"
                    f"  Veri Kalitesi: {verification['data_quality']}\n"
                    f"  Gecikme: {vp.latency_ms:.0f}ms\n\n"
                    f"📈 <b>Strateji</b>\n"
                    f"  Skor: {analysis['composite_score']:.2f}\n"
                    f"  RSI: {analysis['rsi']:.1f}\n"
                    f"  Hacim: {analysis['volume_ratio']:.1f}x\n"
                    f"  Onay: {analysis['buy_count']}B/{analysis['sell_count']}S\n"
                    f"  Sebepler: {', '.join(analysis.get('buy_reasons', [])[:3])}\n\n"
                    f"🎯 <b>Pozisyon</b>\n"
                    f"  Giriş: {format_currency(real_price)}\n"
                    f"  Stop Loss: {format_currency(position.stop_loss)}\n"
                    f"  Take Profit: {format_currency(position.take_profit)}\n"
                    f"  Boyut: {format_currency(position.quantity * real_price)}\n"
                    f"  Miktar: {position.quantity:.6f}\n\n"
                    f"💼 Sermaye: {format_currency(self.risk_manager.current_capital)}\n"
                    f"📊 Açık Poz: {len(self.position_manager.open_positions)}/{MAX_CONCURRENT_POSITIONS}\n"
                    f"📓 Journal: <code>{journal_entry.journal_id}</code>\n"
                    f"🔢 Sinyal: <code>{signal.signal_id}</code>",
                    notification_type=NotificationType.TRADE_OPENED,
                    symbol=pair,
                    direction=direction,
                    signal_id=signal.signal_id,
                )

            except Exception as e:
                logger.error(f"Sinyal işleme hatası ({pair}): {e}")

    # ==================== POZİSYON İZLEME ====================

    async def _position_monitor_loop(self):
        """Açık pozisyonları sürekli izle — çıkışta fiyat doğrula ve journal güncelle."""
        while self.is_running:
            try:
                for symbol in list(self.position_manager.open_positions.keys()):
                    # Gerçek fiyat çek
                    verified = await self.price_verifier.verify_price(symbol)
                    if not verified.verified or verified.price <= 0:
                        continue

                    current_price = verified.price

                    # Trade journal'a fiyat snapshot ekle (her 30 kontrolde bir)
                    if self.scan_count % 30 == 0:
                        self.trade_journal.add_price_snapshot(
                            symbol, verified, "MONITORING"
                        )

                    # Pozisyon çıkış kontrolü
                    result = self.position_manager.check_exits(symbol, current_price)
                    if result and "error" not in result:
                        # Çıkış fiyatını da doğrula
                        exit_verification = await self.price_verifier.verify_price(
                            symbol
                        )

                        # Signal tracker güncelle
                        signal = self.signal_tracker.close_signal(
                            symbol=symbol,
                            exit_price=current_price,
                            exit_reason=result["reason"],
                            pnl=result["pnl"],
                            pnl_pct=result["pnl_pct"],
                            fee=result["fee"],
                            exit_verified_price=(
                                exit_verification.price
                                if exit_verification.verified
                                else 0
                            ),
                            exit_data_quality=(
                                "GOOD" if exit_verification.verified else "FAIL"
                            ),
                        )

                        # Trade journal kapat
                        pos = None
                        for sym, p in self.position_manager.open_positions.items():
                            if sym == symbol:
                                pos = p
                                break

                        journal_entry = self.trade_journal.close_entry(
                            symbol=symbol,
                            exit_price=current_price,
                            exit_reason=result["reason"],
                            pnl=result["pnl"],
                            pnl_pct=result["pnl_pct"],
                            fee=result["fee"],
                            exit_verified_price=exit_verification,
                            portfolio_value=self.risk_manager.current_capital,
                            trailing_stop_final=(
                                pos.trailing_stop if pos else 0
                            ),
                        )

                        # Signal ID temizle
                        signal_id = self._signal_id_map.pop(symbol, "")

                        # Sonuç hesapla
                        is_win = result["pnl"] > 0
                        emoji = "✅" if is_win else "❌"
                        result_text = "WIN" if is_win else "LOSS"

                        duration_text = ""
                        if signal and signal.duration_seconds > 0:
                            mins = signal.duration_seconds // 60
                            secs = signal.duration_seconds % 60
                            if mins > 60:
                                hours = mins // 60
                                mins = mins % 60
                                duration_text = f"{hours}s {mins}dk {secs}sn"
                            else:
                                duration_text = f"{mins}dk {secs}sn"

                        integrity = (
                            journal_entry.data_integrity_score
                            if journal_entry
                            else 0
                        )
                        journal_id = (
                            journal_entry.journal_id if journal_entry else "N/A"
                        )
                        now_str = datetime.now(timezone.utc).strftime(
                            "%d.%m.%Y %H:%M:%S.%f"
                        )[:-3]

                        # İZLENEN Telegram bildirimi
                        await self._tracked_notify(
                            f"{emoji} <b>PAPER TRADE KAPANDI — {result_text}</b>\n"
                            f"{'─' * 30}\n"
                            f"📊 <b>{symbol}</b>\n"
                            f"🕐 Kapanış: {now_str} UTC\n"
                            f"📨 Bildirim: {now_str} UTC\n\n"
                            f"💰 <b>İşlem Sonucu</b>\n"
                            f"  Giriş: {format_currency(result['entry_price'])}\n"
                            f"  Çıkış: {format_currency(result['exit_price'])}\n"
                            f"  Doğrulanan Çıkış: {format_currency(exit_verification.price)}\n"
                            f"  Brüt P&L: {format_currency(result['pnl'])}\n"
                            f"  Fee: {format_currency(result['fee'])}\n"
                            f"  Net P&L: {format_currency(result['pnl'] - result['fee'])} "
                            f"({format_pct(result['pnl_pct'])})\n\n"
                            f"📋 <b>Detaylar</b>\n"
                            f"  Sebep: {result['reason']}\n"
                            f"  Süre: {duration_text}\n"
                            f"  Çıkış Kalitesi: {'✅ GOOD' if exit_verification.verified else '❌ FAIL'}\n"
                            f"  Veri Bütünlük: {integrity:.0f}/100\n\n"
                            f"💼 <b>Portföy</b>\n"
                            f"  Sermaye: {format_currency(self.risk_manager.current_capital)}\n"
                            f"  ROI: {format_pct(((self.risk_manager.current_capital - self.initial_capital) / self.initial_capital) * 100)}\n"
                            f"  Açık Poz: {len(self.position_manager.open_positions)}\n\n"
                            f"📓 Journal: <code>{journal_id}</code>",
                            notification_type=NotificationType.TRADE_CLOSED,
                            symbol=symbol,
                            signal_id=signal_id,
                            trade_pnl=result["pnl"],
                            trade_result=result_text,
                        )

                await asyncio.sleep(2)  # 2 saniyede bir kontrol
            except Exception as e:
                logger.error(f"Pozisyon izleme hatası: {e}")
                await asyncio.sleep(5)

    # ==================== PERİYODİK RAPOR ====================

    async def _periodic_report_loop(self):
        """Her 15 dakikada detaylı istatistik raporu."""
        while self.is_running:
            await asyncio.sleep(900)  # 15 dakika
            try:
                stats = self.signal_tracker.get_statistics()
                risk_stats = self.risk_manager.get_stats()
                notif_stats = self.notification_manager.get_statistics()
                journal_stats = self.trade_journal.get_statistics()
                uptime = datetime.now(timezone.utc) - self.start_time
                uptime_str = str(uptime).split(".")[0]
                now_str = datetime.now(timezone.utc).strftime(
                    "%d.%m.%Y %H:%M:%S"
                )

                open_pos_text = ""
                for sym, pos in self.position_manager.open_positions.items():
                    vp = await self.price_verifier.verify_price(sym)
                    if vp.verified:
                        unrealized_pnl = (
                            (vp.price - pos.entry_price) * pos.quantity
                        )
                        unrealized_pct = (
                            (vp.price - pos.entry_price) / pos.entry_price
                        ) * 100
                        pnl_emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
                        open_pos_text += (
                            f"  {pnl_emoji} {sym}: {format_currency(vp.price)} "
                            f"({format_pct(unrealized_pct)}) "
                            f"[{vp.latency_ms:.0f}ms]\n"
                        )
                    else:
                        open_pos_text += f"  ⚠️ {sym}: Fiyat alınamadı\n"

                if not open_pos_text:
                    open_pos_text = "  Açık pozisyon yok\n"

                await self._tracked_notify(
                    f"📊 <b>15dk DURUM RAPORU</b>\n"
                    f"{'─' * 30}\n"
                    f"🕐 {now_str} UTC\n"
                    f"⏱ Uptime: {uptime_str}\n"
                    f"🔍 Tarama: #{self.scan_count}\n\n"
                    f"💰 <b>Portföy</b>\n"
                    f"  Sermaye: {format_currency(self.risk_manager.current_capital)}\n"
                    f"  ROI: {format_pct(risk_stats['roi'])}\n"
                    f"  Max DD: {risk_stats['max_drawdown']:.2f}%\n\n"
                    f"📈 <b>Sinyal İstatistikleri</b>\n"
                    f"  Toplam: {stats['total_signals']}\n"
                    f"  Aktif: {stats['active']}\n"
                    f"  Kapalı: {stats['closed']}\n"
                    f"  Reddedilen: {stats['rejected']}\n"
                    f"  ✅ Win: {stats['wins']} | ❌ Loss: {stats['losses']}\n"
                    f"  🎯 Win Rate: {stats['win_rate']:.1f}%\n"
                    f"  💵 Net P&L: {format_currency(stats['total_pnl'])}\n"
                    f"  📊 Profit Factor: {stats['profit_factor']:.2f}\n\n"
                    f"📱 <b>Bildirim Durumu</b>\n"
                    f"  Gönderilen: {notif_stats['sent']}\n"
                    f"  Başarısız: {notif_stats['failed']}\n"
                    f"  Teslimat: %{notif_stats['delivery_rate']:.1f}\n"
                    f"  Ort. Gecikme: {notif_stats['latency']['avg_ms']:.0f}ms\n\n"
                    f"📓 <b>Journal</b>\n"
                    f"  Toplam: {journal_stats['total_entries']}\n"
                    f"  Ort. Bütünlük: {journal_stats['avg_data_integrity']:.0f}/100\n\n"
                    f"📊 <b>Veri Kalitesi</b>\n"
                    f"  ✅ GOOD: {stats['data_quality']['good']}\n"
                    f"  ⚠️ WARNING: {stats['data_quality']['warning']}\n"
                    f"  ❌ FAIL: {stats['data_quality']['fail']}\n\n"
                    f"📍 <b>Açık Pozisyonlar</b>\n"
                    f"{open_pos_text}\n"
                    f"📆 <b>Bugün</b>\n"
                    f"  Sinyal: {stats['today']['signals']}\n"
                    f"  Kapalı: {stats['today']['closed']}\n"
                    f"  P&L: {format_currency(stats['today']['pnl'])}",
                    notification_type=NotificationType.PERIODIC_REPORT,
                )
            except Exception as e:
                logger.error(f"Periyodik rapor hatası: {e}")

    # ==================== GÜNLÜK ÖZET ====================

    async def _daily_summary_loop(self):
        """Her gün gece yarısında günlük özet raporu."""
        while self.is_running:
            # Sonraki gece yarısına kadar bekle
            now = datetime.now(timezone.utc)
            tomorrow = now.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            if tomorrow <= now:
                from datetime import timedelta
                tomorrow += timedelta(days=1)
            wait_seconds = (tomorrow - now).total_seconds()
            await asyncio.sleep(wait_seconds)

            if not self.is_running:
                break

            try:
                stats = self.signal_tracker.get_statistics()
                notif_stats = self.notification_manager.get_statistics()
                journal_stats = self.trade_journal.get_statistics()
                risk_stats = self.risk_manager.get_stats()

                today_data = stats["today"]
                today_notif = notif_stats["today"]

                roi = ((self.risk_manager.current_capital - self.initial_capital) / self.initial_capital) * 100

                await self._tracked_notify(
                    f"📅 <b>GÜNLÜK ÖZET RAPORU</b>\n"
                    f"{'─' * 30}\n"
                    f"🕐 {datetime.now(timezone.utc).strftime('%d.%m.%Y')} UTC\n\n"
                    f"💰 <b>Portföy</b>\n"
                    f"  Başlangıç: {format_currency(self.initial_capital)}\n"
                    f"  Mevcut: {format_currency(self.risk_manager.current_capital)}\n"
                    f"  Toplam ROI: {format_pct(roi)}\n"
                    f"  Max Drawdown: {risk_stats['max_drawdown']:.2f}%\n\n"
                    f"📊 <b>Bugünkü Aktivite</b>\n"
                    f"  Sinyal Sayısı: {today_data['signals']}\n"
                    f"  Kapatılan: {today_data['closed']}\n"
                    f"  Günlük P&L: {format_currency(today_data['pnl'])}\n\n"
                    f"📈 <b>Genel Performans</b>\n"
                    f"  Toplam Trade: {stats['closed']}\n"
                    f"  Win Rate: {stats['win_rate']:.1f}%\n"
                    f"  Profit Factor: {stats['profit_factor']:.2f}\n"
                    f"  Net P&L: {format_currency(stats['total_pnl'])}\n\n"
                    f"📱 <b>Bildirimler (Bugün)</b>\n"
                    f"  Gönderilen: {today_notif['sent']}\n"
                    f"  Başarısız: {today_notif['failed']}\n"
                    f"  Toplam: {today_notif['total']}\n\n"
                    f"📓 <b>Journal</b>\n"
                    f"  Bugün Kayıt: {journal_stats['today']['entries']}\n"
                    f"  Ort. Bütünlük: {journal_stats['avg_data_integrity']:.0f}/100\n\n"
                    f"🔍 <b>Veri Kalitesi (Genel)</b>\n"
                    f"  GOOD: {stats['data_quality']['good']} | "
                    f"WARNING: {stats['data_quality']['warning']} | "
                    f"FAIL: {stats['data_quality']['fail']}",
                    notification_type=NotificationType.DAILY_SUMMARY,
                )

                # Günlük risk manager sıfırla
                self.risk_manager.reset_daily()

            except Exception as e:
                logger.error(f"Günlük özet hatası: {e}")

    # ==================== DURUM ====================

    def get_status(self) -> dict:
        """Bot durumunu döndür."""
        stats = self.signal_tracker.get_statistics()
        risk_stats = self.risk_manager.get_stats()
        open_pos = self.position_manager.get_open_positions()
        notif_stats = self.notification_manager.get_statistics()
        journal_stats = self.trade_journal.get_statistics()

        return {
            "is_running": self.is_running,
            "mode": "PAPER v2.0",
            "uptime": (
                str(datetime.now(timezone.utc) - self.start_time).split(".")[0]
                if self.start_time
                else "N/A"
            ),
            "scan_count": self.scan_count,
            "signal_stats": stats,
            "risk_stats": risk_stats,
            "open_positions": open_pos,
            "notification_stats": notif_stats,
            "journal_stats": journal_stats,
        }

    def resume_trading(self):
        """Trading'i devam ettir (risk halt sonrası)."""
        self.risk_manager.is_trading_halted = False
        logger.info("Trading devam ettiriliyor")
