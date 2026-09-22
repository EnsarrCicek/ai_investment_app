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
from app.repositories.ai_decision_repository import AIDecisionRepository
from app.repositories.macro_snapshot_repository import MacroSnapshotRepository
from app.repositories.news_analysis_repository import NewsAnalysisRepository
from app.repositories.news_raw_repository import NewsRawRepository
from app.repositories.system_config_repository import SystemConfigRepository
from app.research.canonical_hash import content_sha256
from app.services.news.news_selection import (
    NEWS_SCORE_LIMIT,
    _aggregate_news_score,
    _deduplicate_news_analyses,
    _WeightedNewsAnalysis,
    select_recent_unique_news_analyses,
)

# HATA 15E: `_WeightedNewsAnalysis`/`_aggregate_news_score`/`NEWS_SCORE_LIMIT`/
# `_deduplicate_news_analyses` artık `app.services.news.news_selection`'da
# yaşıyor -- `DecisionEngine` VE `ExplanationEngine` arasında PAYLAŞILAN tek
# seçim katmanı (bkz. o modülün docstring'i). Burada yukarıdaki import
# satırıyla RE-EXPORT edilir -- mevcut testler/çağıranlar
# `from app.engines.decision.engine import _WeightedNewsAnalysis` gibi
# import'ları DEĞİŞTİRMEDEN çalışmaya devam eder.

# HATA 17D: HATA 5C3B'nin "1.1.0"'ı (confidence/channel_completeness
# ayrımı) SONRASINDA, HATA 17B (round-before-classify düzeltmesi --
# classification/persisted final_score artık HAM/unrounded değer) VE HATA
# 17C (macro consumption-tazeliği + haber as_of/causality gate'i --
# `decide_for_asset()`'in girdi UYGUNLUĞU) her ikisi de GERÇEK bilimsel/
# uygunluk davranışı değiştirdi ama versiyon bump'lamadı (o ticket'ların
# kapsamı buydu, geriye dönük DÜZELTİLMİYOR). 17D bunun ÜSTÜNE yalnızca
# provenance alanları ekliyor (davranış değişikliği YOK) ama bu, "düzeltilmiş
# metodoloji" (17B+17C+17D) altında üretilen kararları ESKİ "1.1.0" kararlarından
# ayırt etmek için TEK, kasıtlı bir yakalama bump'ı yapmanın doğru anıdır --
# üç ayrı bump YOK, sahte bir "17D provenance-only bump" da YOK: bu numara
# GERÇEKTEN "1.1.0"dan farklı, gerçekten daha yeni bir bilimsel sözleşmeyi
# temsil ediyor. Threshold snapshot'ının KENDİSİ (bkz. `AIDecision.
# decision_thresholds`/`decision_config_sha256`) bu versiyon numarasının
# YERİNE GEÇMEZ -- config kod DEĞİŞMEDEN değişebilir, ikisi de AYRI AYRI
# persist edilir.
ENGINE_VERSION = "1.2.0"

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

# HATA 17C: HATA 16C'nin `MAX_OBSERVATION_AGE_DAYS`'i, bir MacroSnapshot'ın
# GÖSTERGELERİNİN ÜRETİM ANINDA taze olup olmadığını garanti eder -- bu,
# snapshot'ın KENDİSİNİN bugün, DecisionEngine tarafından TÜKETİLİRKEN hâlâ
# yeterince taze olduğu anlamına GELMEZ (ör. macro job'ı tetikleyen scheduler
# 3 hafta önce sessizce kırılmışsa, o snapshot üretildiği anda geçerliydi ama
# bugün için ARTIK GEÇERLİ DEĞİLDİR -- HATA 17A bulgu #3). `MacroAnalysisEngine`
# talep üzerine/API-tetiklemeli çalışır (bkz. `engines/macro/engine.py` modül
# docstring'i, `POST`/`GET /analysis/macro`) -- repo'da GÜVENİLİR, sabit bir
# scheduler cadence'i (cron/Cloud Scheduler config) YOK, bu yüzden bu eşik
# İSTATİSTİKSEL bir cadence'ten türetilemedi (madde 8, dürüstçe). Bunun
# yerine HATA 16C'nin ZATEN gerekçelendirilmiş, muhafazakâr (sıradan hafta
# sonu + tatil-bitişik hafta sonunu güvenle kapsayan, ama haftalarca eski
# gerçek stale veriyi yakalayan) 5-günlük takvim eşiğiyle AYNI büyüklük
# kullanılır -- bu tutarlılık kasıtlıdır: bir MacroSnapshot'ın "bu haftaki"
# görünümü temsil etmeyi bıraktığı an, tek bir göstergenin stale olduğu
# andan daha az şüpheli DEĞİLDİR. Karşılaştırma HATA 16C'yle AYNI stilde
# (takvim tarihi, UTC, sınır DAHİL, naive/gelecek-tarihli REDDEDİLİR).
MAX_MACRO_SNAPSHOT_CONSUMPTION_AGE_DAYS = 5


