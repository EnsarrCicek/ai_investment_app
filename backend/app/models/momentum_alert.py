"""Erken momentum alarmı — veri modeli ve yapılandırma.

Bu bir AL/SAT motoru DEĞİLDİR: yalnız gün içi fiyat/hacim davranışında olağandışı yukarı yönlü hızlanmayı işaretler.
`momentum_score` gelecekteki getiri tahmini değildir; mevcut anomali kanıtlarının bileşik gücüdür. DecisionEngine,
teknik skor, portföy veya limit kontrolüne hiçbir girdi vermez.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

DISCLAIMER = "Momentum alarmı yatırım kararı değildir."

# Durumlar (karar/skor yalnız OK'ta üretilir)
STATUS_OK = "OK"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
STATUS_STALE_DATA = "STALE_DATA"
STATUS_IDENTITY_UNVERIFIED = "IDENTITY_UNVERIFIED"
STATUS_MARKET_CLOSED = "MARKET_CLOSED"
STATUS_ERROR = "ERROR"

# Alarm düzeyleri (yatırım tavsiyesi çağrıştırmaz)
LEVEL_NONE = "NONE"
LEVEL_WATCH = "WATCH"
LEVEL_STRONG = "STRONG"

COMPONENTS = ("price_impulse", "volume_anomaly", "breakout", "range_expansion", "reversal", "vwap", "event_catalyst")


class MomentumAlertConfig(BaseModel):
    """RESEARCH DEFAULTS — üretimde kalibre EDİLMEMİŞTİR. Gerekçeler:

    * Ağırlıklar: fiyat ve hacim kanıtı ağırlığın %55'ini taşır (olağandışı hareketin çekirdeği); kırılım ve aralık
      genişlemesi fiyatın yapısal teyidi (%25); dönüş bağlamı (%10); VWAP ve katalizör yalnız bağlam (%5 + %5) —
      haber tek başına alarm üretemez. Eksik bileşen skora 0 katkı yapar (yeniden normalize EDİLMEZ, böylece eksik
      veri skoru şişirmez).
    * `price_z_full`: kısa vadeli getiri, önceki seansların gürbüz (MAD) bar oynaklığının √k katı ile normalize edilir;
      4σ olağan gün içi gürültünün çok dışında kabul edilir (bileşen 1.0).
    * `volume_ratio_full`: son 15 dk hacmi aynı saat dilimindeki geçmiş medyanın 5 katı → 1.0.
    * `range_ratio_full`: gerçek aralık, önceki barların medyan aralığının 3 katı → 1.0.
    * Kırılım: önceki `breakout_lookback_bars` barın en yükseği (mevcut bar HARİÇ) aşılırsa; güç ATR'ye göre.
    * Dönüş: son `reversal_sessions` seansta ≥%15 düşüş ve dipten toparlanma.
    * Gecikme: Yahoo BIST gün içi verisi ~15 dk gecikmeli gözlendi (12.10.2026: 15:54'te son bar 15:39).
    """

    model_config = ConfigDict(frozen=True)

    weights: dict[str, float] = Field(default_factory=lambda: {
        "price_impulse": 0.30, "volume_anomaly": 0.25, "breakout": 0.15, "range_expansion": 0.10,
        "reversal": 0.10, "vwap": 0.05, "event_catalyst": 0.05})
    interval_minutes: int = 5
    provider_delay_minutes: int = 15
    freshness_slack_intervals: int = 2
    min_prior_sessions: int = 3
    min_bars_per_prior_session: int = 20
    min_session_bars: int = 2
    return_windows_minutes: tuple[int, ...] = (15, 30, 60)
    price_z_full: float = 4.0
    volume_window_bars: int = 3
    volume_ratio_full: float = 5.0
    breakout_lookback_bars: int = 48
    atr_bars: int = 14
    range_lookback_bars: int = 48
    range_ratio_full: float = 3.0
    reversal_sessions: int = 10
    reversal_min_drawdown: float = 0.15
    reversal_drawdown_full: float = 0.30
    reversal_rebound_full: float = 0.05
    catalyst_max_age_hours: int = 72
    max_session_gap_intervals: int = 2
    evidence_threshold: float = 0.5
    watch_score: float = 40.0
    strong_score: float = 60.0
    strong_price_impulse: float = 0.75
    strong_min_evidence: int = 3

    # --- Kalibrasyon araştırması seçenekleri (varsayılanlar ilk sürümün davranışını BİREBİR korur) ---
    # Öznitelik tabanları: kilitli/düşük bilgili seansları tabanlardan çıkar (bkz. classify_session_quality).
    baseline_quality_filter: bool = False
    min_quality_sessions: int = 3
    # Oynaklık tabanı: "MIN_CONSTANT" (bar başına %0.1) | "HYBRID_TICK" (gürbüz σ ile 1 fiyat adımı/fiyat'ın büyüğü)
    volatility_floor: str = "MIN_CONSTANT"
    # Aralık/ATR tabanı en az fiyat × efektif σ (sıfıra yakın paydadan astronomik oran üretilmez)
    range_floor: bool = False
    # Göreli hacim: "RAW" | "EFFECTIVE" (sıfır hacimli taban seansları dışlanır; skor katkısı `relvol_cap`'te doyar)
    relvol_mode: str = "RAW"
    relvol_cap: float | None = None
    # Sınıflandırma kuralı: "COMPONENT_COUNT" (ilk sürüm) | "GROUPS" (fiyat yapısı + katılım bağımsız gruplar)
    rule_mode: str = "COMPONENT_COUNT"
    # Ardışık doğrulama: son `confirm_n` değerlendirmenin (5 dk arayla) en az `confirm_k`'si düzeye ulaşmalı
    confirm_k: int = 1
    confirm_n: int = 1
    # Alarm için fiyatın önceki seans kapanışına göre en az bu kadar (%) yukarıda olması (None = koşul yok)
    min_session_return_pct: float | None = None


class MomentumAlert(BaseModel):
    asset: str
    status: str
    reason: str | None = None
    detected: bool = False
    level: str | None = None
    momentum_score: float | None = None
    signal_as_of: datetime | None = None  # son TAMAMLANMIŞ barın bitişi
    evaluated_at: datetime
    interval: str = "5m"
    data_age_seconds: float | None = None
    market_session: str | None = None
    components: dict[str, float | None] = Field(default_factory=dict)
    metrics: dict[str, float | bool | str | None] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    source: str | None = None
    identity_check: str | None = None
    disclaimer: str = DISCLAIMER
