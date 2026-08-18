from datetime import datetime

from pydantic import BaseModel


class TokenUsageLog(BaseModel):
    """EventIntelligenceEngine'in her gerçek OpenAI çağrısında bıraktığı
    immutable maliyet kaydı (ai_decisions/news_analyses ile aynı ilke —
    update/delete yok, yalnızca add).
    """

    news_id: str
    asset: str
    model_used: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    created_at: datetime
    immutable: bool = True
