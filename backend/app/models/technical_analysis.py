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

    # 25.08.2026 (HATA 2A denetimi): `created_at` yalnızca motorun HESABI
    # YAPTIĞI anı gösterir — kullanılan piyasa verisinin GERÇEKTEN hangi ana
    # ait olduğunu (son TAMAMLANMIŞ günlük barın tarihi) göstermez. Eski
    # (bu alan eklenmeden önceki) Firestore kayıtlarında bu alan yoktur —
    # `None` varsayılanı geriye dönük uyumluluğu bozmadan bunu ifade eder.
    market_data_as_of: datetime | None = None

    # 25.08.2026 (HATA 2C denetimi): analiz penceresinden (`analysis_start`)
    # ÖNCEYE uzanan bir "pre-roll" bölgesinde en az bir gerçek bar bulunup
    # bulunmadığını (yani sembolün analiz başlangıcından ÖNCE zaten işlem
    # gördüğünün KANITLANIP kanıtlanamadığını) gösterir — bkz.
    # engines/technical/history_window.py, HistoryValidationStatus.
    # "VERIFIED_PRE_WINDOW" veya "LEADING_EDGE_UNVERIFIED" değerini alır.
    # Eski (bu alan eklenmeden önceki) Firestore kayıtlarında yoktur;
    # `None` bunu geriye dönük uyumlu şekilde ifade eder — migration YAPILMADI.
    history_validation_status: str | None = None

    # 26.08.2026 (HATA 3D denetimi): authoritative BIST takvimine göre
    # "expected session" OLMAYAN (hafta sonu/planlı tatil/olağanüstü kapanış/
    # iptal edilmiş seans) bir tarihte provider'ın (Yahoo) döndürdüğü herhangi
    # bir bar varsa, bu barlar skorlamaya girmeden ÖNCE düşürülür — bu iki
    # alan HANGİ tarihlerin, HANGİ gerekçeyle düşürüldüğünü şeffaf şekilde
    # taşır (bkz. services/market_data/trading_calendar.py,
    # normalize_bist_daily_sessions/session_normalization_to_dict). Eski (bu
    # alanlar eklenmeden önceki) Firestore kayıtlarında yoktur; `None`/`[]`
    # varsayılanları geriye dönük uyumluluğu bozmadan bunu ifade eder —
    # migration YAPILMADI.
    session_normalization_policy: str | None = None
    normalized_dropped_sessions: list[dict] = Field(default_factory=list)

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
