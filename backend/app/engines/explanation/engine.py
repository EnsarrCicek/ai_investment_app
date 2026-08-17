"""ExplanationEngine — AŞAMA 24.

Kural tabanlı (LLM gerektirmez): TechnicalAnalysisEngine ve MacroAnalysisEngine
zaten hesapladığı bileşen kırılımını (RSI, MACD, trend, VIX, DXY vb.) Türkçe
şablon cümlelere çevirir. Ana doküman bölüm 72'deki "Missing Data Davranışı"
ilkesiyle uyumlu: news_score ve makro veri eksikliği açıkça belirtilir.
Burada üretilen kararlar AI Decision History'e YAZILMAZ (persist=False) —
bu uç nokta yalnızca mevcut kararın gerekçesini gösterir, yeni bir karar kaydı
oluşturmaz.
"""

from app.engines.decision.engine import DecisionEngine
from app.engines.technical.engine import TechnicalAnalysisEngine
from app.repositories.macro_snapshot_repository import MacroSnapshotRepository

_DECISION_LABELS = {
    "BUY": "AL",
    "WEAK_BUY": "ZAYIF AL",
    "HOLD": "TUT",
    "WEAK_SELL": "ZAYIF SAT",
    "SELL": "SAT",
}

_TECHNICAL_LABELS = {
    "rsi": "RSI",
    "macd": "MACD",
    "trend": "EMA Trend (20/50)",
    "bollinger": "Bollinger Bantları",
    "momentum": "Momentum",
    "roc": "ROC (Değişim Oranı)",
}

_MACRO_LABELS = {
    "dxy": "Dolar Endeksi (DXY)",
    "us_10y_yield": "ABD 10 Yıllık Tahvil Faizi",
    "vix": "VIX (Volatilite Endeksi)",
    "oil": "Petrol",
    "gold": "Altın",
    "usdtry": "USD/TRY",
}


def _direction_phrase(value: float) -> str:
    if value > 5:
        return "olumlu yönde katkı yapıyor"
    if value < -5:
        return "olumsuz yönde baskı yapıyor"
    return "nötr, belirgin bir yön göstermiyor"


def _top_reasons(components: dict[str, float], labels: dict[str, str], limit: int = 3) -> list[str]:
    ranked = sorted(components.items(), key=lambda kv: abs(kv[1]), reverse=True)
    return [
        f"{labels.get(key, key)}: {value:+.1f} puan, {_direction_phrase(value)}"
        for key, value in ranked[:limit]
    ]


class ExplanationEngine:
    def __init__(
        self,
        decision_engine: DecisionEngine | None = None,
        technical_engine: TechnicalAnalysisEngine | None = None,
        macro_repo: MacroSnapshotRepository | None = None,
    ):
        self._decision_engine = decision_engine or DecisionEngine()
        self._technical_engine = technical_engine or TechnicalAnalysisEngine()
        self._macro_repo = macro_repo or MacroSnapshotRepository()

    def explain(self, asset: str) -> dict:
        analysis, analysis_id = self._technical_engine.analyze_with_id(asset, persist=False)
        macro, macro_id = self._macro_repo.get_latest_with_id()

        decision = self._decision_engine.decide(
            asset=asset,
            technical_score=analysis.technical_score,
            macro_score=macro.macro_score if macro else None,
            technical_confidence=analysis.confidence,
            technical_analysis_id=analysis_id,
            macro_snapshot_id=macro_id,
            persist=False,
        )

        label = _DECISION_LABELS.get(decision.decision, decision.decision)
        summary = (
            f"{asset} için '{label}' kararı verildi "
            f"(final skor: {decision.final_score:+.1f}, güven: %{decision.confidence:.0f})."
        )

        missing = []
        if decision.news_score is None:
            missing.append("Haber analizi (EventIntelligenceEngine) henüz uygulanmadı, karara dahil edilmedi.")
        if macro is None:
            missing.append("Güncel bir makro veri anlık görüntüsü bulunamadı.")

        return {
            "asset": asset,
            "decision": decision.decision,
            "final_score": decision.final_score,
            "confidence": decision.confidence,
            "summary": summary,
            "technical_reasons": _top_reasons(analysis.components, _TECHNICAL_LABELS),
            "macro_reasons": _top_reasons(macro.components, _MACRO_LABELS) if macro else [],
            "missing": missing,
        }
