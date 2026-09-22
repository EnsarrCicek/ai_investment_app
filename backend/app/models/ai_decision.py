import re
from datetime import datetime

from pydantic import BaseModel, field_validator

# HATA 17D: HATA 15D ile AYNI desen -- SHA-256 hex digest her zaman 64
# küçük-harf hex karakter.
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class AIDecision(BaseModel):
    asset: str
    created_at: datetime
    technical_score: float | None = None
    news_score: float | None = None
    macro_score: float | None = None
    technical_weight: float
    news_weight: float
    macro_weight: float
    final_score: float
    decision: str
    # 28.08.2026 (HATA 5C3B): "Sinyal Mutabakatı" -- mevcut (available)
    # technical/news/macro kanallarının, `decision_weights` ile ağırlıklandırılmış
    # olarak, final karar yönüyle ne kadar uyuştuğunu ölçer. Olasılık/doğruluk/
    # skor büyüklüğü/veri eksiksizliği DEĞİLDİR (bkz. `channel_completeness`,
    # AYRI bir metrik -- tek sayıya birleştirilmez). `technical_confidence`
    # bağımlılığı ve `0.6` fallback'i RETIRED (bkz. engines/decision/engine.py).
    confidence: float
    # 28.08.2026 (HATA 5C3B): "Veri Kapsamı" -- technical/news/macro kanallarının,
    # configured `decision_weights` açısından ne kadarının mevcut olduğunu ölçer
    # (`available_weight / toplam ağırlık`). `confidence`'a KARIŞTIRILMAZ. Karar
    # üretildiği sürece (`available_weight>0` guard'ı, bkz. `decide()`) her zaman
    # (0,1] aralığında finite bir değerdir. Bu alan eklenmeden önceki kayıtlarda
    # yoktur; `None` bunu geriye dönük uyumlu şekilde ifade eder -- migration YOK.
    channel_completeness: float | None = None
    technical_analysis_id: str | None = None
    news_analysis_ids: list[str] = []
    macro_snapshot_id: str | None = None
    decision_engine_version: str
    immutable: bool = True

    # HATA 17C: bu kararın hesaplandığı anın tek, açık zaman damgası --
    # macro/news freshness/as-of karşılaştırmalarının TÜMÜNÜN kullandığı
    # (ve `created_at` ile AYNI) değer (bkz. `decision/engine.py::decide()`).
    # `None` varsayılan -- 17C-ÖNCESİ mevcut kayıtlarda bu alan yok, geriye
    # dönük migration YOK. Tam threshold/config provenance (HATA 17A bulgu
    # #2) AYRI, henüz açık bir konu -- bu alan yalnızca "hangi anda
    # freshness değerlendirildi" sorusuna cevap verir, threshold/weight
    # provenance'ı KAPSAMAZ.
    decision_as_of: datetime | None = None

    # HATA 17D: `technical_weight`/`news_weight`/`macro_weight` HER ZAMAN
    # (17D-ÖNCESİ dahil) config-resolution-sonrası ama availability-
    # renormalization-ÖNCESİ configured değerlerdi (bkz. `decide()` --
    # `weights["technical"]` doğrudan persist edilir, `available_weight`
    # renormalizasyonu SADECE final_score/channel_completeness/confidence
    # hesaplamasını etkiler). 17D bu semantiği DEĞİŞTİRMEDİ, yalnızca
    # eksik olan threshold tarafını tamamladı: `decision_thresholds`, o
    # kararda GERÇEKTEN kullanılan resolved `{buy, weak_buy, weak_sell,
    # sell}` sözlüğüdür (bir config doküman referansı DEĞİL -- Firestore
    # config zaman içinde değişebilir, bu yüzden ham değerler gömülüdür).
    # Bu ikisi (configured weights + resolved thresholds) birlikte, final_
    # score'un ZATEN mümkün olan reproducibility'sine decision LABEL'ının
    # (ve ondan türeyen confidence'ın) reproducibility'sini de ekler (HATA
    # 17A bulgu #2'nin doğrudan kapanışı). `decision_config_sha256`:
    # yalnızca {weights, thresholds} üzerinden (config KİMLİĞİ -- hangi
    # skorların geldiğinden BAĞIMSIZ; `created_at`/`decision_as_of`/input
    # skorları/doküman ID'leri KASITLI OLARAK DAHİL DEĞİL, bkz. `decision/
    # engine.py::compute_decision_config_sha256`), `app.research.
    # canonical_hash.content_sha256` (proje-genelindeki TEK paylaşılan
    # kanonik JSON/SHA-256 ilkeli, HATA 12N2A/16D ile AYNI) ile hesaplanır
    # -- Python `hash()` KULLANILMAZ. Ayrı bir `decision_input_sha256`
    # KASITLI OLARAK EKLENMEDİ: bu hash'in bağlayacağı HER alan (technical/
    # news/macro skorları+ID'leri, decision_as_of, weights, thresholds,
    # engine_version) zaten ayrı ayrı, doğrudan, dönüşümsüz alanlar olarak
    # persist ediliyor (macro'nun `indicators` sözlüğünün aksine -- orada
    # normalize edilmiş bir iç-içe yapı vardı) -- ikinci bir hash burada
    # yeni bir reproducibility yeteneği EKLEMEZ, yalnızca zaten mevcut
    # alanları tekrar eder (bkz. modül raporu, HATA 17D madde 8 "gereksiz
    # yere mevcut bir provenance sözleşmesini kopyalıyorsa EKLEME").
    # HEPSİ opsiyonel (`None` varsayılan) -- 17D-ÖNCESİ kayıtlarda YOK,
    # destructive migration YOK; eski kayıt için "provenance mevcut değil"
    # dürüstçe temsil edilir, eski threshold/hash UYDURULMAZ.
    decision_thresholds: dict[str, float] | None = None
    decision_config_sha256: str | None = None

    @field_validator("decision_config_sha256")
    @classmethod
    def _validate_config_sha256_hex(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256_HEX_RE.fullmatch(value):
            raise ValueError(
                f"Geçersiz SHA-256 hex digest: {value!r} (64 küçük-harf hex "
                "karakter olmalı) — fail-fast, sessizce coerce EDİLMİYOR."
            )
        return value
