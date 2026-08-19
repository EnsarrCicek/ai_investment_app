"""BIST seans-zamanlaması rejimi — TECHNICAL_ANALYSIS_RESEARCH1.md, rapor
madde 7 adım 14 (intraday kısım).

BIST resmi seans saatleri (Europe/Istanbul, TSİ): 10:00-18:00, aralıksız
(tek seans, öğle arası yok). Açılışın ilk ~30 dakikası ve kapanışın son ~30
dakikası, gün içi en yüksek oynaklığın görüldüğü dilimlerdir (birikmiş emir
akışının açılışta boşalması, gün içi pozisyonların kapanışta kapatılması) —
bu rejimi bilmek, ör. relative_volume/breakout kalitesinin YORUMLANMASINDA
(henüz oraya bağlanmadı) önemlidir: açılıştaki yüksek hacim "anormal" değil,
mevsimsel/beklenen bir durumdur.

Bu modül saf bir zaman sınıflandırıcısıdır — herhangi bir veri kaynağına
bağımlı değildir.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

SESSION_OPEN = time(10, 0)
SESSION_CLOSE = time(18, 0)
OPENING_WINDOW_MINUTES = 30
CLOSING_WINDOW_MINUTES = 30


def classify_session_time(ts: datetime) -> str:
    """OPENING / MIDDAY / CLOSING / CLOSED (hafta sonu ve seans dışı dahil) döner.

    `ts` tz-aware değilse zaten İstanbul saatinde olduğu varsayılır (sessiz
    bir UTC->TSİ dönüşümü YAPILMAZ — çağıran, veri kaynağının hangi saat
    diliminde olduğundan emin olmalıdır).
    """
    local = ts.astimezone(ISTANBUL_TZ) if ts.tzinfo else ts.replace(tzinfo=ISTANBUL_TZ)

    if local.weekday() >= 5:  # Cumartesi=5, Pazar=6
        return "CLOSED"

    current = local.time()
    if current < SESSION_OPEN or current >= SESSION_CLOSE:
        return "CLOSED"

    minutes_since_open = (local.hour * 60 + local.minute) - (SESSION_OPEN.hour * 60 + SESSION_OPEN.minute)
    minutes_to_close = (SESSION_CLOSE.hour * 60 + SESSION_CLOSE.minute) - (local.hour * 60 + local.minute)

    if minutes_since_open < OPENING_WINDOW_MINUTES:
        return "OPENING"
    if minutes_to_close < CLOSING_WINDOW_MINUTES:
        return "CLOSING"
    return "MIDDAY"
