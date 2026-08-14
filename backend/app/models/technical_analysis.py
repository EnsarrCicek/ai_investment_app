from datetime import datetime

from pydantic import BaseModel


class TechnicalAnalysis(BaseModel):
    asset: str
    technical_score: float
    trend: str
    confidence: float
    components: dict[str, float]
    indicators: dict
    created_at: datetime
    engine_version: str = "1.0.0"
