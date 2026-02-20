"""
Multi-Strateji Motor
Tüm stratejilerin sinyallerini birleştirerek composite sinyal üretir.
Multi-timeframe trend filtresi ile yanlış sinyaller azaltılır.
"""

import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal, SignalType
from strategies.rsi_strategy import RSIStrategy
from strategies.macd_strategy import MACDStrategy
from strategies.bollinger_strategy import BollingerStrategy
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.volume_spike import VolumeSpikeStrategy
from strategies.supertrend import SuperTrendStrategy
from strategies.fvg_fibonacci import FVGFibonacciStrategy
from strategies.order_blocks import OrderBlockStrategy
from strategies.liquidity_sweep import LiquiditySweepStrategy
from utils.indicators import TechnicalIndicators
from utils.logger import setup_logger
from utils.cvd import calculate_cvd, get_cvd_score_boost
from utils.market_structure import analyze_market_structure
from utils.market_regime import market_regime_detector
from utils.session_killzone import is_tradeable_session, session_score_multiplier
from utils.economic_calendar import check_news_kill_zone
from utils.derivatives import get_derivatives_score_boost
from config import (
    SIGNAL_BUY_THRESHOLD, SIGNAL_SELL_THRESHOLD, MIN_STRATEGIES_AGREE,
    TREND_FILTER_ENABLED, FVG_FIBONACCI_WEIGHT,
    SESSION_FILTER_ENABLED, SESSION_MIN_QUALITY, REGIME_DETECTION_ENABLED,
    DERIVATIVES_ENABLED,
)

logger = setup_logger("MultiStrategy")


