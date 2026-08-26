"""Pre-roll / leading-edge doğrulama sözleşmesi — HATA 2C (25.08.2026).

Önceki denetimlerde (HATA 2B) kanıtlanan kör nokta: `check_trading_day_continuity`,
kontrolün ALT sınırı olarak yalnızca `df.index[0]`'ı (analiz penceresinin
KENDİ ilk barı) kullanıyordu. Bu, sağlayıcının (Yahoo) analiz penceresinin
TAM BAŞINDAKİ günleri sessizce düşürmesi durumunda, gerçek bir boşluğu
"muhtemelen pre-listing" sanıp sessizce MASKELİYORDU — established bir
sembulun ilk birkaç günü düşürülmüş gibi simüle edilen sentetik testle
kanıtlandı (bkz. HATA 2C denetim raporları).

Çözüm: analiz penceresinden (`analysis_start`) biraz DAHA ÖNCEsine
("pre-roll") uzanan EK bir gözlem bölgesi çekilir. Bu bölgede EN AZ bir
gerçek bar bulunması, sembolün `analysis_start`'tan ÖNCE ZATEN işlem
gördüğünü KANITLAR — artık "ilk gördüğümüz gün = muhtemelen listing"
varsayımına gerek kalmaz.

ÇOK ÖNEMLİ SINIRLAMA: `PRE_ROLL_DAYS` bir DOĞRULUK GARANTİSİ DEĞİLDİR ve
Yahoo'nun olası bir kesintisinin azami süresi de DEĞİLDİR — yalnızca
leading-edge doğrulamasında kullanılan, gözlem/kanıt amaçlı bir tampondur
(observation/evidence buffer). Pre-roll bölgesinin TAMAMI da boş dönerse
(`LEADING_EDGE_UNVERIFIED`), bu GERÇEK bir yeni halka arz ile sağlayıcının
TÜM pre-roll penceresini kaybetmesi arasında HÂLÂ kesin bir ayrım YAPAMAZ —
bu, bilinçli olarak çözülmemiş, kabul edilmiş bir sınırlamadır (bkz.
TEKNIK_ANALIZ_METODOLOJISI.md).

Pre-roll barları HİÇBİR ZAMAN teknik göstergelere (RSI/MACD/EMA/.../Horizon
Classifier) girmez — yalnızca bu modüldeki "kanıt var mı" sorusuna cevap
verir. Skor her zaman yalnızca `analysis_start`'tan itibaren üretilir (bkz.
`engine.py`, `provider_history` → `analysis_history` ayrımı).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum

import pandas as pd
from dateutil.relativedelta import relativedelta

from app.services.market_data.completed_bars import resolve_now

# Canlı motorun kullandığı analiz penceresinin uzunluğu — yfinance'in
# `period="6mo"` davranışıyla GERÇEK ölçümle birebir eşleştiği doğrulanan
# takvim-ay semantiği (`relativedelta`), sabit 180 gün DEĞİL (25.08.2026'da
# ölçüldü: `now - relativedelta(months=6)` yfinance'in period="6mo" ile
# döndürdüğü ilk barla birebir aynı tarihi verdi; sabit 180/182 gün 1 gün
# farklı çıktı).
ANALYSIS_WINDOW_MONTHS = 6

# Bkz. modül docstring'i — CORRECTNESS GARANTİSİ DEĞİLDİR, Yahoo'nun olası
# bir kesintisinin azami süresi DEĞİLDİR. BIST'in 2025-2026 resmi
# takviminde ölçülen en uzun kesintisiz kapanış bloğu 5 takvim günüdür
# (27-31 Mayıs 2026, Kurban Bayramı); bu değer buna makul bir gözlem payı
# eklenerek seçilmiş, kolayca kalibre edilebilir bir sabittir.
PRE_ROLL_DAYS = 15


class HistoryValidationStatus(str, Enum):
    """`TechnicalAnalysis.history_validation_status` alanının olası değerleri."""

    VERIFIED_PRE_WINDOW = "VERIFIED_PRE_WINDOW"
    LEADING_EDGE_UNVERIFIED = "LEADING_EDGE_UNVERIFIED"


@dataclass
class HistoryWindow:
    analysis_start: date
    provider_request_start: date
    provider_request_end: date  # yfinance'te 'end' EXCLUSIVE'dir (ölçüldü)


def compute_history_window(now: datetime | None = None) -> HistoryWindow:
    """Analiz penceresi + pre-roll sınırlarını, `now`'a göre TEK bir yerde hesaplar."""
    now_ist = resolve_now(now)
    analysis_start = now_ist.date() - relativedelta(months=ANALYSIS_WINDOW_MONTHS)
    provider_request_start = analysis_start - timedelta(days=PRE_ROLL_DAYS)
    provider_request_end = now_ist.date() + timedelta(days=1)  # end exclusive -> bugünü kapsamak için +1
    return HistoryWindow(
        analysis_start=analysis_start,
        provider_request_start=provider_request_start,
        provider_request_end=provider_request_end,
    )


def resolve_expected_start(
    provider_history: pd.DataFrame, analysis_start: date
) -> tuple[date, HistoryValidationStatus]:
    """`provider_history` (pre-roll dahil, tamamlanmış barlarla) içinde
    `analysis_start`'tan ÖNCE en az bir bar var mı diye bakar.

    - VARSA: sembolün `analysis_start`'tan önce zaten işlem gördüğü
      KANITLANMIŞTIR — continuity kontrolü `analysis_start`'tan başlamalı
      (`VERIFIED_PRE_WINDOW`).
    - YOKSA: bu otomatik olarak "yeni halka arz" (PRE_LISTING) SAYILMAZ —
      gerçek yeni listing ile sağlayıcının TÜM pre-roll penceresini
      kaybetmesi AYIRT EDİLEMEZ. Durum `LEADING_EDGE_UNVERIFIED` olarak
      işaretlenir ve continuity kontrolü, sembolün GÖZLEMLENEN İLK barından
      itibaren başlar (`analysis_start`'tan sonraki gerçek boşluklar hâlâ
      HARD VETO'ya yol açar — yalnızca `analysis_start`'tan ÖNCESİ hiç
      sorgulanmaz).
    """
    if provider_history.empty:
        return analysis_start, HistoryValidationStatus.LEADING_EDGE_UNVERIFIED

    observed_dates = [ts.date() for ts in provider_history.index]
    first_observed = min(observed_dates)
    has_evidence = any(d < analysis_start for d in observed_dates)

    if has_evidence:
        return analysis_start, HistoryValidationStatus.VERIFIED_PRE_WINDOW
    return max(analysis_start, first_observed), HistoryValidationStatus.LEADING_EDGE_UNVERIFIED
