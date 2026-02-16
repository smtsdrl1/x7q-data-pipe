"""Hızlı test script — fiyat doğrulama + Telegram."""
import asyncio
from utils.data_fetcher import DataFetcher
from utils.price_verifier import PriceVerifier
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


async def test_price():
    """Fiyat doğrulama testi."""
    df = DataFetcher()
    pv = PriceVerifier(df)

    print("=== FIYAT DOĞRULAMA TESTİ ===")
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    for sym in symbols:
        result = await pv.verify_and_compare(sym, 0)
        vp = result["verified_price"]
        print(f"\n{sym}:")
        print(f"  Fiyat: ${vp.price:,.2f}")
        print(f"  Bid: ${vp.bid:,.2f} | Ask: ${vp.ask:,.2f}")
        print(f"  Spread: %{vp.spread:.4f}")
        print(f"  Doğrulandı: {vp.verified}")
        print(f"  Gecikme: {vp.latency_ms:.0f}ms")
        print(f"  Kalite: {result['data_quality']}")

    await df.close()


async def test_telegram():
    """Telegram bağlantı testi."""
    from telegram import Bot
    print("\n=== TELEGRAM TESTİ ===")
    print(f"Token: {TELEGRAM_BOT_TOKEN[:10]}...")
    print(f"Chat ID: {TELEGRAM_CHAT_ID}")

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    me = await bot.get_me()
    print(f"Bot: @{me.username} ({me.first_name})")

    await bot.send_message(
        chat_id=int(TELEGRAM_CHAT_ID),
        text=(
            "🧪 <b>TEST BİLDİRİMİ</b>\n"
            "─" * 30 + "\n"
            "✅ Paper Trading Bot bağlantısı başarılı!\n"
            "📊 Fiyat doğrulama sistemi çalışıyor.\n"
            "📋 Sinyal takip sistemi hazır.\n\n"
            "Bot /start komutu ile kullanılabilir."
        ),
        parse_mode="HTML",
    )
    print("✅ Telegram mesajı gönderildi!")
    await bot.shutdown()


async def main():
    await test_price()
    await test_telegram()
    print("\n✅ Tüm testler başarılı!")


if __name__ == "__main__":
    asyncio.run(main())
