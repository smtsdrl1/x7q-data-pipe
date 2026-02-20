"""
FVG (Fair Value Gap) + Fibonacci Confluence Stratejisi
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Kaynak: Alper INCE @alper3968 — XU100 / Fibonacci / FVG analizi
        https://x.com/alper3968/status/1862990567153557955

Teori (ICT konsepti):
  • Fair Value Gap (FVG): Fiyat çok hızlı hareket ettiğinde 3. mumun alt kısmı ile
    1. mumun üst kısmı arasında bir "boşluk" oluşur. Bu boşluklar güçlü S/R görevi
    görür ve fiyat geri döndüğünde reaksiyon verir.

    Bullish FVG:  candle[i].high < candle[i+2].low    → fiyat yukarı gapladı
    Bearish FVG:  candle[i].low  > candle[i+2].high   → fiyat aşağı gapladı

  • Fibonacci Retracement: Swing high/low arası mesafenin kritik seviyeleri:
    0.236 / 0.382 / 0.500 / 0.618 (altın oran) / 0.786

  • Confluence Zone: Bir FVG bölgesi ile bir Fibonacci seviyesi üst üste geldiğinde
    yüksek olasılıklı dönüş/devam bölgesi oluşur. Bu, en güçlü sniper giriş noktasıdır.

Sinyal Mantığı:
  BUY  → Fiyat bullish FVG + Fib (0.382-0.618) confluence'ına geri döndü + trend yukarda
  SELL → Fiyat bearish FVG + Fib (0.382-0.618) confluence'ına geri döndü + trend aşağıda
"""

import pandas as pd
import numpy as np
from strategies.base_strategy import BaseStrategy, Signal, SignalType
from config import FVG_FIBONACCI_WEIGHT


# ─── FVG Tespit Fonksiyonları ────────────────────────────────────────────────

def detect_fvgs(df: pd.DataFrame, lookback: int = 60) -> list[dict]:
    """
    Son N mum içindeki Fair Value Gap'leri tespit et.

    Returns: list of {
        'type': 'bullish'|'bearish',
        'top': float,      # FVG bölgesinin üst sınırı
        'bottom': float,   # FVG bölgesinin alt sınırı
        'midpoint': float, # Bölgenin ortası
        'idx': int,        # Oluşum bar indeksi
        'filled': bool     # Kapanıp kapanmadığı
    }
    """
    if df is None or len(df) < 5:
        return []

    start = max(0, len(df) - lookback - 2)
    fvgs = []

    for i in range(start, len(df) - 2):
        c0_high = float(df["high"].iloc[i])
        c0_low  = float(df["low"].iloc[i])
        c2_high = float(df["high"].iloc[i + 2])
        c2_low  = float(df["low"].iloc[i + 2])

        # Bullish FVG: c[i].high < c[i+2].low → imbalance above
        if c2_low > c0_high:
            size = c2_low - c0_high
            if size > 0:
                fvgs.append({
                    "type":     "bullish",
                    "top":      c2_low,
                    "bottom":   c0_high,
                    "midpoint": (c0_high + c2_low) / 2,
                    "size":     size,
                    "idx":      i + 1,
                    "filled":   False,
                })

        # Bearish FVG: c[i].low > c[i+2].high → imbalance below
        elif c0_low > c2_high:
            size = c0_low - c2_high
            if size > 0:
                fvgs.append({
                    "type":     "bearish",
                    "top":      c0_low,
                    "bottom":   c2_high,
                    "midpoint": (c2_high + c0_low) / 2,
                    "size":     size,
                    "idx":      i + 1,
                    "filled":   False,
                })

    # Doldurulanları işaretle (sonraki mumlar FVG bölgesini geçtiyse)
    current_close = float(df["close"].iloc[-1])
    for fvg in fvgs:
        # Bullish FVG: fiyat bölgenin altına düştüyse kapandı
        if fvg["type"] == "bullish" and current_close < fvg["bottom"] * 0.998:
            fvg["filled"] = True
        # Bearish FVG: fiyat bölgenin üstüne çıktıysa kapandı
        elif fvg["type"] == "bearish" and current_close > fvg["top"] * 1.002:
            fvg["filled"] = True

    # Sadece aktif (doldurulmamış) FVG'leri döndür, en yeni önce
    active = [f for f in fvgs if not f["filled"]]
    active.sort(key=lambda x: x["idx"], reverse=True)
    return active


