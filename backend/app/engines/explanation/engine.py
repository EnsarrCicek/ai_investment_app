"""ExplanationEngine — AŞAMA 24.

Kural tabanlı (LLM gerektirmez): TechnicalAnalysisEngine ve MacroAnalysisEngine
zaten hesapladığı bileşen kırılımını (RSI, MACD, trend, VIX, DXY vb.) Türkçe
şablon cümlelere çevirir. Ana doküman bölüm 72'deki "Missing Data Davranışı"
ilkesiyle uyumlu: news_score ve makro veri eksikliği açıkça belirtilir.
Burada üretilen kararlar AI Decision History'e YAZILMAZ (persist=False) —
bu uç nokta yalnızca mevcut kararın gerekçesini gösterir, yeni bir karar kaydı
oluşturmaz.

HATA 15E: haber tarafı artık `DecisionEngine.decide_for_asset()` ile AYNI
paylaşımlı seçim yardımcısını (`select_recent_unique_news_analyses`, bkz.
`app.services.news.news_selection`) kullanır -- önceden burada HAM
`news_repo.list_for_asset(limit=NEWS_SCORE_LIMIT)` okunuyordu, HATA 15B/15C
dedup+reliability katmanına HİÇ bağlanmıyordu (bilinen, disclosed açık konu
-- bkz. HATA 15A / HATA 15C FINAL raporları). Artık DecisionEngine ile
BİREBİR aynı son-`NEWS_SCORE_LIMIT`-BENZERSİZ-olay üyeliğini/temsilcisini
görür. Bilinçli olarak `app.engines.decision.engine`'den DEĞİL doğrudan
paylaşımlı modülden import edilir -- ExplanationEngine, DecisionEngine'in
private internal'larına bağımlı OLMAMALI (bkz. news_selection.py docstring'i).

Bu motor, halihazırda Firestore'a kalıcı olarak yazılmış `NewsAnalysis`
kayıtlarını okur -- canlı makale fetch'i (`fetch_article_text`) veya yeniden
LLM analizi (`EventIntelligenceEngine.analyze_item`) ASLA tetiklemez (bkz.
test_explanation_news_consistency.py provenance-regresyon testi).
"""

from app.engines.decision.engine import DecisionEngine
from app.engines.technical.engine import TechnicalAnalysisEngine
from app.models.news_analysis import NewsAnalysis
from app.repositories.macro_snapshot_repository import MacroSnapshotRepository
from app.repositories.news_analysis_repository import NewsAnalysisRepository
from app.repositories.news_raw_repository import NewsRawRepository
from app.services.news.news_selection import (
    NEWS_SCORE_LIMIT,
    _aggregate_news_score,
    select_recent_unique_news_analyses,
)
from app.utils.percent_format import format_percent_fraction, format_percent_value

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

