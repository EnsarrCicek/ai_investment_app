"""Çoklu zaman dilimi uyumu (multi-timeframe alignment) —
TECHNICAL_ANALYSIS_RESEARCH1.md, rapor madde 7, adım 11.

Tek bir zaman diliminde (günlük bar) "yükseliş" görünen bir sinyal, daha
büyük resimde (haftalık) hâlâ bir düşüş trendinin içindeki geçici bir
toparlanma olabilir. Bu modül, aynı varlığın farklı zaman dilimlerindeki
(interval) EMA eğimi yönlerini karşılaştırıp bir "uyum" (alignment) sonucu
üretir — BistProvider.get_history zaten `interval` parametresini destekliyor
(bkz. base.py), bunun için yeni bir provider metoduna gerek yoktur; bu modül
yalnızca zaten çekilmiş Close serileri üzerinde çalışır (tek sorumluluk).

Kapsam notu: Yalnızca yön (pozitif/negatif/nötr) karşılaştırılır, büyüklük
değil — farklı zaman dilimlerindeki EMA eğimi büyüklükleri doğrudan
karşılaştırılabilir değildir (farklı bar sıklığı, farklı volatilite ölçeği).

AŞAMA 48/18 — haftalık zaman dilimi ayrı bir yfinance isteği GEREKTİRMEZ:
`resample_to_weekly_close()`, TechnicalAnalysisEngine'in zaten çekmiş olduğu
günlük Close serisini haftalık kapanışlara indirger (pandas `resample`,
saf hesaplama). Bu, relative_strength.py'de XU100 için çözülen N+1 istek
sorununun farklı bir çözümü — orada seri semboller arasında PAYLAŞILABİLDİĞİ
için önbelleklendi, burada ise zaten elde olan veriden TÜRETİLEBİLDİĞİ için
hiç yeni istek gerekmiyor.

HATA 2A düzeltmesi (25.08.2026): Girdi artık yalnızca TAMAMLANMIŞ günlük
barlardan oluşsa bile (bkz. `services/market_data/completed_bars.py`),
`resample("W").last()` devam eden bir haftayı da "o haftanın kapanışı" gibi
göstermeye devam eder — çünkü resample yalnızca ELİNDEKİ son günü kullanır,
o günün gerçekten haftanın SON beklenen BIST işlem günü olup olmadığını
bilmez. `resample_to_weekly_close()` bu yüzden son haftalık bar'ın gerçekten
tamamlanmış olup olmadığını AYRICA kontrol edip, değilse düşürür (bkz.
`_is_last_week_complete`). HATA 10E (03.09.2026): "tamamlanmış hafta" artık
takvim Cuma'sı DEĞİL, authoritative BIST takviminin o haftanın SON beklenen
işlem günü olarak döndürdüğü tarihtir (bkz. `trading_calendar.
last_expected_trading_session_of_week()`) — Cuma resmi tatilse bu daha erken
bir gün olabilir.
"""

from datetime import datetime

import pandas as pd

from app.engines.technical.indicators import ema_slope
from app.engines.technical.session_timing import ISTANBUL_TZ
from app.services.market_data.trading_calendar import last_expected_trading_session_of_week

DEFAULT_TIMEFRAMES = ("1d", "1wk")

