"""DecisionEngine — ana doküman bölüm 17-19, 32-33, 72.

Durum: EventIntelligenceEngine artık yazıldı (AŞAMA 16+, OpenAI GPT-5.6
Luna). MacroAnalysisEngine ise AŞAMA 21-22'de eklendi. Bu, bölüm 72'deki
"Missing Data Davranışı" ilkesinin canlı kanıtıdır: DecisionEngine eksik
skorları örtbas ETMEZ — kalan skorların ağırlıklarını normalize eder.
Her iki motor eklendiğinde de `decide()`'ın çekirdek final_score mantığı
DEĞİŞMEDİ (tasarım hedefi buydu) — yalnızca `decide_for_asset()` artık
macro_score ve news_score'u da topluyor.

28.08.2026 (HATA 5C3B): `confidence` ("Sinyal Mutabakatı") ve `channel_
completeness` ("Veri Kapsamı") ARTIK AYRI iki alandır -- veri eksikliği
`confidence`'ı DEĞİL, yalnızca `channel_completeness`'i etkiler. `confidence`
mevcut kanalların final kararla YÖNSEL mutabakatını ölçer (bkz. `decide()`,
`_DIRECTION_BY_CLASSIFICATION`); `technical_confidence` bağımlılığı ve `0.6`
sabit fallback'i RETIRED (bkz. HATA 5C1/5C2/5C3A/5C3B audit zinciri,
TEKNIK_ANALIZ_METODOLOJISI.md).

Maliyet kararı: `decide_for_asset()` her çağrıldığında (Dashboard her
açıldığında GET /decisions/{symbol} üzerinden) yeni bir OpenAI çağrısı
YAPMAZ — yalnızca daha önce ayrıca tetiklenmiş (POST /news/{symbol}/analyze)
ve Firestore'a zaten kaydedilmiş NewsAnalysis kayıtlarını okur. Bu, macro
tarafında da uygulanan "en son kaydedilmiş sonucu oku, otomatik yeniden
hesaplama" desenidir — kararın kendisi asla LLM çağrısına bağımlı/yavaş
hale gelmez ve maliyet yalnızca haber analizi ayrıca istendiğinde oluşur.
"""

import math
from datetime import datetime, timezone

from app.engines.technical.engine import TechnicalAnalysisEngine
from app.models.ai_decision import AIDecision
from app.models.news_analysis import NewsAnalysis
from app.repositories.ai_decision_repository import AIDecisionRepository
from app.repositories.macro_snapshot_repository import MacroSnapshotRepository
from app.repositories.news_analysis_repository import NewsAnalysisRepository
from app.repositories.system_config_repository import SystemConfigRepository

ENGINE_VERSION = "1.1.0"

# HATA 5C3B (28.08.2026): production'da ARTIK bir "missing config fallback"
# DEĞİLDİR -- `decision_weights`/`decision_thresholds` Firestore dokümanları
# `resolve_decision_weights()`/`resolve_decision_thresholds()` (fail-fast,
# `get_raw()` tabanlı) ile okunur; eksik/geçersizse SESSİZCE bu sabitlere
# düşülmez. Kalan kullanım alanı: testlerde/scratch araçlarda "geçerli,
# tam bir referans config" olarak (bkz. `technical/engine.py`'deki
# `DEFAULT_WEIGHTS`'in AYNI rolü, HATA 5B2D).
DEFAULT_WEIGHTS = {"technical": 0.50, "news": 0.30, "macro": 0.20}

# Ana doküman bölüm 18: +40..100 AL, +15..39 ZAYIF AL, -14..14 TUT, -39..-15 ZAYIF SAT, -100..-40 SAT
DEFAULT_THRESHOLDS = {"buy": 40.0, "weak_buy": 15.0, "weak_sell": -15.0, "sell": -40.0}

NEWS_SCORE_LIMIT = 10

