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

HATA 18C: `explain()` artık İKİ AYRI, birbirine karışmayan mod sunar --
mimari olarak `_explain_current()` (mevcut, DEĞİŞMEMİŞ canlı yeniden-hesaplama
davranışı) ve `_explain_decision()` (yeni, decision-bound/historical mod).
`decision_id=None` (varsayılan) TAM olarak eski davranışı korur -- var olan
hiçbir çağıran (route dahil) etkilenmez (bkz. HATA 18A bulgu #2: iki ayrı
`GET` çağrısı arasında canlı state değişebiliyordu, hiçbir kimlik/as-of
maruz bırakılmıyordu). `decision_id` verildiğinde, açıklama ARTIK
DecisionEngine'i YENİDEN ÇAĞIRMAZ -- persisted `AIDecision`'ın final_score/
decision/confidence/channel_completeness/weights/decision_thresholds
alanları DOĞRUDAN, KOŞULSUZ kullanılır (bkz. `_explain_decision`
docstring'i, HATA 18A bulgu #2'nin kapanışı). Referanslı technical/news/
macro DETAY kayıtları (zenginleştirilmiş gerekçe metni için) mevcutsa
kullanılır; artık erişilemiyorsa CANLI/GÜNCEL veriyle SESSİZCE
İKAME EDİLMEZ -- bunun yerine persisted skorla birlikte "ayrıntılı kayıt
artık erişilebilir değil" notu düşülür (HATA 18C bölüm 9).
"""

from datetime import datetime, timezone

from app.engines.decision.engine import DecisionEngine, _is_macro_snapshot_fresh_for_consumption
from app.engines.technical.engine import TechnicalAnalysisEngine
from app.models.news_analysis import NewsAnalysis
from app.repositories.ai_decision_repository import AIDecisionRepository
from app.repositories.macro_snapshot_repository import MacroSnapshotRepository
from app.repositories.news_analysis_repository import NewsAnalysisRepository
from app.repositories.news_raw_repository import NewsRawRepository
from app.repositories.technical_analysis_repository import TechnicalAnalysisRepository
from app.services.news.news_selection import (
    NEWS_SCORE_LIMIT,
    _aggregate_news_score,
    select_recent_unique_news_analyses,
)
from app.utils.decision_score_format import format_decision_score
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
        decision_repo: AIDecisionRepository | None = None,
        technical_repo: TechnicalAnalysisRepository | None = None,
    ):
        self._decision_engine = decision_engine or DecisionEngine()
        self._technical_engine = technical_engine or TechnicalAnalysisEngine()
        self._macro_repo = macro_repo or MacroSnapshotRepository()
        self._news_repo = news_repo or NewsAnalysisRepository()
        self._news_raw_repo = news_raw_repo or NewsRawRepository()
        # HATA 18C: yalnızca decision-bound (historical) modda kullanılır --
        # canlı mod (`_explain_current`) bu iki repo'ya HİÇ dokunmaz. Bilinçli
        # olarak LAZY: burada varsayılan (gerçek Firestore) örneği İNŞA
        # EDİLMEZ -- `decision_repo`/`technical_repo` verilmeden `explain()`'i
        # yalnızca canlı modda çağıran mevcut (18C-öncesi) hiçbir test/çağıran
        # bu iki YENİ bağımlılığın inşasından ETKİLENMEMELİDİR.
        self._decision_repo = decision_repo
        self._technical_repo = technical_repo

    def explain(self, asset: str, decision_id: str | None = None) -> dict:
        """HATA 18C: `decision_id=None` (varsayılan) -- TAM olarak eski
        davranış, `_explain_current()`'a delege eder (geriye dönük
        uyumluluk, zorunlu). `decision_id` verildiğinde `_explain_decision()`
        -- persisted `AIDecision`'ı DOĞRUDAN kullanır, DecisionEngine'i
        YENİDEN ÇAĞIRMAZ (bkz. o metodun docstring'i)."""
        if decision_id is not None:
            return self._explain_decision(asset, decision_id)
        return self._explain_current(asset)

    def _explain_current(self, asset: str) -> dict:
        # HATA 17C: bu çağrı için TEK `decision_as_of` -- `DecisionEngine.
        # decide_for_asset()`'inki İLE PAYLAŞILMAZ (ikisi bilinçli olarak
        # BAĞIMSIZ, her biri "şu an" için ayrı hesaplanır -- modül docstring'i,
        # "her zaman mevcut kararın gerekçesi"), ama KENDİ İÇİNDE macro
        # tüketim-tazeliği VE haber `as_of`/causality kontrolleri arasında
        # tutarlıdır (aynı sınır mantığı `decide_for_asset()` ile PAYLAŞILIR --
        # `_is_macro_snapshot_fresh_for_consumption`, `select_recent_unique_
        # news_analyses(as_of=...)`).
        decision_as_of = datetime.now(timezone.utc)

        analysis, analysis_id = self._technical_engine.analyze_with_id(asset, persist=False)
        macro, macro_id = self._macro_repo.get_latest_with_id()
        if macro is not None and not _is_macro_snapshot_fresh_for_consumption(macro.created_at, decision_as_of):
            macro, macro_id = None, None

        # HATA 15E: DecisionEngine.decide_for_asset() ile PAYLAŞILAN seçim
        # yardımcısı -- aynı repo verisiyle çağrıldığında birebir aynı son-
        # NEWS_SCORE_LIMIT-BENZERSİZ-olay üyeliğini/temsilcisini üretir.
        weighted_news = select_recent_unique_news_analyses(
            asset, self._news_repo, self._news_raw_repo, NEWS_SCORE_LIMIT, as_of=decision_as_of
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
            decision_as_of=decision_as_of,
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
        # HATA 18B: `{decision.final_score:+.1f}` YERİNE `format_decision_
        # score(...)` kullanılıyor -- sabit 1-ondalık yuvarlama, eşiğe yakın
        # skorları (ör. 39.996/WEAK_BUY) görsel olarak yanlış katmana
        # (+40.0/BUY) taşıyabiliyordu (bkz. HATA 18A bulgu #1).
        score_text = format_decision_score(decision.final_score, decision.decision, decision.decision_thresholds)
        summary = (
            f"{asset} için '{label}' kararı verildi "
            f"(final skor: {score_text}, "
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
            # HATA 18C bölüm 13: canlı modun KENDİ `decision_as_of`'u --
            # `decision.decision_as_of` ile SAYISAL OLARAK AYNI (aynı
            # `decide()` çağrısına geçirildi) ama BURADA ayrıca, açıkça
            # sızdırılıyor -- daha önce (18C-öncesi) hiç maruz bırakılmıyordu,
            # çağıran taraf bu açıklamanın "ne zaman"a ait olduğunu
            # BİLEMİYORDU (bkz. HATA 18A bulgu #2). Yalnızca ADDITIVE bir alan
            # -- mevcut hiçbir çağıran/test bundan etkilenmez.
            "decision_as_of": decision_as_of,
            "mode": "live",
        }

    def _explain_decision(self, asset: str, decision_id: str) -> dict:
        """HATA 18C: decision-bound (historical) mod -- persisted bir
        `AIDecision`'ın gerekçesini üretir.

        Kilitli ilke (HATA 18A bulgu #2'nin doğrudan kapanışı): final_score/
        decision/confidence/channel_completeness/weights/decision_thresholds
        BURADA ASLA yeniden hesaplanmaz -- `AIDecision`'ın kendi alanları
        KOŞULSUZ, DOĞRUDAN kullanılır. `DecisionEngine.decide()`/
        `decide_for_asset()`, canlı `TechnicalAnalysisEngine`, paylaşımlı
        haber seçici (`select_recent_unique_news_analyses`) veya
        `MacroSnapshotRepository.get_latest_with_id()` BURADA HİÇ
        çağrılmaz (bkz. test_explanation_decision_bound.py, "no
        recomputation" mock-tabanlı regresyon testi).

        Referanslı technical/news/macro DETAY kayıtları yalnızca daha
        zengin gerekçe metni İÇİN, ID'leriyle (BUGÜNKÜ "en son"/"tazelik"
        durumundan BAĞIMSIZ -- `MacroSnapshotRepository.get_by_id()`,
        `get_latest_with_id()` DEĞİL) tek tek geri çağrılır. Bir kayıt
        artık bulunamıyorsa (legacy/silinmiş -- olağan akışta olmamalı ama
        savunma amaçlı) CANLI/GÜNCEL veriyle SESSİZCE İKAME EDİLMEZ --
        yalnızca persisted skorla birlikte açık bir "ayrıntılı kayıt artık
        erişilebilir değil" notu eklenir (bölüm 9). Persisted `AIDecision`
        zaten final_score/decision/confidence/completeness için YETERLİ
        olduğundan, hiçbir detay-kaydı eksikliği bu metodun BAŞARISIZ
        olmasına yol açmaz.
        """
        decision_repo = self._decision_repo or AIDecisionRepository()
        technical_repo = self._technical_repo or TechnicalAnalysisRepository()

        decision = decision_repo.get_by_id(decision_id)
        if decision is None:
            raise LookupError(f"'{decision_id}' kimlikli bir karar bulunamadı.")
        if decision.asset != asset:
            raise LookupError(
                f"'{decision_id}' kimlikli karar '{decision.asset}' varlığına ait, '{asset}' değil."
            )

        label = _DECISION_LABELS.get(decision.decision, decision.decision)
        score_text = format_decision_score(decision.final_score, decision.decision, decision.decision_thresholds)
        summary = (
            f"{asset} için '{label}' kararı verildi "
            f"(final skor: {score_text}, "
            f"sinyal mutabakatı: {format_percent_value(decision.confidence)}, "
            f"veri kapsamı: {format_percent_fraction(decision.channel_completeness)})."
        )

        missing: list[str] = []

        technical_reasons: list[str] = []
        if decision.technical_score is not None:
            technical = (
                technical_repo.get_by_id(decision.technical_analysis_id)
                if decision.technical_analysis_id is not None
                else None
            )
            if technical is not None:
                technical_reasons = _top_reasons(technical.components, _TECHNICAL_LABELS)
            else:
                missing.append(
                    f"Bu kararın teknik skoru {decision.technical_score:+.1f} idi; "
                    "ayrıntılı geçmiş teknik kayıt artık erişilebilir değil."
                )

        news_reasons: list[str] = []
        if decision.news_score is None:
            missing.append("Bu varlık için bu karar sırasında karara dahil edilmiş bir haber yoktu.")
        else:
            resolved_news = [
                found
                for news_id in decision.news_analysis_ids
                if (found := self._news_repo.get_by_news_id(news_id, asset)) is not None
            ]
            news_reasons = _news_reasons(resolved_news)
            unresolved_count = len(decision.news_analysis_ids) - len(resolved_news)
            if unresolved_count:
                missing.append(
                    f"Bu karara katkı sağlayan {unresolved_count} haber kaydı artık "
                    "ayrıntılı olarak erişilebilir değil."
                )

        macro_reasons: list[str] = []
        if decision.macro_score is None:
            missing.append("Güncel bir makro veri anlık görüntüsü bu karara dahil edilmemişti.")
        else:
            macro = (
                self._macro_repo.get_by_id(decision.macro_snapshot_id)
                if decision.macro_snapshot_id is not None
                else None
            )
            if macro is not None:
                macro_reasons = _top_reasons(macro.components, _MACRO_LABELS)
            else:
                missing.append(
                    f"Bu kararın makro skoru {decision.macro_score:+.1f} idi; "
                    "ayrıntılı geçmiş makro kayıt artık erişilebilir değil."
                )

        return {
            "asset": asset,
            "decision": decision.decision,
            "final_score": decision.final_score,
            "confidence": decision.confidence,
            "summary": summary,
            "technical_weight": decision.technical_weight,
            "news_weight": decision.news_weight,
            "macro_weight": decision.macro_weight,
            "technical_reasons": technical_reasons,
            "macro_reasons": macro_reasons,
            "news_reasons": news_reasons,
            # HATA 18C: `AIDecision.news_analysis_ids`'in TAMAMI -- yalnızca
            # BUGÜN detay-kaydı geri çağrılabilenler DEĞİL. Bu liste, kararın
            # ÜRETİLDİĞİ anda GERÇEKTEN katkı sağlayan kimliklerin değişmez
            # tarihsel kaydıdır; bugünkü retrievability'si bu FACT'ı
            # değiştirmez (bkz. bölüm 18).
            "news_analysis_ids": list(decision.news_analysis_ids),
            "missing": missing,
            "decision_id": decision_id,
            "decision_as_of": decision.decision_as_of,
            "mode": "decision_bound",
        }
