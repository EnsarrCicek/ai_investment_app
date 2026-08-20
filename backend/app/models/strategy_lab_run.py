from datetime import datetime

from pydantic import BaseModel


class StrategyPresetAggregate(BaseModel):
    preset: str
    avg_return_pct: float
    avg_win_rate_pct: float
    avg_max_drawdown_pct: float
    best_count: int
    symbol_count: int


class StrategyLabRun(BaseModel):
    """AŞAMA 62: kullanıcı isteği "her test yaptığımızda veri tutsun" —
    Strateji Laboratuvarı'ndaki (AŞAMA 57) her tarama artık kalıcı olarak
    kaydedilir, zamanla test geçmişi karşılaştırılabilir hale gelir.
    Aggregation Flutter tarafında (sembol başına 10'arlı batch ile) yapılır;
    bu model yalnızca SONUCU saklar.
    """

    user_id: str
    period: str
    universe: str  # "PORTFOLIO" | "BIST100"
    tested_count: int
    failed_count: int
    results: list[StrategyPresetAggregate]
    winner_preset: str | None
    created_at: datetime
