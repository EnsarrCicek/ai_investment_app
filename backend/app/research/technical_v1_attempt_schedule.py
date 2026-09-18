"""HATA 13D — Technical V1 attempt/finalizasyon zaman çizelgesi sabitleri.

Kilitli çizelge (Europe/Istanbul, yerel saat/dakika sabit -- `ISTANBUL_TZ`,
ZATEN var olan `app.engines.technical.session_timing`'ten yeniden
kullanılır, İKİNCİ bir "Europe/Istanbul" `ZoneInfo` örneği İCAT EDİLMEZ,
UTC ofseti ELLE HESAPLANMAZ):

  - attempt 1: 08:00
  - attempt 2 karar noktası: 09:00
  - formal (bilimsel) cutoff: 09:45
  - operasyonel finalizasyon VARSAYILANI: 10:15 -- bu BİLİMSEL bir
    eligibility semantiği DEĞİLDİR (bkz. HATA 13D section 4/16), yalnızca
    finalizer job'ının TİPİK olarak ne zaman tetikleneceğine dair bir
    operasyonel öneridir. Hiçbir kod yolu bu sabiti bir cutoff/eligibility
    kararı olarak KULLANMAZ -- finalizer'ın kendisi HER ZAMAN
    `FinalizationContext.formal_cutoff_utc`'yi kullanır (bkz.
    `technical_v1_finalization.py`), bu sabiti DEĞİL. Burada yalnızca
    dokümantasyon/gelecekteki scheduler (HATA 13E) referansı için taşınır.

KİLİTLİ TARİH-TABANI KARARI: bu dört saat, `T_session_date`'İN KENDİSİNE
DEĞİL, T'DEN SONRAKİ İLK BIST işlem gününe (`first_expected_session_on_
or_after`, protokolün `execution_and_return_definition.e1_definition`'ı
İLE AYNI trading-calendar kavramı -- "E1 = first eligible BIST session
after T") ANKORLANIR -- `test_final_evaluation_selector.py`'nin KENDİ,
zaten kilitlenmiş `FinalizationContext` test fixture'larıyla (T_session_
date=2026-09-09 için attempt2_decision_time_utc/formal_cutoff_utc HER
ZAMAN 2026-09-10'a ankorlanmış örnekler) TUTARLI. Capture, T'nin
kapanışından SONRAKİ ilk işlem gününün açılışından ÖNCE tamamlanmalıdır --
`T_session_date + 1 TAKVİM günü` KULLANILMAZ (bir hafta sonu/resmi
tatile denk gelebilirdi).

Bu modül HİÇBİR I/O yapmaz (Firestore/dosya sistemi/ağ erişimi YOK) --
saf, deterministik tarih/saat aritmetiğidir (yalnızca sabit-kodlanmış
authoritative BIST takvim tablosunu okuyan `trading_calendar.py`'ye
bağımlıdır, o da herhangi bir I/O yapmaz)."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone

from app.engines.technical.data_quality import validate_calendar_coverage
from app.engines.technical.session_timing import ISTANBUL_TZ
from app.services.market_data.trading_calendar import first_expected_session_on_or_after

ATTEMPT_1_LOCAL_TIME = time(8, 0)
ATTEMPT_2_DECISION_LOCAL_TIME = time(9, 0)
FORMAL_CUTOFF_LOCAL_TIME = time(9, 45)
OPERATIONAL_FINALIZATION_DEFAULT_LOCAL_TIME = time(10, 15)

# `first_expected_session_on_or_after`'ın kendi arama ufkuna ihtiyacı var
# (section: o fonksiyon keyfi bir sabitle "ne kadar ileri arayayım"
# sorusuna KENDİ BAŞINA cevap vermez) -- BIST'in 2025-2026 takviminde
# gözlemlenen en uzun kesintisiz kapanış bloğu 5 takvim günüdür (bkz.
# `history_window.py::PRE_ROLL_DAYS` docstring'i); burada de AYNI
# gerekçeyle makul bir gözlem payı eklenmiş, kolayca kalibre edilebilir
# bir sabit kullanılır.
_NEXT_SESSION_SEARCH_HORIZON_DAYS = 14

_CANONICAL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_canonical_date(t_session_date: str) -> date:
    """`evidence_identity._validate_canonical_date`/`final_evaluation_
    models._validate_canonical_date_str` İLE AYNI iki-katmanlı sıkı
    doğrulama deseni (regex tam-eşleşme + self-round-trip) -- bu modülün
    KENDİ, kasıtlı olarak ayrı tutulan kopyasıdır (bu kod tabanında
    kurulu, her modülün kendi minimal format-doğrulama kopyasını tuttuğu
    konvansiyonun devamı)."""
    if not isinstance(t_session_date, str) or not _CANONICAL_DATE_RE.match(t_session_date):
        raise ValueError(f"T_session_date kanonik lehçede değil (YYYY-MM-DD bekleniyor): {t_session_date!r}")
    parsed = date.fromisoformat(t_session_date)
    if parsed.isoformat() != t_session_date:
        raise ValueError(f"T_session_date kanonik round-trip'i sağlamıyor: {t_session_date!r}")
    return parsed


def attempt_schedule_base_date(t_session_date: str) -> date:
    """`T_session_date`'ten SONRAKİ İLK BIST işlem gününü döner -- attempt
    çizelgesinin yerel-saat tabanı BUDUR, `T_session_date`'in KENDİSİ
    DEĞİL (bkz. modül docstring'i)."""
    session_date = _validate_canonical_date(t_session_date)
    search_start = session_date + timedelta(days=1)
    search_end = session_date + timedelta(days=_NEXT_SESSION_SEARCH_HORIZON_DAYS)
    validate_calendar_coverage(search_start, search_end)
    next_session = first_expected_session_on_or_after(search_start, search_end)
    if next_session is None:
        raise ValueError(
            f"T_session_date={t_session_date!r} sonrasında (arama ufku {_NEXT_SESSION_SEARCH_HORIZON_DAYS} gün) "
            "beklenen bir BIST işlem günü bulunamadı."
        )
    return next_session


def _localized_utc(base_date: date, local_time: time) -> datetime:
    local_dt = datetime.combine(base_date, local_time, tzinfo=ISTANBUL_TZ)
    return local_dt.astimezone(timezone.utc)


def attempt1_local_time_utc(t_session_date: str) -> datetime:
    return _localized_utc(attempt_schedule_base_date(t_session_date), ATTEMPT_1_LOCAL_TIME)


def attempt2_decision_time_utc(t_session_date: str) -> datetime:
    return _localized_utc(attempt_schedule_base_date(t_session_date), ATTEMPT_2_DECISION_LOCAL_TIME)


def formal_cutoff_utc(t_session_date: str) -> datetime:
    return _localized_utc(attempt_schedule_base_date(t_session_date), FORMAL_CUTOFF_LOCAL_TIME)


def operational_finalization_default_utc(t_session_date: str) -> datetime:
    return _localized_utc(attempt_schedule_base_date(t_session_date), OPERATIONAL_FINALIZATION_DEFAULT_LOCAL_TIME)
