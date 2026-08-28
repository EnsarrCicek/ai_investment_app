"""TechnicalAnalysisEngine — ana doküman bölüm 5.

Kapsam notu: RSI, MACD, EMA trend (kesişim), Bollinger Bands, Momentum, ROC
ve EMA eğimi (AŞAMA 48/9) göstergeleri TechnicalScore'a doğrudan katkı
sağlar; ATR volatilite normalizasyonu için, Volume/Volume SMA ise yön değil
"doğrulama" (confidence) amacıyla kullanılır. ADX, Stochastic RSI ve rejim
tabanlı DİNAMİK ağırlıklandırma bu sürümde YOKTUR.

AŞAMA 48/15 — zenginleştirme katmanı: market_structure/support_resistance/
breakout/relative_volume/regime/gap_analysis/candlestick_patterns/
signal_classifier modülleri artık her analyze_with_id() çağrısında
hesaplanıp TechnicalAnalysis'e EK, AYRI alanlar (market_structure,
signal_class, nearest_support/resistance, breakout, vb.) olarak ekleniyor —
final_score/components hesaplamasını HİÇ ETKİLEMEZ, yalnızca UI'da
gösterilecek açıklayıcı bağlam sağlar. Bilinçli olarak DAHİL EDİLMEYEN:
VWAP/session_timing (intraday bar biriktirme altyapısı henüz otomatik
çalışmıyor, bkz. scripts/fetch_intraday_bars.py).

AŞAMA 48/17 — relative_strength eklendi: XU100'e göre göreli güç, ilk
sürümde "ek yfinance isteği N+1 sorununu geri getirir" gerekçesiyle bilinçli
olarak dışarıda bırakılmıştı. Çözüm: XU100'ün kapanış serisi TÜM semboller
için ortak olduğundan, benchmark_service.get_benchmark_close_series() bunu
technical_analyses ile aynı TTL'li (15 dk), TEK bir Firestore belgesinde
önbellekliyor — Dashboard'un 100 sembolünün ilkinde bir kez çekilir, geri
kalan 99'u önbellekten okur (yeniden N+1 istek oluşturmaz). Benchmark
fetch'i başarısız olursa (ValueError) relative_strength_class sessizce
"UNKNOWN" kalır — bu, tüm sembolün analizini düşürecek kritik bir hata
DEĞİLDİR (Missing Data Davranışı).

AŞAMA 48/18 — multi_timeframe eklendi: haftalık zaman dilimi, relative_
strength'in aksine sembole özeldir (paylaşılamaz) ama ek bir yfinance
isteği de GEREKTİRMEZ — multi_timeframe.resample_to_weekly_close(), zaten
çekilmiş günlük Close serisini haftalık kapanışlara indirger (pandas
resample, saf hesaplama). Günlük ve haftalık EMA eğimi yönü uyuşuyorsa
mtf_aligned=True olur. Bu, signal_classifier.classify_signal()'ın
STRONG_BULLISH_INITIATION dalını GERÇEKTEN ulaşılabilir hale getiriyor —
önceden mtf_aligned hep sabit False varsayıldığından bu en üst sınıf hiçbir
sembol için hiç tetiklenemiyordu.

AŞAMA 48/9 — RSI/MACD/Bollinger ağırlığı düşürüldü: TECHNICAL_ANALYSIS_
RESEARCH1.md, bu göstergelerin bağımsız birincil sürücü değil "doğrulama"
amaçlı kullanılmasını öneriyor (ör. RSI>70 tek başına SAT değildir — rejime
göre değişir). Tam rejim-bağımlı dinamik ağırlıklandırma henüz kalibre
edilmediğinden (regime.py bilinçli olarak henüz buraya bağlanmadı), bunun
yerine STATİK bir yeniden ağırlıklandırma yapıldı: RSI/MACD/Bollinger payı
azaltıldı, trend-takip eden bileşenler (trend, ema_slope, momentum, roc)
payı artırıldı; yeni "ema_slope" bileşeni eklendi (mevcut "trend" bileşeni
yalnızca anlık EMA20-EMA50 farkını alıyordu, zaman içindeki EĞİMİ değil).
Eski/yeni ağırlıklandırma BacktestEngine ile karşılaştırılarak doğrulandı
(bkz. KURULUM_GUNLUGU.md).

Ağırlık toplamı artık 1.0'a EŞİT OLMAK ZORUNDA DEĞİL: final_score, ağırlık
toplamına bölünerek normalize edilir (DecisionEngine'deki "Missing Data
Davranışı" ile aynı desen). Bu, Firestore'da önceden kaydedilmiş eski (6
anahtarlı) bir "technical_indicator_weights" belgesinin, yeni eklenen
"ema_slope" anahtarını distorse etmeden güvenle birleşebilmesini sağlar.

Performans (AŞAMA 44): analyze_with_id() her çağrıldığında yfinance'e taze
bir istek atardı — Dashboard tüm BIST100'ü (100 sembol) her açılışta yeniden
hesaplıyordu, bu da ~60-80 saniyelik yükleme süresine yol açıyordu. Şimdi
macro/news ile aynı ilke uygulanıyor: TECHNICAL_CACHE_TTL_SECONDS'tan daha
taze bir TechnicalAnalysis zaten Firestore'da varsa, yfinance'e HİÇ
gidilmeden o kayıt döner. BIST günlük bar kullandığından (gün içi anlık
tick değil), birkaç dakikalık bir gecikme kararın doğruluğunu etkilemez.
"""