# HATA 5C3B: `_classify()`'ın 5 durumlu (BUY/WEAK_BUY/HOLD/WEAK_SELL/SELL)
# çıktısını, Decision Agreement için 3 durumlu bir yöne indirger -- threshold
# değerlerini/operatörlerini/sıralamasını İKİNCİ KEZ YAZMADAN: `_classify()`
# TEK source olarak kalır, bu yalnızca onun çıktısını yeniden etiketler.
_DIRECTION_BY_CLASSIFICATION = {
    "BUY": "POSITIVE",
    "WEAK_BUY": "POSITIVE",
    "HOLD": "NEUTRAL",
    "WEAK_SELL": "NEGATIVE",
    "SELL": "NEGATIVE",
}


def resolve_decision_weights(raw_doc: dict | None) -> dict[str, float]:
    """`decision_weights` config'i için FAIL-FAST okuma sözleşmesi (HATA
    5C2C/5C3B) -- `technical/scoring.py::resolve_indicator_weights()` ile
    AYNI desen: `get()`'in auto-seed/sessiz-partial-merge davranışı (HATA
    5B2C'nin kök nedeni) burada TEKRARLANMAZ; `get_raw()`'ın ham çıktısı alınır.

      - `raw_doc is None` (doküman HİÇ yok): `ValueError` (FAIL-FAST) --
        `DEFAULT_WEIGHTS`'e SESSİZCE düşülmez, bu artık production config
        corruption/deletion olarak ele alınır.
      - `raw_doc` VAR ama eksik/fazla anahtar içeriyor VEYA herhangi bir
        değer non-numeric/bool/NaN/±inf/negatifse: `ValueError` (FAIL-FAST).
      - Ağırlıkların toplamı <= 0 ise: `ValueError` (tek tek sıfır ağırlık
        SERBESTTİR -- ör. `technical=0` -- ama TÜMÜ sıfır/negatif olamaz).
      - `raw_doc` tam ve geçerliyse: olduğu gibi (kopyalanarak) döner.
    """
    if raw_doc is None:
        raise ValueError(
            "'decision_weights' config dokümanı Firestore'da bulunamadı -- bu, "
            "DecisionEngine 1.1.0 için REQUIRED bir production config'tir; code "
            "DEFAULT_WEIGHTS'e SESSİZCE düşülmez (production config corruption/"
            "deletion olarak ele alınır) -- fail-fast."
        )

    expected_keys = {"technical", "news", "macro"}
    actual_keys = set(raw_doc)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unknown = sorted(actual_keys - expected_keys)
        raise ValueError(
            "'decision_weights' config eksik/geçersiz key seti taşıyor "
            f"(missing={missing}, unknown={unknown}) -- fail-fast, HATA 5B2C'deki "
            "sessiz partial-merge/config-drift kalıbı TEKRARLANMIYOR."
        )

    for key, value in raw_doc.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(
                f"'decision_weights.{key}' geçersiz değer: {value!r} "
                "(finite, negatif olmayan bir sayı olmalı)."
            )

    if sum(raw_doc.values()) <= 0:
        raise ValueError("'decision_weights': ağırlıkların toplamı > 0 olmalı.")

    return {k: float(v) for k, v in raw_doc.items()}


