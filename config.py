"""
Crypto Trading Bot - Konfigürasyon Dosyası
Tüm ayarlar burada merkezi olarak yönetilir.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ============================================
# EXCHANGE AYARLARI
# ============================================
EXCHANGE_ID = "binance"
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET = os.getenv("BINANCE_SECRET", "")
BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "true").lower() == "true"

# ============================================
# TELEGRAM AYARLARI
# ============================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ============================================
# TRADING PARAMETRELERİ
# ============================================
INITIAL_CAPITAL = 1000.0  # Başlangıç sermayesi ($)
TRADING_PAIRS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT",
    "XRP/USDT", "ADA/USDT", "AVAX/USDT", "DOGE/USDT",
    "DOT/USDT", "MATIC/USDT", "LINK/USDT", "UNI/USDT",
    "ATOM/USDT", "LTC/USDT", "FIL/USDT", "APT/USDT",
    "ARB/USDT", "OP/USDT", "NEAR/USDT", "INJ/USDT",
]

# Timeframe'ler (multi-timeframe analiz)
PRIMARY_TIMEFRAME = "5m"      # Ana trade timeframe
CONFIRM_TIMEFRAME = "15m"     # Onay timeframe
TREND_TIMEFRAME = "1h"        # Trend timeframe
OHLCV_LIMIT = 200             # Çekilecek mum sayısı

# ============================================
# STRATEJİ PARAMETRELERİ
# ============================================

# RSI Stratejisi
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
RSI_WEIGHT = 0.20

# MACD Stratejisi
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
MACD_WEIGHT = 0.20

# Bollinger Bands
BB_PERIOD = 20
BB_STD_DEV = 2.0
BB_WEIGHT = 0.15

# EMA Crossover
EMA_FAST = 9
EMA_MID = 21
EMA_SLOW = 55
EMA_WEIGHT = 0.20

# Volume Spike
VOLUME_SPIKE_MULTIPLIER = 2.0
VOLUME_MA_PERIOD = 20
VOLUME_WEIGHT = 0.15

# SuperTrend
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0
SUPERTREND_WEIGHT = 0.10

# Sinyal eşikleri
SIGNAL_BUY_THRESHOLD = 0.60    # Composite skor > 0.60 → Alım
SIGNAL_SELL_THRESHOLD = 0.40   # Composite skor < 0.40 → Satım
MIN_STRATEGIES_AGREE = 3       # Minimum kaç strateji aynı yönde olmalı

# ============================================
# RİSK YÖNETİMİ
# ============================================
MAX_POSITION_PCT = 0.05        # Sermayenin max %5'i tek pozisyon
STOP_LOSS_PCT = 0.012          # %1.2 stop-loss
TAKE_PROFIT_PCT = 0.06         # %6 take-profit (ortalama)
TRAILING_STOP_PCT = 0.02       # %2 trailing stop
MAX_DAILY_LOSS_PCT = 0.03      # Günlük max %3 kayıp
MAX_DRAWDOWN_PCT = 0.15        # Max %15 drawdown
MAX_CONCURRENT_POSITIONS = 5   # Eşzamanlı max 5 pozisyon
RISK_REWARD_MIN = 3.0          # Minimum R:R oranı

# Ardışık kayıp yönetimi
CONSECUTIVE_LOSS_THRESHOLD = 3  # 3 ardışık kayıptan sonra
POSITION_REDUCE_FACTOR = 0.5    # Pozisyon boyutunu yarıya indir

# ============================================
# FEE & SLIPPAGE
# ============================================
MAKER_FEE = 0.001              # %0.1 maker fee
TAKER_FEE = 0.001              # %0.1 taker fee
SLIPPAGE_PCT = 0.0005          # %0.05 slippage tahmini

# ============================================
# BACKTEST AYARLARI
# ============================================
BACKTEST_DAYS = 30             # Backtest süresi (gün)
BACKTEST_INITIAL_CAPITAL = 100.0  # Backtest başlangıç sermayesi

# ============================================
# LOGLAMA
# ============================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = "logs/trading.log"
LOG_FORMAT = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"

# ============================================
# BİLDİRİM VE JOURNAL AYARLARI
# ============================================
NOTIFICATION_RETRY_COUNT = 3           # Başarısız bildirim yeniden deneme sayısı
NOTIFICATION_RETRY_DELAY = 2           # Yeniden deneme arası bekleme (saniye)
PERIODIC_REPORT_INTERVAL = 900         # Periyodik rapor aralığı (saniye) — 15dk
PRICE_SNAPSHOT_INTERVAL = 30           # Fiyat snapshot aralığı (kontrol sayısı)
JOURNAL_MAX_SNAPSHOTS = 100            # Trade başına max fiyat snapshot

# ============================================
# GENEL AYARLAR
# ============================================
SCAN_INTERVAL_SECONDS = 10    # Her kaç saniyede bir tarama yapılsın
DATA_REFRESH_SECONDS = 60     # Veri yenileme aralığı
HEARTBEAT_INTERVAL = 300      # Health check aralığı (saniye)
TIMEZONE = "Europe/Istanbul"
