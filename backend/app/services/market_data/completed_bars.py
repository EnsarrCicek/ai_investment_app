"""Tamamlanmış günlük bar sözleşmesi — HATA 2/2A denetimi (25.08.2026).

Kanıtlanmış sorun: `BistProvider.get_history(..., interval="1d")`, piyasa
açıkken "bugünü" SON SATIR olarak, hâlâ değişen/gelişen (developing/partial)
bir OHLCV bar olarak döner (bkz. TEKNIK_ANALIZ_METODOLOJISI.md ve HATA-2
denetim raporu — aynı `bar_date` için Close/High/Volume'un dakikalar
içinde değiştiği canlı ölçümle gösterildi). `TechnicalAnalysisEngine`'in
GÜNLÜK skoru yalnızca tamamlanmış barlarla üretilmeli — bu modül, bu
filtreyi TEK bir yerde (veri katmanında) uygular; `BacktestEngine` buna
BİLİNÇLİ olarak dokunmaz (kendi tarihsel davranışı zaten çoğunlukla
tamamlanmış barlarla çalışıyor, bkz. denetim raporu madde 3).

Piyasa kapandıktan hemen sonra Yahoo'nun günlük barı "settle" etmesi bir
miktar zaman alabilir (tıpkı gün-içi quote'un ~15-20 dk gecikmeli olması
gibi, bu projede birden fazla kez ölçüldü — bkz. HATA-2 denetimi ve
"fiyat analizi anlık gelmiyor" görüşmesi, 25.08.2026). Bu YÜZDEN kapanış
saatine (18:00) körü körüne bir "clock >= 18:00" kuralı UYGULANMAZ — ek bir
güvenlik payı (`DAILY_BAR_FINALIZATION_DELAY_MINUTES`) eklenir. Bu payın
KENDİSİ (Yahoo'nun günlük barı kapanıştan tam olarak kaç dakika sonra
settle ettiği) doğrudan ÖLÇÜLMEDİ — bunun ölçülmesi ancak gerçek bir
kapanış anını kapsayan bir oturumda mümkündür. Değer, projede tekrar tekrar
gözlenen ~20 dk'lık canlı veri gecikmesine makul bir güvenlik payı eklenerek
seçildi ve BİLİNÇLİ olarak kolayca kalibre edilebilir bir sabit olarak
bırakıldı.

Bilinen, kabul edilmiş sınırlamalar (holiday/half-day takvimi entegre
DEĞİL — projenin "uydurma veri kullanma" ilkesiyle tutarlı: güvenilir,
ücretsiz bir BIST tatil/yarım gün takvimi kaynağı yok):
- Yarım gün (ör. bayram arifesi erken kapanış): bar aslında zamanından önce
  tamamlanmış olsa bile, bu modül yine de standart kapanış+gecikme payına
  kadar bekler — GÜVENLİ yönde bir hata (bir günlük bar bir süre daha
  "tamamlanmamış" sayılır, asla yanlışlıkla erken "tamamlanmış" sayılmaz).
- Resmi tatil: Yahoo o gün için zaten hiç satır döndürmeyeceğinden bu
  modülün hiçbir etkisi olmaz (son satır zaten "bugün" değil).
"""

from datetime import date, datetime, timedelta

import pandas as pd

from app.engines.technical.session_timing import ISTANBUL_TZ, SESSION_CLOSE

# Bkz. modül docstring'i — Yahoo'nun kendi ~20 dk'lık canlı veri gecikmesine
# (defalarca ölçüldü) güvenlik payı eklenerek seçildi; kapanıştan SONRA
# günlük barın "settle" olması için gereken gerçek süre AYRICA ölçülmedi.
DAILY_BAR_FINALIZATION_DELAY_MINUTES = 30


def _to_istanbul(ts) -> datetime:
    if ts.tzinfo is None:
        return ts.tz_localize(ISTANBUL_TZ) if hasattr(ts, "tz_localize") else ts.replace(tzinfo=ISTANBUL_TZ)
    return ts.astimezone(ISTANBUL_TZ)


def resolve_now(now: datetime | None) -> datetime:
    """HATA 2C (25.08.2026): `completed_bars.py`, `data_quality.py` ve
    `history_window.py`'nin HEPSİNİN "şu an" için AYNI, Europe/Istanbul
    saatine göre çözümlenmiş referansı kullanmasını sağlayan tek nokta —
    tarih/saat mantığının üç ayrı yerde birbirinden habersiz tekrarlanıp
    zamanla birbirinden sapmasını önler."""
    return _to_istanbul(now) if now is not None else datetime.now(ISTANBUL_TZ)


def latest_expected_completed_date(now: datetime | None = None) -> date:
    """Şu ana göre TAMAMLANMIŞ kabul edilmesi gereken EN SON takvim gününü
    döner — bugünün kapanış (18:00 TSİ) + finalization payı geçtiyse BUGÜN,
    geçmediyse DÜN.

    Bu sınır, `filter_completed_daily_bars()` (hangi satırın çıkarılacağı)
    VE `data_quality.check_trading_day_continuity()` (süreklilik kontrolünün
    ne kadar İLERİYE bakması gerektiği) tarafından PAYLAŞILIR — HATA 2B
    denetiminde bulunan bir hatayı önlemek için: eğer continuity kontrolü
    yalnızca `df.index[-1]`'e (filtre SONRASI son satıra) bakıyorsa, "bugün"
    çıkarıldığında kontrol aralığının üst sınırı da geri çekilir ve tam da
    bugünden hemen önceki gerçek bir boşluk (ör. 24.08.2026) görünmez hale
    gelirdi. Bu fonksiyonu paylaşarak iki modül de "ne kadar ileriye kadar
    veri BEKLİYORUZ" sorusuna aynı, `df`'in kendisinden BAĞIMSIZ cevabı verir.
    """
    now = resolve_now(now)
    finalization_cutoff = now.replace(
        hour=SESSION_CLOSE.hour, minute=SESSION_CLOSE.minute, second=0, microsecond=0
    ) + timedelta(minutes=DAILY_BAR_FINALIZATION_DELAY_MINUTES)

    if now >= finalization_cutoff:
        return now.date()
    return now.date() - timedelta(days=1)


def filter_completed_daily_bars(df: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """Piyasa açıkken (veya kapanıştan itibaren finalization payı dolmadan)
    oluşan, henüz tamamlanmamış "bugünkü" günlük barı çıkarır.

    - `df`'in son satırı BUGÜNE ait DEĞİLSE (hafta sonu, resmi tatil, ya da
      zaten tamamlanmış bir önceki günse) dokunulmaz.
    - `df`'in son satırı bugüne aitse VE `now`, o günün kapanış saati
      (18:00 TSİ) + `DAILY_BAR_FINALIZATION_DELAY_MINUTES`'i henüz
      geçmediyse, o satır ÇIKARILIR (henüz oluşuyor).
    - Aksi halde (kapanış + gecikme payı geçtiyse) son satır tamamlanmış
      kabul edilip KORUNUR.
    """
    if df.empty:
        return df

    now_ist = resolve_now(now)
    last_bar_date = _to_istanbul(df.index[-1])

    if last_bar_date.date() != now_ist.date():
        return df

    if last_bar_date.date() <= latest_expected_completed_date(now):
        return df

    return df.iloc[:-1]
