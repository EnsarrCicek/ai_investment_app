"""MacroAnalysisEngine — ana doküman bölüm 15.

Yön sözleşmesi (dokümante edilmiş tasarım kararı): DXY, ABD 10Y tahvil faizi, VIX,
petrol ve USD/TRY'nin YÜKSELMESİ risk-off / BIST için negatif olarak yorumlanır
(dolar güçlenmesi ve faiz artışı gelişen piyasalardan çıkışı, VIX artışı risk
iştahının azalmasını, petrol artışı Türkiye'nin ithalatçı konumu nedeniyle
enflasyon baskısını, TL'nin değer kaybı ise maliyet/enflasyon baskısını temsil
eder). Altın için de risk-off proxy'si olarak aynı yön kullanılmıştır. Bu, TÜM
varlıklar için ortak/piyasa-geneli bir skordur (TechnicalScore gibi varlığa özel
değildir) — ana dokümandaki `macro_snapshots` collection'ı ile uyumludur.
"""

from datetime import datetime, timezone

from app.models.macro_snapshot import MacroSnapshot
from app.repositories.macro_snapshot_repository import MacroSnapshotRepository
from app.repositories.system_config_repository import SystemConfigRepository
from app.services.macro.base import MacroDataProvider
from app.services.macro.yahoo_macro_provider import YahooMacroProvider

ENGINE_VERSION = "1.0.0"

# Her göstergenin tipik oynaklığına göre ölçek faktörü (pct_change -> -100..100 puan).
DEFAULT_SCALES = {
    "dxy": 15.0,
    "us_10y_yield": 10.0,
    "vix": 2.0,
    "oil": 5.0,
    "gold": 8.0,
    "usdtry": 8.0,
}

DEFAULT_WEIGHTS = {
    "dxy": 0.20,
    "us_10y_yield": 0.20,
    "vix": 0.20,
    "oil": 0.15,
    "gold": 0.10,
    "usdtry": 0.15,
}


def _clamp(value: float, low: float = -100.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


class MacroAnalysisEngine:
    def __init__(
        self,
        provider: MacroDataProvider | None = None,
        config_repo: SystemConfigRepository | None = None,
        snapshot_repo: MacroSnapshotRepository | None = None,
    ):
        self._provider = provider or YahooMacroProvider()
        self._config_repo = config_repo or SystemConfigRepository()
        self._snapshot_repo = snapshot_repo or MacroSnapshotRepository()

    def analyze(self, persist: bool = True) -> tuple[MacroSnapshot, str | None]:
        changes = self._provider.get_indicator_changes()
        if not changes:
            raise ValueError("Hiçbir makro gösterge verisi alınamadı")

        scales = self._config_repo.get("macro_indicator_scales", DEFAULT_SCALES)
        weights = self._config_repo.get("macro_indicator_weights", DEFAULT_WEIGHTS)

        components = {}
        for key, data in changes.items():
            scale = scales.get(key, 5.0)
            # Tüm göstergeler için: yükseliş = risk-off = negatif katkı (yukarıdaki not).
            components[key] = _clamp(-data["pct_change"] * scale)

        available_weight = sum(weights.get(k, 0.0) for k in components)
        macro_score = round(
            sum(components[k] * weights.get(k, 0.0) for k in components) / available_weight, 2
        ) if available_weight else 0.0

        completeness = len(components) / len(DEFAULT_WEIGHTS)
        agreement = sum(
            1 for s in components.values() if (s >= 0) == (macro_score >= 0)
        ) / len(components)
        confidence = round(_clamp(0.3 + 0.4 * agreement + 0.3 * completeness, 0.0, 1.0), 2)

        snapshot = MacroSnapshot(
            macro_score=macro_score,
            confidence=confidence,
            components=components,
            indicators=changes,
            created_at=datetime.now(timezone.utc),
            engine_version=ENGINE_VERSION,
        )

        doc_id = self._snapshot_repo.add(snapshot) if persist else None
        return snapshot, doc_id
