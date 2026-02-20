"""
Paper Trading Motor — Demo Simülasyon
Gerçek piyasa verileriyle sanal bakiye üzerinden trade simülasyonu.
Her işlem sinyal tracker'a kaydedilir, fiyatlar doğrulanır.
GERÇEK veri, SANAL para.
"""

import asyncio
from datetime import datetime, timezone
from utils.data_fetcher import DataFetcher
from utils.risk_manager import RiskManager, TradeRecord
from utils.position_manager import PositionManager
from utils.price_verifier import PriceVerifier
from utils.signal_tracker import SignalTracker
from utils.logger import setup_logger
from utils.helpers import format_currency, format_pct
from strategies.multi_strategy import MultiStrategyEngine
from strategies.base_strategy import SignalType
from config import (
    TRADING_PAIRS, PRIMARY_TIMEFRAME, OHLCV_LIMIT,
    SCAN_INTERVAL_SECONDS, MAX_CONCURRENT_POSITIONS,
    SIGNAL_COOLDOWN_MINUTES, SIGNAL_SCORE_OVERRIDE_DELTA,
)

logger = setup_logger("PaperTrading")


class PaperTradingEngine:
    """
    Paper Trading Motoru:
    - Gerçek Binance verileriyle piyasa taranır
    - Sinyal üretildiğinde fiyat ANI doğrulanır
    - Sanal bakiye üzerinden pozisyon açılır
    - Pozisyon izlenir (SL/TP/trailing)
    - Çıkışta fiyat tekrar doğrulanır
    - Her detay sinyal tracker'a kaydedilir
    """

    def __init__(self, initial_capital: float = 1000.0):
        self.initial_capital = initial_capital
        self.data_fetcher = DataFetcher()
        self.risk_manager = RiskManager(initial_capital)
        self.position_manager = PositionManager(self.risk_manager)
        self.strategy_engine = MultiStrategyEngine()
        self.price_verifier = PriceVerifier(self.data_fetcher)
        self.signal_tracker = SignalTracker()

        self.is_running = False
        self.scan_count = 0
        self.start_time = None
        self._telegram_callback = None
        self._signal_id_map: dict[str, str] = {}  # symbol → signal_id
        # Sinyal dedup: {symbol: (direction, composite_score, timestamp)}
        # Aynı pair için cooldown süresi içinde tekrar sinyal üretilmesini engeller.
        # Pozisyon açıkken de engeller (position_manager bunu zaten sağlar ama
        # ek güvenlik katmanı olarak burada da tutulur).
        self._signal_dedup: dict[str, tuple] = {}

    def set_telegram_callback(self, callback):
        self._telegram_callback = callback

    async def notify(self, message: str, parse_mode: str = "HTML"):
        """Telegram bildirimi."""
        if self._telegram_callback:
            try:
                await self._telegram_callback(message)
            except Exception as e:
                logger.error(f"Telegram bildirim hatası: {e}")

    async def start(self):
        """Paper trading motorunu başlat."""
        logger.info("=" * 60)
        logger.info("PAPER TRADING MOTORU BAŞLATILIYOR")
        logger.info(f"  Sanal Sermaye: {format_currency(self.initial_capital)}")
        logger.info(f"  Tier-1 ({len(TIER1_PAIRS)} pair): {', '.join(TIER1_PAIRS)}")
        logger.info(f"  Tier-2 ({len(TIER2_PAIRS)} pair): her 3 turda 1 tarama")
        logger.info(f"  Timeframe: {PRIMARY_TIMEFRAME} + {TREND_TIMEFRAME} trend")
        logger.info(f"  WebSocket: {'AKTIF' if USE_WEBSOCKET else 'KAPALI (REST)'}")
        logger.info(f"  Trend Filtresi: {'AKTIF' if TREND_FILTER_ENABLED else 'KAPALI'}")
        logger.info("=" * 60)

        await self.data_fetcher.initialize()

        # WebSocket stream başlat (tüm pairler için )
        if USE_WEBSOCKET:
            try:
                await self.data_fetcher.start_websocket_stream(
                    symbols=TRADING_PAIRS,
                    timeframes=[PRIMARY_TIMEFRAME, TREND_TIMEFRAME]
                )
                ws_status = "WebSocket" if self.data_fetcher._ws_supported else "REST fallback"
            except Exception as e:
                logger.warning(f"WebSocket başlatma hatası: {e} — REST kullanılıyor")
                ws_status = "REST"
        else:
            ws_status = "REST"

        self.is_running = True
        self.start_time = datetime.now(timezone.utc)

        await self.notify(
            "🟢 <b>PAPER TRADING BAŞLATILDI</b>\n"
            f"{'─' * 30}\n"
            f"💰 Sanal Sermaye: {format_currency(self.initial_capital)}\n"
            f"📊 {len(TIER1_PAIRS)} Tier-1 + {len(TIER2_PAIRS)} Tier-2 pair\n"
            f"⚡ Veri: {ws_status}\n"
            f"🔮 Trend Filtresi: {'1h EMA (aktif)' if TREND_FILTER_ENABLED else 'Kapalı'}\n"
            f"⏱ Tarama: her {SCAN_INTERVAL_SECONDS}s\n"
            f"📋 Mode: DEMO (gerçek veri, sanal para)\n"
            f"🕐 Başlangıç: {self.start_time.strftime('%d.%m.%Y %H:%M:%S UTC')}"
        )

        try:
            tasks = [
                self._scan_loop(),
                self._position_monitor_loop(),
                self._periodic_report_loop(),
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
        
        await self.notify(
            "🔴 <b>PAPER TRADING DURDURULDU</b>\n"
            f"{'─' * 30}\n"
            f"💰 Sermaye: {format_currency(self.risk_manager.current_capital)}\n"
            f"📈 ROI: {format_pct(((self.risk_manager.current_capital - self.initial_capital) / self.initial_capital) * 100)}\n"
            f"📊 Toplam Sinyal: {stats['total_signals']}\n"
            f"✅ Win: {stats['wins']} | ❌ Loss: {stats['losses']}\n"
            f"🎯 Win Rate: {stats['win_rate']:.1f}%\n"
            f"💵 Net P&L: {format_currency(stats['total_pnl'])}"
        )

        await self.data_fetcher.close()

    # ==================== TARAMA ====================

    async def _scan_loop(self):
        """Piyasa tarama döngüsü — Tier-1 her tur, Tier-2 her 3 turda bir."""
        logger.info("Tarama döngüsü başladı")
        while self.is_running:
            try:
                self.scan_count += 1
                # Tier-1: her tur
                tier1_pairs = [p for p in TIER1_PAIRS if p not in self.position_manager.open_positions]
                # Tier-2: her 3 turda bir
                if self.scan_count % 3 == 0:
                    tier2_pairs = [p for p in TIER2_PAIRS if p not in self.position_manager.open_positions]
                else:
                    tier2_pairs = []

                scan_pairs = tier1_pairs + tier2_pairs
                logger.info(f"Tarama #{self.scan_count} başlıyor... ({len(scan_pairs)} pair: {len(tier1_pairs)} T1 + {len(tier2_pairs)} T2)")
                await self._scan_markets(scan_pairs)
                logger.info(f"Tarama #{self.scan_count} tamamlandı")
                await asyncio.sleep(SCAN_INTERVAL_SECONDS)
            except Exception as e:
                logger.error(f"Tarama hatası: {e}", exc_info=True)
                await asyncio.sleep(SCAN_INTERVAL_SECONDS * 2)

    async def _scan_markets(self, pairs_to_scan: list = None):
        """Belirtilen pairleri tara, sinyal üret, fiyat doğrula, paper trade aç."""
        if pairs_to_scan is None:
            pairs_to_scan = [p for p in TRADING_PAIRS
                             if p not in self.position_manager.open_positions]

        can_trade, reason = self.risk_manager.can_trade()
        if not can_trade:
            if self.scan_count % 60 == 0:
                logger.warning(f"Trading durdu: {reason}")
            return

        for pair in pairs_to_scan:
            try:
                # 1) OHLCV verisini çek (WebSocket cache öncelikli)
                df = await self.data_fetcher.get_ohlcv(pair, PRIMARY_TIMEFRAME, OHLCV_LIMIT)
                if df.empty or len(df) < 60:
                    continue

                # 2) 1h trend bağlamı çek
                trend_ctx = await self.data_fetcher.fetch_trend_context(pair)

                # 3) Strateji analizi (trend filtresiyle)
                analysis = self.strategy_engine.analyze(df, pair, trend_context=trend_ctx)

                # Trend filtresiyle engellendi mi?
                if analysis.get("trend_filtered"):
                    self.trend_filtered_count += 1
                    continue

                if analysis["signal"] == SignalType.NEUTRAL:
                    continue

                direction = "BUY" if analysis["signal"] == SignalType.BUY else "SELL"
                composite_score = analysis.get("composite_score", 0.5)

                # ── Sinyal Dedup Kontrolü ─────────────────────────────────────
                # Aynı pair için SIGNAL_COOLDOWN_MINUTES içinde tekrar sinyal
                # üretilmesini engelle. Ancak skor belirgin ölçüde iyileşmişse
                # (SIGNAL_SCORE_OVERRIDE_DELTA) yeniden sinyal üretilir.
                # Açık pozisyon varsa zaten position_manager bloklayacak.
                dedup_entry = self._signal_dedup.get(pair)
                if dedup_entry:
                    prev_dir, prev_score, prev_ts = dedup_entry
                    elapsed_min = (datetime.now(timezone.utc) - prev_ts).total_seconds() / 60
                    score_improvement = composite_score - prev_score
                    still_in_cd = elapsed_min < SIGNAL_COOLDOWN_MINUTES
                    score_override = score_improvement >= SIGNAL_SCORE_OVERRIDE_DELTA
                    if still_in_cd and not score_override:
                        logger.debug(
                            f"[{pair}] Dedup: {direction} sinyal engellendi "
                            f"({elapsed_min:.0f}/{SIGNAL_COOLDOWN_MINUTES}dk, "
                            f"skor δ={score_improvement:+.3f})"
                        )
                        continue  # cooled down
                # ─────────────────────────────────────────────────────────────

                # Dedup kaydını güncelle (sinyal geçti, cooldown saat sıfırla)
                self._signal_dedup[pair] = (
                    direction, composite_score, datetime.now(timezone.utc)
                )

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
                        f"Veri kalitesi FAIL: {verification['verified_price'].error}"
                    )
                    await self.notify(
                        f"⚠️ <b>SİNYAL REDDEDİLDİ</b> — Veri Hatası\n"
                        f"{'─' * 30}\n"
                        f"📊 {pair} | {direction}\n"
                        f"❌ Sebep: {verification['verified_price'].error}\n"
                        f"🕐 {signal.signal_time_readable}"
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

                position = self.position_manager.open_position(pair, "buy", real_price, atr)
                if not position:
                    self.signal_tracker.reject_signal(
                        signal.signal_id,
                        "Risk yönetimi tarafından reddedildi"
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

                # 9) Detaylı Telegram bildirimi
                vp = verification["verified_price"]
                await self.notify(
                    f"🟢 <b>PAPER TRADE AÇILDI</b>\n"
                    f"{'─' * 30}\n"
                    f"📊 <b>{pair}</b> | {direction}\n"
                    f"🕐 {signal.signal_time_readable}\n\n"
                    f"💰 <b>Fiyat Bilgisi</b>\n"
                    f"  Sinyal Fiyatı: {format_currency(analysis['price'])}\n"
                    f"  Doğrulanan Fiyat: {format_currency(real_price)}\n"
                    f"  Bid: {format_currency(vp.bid)} | Ask: {format_currency(vp.ask)}\n"
                    f"  Spread: %{vp.spread:.3f}\n"
                    f"  Sapma: %{verification['deviation_pct']:.3f}\n"
                    f"  Veri Kalitesi: {verification['data_quality']}\n"
                    f"  Gecikme: {vp.latency_ms:.0f}ms\n\n"
                    f"📈 <b>Strateji Detayı</b>\n"
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
                    f"📊 Açık Pozisyon: {len(self.position_manager.open_positions)}/{MAX_CONCURRENT_POSITIONS}\n"
                    f"🔢 Sinyal ID: <code>{signal.signal_id}</code>"
                )

            except Exception as e:
                logger.error(f"Sinyal işleme hatası ({pair}): {e}")

    # ==================== POZİSYON İZLEME ====================

    async def _position_monitor_loop(self):
        """Açık pozisyonları sürekli izle — çıkışta fiyat doğrula."""
        while self.is_running:
            try:
                for symbol in list(self.position_manager.open_positions.keys()):
                    # Gerçek fiyat çek
                    verified = await self.price_verifier.verify_price(symbol)
                    if not verified.verified or verified.price <= 0:
                        continue

                    current_price = verified.price

                    # Pozisyon çıkış kontrolü
                    result = self.position_manager.check_exits(symbol, current_price)
                    if result and "error" not in result:
                        # Çıkış fiyatını da doğrula
                        exit_verification = await self.price_verifier.verify_price(symbol)

                        # Signal tracker güncelle
                        signal = self.signal_tracker.close_signal(
                            symbol=symbol,
                            exit_price=current_price,
                            exit_reason=result["reason"],
                            pnl=result["pnl"],
                            pnl_pct=result["pnl_pct"],
                            fee=result["fee"],
                            exit_verified_price=exit_verification.price if exit_verification.verified else 0,
                            exit_data_quality="GOOD" if exit_verification.verified else "FAIL",
                        )

                        # Signal ID temizle
                        self._signal_id_map.pop(symbol, None)

                        # Telegram bildirimi
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

                        await self.notify(
                            f"{emoji} <b>PAPER TRADE KAPANDI — {result_text}</b>\n"
                            f"{'─' * 30}\n"
                            f"📊 <b>{symbol}</b>\n"
                            f"🕐 Kapanış: {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M:%S UTC')}\n\n"
                            f"💰 <b>İşlem Sonucu</b>\n"
                            f"  Giriş: {format_currency(result['entry_price'])}\n"
                            f"  Çıkış: {format_currency(result['exit_price'])}\n"
                            f"  Doğrulanan Çıkış: {format_currency(exit_verification.price)}\n"
                            f"  P&L: {format_currency(result['pnl'])} ({format_pct(result['pnl_pct'])})\n"
                            f"  Fee: {format_currency(result['fee'])}\n"
                            f"  Net P&L: {format_currency(result['pnl'] - result['fee'])}\n\n"
                            f"📋 <b>Detaylar</b>\n"
                            f"  Sebep: {result['reason']}\n"
                            f"  Süre: {duration_text}\n"
                            f"  Veri Kalitesi: {exit_verification.verified}\n\n"
                            f"💼 <b>Portföy Durumu</b>\n"
                            f"  Sermaye: {format_currency(self.risk_manager.current_capital)}\n"
                            f"  ROI: {format_pct(((self.risk_manager.current_capital - self.initial_capital) / self.initial_capital) * 100)}\n"
                            f"  Açık Poz: {len(self.position_manager.open_positions)}"
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
                uptime = datetime.now(timezone.utc) - self.start_time
                uptime_str = str(uptime).split('.')[0]

                open_pos_text = ""
                for sym, pos in self.position_manager.open_positions.items():
                    vp = await self.price_verifier.verify_price(sym)
                    if vp.verified:
                        unrealized_pnl = (vp.price - pos.entry_price) * pos.quantity
                        unrealized_pct = ((vp.price - pos.entry_price) / pos.entry_price) * 100
                        emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
                        open_pos_text += (
                            f"  {emoji} {sym}: {format_currency(vp.price)} "
                            f"({format_pct(unrealized_pct)})\n"
                        )

                if not open_pos_text:
                    open_pos_text = "  Açık pozisyon yok\n"

                await self.notify(
                    f"📊 <b>15dk DURUM RAPORU</b>\n"
                    f"{'─' * 30}\n"
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
                    f"  🚫 Trend Filtresi: {self.trend_filtered_count}\n"
                    f"  ✅ Win: {stats['wins']} | ❌ Loss: {stats['losses']}\n"
                    f"  🎯 Win Rate: {stats['win_rate']:.1f}%\n"
                    f"  💵 Net P&L: {format_currency(stats['total_pnl'])}\n"
                    f"  📊 Profit Factor: {stats['profit_factor']:.2f}\n"
                    f"  🔥 Avg Win: {format_pct(stats['avg_win_pct'])}\n"
                    f"  💧 Avg Loss: {format_pct(stats['avg_loss_pct'])}\n"
                    f"  🏆 Max Seri Win: {stats['max_consecutive_wins']}\n"
                    f"  💀 Max Seri Loss: {stats['max_consecutive_losses']}\n\n"
                    f"📊 <b>Veri Kalitesi</b>\n"
                    f"  ✅ GOOD: {stats['data_quality']['good']}\n"
                    f"  ⚠️ WARNING: {stats['data_quality']['warning']}\n"
                    f"  ❌ FAIL: {stats['data_quality']['fail']}\n"
                    f"  Kalite: %{stats['data_quality']['good_pct']:.1f}\n\n"
                    f"📍 <b>Açık Pozisyonlar</b>\n"
                    f"{open_pos_text}\n"
                    f"📆 <b>Bugün</b>\n"
                    f"  Sinyal: {stats['today']['signals']}\n"
                    f"  Kapalı: {stats['today']['closed']}\n"
                    f"  P&L: {format_currency(stats['today']['pnl'])}"
                )
            except Exception as e:
                logger.error(f"Periyodik rapor hatası: {e}")

    # ==================== DURUM ====================

    def get_status(self) -> dict:
        """Bot durumunu döndür."""
        stats = self.signal_tracker.get_statistics()
        risk_stats = self.risk_manager.get_stats()
        open_pos = self.position_manager.get_open_positions()
        
        return {
            "is_running": self.is_running,
            "mode": "PAPER",
            "uptime": str(datetime.now(timezone.utc) - self.start_time).split('.')[0] if self.start_time else "N/A",
            "scan_count": self.scan_count,
            "signal_stats": stats,
            "risk_stats": risk_stats,
            "open_positions": open_pos,
        }

    def resume_trading(self):
        """Trading'i devam ettir (risk halt sonrası)."""
        self.risk_manager.is_trading_halted = False
        logger.info("Trading devam ettiriliyor")