def calc_fibonacci_levels(df: pd.DataFrame, lookback: int = 100) -> dict:
    """
    Son N mum içindeki swing high/low üzerinden Fibonacci seviyeleri hesapla.
    Hem yukarıdan aşağı (retracement) hem de aşağıdan yukarı hesaplar.

    Returns: {
        'swing_high': float,
        'swing_low': float,
        'direction': 'uptrend'|'downtrend',
        '0.236': float, '0.382': float, '0.500': float,
        '0.618': float, '0.786': float,
        'ext_1.272': float, 'ext_1.618': float,
    }
    """
    if df is None or len(df) < lookback // 2:
        return {}

    recent = df.tail(min(lookback, len(df)))
    swing_high = float(recent["high"].max())
    swing_low  = float(recent["low"].min())
    diff       = swing_high - swing_low

    if diff <= 0:
        return {}

    # Trend yönünü son 20 mum kapanışına bakarak belirle
    close_recent = df["close"].tail(20)
    direction = "uptrend" if float(close_recent.iloc[-1]) > float(close_recent.iloc[0]) else "downtrend"

    # Downtrend: swing_high'dan swing_low'a retracement (yukarı Fibonacci)
    # Uptrend:   swing_low'dan swing_high'a retracement (aşağı Fibonacci)
    if direction == "uptrend":
        # Retracement = swing high'dan aşağı
        ref_high, ref_low = swing_high, swing_low
    else:
        # Retracement = swing low'dan yukarı
        ref_high, ref_low = swing_high, swing_low

    levels = {
        "swing_high":  swing_high,
        "swing_low":   swing_low,
        "direction":   direction,
        "diff":        diff,
        "0.000":       ref_high,
        "0.236":       ref_high - diff * 0.236,
        "0.382":       ref_high - diff * 0.382,
        "0.500":       ref_high - diff * 0.500,
        "0.618":       ref_high - diff * 0.618,   # Altın oran
        "0.786":       ref_high - diff * 0.786,
        "1.000":       ref_low,
        "ext_1.272":   ref_low  - diff * 0.272,   # Extension
        "ext_1.618":   ref_low  - diff * 0.618,   # Golden extension
    }
    return levels


def check_fvg_fib_confluence(
    price: float,
    fvgs: list[dict],
    fib_levels: dict,
    tolerance: float = 0.015,   # %1.5 tolerans
) -> dict | None:
    """
    FVG bölgesi ile Fibonacci seviyesi örtüşüyor mu kontrol et.

    Alper INCE metodolojisi:
    - FVG zone içinde veya yakınında kritik Fib seviyesi varsa → confluence
    - 0.618 seviyesi en güçlü (altın oran) → sniper giriş
    - 0.382 ve 0.786 ikinci derecede güçlü

    Returns: confluence dict or None
    """
    if not fvgs or not fib_levels:
        return None

    KEY_FIBS = {
        "0.618": 1.0,   # Altın oran — en güçlü
        "0.500": 0.8,   # Psikolojik seviye
        "0.382": 0.7,   # Güçlü destek/direnç
        "0.786": 0.65,  # Geri çekilme desteği
        "0.236": 0.5,   # Zayıf
    }

    best = None
    best_strength = -1.0

    for fvg in fvgs:
        for fib_key, fib_base_strength in KEY_FIBS.items():
            fib_price = fib_levels.get(fib_key)
            if fib_price is None:
                continue

            # Fib seviyesi FVG bölgesinin içinde mi?
            in_zone = fvg["bottom"] * (1 - tolerance) <= fib_price <= fvg["top"] * (1 + tolerance)

            # Fib seviyesi FVG'ye yakın mı? (bölge dışında ama yakın)
            near_zone = (
                abs(fib_price - fvg["midpoint"]) / max(fvg["midpoint"], 1e-10) < tolerance * 2
            )

            if not (in_zone or near_zone):
                continue

            # Fiyat confluence bölgesine yakın mı?
            dist_pct = abs(price - fvg["midpoint"]) / max(fvg["midpoint"], 1e-10)
            if dist_pct > tolerance * 3:
                continue

            # Confluence gücü: Fib gücü × mesafe yakınlığı
            proximity_factor = 1.0 - (dist_pct / (tolerance * 3))
            in_zone_bonus = 0.2 if in_zone else 0.0
            strength = fib_base_strength * proximity_factor + in_zone_bonus

            if strength > best_strength:
                best_strength = strength
                best = {
                    "fvg_type":      fvg["type"],
                    "fib_level":     fib_key,
                    "fib_price":     round(fib_price, 6),
                    "fvg_top":       round(fvg["top"], 6),
                    "fvg_bottom":    round(fvg["bottom"], 6),
                    "fvg_midpoint":  round(fvg["midpoint"], 6),
                    "distance_pct":  round(dist_pct * 100, 3),
                    "in_zone":       in_zone,
                    "strength":      round(strength, 3),
                    "is_golden":     fib_key == "0.618",
                }

    return best


# ─── Strateji Sınıfı ────────────────────────────────────────────────────────

