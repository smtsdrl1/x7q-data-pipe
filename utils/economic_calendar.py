"""
Ekonomik Takvim Entegrasyonu
Yüksek etkili ekonomik olaylar öncesi/sırası trading'i filtreler.
Fed/FOMC açıklamaları, CPI rakamları gibi anlarda volatilite patlar.

Veri kaynakları:
1. CoinGlass / Binance calendar (kripto odaklı)
2. Investing.com RSS (ücretsiz)
3. Statik takvim (fallback)

ICT "News Kill": Yüksek etkili haber ±30dk içinde sinyal üretme.
"""

import asyncio
import aiohttp
import json
import time
from datetime import datetime, timezone, timedelta
from utils.logger import setup_logger

logger = setup_logger("EconomicCalendar")

# Cache
_events_cache: tuple[list, float] | None = None
CACHE_TTL = 3600  # 1 saat

# Yüksek etkili kripto/makro olaylar - statik fallback
KNOWN_HIGH_IMPACT_KEYWORDS = [
    "FOMC", "Federal Reserve", "Fed Rate", "CPI", "NFP", "Unemployment",
    "GDP", "PPI", "Inflation", "Interest Rate", "Powell", "Yellen",
    "SEC", "ETF approval", "BTC halving", "Binance", "FTX",
]


async def fetch_calendar_events(days_ahead: int = 3) -> list[dict]:
    """
    Yaklaşan yüksek etkili ekonomik olayları çek.
    
    Returns:
        list[dict]: event_name, event_time_utc, impact_level, currency
    """
    global _events_cache
    
    # Cache kontrolü
    if _events_cache is not None:
        events, ts = _events_cache
        if time.time() - ts < CACHE_TTL:
            return events
    
    events = []
    
    # Yöntem 1: CoinGlass calendar API (kripto odaklı)
    try:
        events_coinglass = await _fetch_coinglass_calendar()
        events.extend(events_coinglass)
    except Exception as e:
        logger.debug(f"CoinGlass calendar hatası: {e}")
    
    # Yöntem 2: Statik takvim (her zaman çalışır)
    static_events = _get_static_upcoming_events()
    events.extend(static_events)
    
    # Duplikasyon temizle
    seen = set()
    unique_events = []
    for e in events:
        key = f"{e.get('event_name', '')}_{e.get('event_time_utc', '')}"
        if key not in seen:
            seen.add(key)
            unique_events.append(e)
    
    # Tarihe göre sırala
    unique_events.sort(key=lambda x: x.get("event_time_utc", ""))
    
    _events_cache = (unique_events, time.time())
    logger.debug(f"Ekonomik takvim: {len(unique_events)} olay yüklendi")
    return unique_events


async def _fetch_coinglass_calendar() -> list[dict]:
    """CoinGlass'tan kripto spesifik olaylar."""
    # Not: CoinGlass ücretsiz API limit var
    url = "https://open-api.coinglass.com/public/v2/calendar"
    headers = {"Content-Type": "application/json"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    raw_events = data.get("data", [])
                    
                    parsed = []
                    for ev in raw_events[:20]:  # Max 20 olay
                        parsed.append({
                            "event_name": ev.get("title", "Bilinmeyen"),
                            "event_time_utc": ev.get("date", ""),
                            "impact_level": ev.get("importance", "LOW").upper(),
                            "currency": "CRYPTO",
                            "source": "coinglass",
                        })
                    return parsed
    except Exception:
        pass
    return []


def _get_static_upcoming_events() -> list[dict]:
    """
    FOMC ve diğer bilinen yüksek etkili olaylar için statik takvim.
    Her ay güncellenmesi gerekir — auto-update mekanizması geliştirilecek.
    """
    now = datetime.now(timezone.utc)
    
    # 2026 FOMC tarihleri (UTC)
    fomc_dates_2026 = [
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-16",
    ]
    
    events = []
    for date_str in fomc_dates_2026:
        try:
            event_dt = datetime.fromisoformat(f"{date_str}T19:00:00").replace(tzinfo=timezone.utc)
            if event_dt > now - timedelta(hours=2):  # Geçmişi dahil etme
                events.append({
                    "event_name": "FOMC Meeting Decision",
                    "event_time_utc": event_dt.isoformat(),
                    "impact_level": "HIGH",
                    "currency": "USD",
                    "source": "static",
                })
        except Exception:
            pass
    
    return events


def check_news_kill_zone(minutes_before: int = 30, minutes_after: int = 30) -> dict:
    """
    Yüksek etkili haber zamanı yakın mı kontrol et.
    ICT "News Kill" konsepti: büyük haberler etrafında trade edilmez.
    
    Returns:
        dict: in_kill_zone, event_name, minutes_until, should_avoid
    """
    global _events_cache
    
    if _events_cache is None:
        return {"in_kill_zone": False, "should_avoid": False, "reason": "Takvim yüklenmedi"}
    
    events, _ = _events_cache
    now = datetime.now(timezone.utc)
    
    for event in events:
        if event.get("impact_level") != "HIGH":
            continue
        
        try:
            event_time = datetime.fromisoformat(event["event_time_utc"].replace("Z", "+00:00"))
            diff = (event_time - now).total_seconds() / 60  # Dakika
            
            # Haber öncesi veya sonrası kill zone
            if -minutes_after <= diff <= minutes_before:
                return {
                    "in_kill_zone": True,
                    "should_avoid": True,
                    "event_name": event["event_name"],
                    "minutes_until": round(diff, 1),
                    "impact_level": event["impact_level"],
                    "reason": f"{'Önceki' if diff > 0 else 'Sonraki'} yüksek etkili haber: {event['event_name']}",
                }
        except Exception:
            pass
    
    return {
        "in_kill_zone": False,
        "should_avoid": False,
        "reason": "Yakın haber yok",
    }


def get_upcoming_high_impact(hours_ahead: int = 24) -> list[dict]:
    """Önümüzdeki X saat içindeki yüksek etkili olayları listele."""
    global _events_cache
    if _events_cache is None:
        return []
    
    events, _ = _events_cache
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=hours_ahead)
    
    result = []
    for event in events:
        if event.get("impact_level") != "HIGH":
            continue
        try:
            event_time = datetime.fromisoformat(event["event_time_utc"].replace("Z", "+00:00"))
            if now <= event_time <= cutoff:
                diff = (event_time - now).total_seconds() / 3600
                result.append({
                    **event,
                    "hours_until": round(diff, 1),
                })
        except Exception:
            pass
    
    return sorted(result, key=lambda x: x.get("hours_until", 999))
