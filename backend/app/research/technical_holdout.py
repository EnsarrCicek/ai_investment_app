"""Prospektif holdout başlangıcı — TEK uygulama yeri.

Kaynak kural (dondurulmuş protokol, `holdout_status.activation_note`, V1 ve V2
protokollerinde AYNI metin): "The effective_holdout_start, once activation
completes, will be the first BIST session whose market open occurs strictly
after the FINAL activation-lock event ... No session before that final
activation event is eligible."

Girdiler (mevcut sözleşmeden, uydurma değil):
  * aktivasyon anı = `INITIAL` aktivasyon olayının Firestore `create_time`'ı
    (`activation_event.py` modül docstring'i: bu değer effective_holdout_start'ın
    ham girdisidir). `LOCK_AUTHORIZED` (revision yeniden yetkilendirmesi)
    başlangıcı DEĞİŞTİRMEZ -- yeni deney/holdout başlatmaz.
  * market open = `app.engines.technical.session_timing.SESSION_OPEN`
    (10:00 Europe/Istanbul; metodoloji parmak izi kapsamındaki dosya).
  * BIST seansları = authoritative `trading_calendar` (yarım günler dahil;
    desteklenmeyen yıl -> hata, tahmin YOK).

Dondurulmuş protokoldeki `holdout_status.effective_holdout_start = null` alanı
protokolün DONDURULMA anındaki durumudur ve DEĞİŞMEZ; aktivasyon sonrası
başlangıç her zaman bu fonksiyonla INITIAL olaydan TÜRETİLİR (kayıt tekrarı
create_time'ı değiştirmediğinden türetilen değer kaymaz).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.engines.technical.session_timing import SESSION_OPEN
from app.services.market_data.trading_calendar import SUPPORTED_BIST_CALENDAR_YEARS, first_expected_session_on_or_after

_IST = ZoneInfo("Europe/Istanbul")


class HoldoutStartUndeterminableError(ValueError):
    """Başlangıç, authoritative takvimle belirlenemiyor (ör. desteklenmeyen yıl)."""


def compute_effective_holdout_start(activation_time: datetime) -> date:
    if activation_time.tzinfo is None:
        raise ValueError("activation_time timezone-aware olmalı (Firestore create_time)")
    day = activation_time.astimezone(_IST).date()
    while True:  # gün her adımda ilerler; desteklenmeyen yıl -> hata
        # Arama tek takvim yılı içinde tutulur: yıl sınırını aşan bir aralık,
        # sonraki yıl desteklenmiyorsa desteklenen yıldaki seansı da gizlerdi.
        session = first_expected_session_on_or_after(day, date(day.year, 12, 31))
        if session is None:
            if day.year not in SUPPORTED_BIST_CALENDAR_YEARS:
                raise HoldoutStartUndeterminableError(
                    f"{day.year} için authoritative BIST takvimi yok -- holdout başlangıcı belirlenemez"
                )
            day = date(day.year + 1, 1, 1)
            continue
        if datetime.combine(session, SESSION_OPEN, tzinfo=_IST) > activation_time:
            return session
        day = session + timedelta(days=1)


def session_is_in_holdout(t_session_date: str, effective_holdout_start: date) -> bool:
    return date.fromisoformat(t_session_date) >= effective_holdout_start