def _is_macro_snapshot_fresh_for_consumption(
    created_at,
    decision_as_of: datetime,
    max_age_days: int = MAX_MACRO_SNAPSHOT_CONSUMPTION_AGE_DAYS,
) -> bool:
    """HATA 17C: bir `MacroSnapshot.created_at`'in, `decision_as_of` anındaki
    bir karar için TÜKETİM açısından hâlâ taze olup olmadığı -- HATA 16C'nin
    `_is_fresh_observation()`'ından KASITLI OLARAK AYRI bir kontrol (üretim-
    anı gösterge tazeliği vs. tüketim-anı snapshot tazeliği, farklı
    katmanlar). Stale bir snapshot SİLİNMEZ/geçersiz İŞARETLENMEZ -- üretildiği
    an geçerliydi, yalnızca BU karar için kullanılamaz (bkz. `decide_for_asset`).
    """
    if not isinstance(created_at, datetime) or created_at.tzinfo is None:
        return False
    created_utc = created_at.astimezone(timezone.utc)
    as_of_utc = decision_as_of.astimezone(timezone.utc)
    age_days = (as_of_utc.date() - created_utc.date()).days
    return 0 <= age_days <= max_age_days


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


def _sorted_copy(d: dict[str, float]) -> dict[str, float]:
    return {k: d[k] for k in sorted(d)}


