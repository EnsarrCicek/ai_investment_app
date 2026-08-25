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
from app.engines.technical.breakout import BreakoutEvent, check_retest, confirm_breakout, detect_breakout
from app.engines.technical.narrative import build_narrative
from app.engines.technical.candlestick_patterns import detect_patterns as detect_candlestick_patterns
from app.engines.technical.data_quality import check_data_quality
from app.engines.technical.gap_analysis import classify_gap, is_gap_filled, latest_gap
from app.engines.technical.horizon_classifier import HorizonInputs, classify_horizon, horizon_reason
from app.engines.technical.market_structure import analyze_market_structure
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

# 25.08.2026: 1.0.0 -> 1.1.0 — RSI hesaplaması gerçek Wilder yöntemine
# (SMA seed + recursive smoothing, warm-up=NaN) düzeltildi; aynı sembol/tarih
# için üretilen technical_score artık eskisinden (yaklaşık-Wilder/EWM) farklı
# olabilir. Eski kayıtlar (Firestore'daki immutable technical_analyses) HİÇ
# değiştirilmedi/silinmedi — yalnızca bu tarihten SONRA üretilecek yeni
# kayıtlar "1.1.0" taşıyacak, denetim izi (audit trail) bozulmadı.
ENGINE_VERSION = "1.1.0"

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
    atr_val: float,
    close_val: float,
    final_score: float,
    provider: MarketDataProvider | None = None,
    benchmark_cache_repo: BenchmarkCacheRepository | None = None,
) -> dict:
    """market_structure/S-R/breakout/hacim/rejim/gap/mum/göreli güç/sinyal
    sınıfı katmanı — relative_strength dışındaki her şey, `analyze_with_id`'nin
    zaten çekmiş olduğu AYNI df üzerinden hesaplanır (ek bir yfinance isteği
    YOK). relative_strength ise önbelleklenmiş, paylaşılan bir XU100 serisi
    kullanır (bkz. modül docstring'i, AŞAMA 48/17).
    """
    close, volume = df["Close"], df["Volume"]

    structure_result = analyze_market_structure(df)
    zones = build_zones(structure_result["swing_points"], atr=atr_val)
    support = nearest_zone(zones, price=close_val, zone_type="SUPPORT")
    resistance = nearest_zone(zones, price=close_val, zone_type="RESISTANCE")

    breakout_event: BreakoutEvent | None = None
    active_zone = nearest_zone(zones, price=close_val)
    if active_zone is not None:
        breakout_event = detect_breakout(close, active_zone, index=len(df) - 1, atr=atr_val)
        if breakout_event is not None:
            breakout_event = confirm_breakout(close, breakout_event)
            breakout_event = check_retest(close, breakout_event)

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
    weekly_close = resample_to_weekly_close(close)
    weekly_direction = timeframe_direction(weekly_close)
    alignment = check_alignment({"1d": daily_direction, "1wk": weekly_direction})

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
        self, symbol: str, persist: bool = True, max_age_seconds: int = TECHNICAL_CACHE_TTL_SECONDS
    ) -> tuple[TechnicalAnalysis, str | None]:
        cached, cached_id = self._analysis_repo.get_latest_with_id(symbol)
        if cached is not None:
            age = (datetime.now(timezone.utc) - cached.created_at).total_seconds()
            if age < max_age_seconds:
                return cached, cached_id

        df = self._provider.get_history(symbol, period="6mo")
        check_data_quality(df, symbol, min_history_days=MIN_HISTORY_DAYS)

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

        components = {
            "rsi": _clamp((rsi_val - 50) * 2),
            "macd": _clamp((macd_hist_val / atr_val) * 25) if atr_val else 0.0,
            "trend": _clamp(((ema_short_val - ema_long_val) / ema_long_val) * 1000) if ema_long_val else 0.0,
            "ema_slope": _clamp(ema_slope_val * 15),
            "bollinger": _clamp(((close_val - middle_val) / band_width) * 100) if band_width else 0.0,
            "momentum": _clamp((momentum_val / atr_val) * 20) if atr_val else 0.0,
            "roc": _clamp(roc_val * 8),
        }

        weight_sum = sum(weights.get(k, 0.0) for k in components)
        raw_score = sum(components[k] * weights.get(k, 0.0) for k in components)
        final_score = round(_clamp(raw_score / weight_sum) if weight_sum else 0.0, 2)

        agreement = sum(
            1 for s in components.values() if (s >= 0) == (final_score >= 0)
        ) / len(components)
        volume_confirmation = min(current_volume / volume_sma_val, 2.0) / 2.0 if volume_sma_val else 0.5
        confidence = round(_clamp(0.4 + 0.4 * agreement + 0.2 * volume_confirmation, 0.0, 1.0), 2)

        trend = "BULLISH" if final_score > 15 else "BEARISH" if final_score < -15 else "NEUTRAL"

        enrichment = _compute_enrichment(
            df, atr_val, close_val, final_score, provider=self._provider, benchmark_cache_repo=self._benchmark_cache_repo
        )

        analysis = TechnicalAnalysis(
            asset=symbol,
            technical_score=final_score,
            trend=trend,
            confidence=confidence,
            components=components,
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