# HATA 10D (03.09.2026): `timeframe_direction()`'ın kendisi `window=20,
# slope_lookback=5` ile yalnızca 6 gözlemden (slope_lookback+1) sonra
# matematiksel olarak hesaplanabilir hale gelir -- bu, "hesaplanabilir" ile
# "istatistiksel olarak olgun" arasındaki farkı GÖRMEZDEN GELİR (bkz. HATA
# 10/10A/10B/10C audit'leri). Haftalık zaman dilimi için bu özellikle
# önemlidir: prodüksiyon her analizde göstergeleri YALNIZCA son ~6 takvim
# ayından besler (pre-roll asla göstergelere girmez, bkz. history_window.py)
# -- yeni/kısa geçmişli bir sembol, `MIN_HISTORY_DAYS=60` (~12 tamamlanmış
# hafta) ile motora girip HİÇBİR UNKNOWN'a düşmeden UP/DOWN/FLAT üretebilir,
# gerçek tarihsel veride (HATA 10A/10C) bunun ciddi (%0.6-2.5) ters-yön
# (UP<->DOWN) uyuşmazlığına yol açtığı KANITLANDI. `min_observations`,
# KİLİTLİ, formül-türevli bir UYGUNLUK SÖZLEŞMESİDİR -- "gerçek EMA
# olgunluğu" veya "tam-geçmiş EMA ile yakınsama garantisi" İDDİA ETMEZ
# (HATA 10C, madde 2: W26 tam da bu nedenle KASITLI OLARAK reddedildi --
# doğrulama örnekleminin SON gözlemlenen karşı-örneğini elemek için
# seçilmiş, formülden bağımsız bir eşik olurdu). `None` (varsayılan)
# iken fonksiyonun ESKİ davranışı (6 gözlemden itibaren hesaplanabilir)
# TAMAMEN KORUNUR -- günlük çağrı (`engine.py`) bu parametreyi HİÇ
# vermez, yalnızca haftalık çağrı verir.
WEEKLY_DIRECTION_MIN_OBSERVATIONS = 25  # = EMA window(20) + slope_lookback(5)


def _is_last_week_complete(last_bar_date: pd.Timestamp, now: datetime) -> bool:
    """Girdi serisinin SON gününün ait olduğu hafta gerçekten bitti mi?

    HATA 10E (03.09.2026): tamamlanmış hafta artık "Cuma" DEĞİL, o ISO
    haftanın authoritative takvimdeki (`last_expected_trading_session_of_
    week()`) SON BEKLENEN BIST işlem günü ile tanımlanır -- Cuma'nın resmi
    tatil olduğu haftalarda bu Perşembe (hatta çok günlü kapanışlarda daha
    erken bir gün) olabilir.

    Kural: `last_bar_date`, `now`'dan FARKLI bir ISO haftadaysa (artık
    kesin geçmişte kalmış bir hafta) tamamlanmış sayılır -- bu haftanın
    İÇİNDE beklenen ama eksik bir gün olup olmadığı bu fonksiyonun değil,
    yukarı akıştaki `check_trading_day_continuity()`'nin sorumluluğudur.
    AYNI ISO haftadaysa, hafta ancak `last_bar_date` o haftanın SON
    beklenen işlem gününün TA KENDİSİYSE tamamlanmış sayılır -- takvim o
    hafta için hiçbir beklenen gün DÖNMEZSE (`None`, desteklenmeyen yıl
    veya gerçekten sıfır seans) "tamamlanmış" SONUCU ÇIKARILMAZ (muhafazakar/
    eksik kalır, sessizce bir varsayım/ikinci takvim YÜRÜTÜLMEZ).
    """
    if last_bar_date.isocalendar()[:2] != now.isocalendar()[:2]:
        return True
    final_expected = last_expected_trading_session_of_week(last_bar_date.date())
    if final_expected is None:
        return False
    return last_bar_date.date() == final_expected


def _direction(slope_value: float, neutral_band: float = 0.5) -> str:
    if pd.isna(slope_value):
        return "UNKNOWN"
    if slope_value > neutral_band:
        return "UP"
    if slope_value < -neutral_band:
        return "DOWN"
    return "FLAT"


def resample_to_weekly_close(daily_close: pd.Series, now: datetime | None = None) -> pd.Series:
    """Günlük kapanış serisini haftalık kapanışlara indirger (her haftanın
    son işlem günü) — ek bir yfinance isteği olmadan, zaten çekilmiş günlük
    veriden haftalık zaman dilimini türetir.

    Son haftalık bar, girdinin SON gününün haftası henüz bitmediyse (bkz.
    `_is_last_week_complete`) düşürülür — aksi halde "bu hafta" devam
    ediyorken bile tamamlanmış bir haftalık kapanışmış gibi kullanılırdı.
    """
    weekly = daily_close.resample("W").last().dropna()
    if weekly.empty or daily_close.empty:
        return weekly

    last_bar_date = daily_close.index[-1]
    if last_bar_date.tzinfo is None:
        last_bar_date = last_bar_date.tz_localize(ISTANBUL_TZ)
    else:
        last_bar_date = last_bar_date.astimezone(ISTANBUL_TZ)

    reference_now = now or datetime.now(ISTANBUL_TZ)
    reference_now = reference_now.astimezone(ISTANBUL_TZ) if reference_now.tzinfo else reference_now.replace(tzinfo=ISTANBUL_TZ)

    if not _is_last_week_complete(last_bar_date, reference_now):
        weekly = weekly.iloc[:-1]
    return weekly