def resolve_decision_thresholds(raw_doc: dict | None) -> dict[str, float]:
    """`decision_thresholds` config'i için FAIL-FAST okuma sözleşmesi (HATA
    5C2C/5C3B). `[-100,100]` gibi YENİ bir range invariant'ı KASITLI OLARAK
    EKLENMEDİ -- `_classify()` herhangi bir sıralı 4-eşik kümesiyle doğru
    çalışır, bu ek bir hata senaryosunu ÖNLEMEZ.

      - `raw_doc is None`: `ValueError` (FAIL-FAST) -- `DEFAULT_THRESHOLDS`'a
        SESSİZCE düşülmez.
      - `raw_doc` VAR ama eksik/fazla anahtar içeriyor VEYA herhangi bir değer
        non-numeric/bool/NaN/±inf ise: `ValueError` (FAIL-FAST).
      - Sıralama `sell < weak_sell < weak_buy < buy` sağlanmıyorsa: `ValueError`
        -- bu, `_classify()`'ın KENDİ if/elif zincirinin doğru/anlamlı
        çalışması için gereken, threshold config'inin kendi iç tutarlılığıdır
        (yeni bir DEĞER kısıtı değil, mevcut semantics'in bir ön-koşulu).
      - `raw_doc` tam ve geçerliyse: olduğu gibi (kopyalanarak) döner.
    """
    if raw_doc is None:
        raise ValueError(
            "'decision_thresholds' config dokümanı Firestore'da bulunamadı -- bu, "
            "DecisionEngine 1.1.0 için REQUIRED bir production config'tir; code "
            "DEFAULT_THRESHOLDS'a SESSİZCE düşülmez -- fail-fast."
        )

    expected_keys = {"buy", "weak_buy", "weak_sell", "sell"}
    actual_keys = set(raw_doc)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unknown = sorted(actual_keys - expected_keys)
        raise ValueError(
            "'decision_thresholds' config eksik/geçersiz key seti taşıyor "
            f"(missing={missing}, unknown={unknown}) -- fail-fast, HATA 5B2C'deki "
            "sessiz partial-merge/config-drift kalıbı TEKRARLANMIYOR."
        )

    for key, value in raw_doc.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(
                f"'decision_thresholds.{key}' geçersiz değer: {value!r} (finite bir sayı olmalı)."
            )

    if not (raw_doc["sell"] < raw_doc["weak_sell"] < raw_doc["weak_buy"] < raw_doc["buy"]):
        raise ValueError(
            "'decision_thresholds': sell < weak_sell < weak_buy < buy sıralaması sağlanmalı "
            f"(sell={raw_doc['sell']}, weak_sell={raw_doc['weak_sell']}, "
            f"weak_buy={raw_doc['weak_buy']}, buy={raw_doc['buy']})."
        )

    return {k: float(v) for k, v in raw_doc.items()}


