from datetime import datetime

from pydantic import BaseModel


class MacroSnapshot(BaseModel):
    macro_score: float
    confidence: float
    components: dict[str, float]
    indicators: dict
    created_at: datetime
    engine_version: str = "1.1.0"

    # HATA 16D: bilimsel reproducibility/provenance alanları -- HEPSİ opsiyonel
    # (`None` varsayılan) çünkü 16D-ÖNCESİ mevcut production `MacroSnapshot`
    # kayıtları bu alanları İÇERMEZ ve destructive migration YAPILMAZ; eski
    # kayıtlar için "provenance mevcut değil" dürüstçe temsil edilir, eski
    # provider/weights/scales/hash UYDURULMAZ. `provider_id`/`window`/
    # `max_observation_age_days`/`resolved_weights`/`resolved_scales` bu run'da
    # GERÇEKTEN kullanılan değerlerdir (Firestore config referansı DEĞİL --
    # config zaman içinde değişebilir, bu yüzden ham değerler gömülüdür).
    # `macro_config_sha256`: yalnızca weights+scales+window+freshness-eşiği
    # (metodoloji/config parametreleri) üzerinden -- iki run'ın AYNI config'i
    # kullanıp kullanmadığını, hangi piyasa verisi geldiğinden BAĞIMSIZ olarak
    # tespit etmek için. `macro_input_sha256`: provider+window+eşik+weights+
    # scales+engine_version+KULLANILAN (fresh) gözlemlerin TAMAMI üzerinden --
    # bu spesifik snapshot'ın kendi kendine yeten (self-contained) tam bilimsel
    # imzası. İkisi de `app.research.canonical_hash.content_sha256` ile
    # (proje-genelindeki TEK paylaşılan kanonik JSON/SHA-256 ilkeli, HATA
    # 12N2A) hesaplanır -- Python `hash()` KULLANILMAZ.
    provider_id: str | None = None
    window: int | None = None
    max_observation_age_days: int | None = None
    resolved_weights: dict[str, float] | None = None
    resolved_scales: dict[str, float] | None = None
    macro_config_sha256: str | None = None
    macro_input_sha256: str | None = None
