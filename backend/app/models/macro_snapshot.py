from datetime import datetime

from pydantic import BaseModel


class MacroSnapshot(BaseModel):
    macro_score: float
    confidence: float
    components: dict[str, float]
    indicators: dict
    created_at: datetime
    engine_version: str = "1.0.0"
