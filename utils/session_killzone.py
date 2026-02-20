"""
ICT Session Killzone Filtresi
Yalnızca yüksek likidite pencerelerinde (London/NY/Asia Killzone) sinyal al.
Düşük aktiviteli saatlerde çıkan gürültülü sinyalleri filtreler.

ICT (Inner Circle Trader) session theory:
- Asia Session    : 00:00 - 03:00 UTC | Düşük volatilite, range
- London Killzone : 02:00 - 05:00 UTC | Yüksek likidite girişi ✅
- NY Killzone     : 13:00 - 16:00 UTC | En yüksek hacim ✅
- NY AM Session   : 13:00 - 17:00 UTC | Overlap period
- Dead Zone       : 20:00 - 23:59 UTC | Düşük hacim ❌
"""

from datetime import datetime, timezone
from utils.logger import setup_logger
from config import (
    LONDON_KILLZONE_START, LONDON_KILLZONE_END,
    NY_KILLZONE_START, NY_KILLZONE_END,
    ASIA_KILLZONE_START, ASIA_KILLZONE_END,
    SESSION_FILTER_ENABLED
)

logger = setup_logger("SessionKillzone")


# Session adları
SESSIONS = {
    "LONDON_KILLZONE": {"emoji": "🇬🇧", "quality": 5},
    "NY_KILLZONE":     {"emoji": "🇺🇸", "quality": 5},
    "ASIA_KILLZONE":   {"emoji": "🌏", "quality": 3},
    "LONDON_NY_OVERLAP": {"emoji": "🔥", "quality": 6},  # En iyi!
    "OFF_HOURS":       {"emoji": "😴", "quality": 1},
}


def get_current_session(dt: datetime = None) -> dict:
    """
    Verilen zaman için aktif trading session'ı döndür.
    
    Args:
        dt: UTC datetime (None ise şu an)
    
    Returns:
        dict: session_name, quality (1-6), is_killzone, emoji, description
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    
    hour = dt.hour  # UTC saat
    
    # London × NY Overlap (en değerli)
    if LONDON_KILLZONE_START <= hour < NY_KILLZONE_END and hour >= NY_KILLZONE_START:
        # 13:00-16:00 + London hâlâ aktif (08:00-12:00 UTC London close ~17:00)
        # Gerçek overlap UTC 13:00-16:00
        if NY_KILLZONE_START <= hour < min(NY_KILLZONE_END, 16):
            return {
                "session": "LONDON_NY_OVERLAP",
                "quality": 6,
                "is_killzone": True,
                "emoji": "🔥",
                "description": "London × NY Overlap - En Yüksek Likidite",
            }
    
    # London Killzone
    if LONDON_KILLZONE_START <= hour < LONDON_KILLZONE_END:
        return {
            "session": "LONDON_KILLZONE",
            "quality": 5,
            "is_killzone": True,
            "emoji": "🇬🇧",
            "description": "London Killzone - Yüksek Likidite",
        }
    
    # NY Killzone
    if NY_KILLZONE_START <= hour < NY_KILLZONE_END:
        return {
            "session": "NY_KILLZONE",
            "quality": 5,
            "is_killzone": True,
            "emoji": "🇺🇸",
            "description": "NY Killzone - Yüksek Likidite",
        }
    
    # Asia Killzone
    if ASIA_KILLZONE_START <= hour < ASIA_KILLZONE_END:
        return {
            "session": "ASIA_KILLZONE",
            "quality": 3,
            "is_killzone": True,
            "emoji": "🌏",
            "description": "Asia Killzone - Orta Likidite",
        }
    
    # Off hours
    return {
        "session": "OFF_HOURS",
        "quality": 1,
        "is_killzone": False,
        "emoji": "😴",
        "description": f"Düşük Hacim Saati (UTC {hour:02d}:xx)",
    }


def is_tradeable_session(min_quality: int = 3, dt: datetime = None) -> tuple[bool, dict]:
    """
    Mevcut session trade için uygun mu?
    
    Args:
        min_quality: Minimum session kalitesi (1-6). Default 3 = Asia+ dahil
        dt: Kontrol edilecek UTC datetime
    
    Returns:
        tuple[bool, dict]: (tradeable, session_info)
    """
    if not SESSION_FILTER_ENABLED:
        session = get_current_session(dt)
        session["filtered"] = False
        return True, session
    
    session = get_current_session(dt)
    tradeable = session["quality"] >= min_quality
    session["filtered"] = not tradeable
    
    if not tradeable:
        logger.debug(
            f"Session filtresi: {session['session']} (kalite {session['quality']}) "
            f"min_quality={min_quality} → trade reddedildi"
        )
    
    return tradeable, session


def get_next_killzone() -> dict:
    """
    Bir sonraki killzone'un başlangıç zamanını hesapla.
    
    Returns:
        dict: session_name, hours_until, minutes_until
    """
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    minute = now_utc.minute
    
    # Killzone başlangıç saatleri
    killzones = [
        ("ASIA_KILLZONE", ASIA_KILLZONE_START),
        ("LONDON_KILLZONE", LONDON_KILLZONE_START),
        ("NY_KILLZONE", NY_KILLZONE_START),
    ]
    
    # En yakın sonraki killzone'u bul
    for name, start_hour in killzones:
        if start_hour > hour or (start_hour == hour and minute < 30):
            diff_hours = start_hour - hour
            diff_minutes = (diff_hours * 60) - minute
            return {
                "next_session": name,
                "hours_until": diff_hours,
                "minutes_until": diff_minutes,
                "start_hour_utc": start_hour,
            }
    
    # Bugün kalan yoksa yarın ilk killzone
    first_kz = killzones[0]
    hours_until = (24 - hour) + first_kz[1]
    return {
        "next_session": first_kz[0],
        "hours_until": hours_until,
        "minutes_until": hours_until * 60 - minute,
        "start_hour_utc": first_kz[1],
    }


def session_score_multiplier(session_info: dict) -> float:
    """
    Session kalitesine göre sinyal skoru çarpanı.
    Düşük kaliteli session → düşük çarpan → sinyal geçmesi zorlaşır.
    
    Returns:
        float: 0.5 (off hours) ile 1.2 (overlap) arasında çarpan
    """
    quality = session_info.get("quality", 1)
    multipliers = {
        1: 0.5,   # Off hours
        2: 0.7,
        3: 0.85,  # Asia
        4: 0.95,
        5: 1.0,   # London/NY
        6: 1.2,   # Overlap
    }
    return multipliers.get(quality, 1.0)


def format_session_status() -> str:
    """Telegram için session durum mesajı."""
    session = get_current_session()
    next_kz = get_next_killzone()
    
    emoji = session["emoji"]
    name = session["session"].replace("_", " ")
    quality = session["quality"]
    stars = "⭐" * quality
    
    lines = [
        f"{emoji} <b>Session:</b> {name}",
        f"📊 Kalite: {stars} ({quality}/6)",
    ]
    
    if not session["is_killzone"]:
        lines.append(
            f"⏰ Sonraki KZ: {next_kz['next_session'].replace('_', ' ')} "
            f"(~{next_kz['hours_until']}s sonra)"
        )
    else:
        lines.append(f"✅ {session['description']}")
    
    return "\n".join(lines)