def _aggregate_news_score(analyses: list[NewsAnalysis]) -> float | None:
    """Son N haber analizinin confidence-ağırlıklı ortalama sentiment_score'u.

    Confidence ağırlıklandırması: modelin düşük güvenle verdiği bir analiz,
    yüksek güvenle verilen bir analizle aynı ağırlıkta kararı etkilememeli.
    Hiç analiz yoksa None döner (Missing Data Davranışı — 0 gibi yanlış bir
    "nötr" varsayımı YAPILMAZ).
    """
    if not analyses:
        return None
    weight_total = sum(a.confidence for a in analyses)
    if weight_total == 0:
        return None
    weighted_sum = sum(a.sentiment_score * a.confidence for a in analyses)
    return round(weighted_sum / weight_total, 2)


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
        technical_analysis_id: str | None = None,
        news_analysis_ids: list[str] | None = None,
        macro_snapshot_id: str | None = None,
        persist: bool = True,
    ) -> AIDecision:
        # HATA 5C3B (28.08.2026): `get()` (auto-seed + sessiz partial-merge,
        # HATA 5B2C'nin kök nedeni) ARTIK KULLANILMIYOR -- `get_raw()` +
        # fail-fast resolver'lar (yukarıda) production path'te TEK kaynak.
        weights = resolve_decision_weights(self._config_repo.get_raw("decision_weights"))
        thresholds = resolve_decision_thresholds(self._config_repo.get_raw("decision_thresholds"))

        scores = {"technical": technical_score, "news": news_score, "macro": macro_score}
        available = {k: v for k, v in scores.items() if v is not None}
        if not available:
            raise ValueError(f"'{asset}' için hiçbir analiz skoru mevcut değil (INSUFFICIENT_DATA)")

        available_weight = sum(weights[k] for k in available)
        # HATA 5C3B madde 8: config valid olsa bile (ör. technical=0, news=.7,
        # macro=.3) mevcut skorların TAMAMI sıfır-ağırlıklı kanallara ait
        # olabilir -- eski kod burada guard'sız `ZeroDivisionError` fırlatırdı.
        # Explicit, doğru semantikli bir hata: veri GERÇEKTEN var (INSUFFICIENT_
        # DATA YANLIŞ olurdu), yalnızca configured ağırlığı sıfır. 0 score/
        # confidence UYDURULMAZ.
        if available_weight == 0:
            raise ValueError(
                f"'{asset}' için mevcut skorların tamamı sıfır ağırlıklı kanallara ait "
                "(NO_POSITIVE_WEIGHT_AVAILABLE) -- karar üretilemez."
            )

        final_score = round(sum(scores[k] * weights[k] for k in available) / available_weight, 2)

        # HATA 5C3B madde 13: "Veri Kapsamı" -- yalnızca kanal/ağırlık
        # mevcudiyetini ölçer, `confidence`'a KARIŞTIRILMAZ (ayrı, çarpılmayan/
        # ortalaması alınmayan bir alan). Guard'lar (`not available`,
        # `available_weight==0`) sayesinde persist edilen bir karar için bu
        # HER ZAMAN (0,1] aralığındadır, asla tam 0 değildir.
        channel_completeness = available_weight / sum(weights.values())

        # HATA 5C3B madde 9-11 — "Sinyal Mutabakatı": mevcut kanalların, final
        # kararla AYNI yönde olup olmadığı. Threshold logic İKİNCİ KEZ
        # YAZILMADI -- her skor `_classify()`'dan (TEK source) geçirilip 3
        # duruma (`_DIRECTION_BY_CLASSIFICATION`) indirgeniyor. technical_
        # confidence/news_confidence/macro_confidence GİRDİ OLARAK KULLANILMIYOR
        # -- her kanal yalnızca KENDİ SKORUNUN yönüyle temsil ediliyor.
        decision = _classify(final_score, thresholds)
        final_direction = _DIRECTION_BY_CLASSIFICATION[decision]
        agreement = sum(
            weights[k]
            for k in available
            if _DIRECTION_BY_CLASSIFICATION[_classify(scores[k], thresholds)] == final_direction
        ) / available_weight
        confidence = round(agreement * 100, 2)

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
            channel_completeness=round(channel_completeness, 2),
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
        news_repo: NewsAnalysisRepository | None = None,
        persist: bool = True,
    ) -> AIDecision:
        """Mevcut tüm engine çıktılarını otomatik toplayıp karar üretir.

        MacroScore, her istekte yeniden hesaplanmaz — piyasa geneli olduğu için
        en son kaydedilmiş `macro_snapshots` kaydı kullanılır (macro engine
        ayrı bir zamanlamayla / talep üzerine çalıştırılır). NewsScore de aynı
        şekilde: burada YENİ bir EventIntelligenceEngine/OpenAI çağrısı
        YAPILMAZ, yalnızca daha önce POST /news/{symbol}/analyze ile üretilmiş
        NewsAnalysis kayıtları okunur (bkz. modül docstring'i — maliyet kararı).
        """
        engine = technical_engine or TechnicalAnalysisEngine()
        analysis, analysis_id = engine.analyze_with_id(asset, persist=persist)

        macro, macro_id = (macro_repo or MacroSnapshotRepository()).get_latest_with_id()

        news_analyses = (news_repo or NewsAnalysisRepository()).list_for_asset(asset, limit=NEWS_SCORE_LIMIT)

        return self.decide(
            asset=asset,
            technical_score=analysis.technical_score,
            news_score=_aggregate_news_score(news_analyses),
            macro_score=macro.macro_score if macro else None,
            technical_analysis_id=analysis_id,
            news_analysis_ids=[a.news_id for a in news_analyses],
            macro_snapshot_id=macro_id,
            persist=persist,
        )
