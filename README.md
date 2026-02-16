# 🚀 Crypto Trading Bot - Algorithmic Trading System

## Performance Hedefleri
| Metrik | Değer |
|--------|-------|
| Başlangıç Sermayesi | $1,000 |
| Hedef ROI | +%15,795 |
| Aylık Compound | ~%28 |
| Günlük Ortalama Trade | ~29 trade/gün |
| Win Rate | %50-60 |
| Avg Win | +%4-8 |
| Avg Loss | -%1.2 |

## Özellikler

- **Multi-Strateji Motor**: RSI, MACD, Bollinger Bands, EMA Crossover, Volume Spike, SuperTrend
- **Risk Yönetimi**: Dinamik pozisyon boyutlama, trailing stop-loss, max drawdown koruması
- **Backtest Engine**: 30+ günlük geçmiş veri ile kapsamlı backtest
- **Canlı Trading**: Binance API üzerinden otomatik trade execution
- **Telegram Bildirimleri**: Gerçek zamanlı sinyal ve P&L raporları
- **Dashboard**: Terminal tabanlı canlı performans takibi
- **Compound Growth**: Kârları otomatik reinvest eden bileşik büyüme sistemi

## Kurulum

```bash
# 1. Repository klonla
git clone https://github.com/YOUR_USERNAME/crypto-trading-bot.git
cd crypto-trading-bot

# 2. Virtual environment oluştur
python3 -m venv venv
source venv/bin/activate

# 3. Bağımlılıkları yükle
pip install -r requirements.txt

# 4. Environment değişkenlerini ayarla
cp .env.example .env
# .env dosyasını düzenle ve API anahtarlarını ekle

# 5. Backtest çalıştır
python backtest.py

# 6. Canlı trading başlat
python main.py

# 7. Sadece Telegram bot
python telegram_bot.py
```

## Proje Yapısı

```
crypto-trading-bot/
├── main.py                  # Ana trading motoru
├── backtest.py              # Backtest engine
├── telegram_bot.py          # Telegram bot entegrasyonu
├── dashboard.py             # Terminal dashboard
├── config.py                # Konfigürasyon
├── strategies/
│   ├── __init__.py
│   ├── base_strategy.py     # Temel strateji sınıfı
│   ├── rsi_strategy.py      # RSI tabanlı strateji
│   ├── macd_strategy.py     # MACD crossover stratejisi
│   ├── bollinger_strategy.py # Bollinger Bands stratejisi
│   ├── ema_crossover.py     # EMA crossover stratejisi
│   ├── volume_spike.py      # Hacim spike stratejisi
│   ├── supertrend.py        # SuperTrend stratejisi
│   └── multi_strategy.py    # Çoklu strateji birleştirici
├── utils/
│   ├── __init__.py
│   ├── risk_manager.py      # Risk yönetimi
│   ├── position_manager.py  # Pozisyon yönetimi
│   ├── data_fetcher.py      # Veri çekme modülü
│   ├── indicators.py        # Teknik göstergeler
│   ├── logger.py            # Loglama sistemi
│   └── helpers.py           # Yardımcı fonksiyonlar
├── tests/
│   └── test_strategies.py   # Strateji testleri
├── data/                    # Geçmiş veri depolama
├── logs/                    # Log dosyaları
├── .env.example             # Örnek environment dosyası
├── .gitignore               # Git ignore
├── requirements.txt         # Python bağımlılıkları
└── README.md                # Bu dosya
```

## Stratejiler

### 1. RSI Reversal
- RSI < 30 → Alım sinyali (oversold)
- RSI > 70 → Satım sinyali (overbought)
- Multi-timeframe onaylama

### 2. MACD Crossover
- MACD çizgisi sinyal çizgisini yukarı keserse → Alım
- MACD çizgisi sinyal çizgisini aşağı keserse → Satım
- Histogram divergence tespiti

### 3. Bollinger Bands Squeeze
- Fiyat alt banda dokunursa → Alım
- Fiyat üst banda dokunursa → Satım
- Squeeze breakout tespiti

### 4. EMA Crossover
- EMA(9) > EMA(21) > EMA(55) → Güçlü alım
- EMA(9) < EMA(21) < EMA(55) → Güçlü satım

### 5. Volume Spike
- Hacim 2x+ ortalamanın üstünde + fiyat artışı → Alım
- Hacim 2x+ ortalamanın üstünde + fiyat düşüşü → Satım

### 6. SuperTrend
- ATR tabanlı trend takibi
- Trend değişimi sinyalleri

## Risk Yönetimi

| Parametre | Değer |
|-----------|-------|
| Maks Pozisyon | Sermayenin %5'i |
| Stop-Loss | %1.2 (ATR bazlı dinamik) |
| Take-Profit | %4-8 (R:R bazlı) |
| Trailing Stop | %2 |
| Günlük Maks Kayıp | %3 |
| Maks Drawdown | %15 |
| Eşzamanlı Pozisyon | Maks 5 |

## Telegram Komutları

| Komut | Açıklama |
|-------|----------|
| `/start` | Bot'u başlat |
| `/durum` | Anlık portföy durumu |
| `/bakiye` | Bakiye ve P&L bilgisi |
| `/trades` | Son trade'ler |
| `/sinyal` | Aktif sinyaller |
| `/backtest` | Son backtest sonuçları |
| `/risk` | Risk metrikleri |
| `/durdur` | Trading'i durdur |
| `/baslat` | Trading'i başlat |

## ⚠️ Uyarı

Bu yazılım eğitim amaçlıdır. Kripto para ticareti yüksek risk içerir. Kaybetmeyi göze alamayacağınız parayla yatırım yapmayın. Geçmiş performans gelecek performansın garantisi değildir.

## Lisans

MIT License
