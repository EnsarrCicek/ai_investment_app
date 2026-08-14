"""DecisionEngine — ana doküman bölüm 17-19, 32-33, 72.

Durum: EventIntelligenceEngine henüz yazılmadı (bkz. AŞAMA 16+, bir LLM
entegrasyonu gerektiriyor), bu yüzden news_score hâlâ hiçbir zaman mevcut
değil. MacroAnalysisEngine ise AŞAMA 21-22'de eklendi. Bu, bölüm 72'deki
"Missing Data Davranışı" ilkesinin canlı kanıtıdır: DecisionEngine eksik
skorları örtbas ETMEZ — kalan skorların ağırlıklarını normalize eder ve
`confidence`'ı veri eksikliği oranında düşürür. MacroAnalysisEngine
eklendiğinde `decide()`'ın çekirdek mantığı DEĞİŞMEDİ (tasarım hedefi
buydu) — yalnızca `decide_for_asset()` artık macro_score'u da topluyor.
"""

from datetime import datetime, timezone

from app.engines.technical.engine import TechnicalAnalysisEngine
from app.models.ai_decision import AIDecision
from app.repositories.ai_decision_repository import AIDecisionRepository
from app.repositories.macro_snapshot_repository import MacroSnapshotRepository
from app.repositories.system_config_repository import SystemConfigRepository

ENGINE_VERSION = "1.0.0"

DEFAULT_WEIGHTS = {"technical": 0.50, "news": 0.30, "macro": 0.20}

# Ana doküman bölüm 18: +40..100 AL, +15..39 ZAYIF AL, -14..14 TUT, -39..-15 ZAYIF SAT, -100..-40 SAT
DEFAULT_THRESHOLDS = {"buy": 40.0, "weak_buy": 15.0, "weak_sell": -15.0, "sell": -40.0}


def _classify(score: float, t: dict) -> str:
    if score >= t["buy"]:
        return "BUY"
    if score >= t["weak_buy"]:
        return "WEAK_BUY"
    if score <= t["sell"]:
        return "SELL"
    if score <= t["weak_sell"]:
        return "WEAK_SELL"
    return "HOLD"


class DecisionEngine:
    def __init__(
        self,
        config_repo: SystemConfigRepository | None = None,
        decision_repo: AIDecisionRepository | None = None,
    ):
        self._config_repo = config_repo or SystemConfigRepository()
        self._decision_repo = decision_repo or AIDecisionRepository()

    def decide(
        self,
        asset: str,
        technical_score: float | None = None,
        news_score: float | None = None,
        macro_score: float | None = None,
        technical_confidence: float | None = None,
        technical_analysis_id: str | None = None,
        news_analysis_ids: list[str] | None = None,
        macro_snapshot_id: str | None = None,
        persist: bool = True,
    ) -> AIDecision:
        weights = self._config_repo.get("decision_weights", DEFAULT_WEIGHTS)
        thresholds = self._config_repo.get("decision_thresholds", DEFAULT_THRESHOLDS)

        scores = {"technical": technical_score, "news": news_score, "macro": macro_score}
        available = {k: v for k, v in scores.items() if v is not None}
        if not available:
            raise ValueError(f"'{asset}' için hiçbir analiz skoru mevcut değil (INSUFFICIENT_DATA)")

        available_weight = sum(weights[k] for k in available)
        final_score = round(
            sum(scores[k] * weights[k] for k in available) / available_weight, 2
        )

        completeness = available_weight / sum(weights.values())
        base_confidence = technical_confidence if technical_confidence is not None else 0.6
        confidence = round(base_confidence * completeness * 100, 2)

        decision = _classify(final_score, thresholds)

        record = AIDecision(
            asset=asset,
            created_at=datetime.now(timezone.utc),
            technical_score=technical_score,
            news_score=news_score,
            macro_score=macro_score,
            technical_weight=weights["technical"],
            news_weight=weights["news"],
            macro_weight=weights["macro"],
            final_score=final_score,
            decision=decision,
            confidence=confidence,
            technical_analysis_id=technical_analysis_id,
            news_analysis_ids=news_analysis_ids or [],
            macro_snapshot_id=macro_snapshot_id,
            decision_engine_version=ENGINE_VERSION,
        )

        if persist:
            self._decision_repo.add(record)

        return record

    def decide_for_asset(
        self,
        asset: str,
        technical_engine: TechnicalAnalysisEngine | None = None,
        macro_repo: MacroSnapshotRepository | None = None,
        persist: bool = True,
    ) -> AIDecision:
        """Mevcut tüm engine çıktılarını otomatik toplayıp karar üretir.

        NewsScore henüz yok (EventIntelligenceEngine bekliyor, AŞAMA 16+).
        MacroScore, her istekte yeniden hesaplanmaz — piyasa geneli olduğu için
        en son kaydedilmiş `macro_snapshots` kaydı kullanılır (macro engine
        ayrı bir zamanlamayla / talep üzerine çalıştırılır).
        """
        engine = technical_engine or TechnicalAnalysisEngine()
        analysis, analysis_id = engine.analyze_with_id(asset, persist=persist)

        macro, macro_id = (macro_repo or MacroSnapshotRepository()).get_latest_with_id()

        return self.decide(
            asset=asset,
            technical_score=analysis.technical_score,
            macro_score=macro.macro_score if macro else None,
            technical_confidence=analysis.confidence,
            technical_analysis_id=analysis_id,
            macro_snapshot_id=macro_id,
            persist=persist,
        )
