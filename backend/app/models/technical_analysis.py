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
    volatility_regime: str | None = None
    trend_regime: str | None = None
    gap_class: str | None = None
    candlestick_patterns: list[str] = Field(default_factory=list)
    nearest_support: dict | None = None
    nearest_resistance: dict | None = None
    breakout: dict | None = None
