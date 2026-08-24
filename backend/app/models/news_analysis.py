from datetime import datetime
from typing import Literal

from pydantic import BaseModel, computed_field

EventType = Literal[
    "earnings", "regulatory", "corporate_action", "macro", "market_sentiment", "other"
]
TimeHorizon = Literal["short_term", "medium_term", "long_term"]

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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sentiment_label(self) -> Literal["positive", "negative", "neutral"]:
        if self.sentiment_score > _NEUTRAL_BAND:
            return "positive"
        if self.sentiment_score < -_NEUTRAL_BAND:
            return "negative"
        return "neutral"
