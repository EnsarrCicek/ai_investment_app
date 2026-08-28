from datetime import datetime

from pydantic import BaseModel, Field


class TechnicalAnalysis(BaseModel):
    asset: str
    # HATA 5B1 (27.08.2026): 7 component'in TAMAMI unavailable (finite değil)
    # olduğu (son derece nadir, bkz. scoring.py modül docstring'i) durumda
    # `None` -- 0.0/100.0 gibi sahte bir "nötr"/"maksimum" skor UYDURULMAZ.
    # Eski Firestore kayıtlarının TAMAMI gerçek bir float taşıdığından
    # (`float` bu tip birleşiminin bir alt kümesidir) geriye dönük okuma
    # BOZULMAZ, migration YAPILMADI.
    technical_score: float | None
    # 27.08.2026 (HATA 5B1 FINAL PRE-COMMIT GATE): `technical_score is None`
    # olduğunda `trend` de `None` olur -- "NEUTRAL" GERÇEK bir teknik yön
    # bilgisidir (skor [-15, 15] aralığında demektir), "yön hesaplanamadı"
    # ile AYNI şey DEĞİLDİR. `technical_score == 0.0` (geçerli, hesaplanmış
    # bir skor) hâlâ `trend == "NEUTRAL"` üretir -- yalnızca skorun kendisi
    # `None` (7 component'in tamamı unavailable) olduğunda `trend` de `None`
    # olur. Eski Firestore kayıtlarının TAMAMI gerçek bir `str` taşıdığından
    # geriye dönük okuma BOZULMAZ, migration YAPILMADI.
    trend: str | None
    # 27.08.2026 (HATA 5B1 FINAL PRE-COMMIT GATE, madde 3): `technical_score
    # is None` olduğunda `confidence=0.0` KALIR (nullable YAPILMADI) --
    # burada `confidence`'ın anlamı "üretilebilir bir teknik skora ne kadar
    # güveniliyor" demektir; skor hiç üretilemediğinde %0 güven DÜRÜST bir
    # değerdir, "nötr skor" anlamına GELMEZ. `DecisionEngine.decide()` zaten
    # bu semantiği kullanıyor: `technical_confidence=0.0` overall confidence'ı
    # sıfırlar (bkz. engines/decision/engine.py, `base_confidence` satırı) --
    # None ile karıştırılmaz çünkü `technical_confidence: float | None`
    # parametresi yalnızca HİÇ değer verilmediğinde (0.6) varsayılana düşer.
    confidence: float
    components: dict[str, float]
    # 27.08.2026 (HATA 5B2D): `technical_score` artık iki seviyeli (component
    # -> family -> technical_score) aggregation'dır (bkz. engines/technical/
    # scoring.py, `FAMILY_MEMBERSHIP`) -- bu alan ara `family_score`'ları
    # (trend/oscillator_position/momentum_rate) debugging/explanation/
    # historical provenance için saklar, `technical_score`'u ETKİLEMEZ.
    # `components` ile AYNI omit-unavailable/keep-valid-zero sözleşmesi
    # geçerlidir. Eski (bu alan eklenmeden önceki, flat-weighted) Firestore
    # kayıtlarında yoktur; `default_factory=dict` bunu geriye dönük uyumlu
    # şekilde ifade eder — migration YAPILMADI.
    family_scores: dict[str, float] = Field(default_factory=dict)
    # 27.08.2026 (HATA 5B2D TRUE FINAL COMMIT GATE): `technical_score` artık
    # iki Firestore config'ine (`technical_indicator_weights`, `technical_
    # family_weights`) bağımlı -- bu alan, o an `technical_score`'u ÜRETMİŞ
    # OLAN resolved config'in deterministik bir parmak izidir (bkz.
    # `engines/technical/scoring.py::compute_scoring_config_hash`). 15
    # dakikalık cache, bu hash'i `engine_version` ile BİRLİKTE karşılaştırır
    # -- AYNI engine_version altında config değişse (veya REQUIRED
    # `technical_indicator_weights` silinse) bile fresh bir cache kaydının
    # ARTIK GEÇERSİZ bir config'ten geldiğini fark edebilmek için. Eski (bu
    # alan eklenmeden önceki) Firestore kayıtlarında yoktur; `None` bunu
    # geriye dönük uyumlu şekilde ifade eder -- migration YAPILMADI, ve
    # `None` cache karşılaştırmasında KASITLI OLARAK her zaman "eşleşmez"
    # (cache MISS) sonucunu verir.
    scoring_config_hash: str | None = None
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

    # HATA 4B (27.08.2026): `notify_if_new_opportunity()`'nin AYNI breakout
    # event'i için tekrar tekrar bildirim göndermemesi amacıyla (event-specific
    # dedupe) — `breakout_timeline.BreakoutTimelineEvent.event_id` (stateless,
    # yalnız bir kimlik string'i; tam timeline modeli Firestore'a HİÇ
    # PERSIST EDİLMEZ, bkz. breakout_timeline.py). Eski kayıtlarda yoktur;
    # `None` bunu geriye dönük uyumlu şekilde ifade eder.
    breakout_event_id: str | None = None

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
