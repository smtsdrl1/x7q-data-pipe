"""
One-Shot Scanner — GitHub Actions için tek seferlik tarama.
Her çalışmada tüm TRADING_PAIRS'i tarar, kaliteli sinyalleri
Telegram'a gönderir ve çıkar. Paper trading loop'u gerektirmez.

Çalıştırma: python scan_once.py
Ortam değişkenleri: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from utils.data_fetcher import DataFetcher
from utils.logger import setup_logger
from strategies.multi_strategy import MultiStrategyEngine
from strategies.base_strategy import SignalType
from config import (
    TRADING_PAIRS, PRIMARY_TIMEFRAME, OHLCV_LIMIT, TREND_TIMEFRAME,
    SIGNAL_BUY_THRESHOLD, SIGNAL_SELL_THRESHOLD, MIN_STRATEGIES_AGREE,
)

logger = setup_logger("ScanOnce")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


async def send_telegram(text: str):
    """Telegram mesaj gönder (python-telegram-bot olmadan, aiohttp ile)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram token/chat_id eksik — bildirim gönderilmedi")
        return
    try:
        import aiohttp
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.error(f"Telegram HTTP {resp.status}: {await resp.text()}")
    except Exception as e:
        logger.error(f"Telegram hata: {e}")


def build_signal_message(pair: str, direction: str, analysis: dict) -> str:
    price      = analysis.get("price", 0)
    score      = analysis.get("composite_score", 0)
    buy_count  = analysis.get("buy_count", 0)
    sell_count = analysis.get("sell_count", 0)
    rsi        = analysis.get("rsi", 0)
    regime     = analysis.get("regime", "UNKNOWN")
    trend_1h   = analysis.get("trend_1h", "NEUTRAL")
    session    = analysis.get("session_info", {}).get("session", "")

    dir_emoji = "🟢" if direction == "BUY" else "🔴"
    dir_label = "ALIM" if direction == "BUY" else "SATIM"

    reasons = analysis.get("buy_reasons" if direction == "BUY" else "sell_reasons", [])
    reasons_str = "\n".join(f"  • {r}" for r in reasons[:3]) if reasons else "  • —"

    return (
        f"{dir_emoji} <b>{dir_label} SİNYALİ</b> — {pair}\n"
        f"{'─' * 32}\n"
        f"💰 Fiyat  : <code>{price:.6g}</code>\n"
        f"📊 Skor   : <b>{score:.2f}</b>  ({buy_count}B / {sell_count}S)\n"
        f"📈 RSI    : {rsi:.1f}\n"
        f"🌊 Rejim  : {regime}\n"
        f"🕐 1h Trend: {trend_1h} | Session: {session}\n"
        f"🔍 Sebepler:\n{reasons_str}\n"
        f"⏱ {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M UTC')}"
    )


async def main():
    logger.info("=" * 55)
    logger.info(f"ONE-SHOT SCANNER başlıyor ({len(TRADING_PAIRS)} pair)")
    logger.info("=" * 55)

    fetcher  = DataFetcher()
    engine   = MultiStrategyEngine()
    signals_sent = 0

    await fetcher.initialize()

    for pair in TRADING_PAIRS:
        try:
            # 5m veri
            df = await fetcher.fetch_ohlcv(pair, PRIMARY_TIMEFRAME, limit=OHLCV_LIMIT)
            if df.empty or len(df) < 60:
                logger.warning(f"[{pair}] Yetersiz 5m veri — atlandı")
                continue

            # 1h trend context
            trend_ctx = await fetcher.fetch_trend_context(pair)

            # Strateji analizi
            analysis = engine.analyze(df, pair, trend_context=trend_ctx)

            sig   = analysis["signal"]
            score = analysis["composite_score"]
            buy_c = analysis.get("buy_count", 0)
            sell_c = analysis.get("sell_count", 0)

            if sig == SignalType.NEUTRAL:
                logger.debug(f"[{pair}] NEUTRAL — atlandı")
                continue

            direction = "BUY" if sig == SignalType.BUY else "SELL"

            # Eşik kontrolü (zaten MultiStrategy içinde yapılıyor ama çift kontrol)
            if sig == SignalType.BUY and (score < SIGNAL_BUY_THRESHOLD or buy_c < MIN_STRATEGIES_AGREE):
                logger.info(f"[{pair}] BUY skor/onay yetersiz ({score:.2f}, {buy_c} strateji)")
                continue
            if sig == SignalType.SELL and (score > SIGNAL_SELL_THRESHOLD or sell_c < MIN_STRATEGIES_AGREE):
                logger.info(f"[{pair}] SELL skor/onay yetersiz ({score:.2f}, {sell_c} strateji)")
                continue

            logger.info(
                f"[{pair}] ✅ {direction} sinyal! Skor:{score:.2f} "
                f"Onay:{buy_c}B/{sell_c}S Trend:{analysis.get('trend_1h','?')}"
            )

            msg = build_signal_message(pair, direction, analysis)
            await send_telegram(msg)
            signals_sent += 1

        except Exception as e:
            logger.error(f"[{pair}] Hata: {e}", exc_info=True)

    await fetcher.close()

    # Özet mesaj
    now = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    summary = (
        f"📡 <b>Tarama Tamamlandı</b>\n"
        f"  Taranan  : {len(TRADING_PAIRS)} pair\n"
        f"  Sinyal   : {signals_sent} adet\n"
        f"  ⏱ {now}"
    )
    logger.info(f"Tarama bitti — {signals_sent} sinyal gönderildi")

    if signals_sent == 0:
        # Hiç sinyal yoksa kısa özet gönder (spam olmadan; her 6h'de 1 kez)
        hour = datetime.now(timezone.utc).hour
        if hour % 6 == 0:
            await send_telegram(summary)
    else:
        await send_telegram(summary)


if __name__ == "__main__":
    asyncio.run(main())