class MultiStrategyEngine:
    """Birden fazla stratejiyi birleştiren motor."""

    def __init__(self):
        self.strategies: list[BaseStrategy] = [
            RSIStrategy(),
            MACDStrategy(),
            BollingerStrategy(),
            EMACrossoverStrategy(),
            VolumeSpikeStrategy(),
            SuperTrendStrategy(),
            FVGFibonacciStrategy(),      # FVG + Fibonacci Confluence — Alper INCE metodu
            OrderBlockStrategy(),         # ICT Order Block Detection
            LiquiditySweepStrategy(),     # ICT Liquidity Sweep / Stop Hunt
        ]
        self.indicators = TechnicalIndicators()

    def analyze(self, df: pd.DataFrame, symbol: str,
                trend_context: dict = None,
                backtest_dt=None,
                derivatives_context: dict = None) -> dict:
        """
        Tüm stratejileri çalıştır ve composite sinyal üret.
        trend_context: {"trend": "BULLISH"|"BEARISH"|"NEUTRAL", ...} – 1h trend bilgisi
        derivatives_context: {"oi": {...}, "fr": {...}} – önceden çekilmiş OI/FR verisi
        """
        if df.empty or len(df) < 60:
            return {
                "signal": SignalType.NEUTRAL,
                "composite_score": 0.5,
                "signals": [],
                "reason": "Yetersiz veri",
                "trend": "UNKNOWN",
            }

        # Göstergeleri hesapla
        df = self.indicators.calculate_all(df)

        # Her stratejiyi çalıştır
        signals: list[Signal] = []
        for strategy in self.strategies:
            try:
                signal = strategy.analyze(df, symbol)
                signals.append(signal)
            except Exception as e:
                logger.error(f"Strateji hatası ({strategy.name}): {e}")

        # Composite skor hesapla
        composite = self._calculate_composite(signals)

        # Sinyal yönü belirle (filtreler için önce belirlenmeli)
        buy_count = sum(1 for s in signals if s.signal_type == SignalType.BUY)
        sell_count = sum(1 for s in signals if s.signal_type == SignalType.SELL)

        if composite >= SIGNAL_BUY_THRESHOLD and buy_count >= MIN_STRATEGIES_AGREE:
            final_signal = SignalType.BUY
        elif composite <= SIGNAL_SELL_THRESHOLD and sell_count >= MIN_STRATEGIES_AGREE:
            final_signal = SignalType.SELL
        else:
            final_signal = SignalType.NEUTRAL

        # ── SESSION KİLLZONE FİLTRESİ ─────────────────────────────
        session_tradeable, session_info = is_tradeable_session(
            min_quality=SESSION_MIN_QUALITY,
            dt=backtest_dt,  # None → datetime.now(); geçilirse tarihsel mum saati
        )
        session_multiplier = session_score_multiplier(session_info)
        session_filtered = False

        if SESSION_FILTER_ENABLED and not session_tradeable and final_signal != SignalType.NEUTRAL:
            logger.debug(
                f"🕐 {symbol} Session filtresi: {session_info['session']} "
                f"(kalite {session_info['quality']}) → engellendi"
            )
            final_signal = SignalType.NEUTRAL
            session_filtered = True
        # ──────────────────────────────────────────────────────────

        # ── MARKET REGIME ANALİZİ ──────────────────────────────────
        regime_info = {}
        if REGIME_DETECTION_ENABLED:
            regime_info = market_regime_detector.detect(df, symbol)
            regime = regime_info.get("regime", "TRANSITION")

            # QUIET rejimde sinyal üretme
            if regime == "QUIET" and final_signal != SignalType.NEUTRAL:
                logger.debug(f"📉 {symbol} Quiet market → sinyal engellendi")
                final_signal = SignalType.NEUTRAL
        # ──────────────────────────────────────────────────────────

        # ── CVD ANALİZİ ──────────────────────────────────────────────────────
        cvd_data = calculate_cvd(df)
        cvd_boost = 0
        if final_signal == SignalType.BUY:
            cvd_boost = get_cvd_score_boost(cvd_data, "buy")
        elif final_signal == SignalType.SELL:
            cvd_boost = get_cvd_score_boost(cvd_data, "sell")
        # ────────────────────────────────────────────────────────────────────

        # ── DERIVATIVES (OI + FUNDING RATE) SKOR BOOST ──────────────────────
        deriv_boost = 0.0
        deriv_data = {}
        if DERIVATIVES_ENABLED and derivatives_context and final_signal != SignalType.NEUTRAL:
            oi_data = derivatives_context.get("oi", {})
            fr_data = derivatives_context.get("fr", {})
            if oi_data or fr_data:
                side = "buy" if final_signal == SignalType.BUY else "sell"
                deriv_boost = get_derivatives_score_boost(oi_data, fr_data, side)
                deriv_data = {"oi": oi_data, "fr": fr_data, "boost": deriv_boost}
                if deriv_boost != 0:
                    logger.debug(
                        f"📈 {symbol} Derivatives boost: {deriv_boost:+.3f} "
                        f"(OI={oi_data.get('oi_value', 0):.0f}, "
                        f"FR={fr_data.get('funding_rate', 0):.4f})"
                    )
        # ────────────────────────────────────────────────────────────────────

        # ── EKONOMİK TAKVİM (NEWS KILL ZONE) ────────────────────────────────
        news_kill_data = check_news_kill_zone(minutes_before=30, minutes_after=30)
        news_filtered = False
        if news_kill_data.get("in_kill_zone") and final_signal != SignalType.NEUTRAL:
            event_name = news_kill_data.get("nearest_event", {}).get("name", "Yüksek etkili haber")
            logger.info(
                f"📰 {symbol} Haber Kill Zone: {event_name} → sinyal engellendi"
            )
            final_signal = SignalType.NEUTRAL
            news_filtered = True
        # ──────────────────────────────────────────────────────────

        # ── MARKET STRUCTURE ANALİZİ ──────────────────────────────
        ms_data = analyze_market_structure(df)
        ms_boost = ms_data.get("score_boost", 0)
        # ──────────────────────────────────────────────────────────

        # ── 1H TREND FİLTRESİ ──────────────────────────────────────
        trend = "NEUTRAL"
        trend_filtered = False
        if trend_context:
            trend = trend_context.get("trend", "NEUTRAL")

        if TREND_FILTER_ENABLED and trend_context and final_signal != SignalType.NEUTRAL:
            if trend == "BEARISH" and final_signal == SignalType.BUY:
                # Ayı trendi içinde BUY sinyali → filtrele
                logger.debug(f"🚫 {symbol} BUY sinyali 1h BEARISH trend nedeniyle engellendi")
                final_signal = SignalType.NEUTRAL
                trend_filtered = True
            elif trend == "BULLISH" and final_signal == SignalType.SELL:
                # Boğa trendi içinde SELL sinyali → filtrele
                logger.debug(f"🚫 {symbol} SELL sinyali 1h BULLISH trend nedeniyle engellendi")
                final_signal = SignalType.NEUTRAL
                trend_filtered = True
        # ──────────────────────────────────────────────────────────

        # Açıklama oluştur
        buy_reasons = [s.reason for s in signals if s.signal_type == SignalType.BUY]
        sell_reasons = [s.reason for s in signals if s.signal_type == SignalType.SELL]

        result = {
            "signal": final_signal,
            "composite_score": composite,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "signals": signals,
            "buy_reasons": buy_reasons,
            "sell_reasons": sell_reasons,
            "price": df["close"].iloc[-1],
            "atr": df["atr"].iloc[-1] if "atr" in df.columns else 0,
            "rsi": df["rsi"].iloc[-1] if "rsi" in df.columns else 50,
            "volume_ratio": df["volume_ratio"].iloc[-1] if "volume_ratio" in df.columns else 1,
            "trend_1h": trend,
            "trend_filtered": trend_filtered,
            "session_filtered": session_filtered,
            "session_info": session_info,
            "session_multiplier": session_multiplier,
            "regime": regime_info.get("regime", "UNKNOWN"),
            "regime_info": regime_info,
            "cvd_data": cvd_data,
            "cvd_boost": cvd_boost,
            "ms_data": ms_data,
            "ms_boost": ms_boost,
            "deriv_data": deriv_data,
            "deriv_boost": deriv_boost,
            "news_kill_data": news_kill_data,
            "news_filtered": news_filtered,
        }

        if final_signal != SignalType.NEUTRAL:
            direction = "ALIM" if final_signal == SignalType.BUY else "SATIM"
            trend_tag = f" [1h:{trend}]" if trend != "NEUTRAL" else ""
            regime_tag = f" [{regime_info.get('regime', '')}]" if regime_info else ""
            logger.info(
                f"📊 {symbol} | {direction} sinyali | "
                f"Skor: {composite:.2f} | Onay: {buy_count}B/{sell_count}S | "
                f"Fiyat: {result['price']:.6f}{trend_tag}{regime_tag}"
            )
        elif trend_filtered:
            direction_orig = "BUY" if buy_count >= MIN_STRATEGIES_AGREE else "SELL"
            logger.info(
                f"🚫 {symbol} | {direction_orig} FİLTRELENDİ | 1h:{trend} | "
                f"Skor: {composite:.2f}"
            )
        elif session_filtered:
            logger.debug(f"🕐 {symbol} | SESSION FİLTRELENDİ | {session_info['session']}")

        return result

    def _calculate_composite(self, signals: list[Signal]) -> float:
        """Ağırlıklı composite skor hesapla (0-1)."""
        if not signals:
            return 0.5

        total_weight = 0.0
        weighted_score = 0.0

        for signal in signals:
            weight = 1.0
            # İlgili stratejiden ağırlığı al
            for strategy in self.strategies:
                if strategy.name == signal.strategy_name:
                    weight = strategy.weight
                    break

            total_weight += weight

            if signal.signal_type == SignalType.BUY:
                score = 0.5 + (signal.strength * 0.5)  # 0.5 - 1.0
            elif signal.signal_type == SignalType.SELL:
                score = 0.5 - (signal.strength * 0.5)  # 0.0 - 0.5
            else:
                score = 0.5

            weighted_score += score * weight

        if total_weight == 0:
            return 0.5

        return weighted_score / total_weight

    def get_strategy_names(self) -> list[str]:
        """Strateji isimlerini döndür."""
        return [s.name for s in self.strategies]