from datetime import datetime, timezone

import pandas as pd

from app.engines.technical import indicators as ind
from app.engines.technical.breakout import BreakoutEvent
from app.engines.technical.breakout_timeline import build_breakout_timeline, select_live_breakout_event, to_legacy_breakout_event
from app.engines.technical.narrative import build_narrative
from app.engines.technical.candlestick_patterns import detect_patterns as detect_candlestick_patterns
from app.engines.technical.data_quality import check_data_quality, check_raw_ohlcv_integrity, check_trading_day_continuity
from app.engines.technical.gap_analysis import classify_gap, is_gap_filled, latest_gap
from app.engines.technical.horizon_classifier import HorizonInputs, classify_horizon, horizon_reason
from app.engines.technical.history_window import compute_history_window, resolve_expected_start
from app.engines.technical.scoring import aggregate_available_components, clamp_component, is_available, safe_ratio
from app.engines.technical.market_structure import analyze_market_structure
from app.services.market_data.completed_bars import filter_completed_daily_bars
from app.engines.technical.multi_timeframe import check_alignment, resample_to_weekly_close, timeframe_direction
from app.engines.technical.regime import (
    atr_percentile,
    classify_trend_regime,
    classify_volatility_regime,
    efficiency_ratio,
)
from app.engines.technical.relative_strength import (
    classify_relative_strength,
    relative_strength_ratio,
    relative_strength_score,
)
from app.engines.technical.relative_volume import classify_relative_volume, relative_volume_series
from app.engines.technical.signal_classifier import SignalInputs, classify_signal
from app.engines.technical.support_resistance import SRZone, build_zones, nearest_zone
from app.models.technical_analysis import TechnicalAnalysis
from app.repositories.benchmark_cache_repository import BenchmarkCacheRepository
from app.repositories.system_config_repository import SystemConfigRepository
from app.repositories.technical_analysis_repository import TechnicalAnalysisRepository
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.benchmark_service import get_benchmark_close_series
from app.services.market_data.bist_provider import BistProvider
from app.services.market_data.trading_calendar import normalize_bist_daily_sessions, session_normalization_to_dict

