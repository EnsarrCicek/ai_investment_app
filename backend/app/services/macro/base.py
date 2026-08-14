from abc import ABC, abstractmethod


class MacroDataProvider(ABC):
    """Provider arayüzü — engine doğrudan bir veri kaynağına bağlanmaz (ana doküman bölüm 67)."""

    @abstractmethod
    def get_indicator_changes(self, window: int = 20) -> dict[str, dict]:
        """Her gösterge için {'value': son_değer, 'pct_change': N günlük yüzde değişim} döndürür."""
        ...
