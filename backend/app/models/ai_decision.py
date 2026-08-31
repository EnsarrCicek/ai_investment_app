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