_EVENT_TYPE_LABELS = {
    "earnings": "Bilanço/Kâr",
    "regulatory": "Düzenleyici Karar",
    "corporate_action": "Kurumsal Eylem",
    "macro": "Makro Haber",
    "market_sentiment": "Piyasa Algısı",
    "other": "Diğer",
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


def _news_reasons(analyses: list[NewsAnalysis], limit: int = 3) -> list[str]:
    """En önemli (importance*confidence) haberleri kısa gerekçeleriyle listeler."""
    ranked = sorted(analyses, key=lambda a: a.importance * a.confidence, reverse=True)
    return [
        f"{_EVENT_TYPE_LABELS.get(a.event_type, a.event_type)}: {a.reasoning} "
        f"({a.sentiment_score:+.0f} puan, {_direction_phrase(a.sentiment_score)})"
        for a in ranked[:limit]
    ]


class ExplanationEngine:
    def __init__(
        self,
        decision_engine: DecisionEngine | None = None,
        technical_engine: TechnicalAnalysisEngine | None = None,
        macro_repo: MacroSnapshotRepository | None = None,
        news_repo: NewsAnalysisRepository | None = None,
        news_raw_repo: NewsRawRepository | None = None,
    ):
        self._decision_engine = decision_engine or DecisionEngine()
        self._technical_engine = technical_engine or TechnicalAnalysisEngine()
        self._macro_repo = macro_repo or MacroSnapshotRepository()
        self._news_repo = news_repo or NewsAnalysisRepository()
        self._news_raw_repo = news_raw_repo or NewsRawRepository()

    def explain(self, asset: str) -> dict:
        analysis, analysis_id = self._technical_engine.analyze_with_id(asset, persist=False)
        macro, macro_id = self._macro_repo.get_latest_with_id()

        # HATA 15E: DecisionEngine.decide_for_asset() ile PAYLAŞILAN seçim
        # yardımcısı -- aynı repo verisiyle çağrıldığında birebir aynı son-
        # NEWS_SCORE_LIMIT-BENZERSİZ-olay üyeliğini/temsilcisini üretir.
        weighted_news = select_recent_unique_news_analyses(
            asset, self._news_repo, self._news_raw_repo, NEWS_SCORE_LIMIT
        )
        news_analyses = [w.analysis for w in weighted_news]

        decision = self._decision_engine.decide(
            asset=asset,
            technical_score=analysis.technical_score,
            news_score=_aggregate_news_score(weighted_news),
            macro_score=macro.macro_score if macro else None,
            technical_analysis_id=analysis_id,
            news_analysis_ids=[a.news_id for a in news_analyses],
            macro_snapshot_id=macro_id,
            persist=False,
        )

        label = _DECISION_LABELS.get(decision.decision, decision.decision)
        # HATA 5C-UI3 (31.08.2026): eski "güven: %XX" ifadesi DecisionEngine
        # 1.1.0'ın iki AYRI metriğini (bkz. 5C3B) tek bir generic kelimeye
        # sıkıştırıyordu. `decision` burada zaten `decide(persist=False)`'in
        # ürettiği TAM AIDecision nesnesi -- `channel_completeness` HER ZAMAN
        # (persist=False dahil) hesaplanmış haldedir (bkz. `decision/engine.py`
        # `decide()` -- `persist` yalnızca `_decision_repo.add()` çağrısını
        # etkiler, alanları DEĞİL), bu yüzden ek bir None fallback GEREKMEZ.
        # HATA 5C-UI4 (31.08.2026): `%{value:.0f}` YERİNE `format_percent_*`
        # kullanılıyor -- Python'un `.0f}` formatı round-half-to-EVEN (62.5 ->
        # "62"), Flutter'ın `toStringAsFixed(0)`'ı ise round-half-UP (62.5 ->
        # "63") kullanıyordu; bu, aynı kararın ekranlar arasında farklı
        # yüzdeyle görünmesine yol açıyordu (bkz. HATA 5C-UI3 raporu).
        summary = (
            f"{asset} için '{label}' kararı verildi "
            f"(final skor: {decision.final_score:+.1f}, "
            f"sinyal mutabakatı: {format_percent_value(decision.confidence)}, "
            f"veri kapsamı: {format_percent_fraction(decision.channel_completeness)})."
        )

        missing = []
        if decision.news_score is None:
            missing.append("Bu varlık için henüz analiz edilmiş bir haber yok, karara dahil edilmedi.")
        if macro is None:
            missing.append("Güncel bir makro veri anlık görüntüsü bulunamadı.")

        return {
            "asset": asset,
            "decision": decision.decision,
            "final_score": decision.final_score,
            "confidence": decision.confidence,
            "summary": summary,
            "technical_weight": decision.technical_weight,
            "news_weight": decision.news_weight,
            "macro_weight": decision.macro_weight,
            "technical_reasons": _top_reasons(analysis.components, _TECHNICAL_LABELS),
            "macro_reasons": _top_reasons(macro.components, _MACRO_LABELS) if macro else [],
            "news_reasons": _news_reasons(news_analyses),
            # HATA 15E: DecisionEngine.decide_for_asset()'in ürettiği
            # `news_analysis_ids` ile AYNI kimlik listesi (yalnızca ID'ler --
            # HATA 15D provenance alanları/hash'leri BURADA sızdırılmıyor).
            # Parity testinin kilitlediği load-bearing invariant budur.
            "news_analysis_ids": [a.news_id for a in news_analyses],
            "missing": missing,
        }