# 25.08.2026: 1.0.0 -> 1.1.0 — RSI hesaplaması gerçek Wilder yöntemine
# (SMA seed + recursive smoothing, warm-up=NaN) düzeltildi; aynı sembol/tarih
# için üretilen technical_score artık eskisinden (yaklaşık-Wilder/EWM) farklı
# olabilir. Eski kayıtlar (Firestore'daki immutable technical_analyses) HİÇ
# değiştirilmedi/silinmedi — yalnızca bu tarihten SONRA üretilecek yeni
# kayıtlar "1.1.0" taşıyacak, denetim izi (audit trail) bozulmadı.
#
# 25.08.2026: 1.1.0 -> 1.2.0 — HATA 2A: günlük teknik analiz artık yalnızca
# TAMAMLANMIŞ günlük barları kullanıyor (piyasa açıkken "bugünün" hâlâ
# oluşmakta olan/partial barı çıkarılıyor, bkz. completed_bars.py); haftalık
# MTF karşılaştırması da devam eden (henüz Cuma'sı gelmemiş) haftayı artık
# kullanmıyor. Piyasa açıkken üretilen technical_score, eskisinden (bugünün
# canlı fiyatını içeren) FARKLI olabilir — genellikle bir önceki tamamlanmış
# günün skorüne eşittir. Eski kayıtlar değiştirilmedi/silinmedi.
#
# 25.08.2026: 1.2.0 -> 1.3.0 — HATA 2B: BIST'in resmi işlem takvimine göre
# beklenen ama seride bulunmayan bir işlem günü varsa (bkz. data_quality.py,
# check_trading_day_continuity — ör. 24.08.2026'da tüm BIST100'ü etkileyen
# Yahoo veri boşluğu) artık analiz HİÇ ÜRETİLMEZ (HARD VETO) — eskiden bu
# durum hiç tespit edilmiyor, boşluk sessizce göz ardı ediliyordu. Bazı
# semboller için (gerçek bir boşluk sürdüğü sürece) `GET /decisions/{symbol}`
# ve `GET /analysis/{symbol}/technical` artık 422 dönebilir. Eski kayıtlar
# değiştirilmedi/silinmedi.
#
# 25.08.2026: 1.3.0 -> 1.4.0 — HATA 2C: `analysis_start`'tan (df.index[0])
# ÖNCEYE uzanan bir "pre-roll" penceresi artık her istekte AYRICA çekiliyor
# — yalnızca sembolün analysis_start'tan ÖNCE zaten işlem gördüğünü
# KANITLAMAK için (bkz. history_window.py); pre-roll barları göstergelere
# ASLA girmez. Pre-roll'da kanıt yoksa analiz artık otomatik veto edilmiyor
# (yeni yürürlüğe giren yanlış varsayım riski önlendi) — bunun yerine
# `history_validation_status="LEADING_EDGE_UNVERIFIED"` ile işaretlenip
# sembolün gözlemlenen ilk barından itibaren normal continuity kontrolüne
# tabi tutuluyor. Bu, bazı sembollerde (özellikle pre-roll penceresinde
# Yahoo'nun hiç veri döndürmediği durumlarda) `expected_start`'ı eskisinden
# daha ileri bir tarihe kaydırabilir — technical_score hesaplamasının
# GİRDİSİ (kaç günlük veri kullanıldığı) bu sembollerde değişebilir. Eski
# kayıtlar değiştirilmedi/silinmedi.
#
# 26.08.2026: 1.4.0 -> 1.5.0 — HATA 3D: authoritative BIST takvimine göre
# "expected session" OLMAYAN (hafta sonu/planlı tatil/olağanüstü kapanış/
# iptal edilmiş seans) hiçbir tarihteki provider barı — OHLC/Volume
# içeriğine BAKILMADAN — artık normalize aşamasında ÖNCEDEN düşürülüyor
# (bkz. `trading_calendar.normalize_bist_daily_sessions()`). Önceden bu
# barlar ya HATA 3C'nin `UNEXPECTED_TRADING_SESSION` kontrolüne takılıp
# analizi TAMAMEN veto ediyordu (ör. 27-29 Mayıs 2026 Kurban Bayramı'nda
# Yahoo'nun bireysel hisselerde döndürdüğü phantom barlar YÜZÜNDEN BIST100'ün
# TAMAMI HARD_VETO alıyordu) ya da (normalize edilmeden önce) sessizce
# göstergelere sızabiliyordu. Artık analiz, bu tarihler HİÇ VARMIŞ GİBİ,
# yalnızca gerçek completed session'lar üzerinden üretiliyor — bazı
# sembollerde bu, önceden HARD_VETO edilen bir analizin artık BAŞARIYLA
# üretilmesi VEYA technical_score'un girdisinin (kaç/hangi bar kullanıldığı)
# değişmesi anlamına gelebilir. Düşürülen her tarihin provenance'ı
# (`session_normalization_policy`/`normalized_dropped_sessions`) yeni,
# backward-compatible alanlarla sonuca şeffaf şekilde eklendi. Eski kayıtlar
# değiştirilmedi/silinmedi.
#
# 27.08.2026: 1.5.0 -> 1.6.0 — HATA 4B: `breakout` artık her çağrıda "bugün"e
# yeniden ankorlanan tek-anlık bir `detect_breakout()` kontrolü DEĞİL,
# stateless bir zaman çizelgesinden (`breakout_timeline.build_breakout_
# timeline()`) seçilen, `event_at`'ından itibaren en fazla 15 tamamlanmış
# seans boyunca "yaşayan" bir event'tir (bkz. breakout_timeline.py modül
# docstring'i). Kanıtlanan kök neden: eski çağrı deseni `confirm_breakout()`
# için gereken gelecek barları hiçbir zaman "bugün"ün ötesinde bulamadığından
# `breakout.confirmed` DAİMA `None` kalıyor, dolayısıyla `STRONG_BULLISH_
# INITIATION`/`notify_if_new_opportunity()` production'da asla erişilemiyordu
# (look-ahead LEAK değil, event lifecycle/state persistence eksikliği). Yeni
# alan: `breakout_event_id` (bildirim dedupe'u için, bkz. fcm_sender.py).
# `technical_score`/`components`/DecisionEngine hiç etkilenmedi (breakout
# hiçbir zaman skora girmiyordu, bkz. HATA 4A audit'i). Eski kayıtlar
# değiştirilmedi/silinmedi.
ENGINE_VERSION = "1.6.0"

