from pydantic import BaseModel

from app.models.strategy_lab_run import StrategyPresetAggregate


class StrategyLabRunCreate(BaseModel):
    period: str
    universe: str
    tested_count: int
    failed_count: int
    results: list[StrategyPresetAggregate]
