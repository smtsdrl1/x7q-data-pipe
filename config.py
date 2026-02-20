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

# Tier-1: Yüksek likidite, güvenilir sinyal — her turda taranır
TIER1_PAIRS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
]
# Tier-2: Orta likidite — her 3 turda bir taranır
TIER2_PAIRS = [
    "ADA/USDT", "AVAX/USDT", "DOGE/USDT", "DOT/USDT", "LINK/USDT",
    "UNI/USDT", "ATOM/USDT", "LTC/USDT", "APT/USDT", "ARB/USDT",
    "OP/USDT", "NEAR/USDT", "INJ/USDT", "FIL/USDT", "MATIC/USDT",
]
TRADING_PAIRS = TIER1_PAIRS + TIER2_PAIRS

# Timeframe'ler (multi-timeframe analiz)
PRIMARY_TIMEFRAME = "5m"      # Ana trade timeframe
CONFIRM_TIMEFRAME = "15m"     # Onay timeframe
TREND_TIMEFRAME = "1h"        # Trend filtresi timeframe — AKTIF
OHLCV_LIMIT = 200             # Çekilecek mum sayısı

# ============================================
# GELİŞMİŞ AYARLAR
# ============================================
USE_WEBSOCKET = True          # WebSocket ile anlık veri (REST yerine)
TREND_FILTER_ENABLED = True   # 1h trend filtresi — trendle zıt sinyalleri engelle
SIGNAL_ACCURACY_CANDLES = 12 # Sinyal doğruluk ölçümü için ileriki N mum (5m×12=1h)

# ============================================
# STRATEJİ PARAMETRELERİ
# ============================================

# RSI Stratejisi
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
RSI_WEIGHT = 0.15          # ↓ (0.20→0.15) — mean-reversion tek başına zayıf

# MACD Stratejisi
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
MACD_WEIGHT = 0.15          # ↓ (0.20→0.15)

# Bollinger Bands
BB_PERIOD = 20
BB_STD_DEV = 2.0
BB_WEIGHT = 0.15

# EMA Crossover
EMA_FAST = 9
EMA_MID = 21
EMA_SLOW = 55
EMA_WEIGHT = 0.25           # ↑ (0.20→0.25) — trend takibi güçlü

# Volume Spike
VOLUME_SPIKE_MULTIPLIER = 2.0
VOLUME_MA_PERIOD = 20
VOLUME_WEIGHT = 0.25        # ↑ (0.15→0.25) — kırılım doğrulaması

# SuperTrend
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0
SUPERTREND_WEIGHT = 0.20    # ↑ (0.10→0.20)

# FVG + Fibonacci Confluence — Alper INCE (@alper3968) metodolojisi
# Kaynak: https://x.com/alper3968/status/1862990567153557955
# FVG (Fair Value Gap) + Fibonacci retracement seviyelerinin örtüşmesi
# = yüksek olasılıklı sniper giriş noktası
FVG_FIBONACCI_WEIGHT      = 0.25   # Diğer stratejilerle eşit ağırlık
FVG_LOOKBACK_CANDLES      = 60     # FVG tarama penceresi (mum sayısı)
FIB_LOOKBACK_CANDLES      = 100    # Fibonacci swing hesaplama penceresi  
FVG_CONFLUENCE_TOLERANCE  = 0.015  # FVG–Fib örtüşme toleransı (%1.5)

# Sinyal eşikleri — daha kaliteli sinyal için sıkılaştırıldı
SIGNAL_BUY_THRESHOLD = 0.60    # ↑ (0.55→0.60): daha güçlü consensus gerekli
SIGNAL_SELL_THRESHOLD = 0.40   # eşdeğer simetri
MIN_STRATEGIES_AGREE = 3        # ↑ (2→3): en az 3 strateji aynı yönde

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
# SESSION KILLZONE AYARLARI (ICT)
# ============================================
SESSION_FILTER_ENABLED = True  # Session filtresi aktif/pasif
LONDON_KILLZONE_START = 2      # UTC saat başlangıcı
LONDON_KILLZONE_END   = 5      # UTC saat bitişi
NY_KILLZONE_START     = 13     # UTC
NY_KILLZONE_END       = 16     # UTC
ASIA_KILLZONE_START   = 0      # UTC
ASIA_KILLZONE_END     = 2      # UTC
SESSION_MIN_QUALITY   = 3      # Minimum session kalitesi (1=kötü, 6=mükemmel)