def compute_decision_config_sha256(weights: dict[str, float], thresholds: dict[str, float]) -> str:
    """HATA 17D: `MacroAnalysisEngine.compute_macro_config_sha256` (HATA 16D)
    İLE AYNI dar-kapsamlı desen -- yalnızca bir kararı klasifiye eden CONFIG
    KİMLİĞİ üzerinden (resolved decision_weights + resolved decision_
    thresholds), hangi skorların/ID'lerin geldiğinden BAĞIMSIZ. `created_at`/
    `decision_as_of`/input skorları/doküman ID'leri KASITLI OLARAK dahil
    DEĞİL -- onlar runtime/input provenance'tır, config KİMLİĞİ değil (bkz.
    modül raporu madde 6). `decision_weights`/`decision_thresholds` dışında,
    `decide()`'da klasifikasyonu/skorlamayı doğrudan etkileyen BAŞKA bir
    Firestore config değeri YOK (audit edildi) -- bu yüzden payload yalnızca
    bu ikisini bağlar. `app.research.canonical_hash.content_sha256`
    (proje-genelindeki TEK paylaşılan kanonik JSON/SHA-256 ilkeli, HATA
    12N2A) kullanılır -- sıralı anahtarlar + UTF-8, dict ekleme sırasından
    BAĞIMSIZ, Python `hash()` KULLANILMAZ.
    """
    payload = {"weights": _sorted_copy(weights), "thresholds": _sorted_copy(thresholds)}
    return content_sha256(payload)


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
        decision_as_of: datetime | None = None,
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

        # HATA 17B (round-before-classify bugfix): `final_score` ARTIK
        # `round(...)` EDİLMİYOR -- ham (unrounded) ağırlıklı ortalama
        # DOĞRUDAN `_classify()`'a geçirilir VE persist edilir. Önceki
        # davranış (`round(raw, 2)` sonra `_classify(rounded, ...)`)
        # eşik-geçişi bug'ıydı: ör. raw=39.996 (BUY eşiği 40.0'ın ALTINDA,
        # bilimsel olarak WEAK_BUY) `round(39.996, 2) == 40.0` olduğundan
        # YANLIŞLIKLA BUY'a sınıflandırılıyordu (bkz. HATA 17A audit
        # bulgu #1). Persisted `final_score` ile `decision` arasında ASLA
        # tutarsızlık (ör. final_score=40.00 yanında decision=WEAK_BUY)
        # oluşmaması için ikisi de AYNI (ham) değerden türetilir -- ikinci
        # bir "rounded_final_score"/"display_score" alanı EKLENMEDİ (bkz.
        # modül raporu). 2 ondalığa yuvarlama artık yalnızca sunum
        # katmanında (varsa) yapılmalı, bilimsel depoda DEĞİL.
        final_score = sum(scores[k] * weights[k] for k in available) / available_weight

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

        # HATA 17C bölüm 14: `decision_as_of` verilmemişse (mevcut/eski
        # çağıranlar) TEK bir `now()` burada üretilir ve HEM `created_at`
        # HEM `decision_as_of` için kullanılır -- iki ayrı `datetime.now()`
        # çağrısı arasında (teorik) bir sürüklenme riski YOK. `decide_for_
        # asset()` kendi `decision_as_of`'unu ÖNCEDEN (macro/news freshness
        # kontrollerinde de kullanılan AYNI değer) yakalayıp buraya geçirir.
        now = decision_as_of or datetime.now(timezone.utc)

        record = AIDecision(
            asset=asset,
            created_at=now,
            decision_as_of=now,
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
            # HATA 17D: threshold snapshot + config kimlik hash'i -- final_score
            # (zaten reproducible, weights de zaten yukarıda persist ediliyor)
            # İLE BİRLİKTE, `decision` LABEL'ının (ve ondan türeyen `confidence`'ın)
            # de mevcut Firestore config'i OKUMADAN, yalnızca bu kayıttan
            # yeniden üretilebilmesini sağlar (HATA 17A bulgu #2'nin kapanışı).
            decision_thresholds=dict(thresholds),
            decision_config_sha256=compute_decision_config_sha256(weights, thresholds),
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
        news_raw_repo: NewsRawRepository | None = None,
        persist: bool = True,
    ) -> AIDecision:
        """Mevcut tüm engine çıktılarını otomatik toplayıp karar üretir.

        MacroScore, her istekte yeniden hesaplanmaz — piyasa geneli olduğu için
        en son kaydedilmiş `macro_snapshots` kaydı kullanılır (macro engine
        ayrı bir zamanlamayla / talep üzerine çalıştırılır). NewsScore de aynı
        şekilde: burada YENİ bir EventIntelligenceEngine/OpenAI çağrısı
        YAPILMAZ, yalnızca daha önce POST /news/{symbol}/analyze ile üretilmiş
        NewsAnalysis kayıtları okunur (bkz. modül docstring'i — maliyet kararı).

        HATA 15E: seçim mantığının kendisi (dedup + backfill semantiği,
        eski `_deduplicate_news_analyses`) artık `app.services.news.
        news_selection.select_recent_unique_news_analyses`'te yaşıyor --
        `ExplanationEngine.explain()` de AYNI fonksiyonu çağırır, böylece
        iki motor birebir aynı üyeliği/temsilciyi görür (bkz. o modülün
        docstring'i, test_explanation_news_consistency.py parity testi).

        HATA 15B FINAL: skorlama penceresi "son `NEWS_SCORE_LIMIT` BENZERSİZ
        mantıksal olay" anlamına gelir — "son `NEWS_SCORE_LIMIT` HAM kayıttan
        tekilleştirilmiş alt küme" DEĞİL (bkz. `select_recent_unique_news_
        analyses` docstring'i, HATA 15A bulgu #2).

        HATA 17C: `decision_as_of` bu execution için BİR KEZ yakalanır ve HEM
        macro tüketim-tazeliği kontrolünde HEM haber `as_of`/causality
        filtresinde HEM persist edilen kayıtta kullanılır -- macro/news için
        AYRI `datetime.now()` çağrıları YAPILMAZ (sınır tutarsızlığı riski,
        bkz. `_is_macro_snapshot_fresh_for_consumption`/`select_recent_
        unique_news_analyses` docstring'leri). Stale bir `MacroSnapshot`
        (üretildiği anda geçerliydi ama bugün için çok eski -- HATA 17A
        bulgu #3) bu karar için `None`'a düşürülür; ne snapshot silinir/
        mutasyona uğrar (üretim-anı geçerliliği KORUNUR) ne de `macro_
        snapshot_id` katkı sağlamamış bir referans olarak persist edilir.
        """
        decision_as_of = datetime.now(timezone.utc)

        engine = technical_engine or TechnicalAnalysisEngine()
        analysis, analysis_id = engine.analyze_with_id(asset, persist=persist)

        macro, macro_id = (macro_repo or MacroSnapshotRepository()).get_latest_with_id()
        if macro is not None and not _is_macro_snapshot_fresh_for_consumption(macro.created_at, decision_as_of):
            macro, macro_id = None, None

        weighted_news = select_recent_unique_news_analyses(
            asset,
            news_repo or NewsAnalysisRepository(),
            news_raw_repo,
            NEWS_SCORE_LIMIT,
            as_of=decision_as_of,
        )

        return self.decide(
            asset=asset,
            technical_score=analysis.technical_score,
            news_score=_aggregate_news_score(weighted_news),
            macro_score=macro.macro_score if macro else None,
            technical_analysis_id=analysis_id,
            news_analysis_ids=[w.analysis.news_id for w in weighted_news],
            macro_snapshot_id=macro_id,
            persist=persist,
            decision_as_of=decision_as_of,
        )