DEFAULT_WEIGHTS = {
    "rsi": 0.10,
    "macd": 0.10,
    "trend": 0.15,
    "ema_slope": 0.20,
    "bollinger": 0.10,
    "momentum": 0.15,
    "roc": 0.20,
}

MIN_HISTORY_DAYS = 60
TECHNICAL_CACHE_TTL_SECONDS = 900  # 15 dakika


def _clamp(value: float, low: float = -100.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


# Grafikte çizilecek destek/direnç bölgesi sayısı — kullanıcı isteği: "grafikte
# nasıl dirençler var, nasıl çizgiler çiziyorsun" — tüm zone'ları değil,
# güncel fiyata en yakın olanları göstermek grafiği okunaklı tutar.
MAX_CHART_ZONES = 8


def _zone_to_dict(zone: SRZone | None) -> dict | None:
    if zone is None:
        return None
    return {
        "type": zone.type,
        "low": round(zone.low, 4),
        "high": round(zone.high, 4),
        "touch_count": zone.touch_count,
    }


def _breakout_to_dict(event: BreakoutEvent | None) -> dict | None:
    if event is None:
        return None
    return {
        "direction": event.direction,
        "breakout_atr": event.breakout_atr,
        "confirmed": event.confirmed,
        "retest_held": event.retest_held,
        "zone": _zone_to_dict(event.zone),
    }


def _compute_enrichment(
    df: pd.DataFrame,
    symbol: str,
    atr_val: float,
    close_val: float,
    final_score: float | None,
    provider: MarketDataProvider | None = None,
    benchmark_cache_repo: BenchmarkCacheRepository | None = None,
    now: datetime | None = None,
) -> dict:
    """market_structure/S-R/breakout/hacim/rejim/gap/mum/göreli güç/sinyal
    sınıfı katmanı — relative_strength dışındaki her şey, `analyze_with_id`'nin
    zaten çekmiş olduğu AYNI df üzerinden hesaplanır (ek bir yfinance isteği
    YOK). relative_strength ise önbelleklenmiş, paylaşılan bir XU100 serisi
    kullanır (bkz. modül docstring'i, AŞAMA 48/17).

    HATA 4B (27.08.2026): breakout artık `detect_breakout()`'un HER GÜN
    "bugün"e yeniden ankorladığı tek-anlık bir kontrol DEĞİL, stateless bir
    `build_breakout_timeline()` zaman çizelgesinden `select_live_breakout_event()`
    ile seçilen TEK event'tir — bu event, `event_at`'ından itibaren en fazla
    `MAX_EVENT_AGE_SESSIONS` boyunca (confirmation/retest lifecycle'ı boyunca)
    "bugün"ün breakout'u olarak yaşamaya devam eder (bkz. breakout_timeline.py
    modül docstring'i). Support/Resistance DISPLAY zone'ları (aşağıdaki
    `zones`/`support`/`resistance`/`chart_zones`) bundan ETKİLENMEZ — onlar
    hâlâ "bugün itibarıyla bilinen her şeyi" (ATR[T] dahil) kullanan bir anlık
    görüntüdür; yalnız BREAKOUT TESPİTİ kendi ayrı, T-1 ile sınırlı nedensel
    zone/ATR sözleşmesini kullanır.
    """
    close, volume = df["Close"], df["Volume"]

    structure_result = analyze_market_structure(df)
    zones = build_zones(structure_result["swing_points"], atr=atr_val)
    support = nearest_zone(zones, price=close_val, zone_type="SUPPORT")
    resistance = nearest_zone(zones, price=close_val, zone_type="RESISTANCE")

    timeline = build_breakout_timeline(df, symbol)
    live_event = select_live_breakout_event(timeline, today_index=len(df) - 1)
    breakout_event: BreakoutEvent | None = to_legacy_breakout_event(live_event)
    breakout_event_id = live_event.event_id if live_event is not None else None

    rv_series = relative_volume_series(volume)
    rv_ratio = rv_series.iloc[-1]
    rv_class = classify_relative_volume(rv_ratio)

    vol_percentile = atr_percentile(ind.atr(df)).iloc[-1]
    vol_regime = classify_volatility_regime(vol_percentile)
    er = efficiency_ratio(close).iloc[-1]
    trend_regime_val = classify_trend_regime(er)

    gap = latest_gap(df, atr=atr_val)
    filled = is_gap_filled(df)
    gap_class = classify_gap(gap, filled)

    candlestick = detect_candlestick_patterns(df)

    try:
        benchmark_close = get_benchmark_close_series(provider=provider, cache_repo=benchmark_cache_repo)
        asset_close_by_date = close.copy()
        asset_close_by_date.index = [ts.date() for ts in asset_close_by_date.index]
        rs_score = relative_strength_score(relative_strength_ratio(asset_close_by_date, benchmark_close))
    except ValueError:
        rs_score = None  # XU100 verisi geçici olarak alınamadı — sembolün asıl analizini düşürmez
    rs_class = classify_relative_strength(rs_score)

    daily_direction = timeframe_direction(close)
    weekly_close = resample_to_weekly_close(close, now=now)
    weekly_direction = timeframe_direction(weekly_close)
    alignment = check_alignment({"1d": daily_direction, "1wk": weekly_direction})

    # HATA 5B1 (27.08.2026): `technical_score` unavailable (`None`) olduğunda
    # `classify_signal()`/`classify_horizon()` sayısal threshold karşılaştırması
    # (`score >= 40` vb.) YAPAMAZ -- `None`'ı sahte bir "0"/"WATCHLIST"/
    # "BULLISH" sınıfına ÇEVİRMEK invented bir semantik olurdu. Bu iki alan
    # skorun kendisi kadar dürüst biçimde `None` kalır; breakout/market_
    # structure/relative_volume/relative_strength/mtf_alignment gibi
    # technical_score'dan BAĞIMSIZ enrichment alanları ETKİLENMEZ (aşağıda
    # DEĞİŞMEDEN hesaplanmaya devam eder).
    if final_score is not None:
        signal_inputs = SignalInputs(
            technical_score=final_score,
            market_structure=structure_result["structure"],
            breakout_event=breakout_event,
            relative_volume_class=rv_class,
            relative_strength_class=rs_class,
            mtf_aligned=alignment["aligned"],
            mtf_consensus=alignment["consensus"],
        )
        signal_class = classify_signal(signal_inputs)

        horizon_inputs = HorizonInputs(
            signal_class=signal_class,
            market_structure=structure_result["structure"],
            trend_regime=trend_regime_val,
            relative_strength_class=rs_class,
            mtf_aligned=alignment["aligned"],
            mtf_consensus=alignment["consensus"],
        )
        investment_horizon = classify_horizon(horizon_inputs)
        investment_horizon_reason = horizon_reason(investment_horizon, horizon_inputs)
    else:
        signal_class = None
        investment_horizon = None
        investment_horizon_reason = ""

    nearest_support_dict = _zone_to_dict(support)
    nearest_resistance_dict = _zone_to_dict(resistance)
    breakout_dict = _breakout_to_dict(breakout_event)

    chart_zones = sorted(zones, key=lambda z: abs(z.mid - close_val))[:MAX_CHART_ZONES]

    return {
        "market_structure": structure_result["structure"],
        "signal_class": signal_class,
        "investment_horizon": investment_horizon,
        "investment_horizon_reason": investment_horizon_reason,
        "relative_volume_class": rv_class,
        "relative_strength_class": rs_class,
        "volatility_regime": vol_regime,
        "trend_regime": trend_regime_val,
        "gap_class": gap_class,
        "candlestick_patterns": candlestick,
        "nearest_support": nearest_support_dict,
        "nearest_resistance": nearest_resistance_dict,
        "breakout": breakout_dict,
        "breakout_event_id": breakout_event_id,
        "all_zones": [_zone_to_dict(z) for z in chart_zones],
        "narrative": build_narrative(nearest_support_dict, nearest_resistance_dict, breakout_dict),
        "mtf_aligned": alignment["aligned"],
        "mtf_consensus": alignment["consensus"],
    }


class TechnicalAnalysisEngine:
    def __init__(
        self,
        provider: MarketDataProvider | None = None,
        config_repo: SystemConfigRepository | None = None,
        analysis_repo: TechnicalAnalysisRepository | None = None,
        benchmark_cache_repo: BenchmarkCacheRepository | None = None,
    ):
        self._provider = provider or BistProvider()
        self._config_repo = config_repo or SystemConfigRepository()
        self._analysis_repo = analysis_repo or TechnicalAnalysisRepository()
        self._benchmark_cache_repo = benchmark_cache_repo or BenchmarkCacheRepository()

    def analyze(self, symbol: str, persist: bool = True) -> TechnicalAnalysis:
        analysis, _doc_id = self.analyze_with_id(symbol, persist=persist)
        return analysis

    def analyze_with_id(
        self,
        symbol: str,
        persist: bool = True,
        max_age_seconds: int = TECHNICAL_CACHE_TTL_SECONDS,
        now: datetime | None = None,
    ) -> tuple[TechnicalAnalysis, str | None]:
        cached, cached_id = self._analysis_repo.get_latest_with_id(symbol)
        if cached is not None:
            age = (datetime.now(timezone.utc) - cached.created_at).total_seconds()
            if age < max_age_seconds:
                return cached, cached_id

        # HATA 2C (25.08.2026): analiz penceresinden (analysis_start) BİRAZ
        # daha ÖNCESİNİ ("pre-roll") de kapsayan TEK bir geniş istek yapılır
        # — pre-roll, sembolün analysis_start'tan ÖNCE zaten işlem gördüğünü
        # KANITLAMAK içindir, göstergelere ASLA girmez (bkz. history_window.py).
        history_window = compute_history_window(now)
        provider_history = self._provider.get_history(
            symbol,
            start=history_window.provider_request_start.isoformat(),
            end=history_window.provider_request_end.isoformat(),
        )
        # HATA 2A (25.08.2026): piyasa açıkken "bugün" satırı hâlâ oluşuyor
        # olabilir (developing/partial bar) — günlük teknik analiz yalnızca
        # TAMAMLANMIŞ barlarla üretilir (bkz. services/market_data/completed_bars.py).
        provider_history = filter_completed_daily_bars(provider_history, now=now)

        # HATA 3D (26.08.2026): authoritative takvime göre "expected session"
        # OLMAYAN (hafta sonu/planlı tatil/olağanüstü kapanış/iptal edilmiş
        # seans) hiçbir tarihteki bar — OHLC/Volume içeriğine BAKILMADAN —
        # düşürülür (ör. 27-29 Mayıs 2026 Kurban Bayramı'nda Yahoo'nun
        # bireysel hisselerde döndürdüğü, Open=High=Low=Close=önceki kapanış
        # + Volume=0 "phantom" barlar — BIST100'ün TAMAMINDA gözlemlendi).
        # KRİTİK SIRALAMA: bu adım `resolve_expected_start()`'TAN (aşağıda)
        # ÖNCE çalışmalı — aksi halde pre-roll bölgesine denk gelen bir
        # phantom bar, sembolün gerçekten `analysis_start`'tan önce işlem
        # gördüğüne dair SAHTE bir "kanıt" (VERIFIED_PRE_WINDOW) üretebilirdi.
        provider_history, session_normalization_result = normalize_bist_daily_sessions(
            provider_history, symbol=symbol, provider="yahoo_finance"
        )

        # Pre-roll bölgesinde en az bir bar varsa (analysis_start'tan ÖNCE),
        # sembolün zaten işlem gördüğü KANITLANMIŞTIR (VERIFIED_PRE_WINDOW) —
        # continuity kontrolü analysis_start'tan başlar. Yoksa (LEADING_EDGE_
        # UNVERIFIED) ne "PRE_LISTING" varsayılır ne otomatik HARD VETO
        # uygulanır — yalnızca sembolün gözlemlenen ilk barından itibaren
        # kontrol edilir (o tarihten SONRAKİ gerçek boşluklar hâlâ veto sebebidir).
        expected_start, validation_status = resolve_expected_start(provider_history, history_window.analysis_start)

        # HATA 2B (25.08.2026): "bugünü çıkar" yeterli değil — serinin
        # İÇİNDE de BIST'in resmi takvimine göre beklenen ama Yahoo'da
        # bulunmayan bir işlem günü olabilir (bkz. 24.08.2026 örneği, tüm
        # BIST100'ü aynı anda etkiledi). Böyle bir boşluk varsa, RSI/MACD/
        # EMA gibi recursive göstergeler sessizce yanlış bir "N gün önce"
        # referansı kullanacağından, eksik veri UYDURULMAZ/yoksayılmaz —
        # analiz hiç ÜRETİLMEZ (HARD VETO).
        check_trading_day_continuity(provider_history, symbol, now=now, expected_start=expected_start)

        # Pre-roll barları ASLA göstergelere girmez — skorlama yalnızca
        # analysis_start'tan itibaren çalışır. `MIN_HISTORY_DAYS` kontrolü de
        # BİLİNÇLİ OLARAK bu kırpılmış seri üzerinde yapılır (pre-roll'un
        # kendisi minimum-geçmiş şartını "sahte" karşılamasın diye).
        df = provider_history[provider_history.index.date >= expected_start]

        # HATA 5B1 (27.08.2026) — LAYER 1: mandatory analiz penceresi İÇİNDE
        # (yalnızca son bar DEĞİL) NaN/±inf/geçersiz fiyat/negatif hacim/
        # imkânsız OHLC ilişkisi varsa HARD VETO — component-seviyesi
        # "unavailable" renormalizasyonu (aşağıda) bozuk market datayı ASLA
        # gizlemez. Pre-roll bu kontrolün DIŞINDA kalır (`df` zaten yalnızca
        # `expected_start` ve SONRASINI içerir).
        check_raw_ohlcv_integrity(df, symbol)
        check_data_quality(df, symbol, min_history_days=MIN_HISTORY_DAYS, now=now)

        weights = self._config_repo.get("technical_indicator_weights", DEFAULT_WEIGHTS)

        close, volume = df["Close"], df["Volume"]

        rsi_val = float(ind.rsi(close).iloc[-1])
        _, _, macd_hist = ind.macd(close)
        macd_hist_val = float(macd_hist.iloc[-1])
        ema_short_val = float(ind.ema(close, 20).iloc[-1])
        ema_long_val = float(ind.ema(close, 50).iloc[-1])
        ema_slope_val = float(ind.ema_slope(close, window=20, slope_lookback=5).iloc[-1])
        upper, middle, lower = ind.bollinger_bands(close)
        upper_val, middle_val, lower_val = float(upper.iloc[-1]), float(middle.iloc[-1]), float(lower.iloc[-1])
        atr_val = float(ind.atr(df).iloc[-1])
        momentum_val = float(ind.momentum(close).iloc[-1])
        roc_val = float(ind.roc(close).iloc[-1])
        volume_sma_val = float(ind.volume_sma(volume).iloc[-1])
        current_volume = float(volume.iloc[-1])
        close_val = float(close.iloc[-1])

        band_width = upper_val - middle_val

        # HATA 5B1 (27.08.2026): eski `if atr_val else 0.0` deseni yalnızca
        # LİTERAL sıfır paydayı yakalıyordu — NaN Python'da TRUTHY olduğundan
        # (`bool(float('nan'))==True`) bu guard NaN'ı HİÇ yakalamıyordu, sonuç
        # `_clamp(nan)` (Python `max`/`min`'in NaN karşılaştırma davranışı
        # nedeniyle) DETERMİNİSTİK olarak `+100.0` oluyordu — eksik bir
        # component sahte bir "maksimum bullish" sinyaline dönüşüyordu.
        # `safe_ratio()`/`clamp_component()` (bkz. `scoring.py`) hem NaN hem
        # `x/0` hem `0/0` durumunu AYNI, tutarlı NaN sonucuna götürür; RSI'ın
        # düz-seri `50.0`'ı (component `0.0`) `indicators.rsi()`'ın KENDİ
        # kasıtlı tanımıdır — GERÇEK bir geçerli sıfırdır, bu değişiklikten
        # ETKİLENMEZ. Component formülleri/skala katsayıları (25/1000/15/
        # 100/20/8) HİÇ DEĞİŞMEDİ.
        raw_components = {
            "rsi": (rsi_val - 50) * 2,
            "macd": safe_ratio(macd_hist_val, atr_val) * 25,
            "trend": safe_ratio(ema_short_val - ema_long_val, ema_long_val) * 1000,
            "ema_slope": ema_slope_val * 15,
            "bollinger": safe_ratio(close_val - middle_val, band_width) * 100,
            "momentum": safe_ratio(momentum_val, atr_val) * 20,
            "roc": roc_val * 8,
        }
        components = {k: clamp_component(v) for k, v in raw_components.items()}

        # HATA 5B1: yalnız AVAILABLE (finite) component'ler üzerinden
        # ağırlıklı ortalama, KALAN mevcut ağırlıklar renormalize edilerek
        # (bkz. `scoring.aggregate_available_components`). Hiçbir component
        # available değilse `final_score=None` — `0.0`/`100.0` UYDURULMAZ.
        final_score = aggregate_available_components(components, weights)

        # Firestore'a/API'ye giden `components` dict'i unavailable component'leri
        # OMIT eder (None/NaN sentinel TUTMAZ) — hem "bu component için skor
        # yok" anlamını en dürüst şekilde taşır hem de downstream tüketicilerde
        # (ör. ExplanationEngine._top_reasons'ın `abs()` çağrısı) bir sentinel
        # değer nedeniyle crash riski oluşturmaz.
        stored_components = {k: v for k, v in components.items() if is_available(v)}

        if final_score is None:
            # Tüm 7 component birden unavailable — son derece nadir (HATA 5B1
            # audit'i: gerçek 5-sembol/2-yıl veri setinde 0 gözlem), ama
            # skor-bağımlı türetilmiş alanlar (confidence/trend) sahte bir
            # sayı UYDURMAZ. FINAL PRE-COMMIT GATE (27.08.2026, madde 2):
            # `trend="NEUTRAL"` da bir UYDURMAdır -- NEUTRAL, skorun
            # HESAPLANDIĞI ama [-15, 15] aralığında kaldığı GERÇEK bir teknik
            # yön bilgisidir; skor hiç hesaplanamadığında `trend=None` (bkz.
            # models/technical_analysis.py, `trend: str | None`).
            confidence = 0.0
            trend = None
        else:
            agreement = (
                sum(1 for s in stored_components.values() if (s >= 0) == (final_score >= 0)) / len(stored_components)
                if stored_components
                else 0.0
            )
            volume_confirmation = min(current_volume / volume_sma_val, 2.0) / 2.0 if volume_sma_val else 0.5
            confidence = round(_clamp(0.4 + 0.4 * agreement + 0.2 * volume_confirmation, 0.0, 1.0), 2)
            trend = "BULLISH" if final_score > 15 else "BEARISH" if final_score < -15 else "NEUTRAL"

        enrichment = _compute_enrichment(
            df,
            symbol,
            atr_val,
            close_val,
            final_score,
            provider=self._provider,
            benchmark_cache_repo=self._benchmark_cache_repo,
            now=now,
        )

        analysis = TechnicalAnalysis(
            asset=symbol,
            technical_score=final_score,
            trend=trend,
            confidence=confidence,
            components=stored_components,
            market_data_as_of=df.index[-1].to_pydatetime(),
            history_validation_status=validation_status.value,
            **session_normalization_to_dict(session_normalization_result),
            **enrichment,
            indicators={
                "rsi": round(rsi_val, 2),
                "macd_histogram": round(macd_hist_val, 4),
                "ema_20": round(ema_short_val, 2),
                "ema_50": round(ema_long_val, 2),
                "ema_slope": round(ema_slope_val, 4),
                "bollinger_upper": round(upper_val, 2),
                "bollinger_middle": round(middle_val, 2),
                "bollinger_lower": round(lower_val, 2),
                "atr": round(atr_val, 4),
                "momentum": round(momentum_val, 4),
                "roc": round(roc_val, 4),
                "volume": int(current_volume),
                "volume_sma": round(volume_sma_val, 2),
            },
            created_at=datetime.now(timezone.utc),
            engine_version=ENGINE_VERSION,
        )

        doc_id = self._analysis_repo.add(analysis) if persist else None
        return analysis, doc_id