# ============================================
# ORDER BLOCK + LIQUIDITY SWEEP
# ============================================
ORDER_BLOCK_WEIGHT       = 0.20  # Strateji ağırlığı
LIQUIDITY_SWEEP_WEIGHT   = 0.20
ORDER_BLOCK_MIN_IMPULSE  = 0.5   # % minimum impulse OB tespiti için
OB_TOUCH_TOLERANCE       = 0.003 # %0.3 tolerans

# ============================================
# KORELASYON KONTROLÜ
# ============================================
CORRELATION_ENABLED         = True
MAX_CORRELATION_THRESHOLD   = 0.75  # Bu üstündeyse aynı anda aç
CORRELATION_LOOKBACK_HOURS  = 24    # Korelasyon hesap penceresi

# ============================================
# KELLY KRİTER POZISYON BOYUTU
# ============================================
KELLY_SIZING_ENABLED   = True
KELLY_FRACTION         = 0.5      # Half-Kelly (daha güvenli)
KELLY_MAX_PCT          = 0.10    # Max %10 sermaye (güvenlik sınırı)

# ============================================
# PARSİYEL TP + BREAKEVEN SL
# ============================================
PARTIAL_TP_ENABLED       = True
PARTIAL_TP1_RATIO        = 0.5    # TP1'de pozisyonun %50'sini kapat
PARTIAL_TP1_MULTIPLIER   = 1.5    # Risk'in 1.5x'ine gel → TP1
BREAKEVEN_AFTER_TP1      = True   # TP1 sonrası SL=giriş fiyatı
PYRAMID_ENABLED          = False  # Şimdilik kapalı (gelecek sürüm)

# ============================================
# DERIVATIVES / OI + FUNDING RATE
# ============================================
DERIVATIVES_ENABLED      = True
OI_SCORE_WEIGHT          = 0.05   # Toplam skor içindeki ağırlık
FUNDING_RATE_EXTREME     = 0.001  # %0.1 = extreme FR eşiği

# ============================================
# MARKET REGIME
# ============================================
REGIME_DETECTION_ENABLED = True
ADX_TREND_THRESHOLD      = 25     # ADX > 25 = trending
ATR_VOLATILE_THRESHOLD   = 2.5    # ATR% > 2.5 = volatile

# ============================================
# CIRCUIT BREAKER (GELİŞMİŞ)
# ============================================
CB_CONSECUTIVE_LOSSES    = 3      # Kaç ardışık kayıptan sonra trip
CB_HOURLY_LOSS_LIMIT     = 0.03   # %3 saatlik kayıp limiti
CB_DAILY_LOSS_LIMIT      = 0.06   # %6 günlük kayıp limiti
CB_BTC_DUMP_THRESHOLD    = -0.05  # BTC -5% → tüm stop
CB_MAX_SPREAD_PCT        = 0.001  # Max %0.1 spread (1USDT için 0.001 = 0.1c)

# ============================================
# ON-CHAIN / FEAR-GREED
# ============================================
ONCHAIN_ENABLED          = True
FEAR_GREED_MIN_BUY       = 20     # FG < 20 → extreme fear → alım fırsatı
FEAR_GREED_MAX_BUY       = 70     # FG > 70 → greed → dikkatli ol

# ============================================
# GENEL AYARLAR
# ============================================
SCAN_INTERVAL_SECONDS = 10    # Her kaç saniyede bir tarama yapılsın
DATA_REFRESH_SECONDS = 60     # Veri yenileme aralığı
HEARTBEAT_INTERVAL = 300      # Health check aralığı (saniye)
TIMEZONE = "Europe/Istanbul"

# ============================================
# SİNYAL TEKRAR ENGELLEME (DEDUP)
# ============================================
# Aynı pair için tekrar sinyal üretilmesi engellenir bu süre içinde.
# Açık pozisyon kapatılana kadar otomatik bloke edilir.
# Bu süre yalnızca sinyal üretimi için geçerlidir (pozisyon yönetimi farklı).
SIGNAL_COOLDOWN_MINUTES = 60        # Dakika (varsayılan 1 saat)
SIGNAL_SCORE_OVERRIDE_DELTA = 0.10  # Bu kadar daha yüksek skor gelse cooldown geçersiz
