import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, computed_field, field_validator

EventType = Literal[
    "earnings", "regulatory", "corporate_action", "macro", "market_sentiment", "other"
]
TimeHorizon = Literal["short_term", "medium_term", "long_term"]

# HATA 15D: SHA-256 hex digest — her zaman 64 küçük-harf hex karakter.
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

# Yön sınıflandırması sentiment_score'dan TÜRETİLİR (ayrı bir LLM şema alanı
# DEĞİL) — skor zaten yönü tam olarak taşıyor, ikinci bir alan hem gereksiz
# token maliyeti hem de skorla çelişme riski yaratırdı. Küçük bir "nötr
# bölgesi" (+-5) var: gerçekten anlamsız/etkisiz haberlerin ufak gürültüden
# ötürü pozitif/negatif etiketlenmesini önlemek için.
_NEUTRAL_BAND = 5.0


class NewsAnalysis(BaseModel):
    """EventIntelligenceEngine'in bir haberi analiz ettiğinde ürettiği,
    Firestore'a immutable olarak yazılan kayıt (ai_decisions/technical_analyses
    ile aynı ilke: AI'nin ürettiği kayıt asla güncellenmez, yeniden
    değerlendirme her zaman yeni bir doküman olarak eklenir).
    """

    news_id: str
    asset: str
    sentiment_score: float  # -100 (çok olumsuz) .. +100 (çok olumlu)
    confidence: float  # 0..1
    importance: float  # 0..1 — olayın piyasa etkisi önemi
    event_type: EventType
    # Var olan eski kayıtlarda (bu alan eklenmeden önce) bulunmuyor —
    # immutable kayıtlar asla geriye dönük güncellenmediği için varsayılan
    # değer geriye dönük uyumluluk için ZORUNLU (bkz. NewsAnalysisRepository).
    time_horizon: TimeHorizon = "medium_term"
    reasoning: str
    model_used: str
    created_at: datetime
    engine_version: str = "1.0.0"
    immutable: bool = True

    # HATA 15D: reproducibility/provenance alanları — hepsi `None` varsayılan
    # (bu alanlar eklenmeden ÖNCE yazılmış legacy kayıtlar bunları hiç
    # içermez; destructive migration YOK, eski kayıtlar güvenle okunmaya
    # devam eder — bkz. NewsAnalysisRepository, HATA 15D bölüm 26). Yeni
    # üretilen HER kayıt için EventIntelligenceEngine bu alanları DOLU
    # gönderir (bkz. engine.py `analyze_item`).
    #
    # `analyzed_text`: LLM'e GERÇEKTEN gönderilen son metin (başlık/özet/
    # makale-gövdesi seçimi + kırpma sonrası) — canlı sayfa daha sonra
    # değişse bile bu kayıt SABİT kalır (immutable, bkz. bölüm 4/14/18).
    analyzed_text: str | None = None
    # `analyzed_text_sha256`: yukarıdaki metnin SHA-256 hex digest'i (Python
    # hash() DEĞİL — canonical UTF-8 bytes üzerinden, süreçler arası kararlı).
    analyzed_text_sha256: str | None = None
    prompt_version: str | None = None
    prompt_sha256: str | None = None
    output_schema_version: str | None = None

    @field_validator("analyzed_text_sha256", "prompt_sha256")
    @classmethod
    def _validate_sha256_hex(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256_HEX_RE.fullmatch(value):
            raise ValueError(
                f"Geçersiz SHA-256 hex digest: {value!r} (64 küçük-harf hex "
                "karakter olmalı) — fail-fast, sessizce coerce EDİLMİYOR."
            )
        return value

    @field_validator("prompt_version", "output_schema_version")
    @classmethod
    def _validate_non_empty_version(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Versiyon alanı boş/whitespace-only olamaz.")
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sentiment_label(self) -> Literal["positive", "negative", "neutral"]:
        if self.sentiment_score > _NEUTRAL_BAND:
            return "positive"
        if self.sentiment_score < -_NEUTRAL_BAND:
            return "negative"
        return "neutral"
