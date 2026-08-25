from datetime import datetime

from pydantic import BaseModel, Field


class TechnicalAnalysis(BaseModel):
    asset: str
    technical_score: float
    trend: str
    confidence: float
    components: dict[str, float]
    indicators: dict
    created_at: datetime
    engine_version: str = "1.0.0"

    # AŞAMA 48/15: market structure/S-R/breakout/hacim/rejim/gap/mum/sinyal
    # sınıfı — TechnicalAnalysisEngine'in üç bileşenli çekirdek skorunu
    # (rsi/macd/trend/ema_slope/bollinger/momentum/roc) DEĞİŞTİRMEZ, yalnızca
    # zenginleştirilmiş, açıklayıcı bağlam ekler (bkz. engine.py docstring).
    market_structure: str | None = None
    signal_class: str | None = None
    relative_volume_class: str | None = None
    relative_strength_class: str | None = None
    volatility_regime: str | None = None
    trend_regime: str | None = None
    gap_class: str | None = None
    candlestick_patterns: list[str] = Field(default_factory=list)
    nearest_support: dict | None = None
    nearest_resistance: dict | None = None
    breakout: dict | None = None
    mtf_aligned: bool | None = None
    mtf_consensus: str | None = None

    # 25.08.2026: kullanıcı isteği "hangi hisseyi uzun süreli alıyoruz hangi
    # hisseyi kısa süreli alıyoruz bunu belirt" — saf teknik yapıya dayanan
    # kural tabanlı vade sınıflandırması (bkz. horizon_classifier.py).
    investment_horizon: str | None = None
    investment_horizon_reason: str = ""

    # AŞAMA 66: kullanıcı isteği "grafikte dirençler nasıl çiziliyor, neden
    # AL diyorsun detaylı açıkla" — grafikte çizilecek tüm destek/direnç
    # bölgeleri (fiyata en yakın MAX_CHART_ZONES tanesi) ve kural tabanlı
    # (LLM'siz) Türkçe anlatı (bkz. engines/technical/narrative.py).
    all_zones: list[dict] = Field(default_factory=list)
    narrative: str = ""
