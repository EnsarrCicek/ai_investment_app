from datetime import datetime

from pydantic import BaseModel


class NewsRawItem(BaseModel):
    external_id: str
    title: str
    summary: str
    url: str
    publisher: str
    source: str
    source_reliability: float | None
    related_assets: list[str]
    published_at: datetime
    received_at: datetime
    is_analyst_mention: bool = False
    analyst_firm: str | None = None