def timeframe_direction(
    close: pd.Series,
    window: int = 20,
    slope_lookback: int = 5,
    min_observations: int | None = None,
) -> str:
    """Tek bir zaman dilimi için EMA eğimi yönü (UP/DOWN/FLAT/UNKNOWN).

    `min_observations` (HATA 10D, varsayılan `None`): verilirse ve
    `len(close) < min_observations` ise, slope MATEMATİKSEL OLARAK
    hesaplanabilir olsa BİLE `UNKNOWN` döner -- bkz. modül içindeki
    `WEEKLY_DIRECTION_MIN_OBSERVATIONS` yorumu. `None` iken davranış HİÇ
    DEĞİŞMEDEN eski haliyle kalır (yalnızca `slope` gerçekten NaN/boşsa
    `UNKNOWN`).
    """
    if min_observations is not None and len(close) < min_observations:
        return "UNKNOWN"
    slope = ema_slope(close, window=window, slope_lookback=slope_lookback)
    if slope.empty or pd.isna(slope.iloc[-1]):
        return "UNKNOWN"
    return _direction(float(slope.iloc[-1]))


def check_alignment(directions: dict[str, str]) -> dict:
    """Farklı zaman dilimlerindeki yönleri karşılaştırıp genel bir uyum sonucu üretir.

    - Configured TÜM zaman dilimleri aynı yöndeyse (UP ya da DOWN): aligned=True.
    - UP ve DOWN bir arada varsa: "CONFLICTING" (en riskli durum — sinyal
      zaman dilimine göre çelişiyor).
    - Diğer karışık durumlar (ör. UP+FLAT): "MIXED".

    HATA 7C-FIX (01.09.2026): configured zaman dilimlerinden HERHANGİ BİRİ
    "UNKNOWN" ise (yalnızca TÜMÜ UNKNOWN olduğunda DEĞİL) `aligned=False`,
    `consensus="UNKNOWN"` döner — eski sürüm UNKNOWN olan zaman dilimini
    SESSİZCE eleyip kalan TEK bilinen zaman dilimini "uyumlu" sayıyordu
    (ör. `{"1d":"UP","1wk":"UNKNOWN"}` → `aligned=True, consensus="UP"`),
    bu da dokümantasyonun ("günlük VE haftalık yönü karşılaştırılır, ikisi
    de aynı yöndeyse uyumlu") iddia ettiği İKİ-taraflı karşılaştırmayı
    tek-taraflı bir varsayıma indirgiyordu — eksik kanıtı (missing evidence)
    sessizce "tam uyum" gibi sunan bir HATA 5B1-tarzı ihlaldi. `investment_
    horizon`/`signal_class` (ör. STRONG_BULLISH_INITIATION, UZUN_VADELI) bu
    dejenere "uyum"u gerçek çift-zaman-dilimi teyidiyle AYIRT EDEMİYORDU.
    UNKNOWN, ne DOWN'a ne FLAT'e forward-fill EDİLMEZ — yalnızca "MTF
    kanıtı eksik, uyum/consensus İDDİA EDİLEMEZ" anlamına gelir.
    """
    if any(direction == "UNKNOWN" for direction in directions.values()):
        return {"aligned": False, "consensus": "UNKNOWN", "directions": directions}

    unique = set(directions.values())
    if len(unique) == 1:
        consensus = next(iter(unique))
        return {"aligned": consensus in ("UP", "DOWN"), "consensus": consensus, "directions": directions}

    if "UP" in unique and "DOWN" in unique:
        return {"aligned": False, "consensus": "CONFLICTING", "directions": directions}

    return {"aligned": False, "consensus": "MIXED", "directions": directions}