class FVGFibonacciStrategy(BaseStrategy):
    """
    FVG + Fibonacci Confluence Stratejisi — Alper INCE metodu.

    Sinyal Mantığı:
    ─ BUY  ─
      • Aktif bir Bullish FVG mevcut
      • Bu FVG, kritik bir Fibonacci seviyesiyle (0.382–0.786) örtüşüyor
      • Fiyat bu confluence bölgesine dönmüş (geri çekilme)
      • EMA9 > EMA21 (trend desteği)

    ─ SELL ─
      • Aktif bir Bearish FVG mevcut
      • Bu FVG, kritik bir Fibonacci seviyesiyle örtüşüyor
      • Fiyat bu confluence bölgesine yükselmiş (tepki)
      • EMA9 < EMA21 (trend desteği)
    """

    FVG_LOOKBACK = 60
    FIB_LOOKBACK = 100
    CONFLUENCE_TOLERANCE = 0.015  # %1.5

    def __init__(self):
        super().__init__(name="FVG+Fibonacci", weight=FVG_FIBONACCI_WEIGHT)

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        if df is None or len(df) < 50:
            return self._neutral_signal(symbol, float(df["close"].iloc[-1]) if df is not None and len(df) > 0 else 0)

        price = float(df["close"].iloc[-1])

        # 1. FVG'leri tespit et
        fvgs    = detect_fvgs(df, lookback=self.FVG_LOOKBACK)
        # 2. Fibonacci seviyeleri hesapla
        fib     = calc_fibonacci_levels(df, lookback=self.FIB_LOOKBACK)
        # 3. Confluence kontrolü
        conf    = check_fvg_fib_confluence(price, fvgs, fib, tolerance=self.CONFLUENCE_TOLERANCE)

        if not conf:
            return self._neutral_signal(symbol, price)

        # 4. EMA trend filtresi (conf yönü ile EMA uyumu)
        ema9_aligned  = True
        ema21_aligned = True
        if "ema_9" in df.columns and "ema_21" in df.columns:
            ema9  = float(df["ema_9"].iloc[-1])
            ema21 = float(df["ema_21"].iloc[-1])
            if conf["fvg_type"] == "bullish":
                ema9_aligned  = ema9 > ema21 * 0.998   # hafif tolerans
            else:
                ema9_aligned  = ema9 < ema21 * 1.002
        elif "ema9" in df.columns and "ema21" in df.columns:
            ema9  = float(df["ema9"].iloc[-1])
            ema21 = float(df["ema21"].iloc[-1])
            if conf["fvg_type"] == "bullish":
                ema9_aligned = ema9 > ema21 * 0.998
            else:
                ema9_aligned = ema9 < ema21 * 1.002

        # 5. Sinyal gücü
        base_strength  = 0.55 + conf["strength"] * 0.30   # 0.55 – 0.85
        golden_bonus   = 0.10 if conf["is_golden"] else 0.0
        ema_bonus      = 0.05 if ema9_aligned else -0.05
        in_zone_bonus  = 0.05 if conf["in_zone"] else 0.0
        signal_strength = min(0.95, base_strength + golden_bonus + ema_bonus + in_zone_bonus)

        fib_label = f"Fib {conf['fib_level']}"
        fvg_label = conf["fvg_type"].upper()
        golden    = " [ALTIN ORAN 🏆]" if conf["is_golden"] else ""

        if conf["fvg_type"] == "bullish":
            reason = (
                f"FVG+Fib Confluence BUY: "
                f"Bullish FVG ({conf['fvg_bottom']:.4f}–{conf['fvg_top']:.4f}) "
                f"× {fib_label}{golden} "
                f"| Mesafe: %{conf['distance_pct']:.2f} "
                f"| Güç: {conf['strength']:.2f}"
            )
            return Signal(
                signal_type=SignalType.BUY,
                strength=signal_strength,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=reason,
                metadata={
                    "confluence": conf,
                    "fib_levels": {k: v for k, v in fib.items() if isinstance(v, float)},
                    "active_fvgs": len(fvgs),
                    "ema_aligned": ema9_aligned,
                },
            )
        else:
            reason = (
                f"FVG+Fib Confluence SELL: "
                f"Bearish FVG ({conf['fvg_bottom']:.4f}–{conf['fvg_top']:.4f}) "
                f"× {fib_label}{golden} "
                f"| Mesafe: %{conf['distance_pct']:.2f} "
                f"| Güç: {conf['strength']:.2f}"
            )
            return Signal(
                signal_type=SignalType.SELL,
                strength=signal_strength,
                strategy_name=self.name,
                symbol=symbol,
                price=price,
                reason=reason,
                metadata={
                    "confluence": conf,
                    "fib_levels": {k: v for k, v in fib.items() if isinstance(v, float)},
                    "active_fvgs": len(fvgs),
                    "ema_aligned": ema9_aligned,
                },
            )
