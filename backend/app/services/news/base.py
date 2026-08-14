from abc import ABC, abstractmethod

from app.models.news_raw import NewsRawItem


class NewsProvider(ABC):
    """Provider arayüzü — engine'ler doğrudan bir haber kaynağına bağlanmaz (ana doküman bölüm 67)."""

    @abstractmethod
    def get_latest_news(self, symbol: str, limit: int = 10) -> list[NewsRawItem]: ...
