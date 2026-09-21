from abc import ABC, abstractmethod


class MacroDataProvider(ABC):
    """Provider arayüzü — engine doğrudan bir veri kaynağına bağlanmaz (ana doküman bölüm 67)."""

    @abstractmethod
    def get_indicator_changes(self, window: int = 20) -> dict[str, dict]:
        """Her gösterge için {'value': son_değer, 'pct_change': N günlük yüzde değişim,
        'observed_at': son gözlemin UTC-aware datetime'ı (HATA 16C) ya da bilinmiyorsa
        `None`} döndürür. `observed_at`, `MacroAnalysisEngine` tarafından freshness
        kontrolü için kullanılır -- eksik/geçersiz/gelecek tarihli olması gösterge
        elenmesine yol açar, asla stale bir değeri güncelmiş gibi kullandırmaz."""
        ...
