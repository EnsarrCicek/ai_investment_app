from datetime import datetime

from pydantic import BaseModel


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
    confidence: float
    technical_analysis_id: str | None = None
    news_analysis_ids: list[str] = []
    macro_snapshot_id: str | None = None
    decision_engine_version: str
    immutable: bool = True
