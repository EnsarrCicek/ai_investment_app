from datetime import datetime
from typing import Literal

from pydantic import BaseModel

EventType = Literal[
    "earnings", "regulatory", "corporate_action", "macro", "market_sentiment", "other"
]


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
    reasoning: str
    model_used: str
    created_at: datetime
    engine_version: str = "1.0.0"
    immutable: bool = True
