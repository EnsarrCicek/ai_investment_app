"""Paylaşımlı haber-analizi SEÇİM katmanı — HATA 15E.

HATA 15A bulgu (ve HATA 15C FINAL raporunda "ayrı açık konu" olarak
disclosed edilen): `DecisionEngine.decide_for_asset()` son-N BENZERSİZ
mantıksal-olay SEÇİMİNİ (HATA 15B kümeleme + HATA 15B FINAL backfill
semantiği + HATA 15C temsilci-reliability eşleme) yalnızca KENDİ içinde
yapıyordu; `ExplanationEngine.explain()` ise doğrudan ham
`news_repo.list_for_asset(asset, limit=NEWS_SCORE_LIMIT)` okuyordu — HİÇ
dedup'lanmamış, HİÇ reliability eşlenmemiş bir liste. Sonuç: DecisionEngine
"son 10 BENZERSİZ olay" üzerinden skor üretirken, ExplanationEngine "son 10
HAM kayıt" üzerinden açıklama üretebiliyordu — üyelik/temsilci tutarsızlığı.

Bu modül, SEÇİM mantığını (`_deduplicate_news_analyses` + backfill-until-
limit semantiği) `DecisionEngine`'den ayıklayıp tek bir paylaşımlı yardımcıya
(`select_recent_unique_news_analyses`) çıkarır. `DecisionEngine` ve
`ExplanationEngine` artık İKİSİ DE bu TEK fonksiyonu çağırır — aynı repo
fixture'larıyla çağrıldıklarında birebir aynı üyeliği/temsilciyi üretmeleri
GARANTİ edilir (bkz. test_explanation_news_consistency.py, parity testi).

SEÇİM (bu modül) ile TOPLAMA/SKORLAMA (`_aggregate_news_score`) BİLİNÇLİ
olarak ayrı tutulur — bu modül "hangi benzersiz olaylar, hangi temsilcilerle"
sorusuna cevap verir, skorlama matematiğine karışmaz. `ExplanationEngine`
bu skorlama matematiğini yeniden hesaplamak zorunda değildir ama AYNI
temsilci kümesini kullanmalıdır (bkz. HATA 15E bölüm 8).

`app.engines.decision.engine` ve `app.engines.explanation.engine` HER İKİSİ
DE bu modülden import eder — `ExplanationEngine`'in `DecisionEngine`'in
private internal'larını import etmesi gerekmez (dairesel import riski de
yok: bu modül yalnızca repository/model/event_dedup katmanına bağımlı,
hiçbir engine modülünü import ETMEZ).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from app.models.news_analysis import NewsAnalysis
from app.repositories.news_analysis_repository import NewsAnalysisRepository
from app.repositories.news_raw_repository import NewsRawRepository
from app.services.news.event_dedup import DedupEntry, cluster_by_event

NEWS_SCORE_LIMIT = 10


@dataclass(frozen=True)
class _WeightedNewsAnalysis:
    """HATA 15C: `_deduplicate_news_analyses()`'ın döndürdüğü, her BENZERSİZ
    mantıksal olayın temsilci analizini KENDİ kaynak güvenilirliğiyle
    eşleyen zarf. `source_reliability=None`, o temsilcinin ham makale
    kaydı bulunamadığı (provenance eksik) anlamına gelir -- ASLA fabrike
    bir OTHER_MEDIA=0.60 değeri DEĞİL (bkz. HATA 15C bölüm 8-9).

    `analysis`'ın olmayan bir alanına erişim (ör. `.news_id`,
    `.sentiment_score`) şeffaf şekilde ona yönlendirilir -- çağıran kod
    için `NewsAnalysis`'in kendisi gibi davranır."""

    analysis: NewsAnalysis
    source_reliability: float | None

    def __getattr__(self, name: str):
        return getattr(self.analysis, name)


def _effective_news_weight(confidence: float, source_reliability: float | None) -> float:
    """HATA 15C bölüm 6/8/9: bir olayın skorlamadaki etkin ağırlığı.

    `source_reliability` gerçekten mevcut ve geçerliyse (0..1 -- bkz.
    `source_reliability.py::DEFAULT_SOURCE_RELIABILITY`, gerçek production
    ölçeği) `confidence * source_reliability` döner. `None` ise (ham
    provenance bulunamadı) reliability boyutu bu olay için DIŞLANIR --
    `effective_weight = confidence` (yalnızca "mevcut boyutlarla" ağırlıklandırma,
    ASLA icat edilmiş bir reliability değeri DEĞİL).

    Geçersiz (negatif/NaN/±inf/1'den büyük) bir `source_reliability` sessizce
    clamp/coerce EDİLMEZ -- fail-fast (bölüm 21), bu projenin
    `resolve_decision_weights`/`resolve_decision_thresholds` ile aynı
    "corrupted config/data'yı gizlice düzeltme" karşıtı ilkesiyle tutarlı.
    """
    if source_reliability is None:
        return confidence
    if (
        isinstance(source_reliability, bool)
        or not isinstance(source_reliability, (int, float))
        or not math.isfinite(source_reliability)
        or source_reliability < 0.0
        or source_reliability > 1.0
    ):
        raise ValueError(
            f"Geçersiz source_reliability değeri: {source_reliability!r} "
            "(0..1 aralığında finite bir sayı olmalı) -- fail-fast, sessizce "
            "clamp/coerce EDİLMİYOR (HATA 15C bölüm 21)."
        )
    return confidence * source_reliability


def _aggregate_news_score(weighted: list[_WeightedNewsAnalysis]) -> float | None:
    """Son N BENZERSİZ olayın, kaynak-güvenilirlik-farkında ağırlıklı
    ortalama sentiment_score'u (HATA 15C).

    Formül DEĞİŞMEDİ (HATA 15B'den): yalnızca ağırlık artık salt
    `confidence` değil `confidence * source_reliability` (mevcutsa) --
    bkz. `_effective_news_weight()`. Hiç girdi yoksa VEYA toplam etkin
    ağırlık sıfırsa None döner (Missing Data Davranışı — 0 gibi yanlış bir
    "nötr" varsayımı YAPILMAZ, ne confidence=0 ne de reliability=0 için).
    """
    if not weighted:
        return None
    weights = [_effective_news_weight(w.analysis.confidence, w.source_reliability) for w in weighted]
    weight_total = sum(weights)
    if weight_total == 0:
        return None
    weighted_sum = sum(w.analysis.sentiment_score * wt for w, wt in zip(weighted, weights))
    return round(weighted_sum / weight_total, 2)


def _deduplicate_news_analyses(
    analyses: list[NewsAnalysis], news_raw_repo: NewsRawRepository
) -> list[_WeightedNewsAnalysis]:
    """HATA 15B: skorlama girdisini benzersiz MANTIKSAL OLAYLARA indirger.
    HATA 15C: her benzersiz olayın temsilcisini KENDİ `source_reliability`'si
    ile eşler (diğer küme üyelerininki TOPLANMAZ/ORTALANMAZ -- bkz. bölüm 15).

    Sorun (HATA 15A bulgu #2): aynı gerçek-dünya olayı Yahoo/Google/Foreks'ten
    ayrı `external_id`'lerle geldiği ve hiçbir yerde birleştirilmediği için,
    son-N NewsAnalysis penceresinde bir olay birden çok slot işgal edip
    `_aggregate_news_score()`'u orantısız etkileyebiliyordu. Bu fonksiyon
    (yeni VEYA bu düzeltmeden ÖNCE üretilmiş legacy) analiz kayıtlarını
    kaynak ham habere (`news_raw`) geri bağlayıp aynı asset+zaman-penceresi+
    başlık-benzerliği kümesindeki analizlerden yalnızca kümenin deterministik
    temsilcisininkini bırakır (bkz. app/services/news/event_dedup.py).

    `_aggregate_news_score()`'un formülü DEĞİŞMEDİ — yalnızca ona giden girdi
    kümesi artık tekilleştirilmiş VE her girdi kendi temsilcisinin
    reliability'siyle etiketlenmiş.

    Ham haber kaydı bulunamayan (savunma amaçlı; olağan akışta olmamalı) bir
    analiz kümelenemez -- kendi başına tek üyeli bir küme olarak GÜVENLİ
    şekilde geçilir, crash YOK, sessizce yanlış bir kümeye de eklenmez, ve
    reliability'si `None` (fabrike bir OTHER_MEDIA=0.60 DEĞİL) olarak kalır.
    Bu durumda kümenin sıralama anahtarı olarak `analysis.created_at`
    kullanılır (en iyi mevcut sinyal -- gerçek `published_at` yok).

    HATA 15F: dönen liste, kümelerin `EventCluster.event_recency`'sine
    (temsilcinin `published_at`'i) göre azalan sıradadır -- `analyses`
    girdi listesinin `created_at` sırası DEĞİL (bkz. bölüm 5-9,
    `select_recent_unique_news_analyses` docstring'i).
    """
    if not analyses:
        return []

    entries: list[DedupEntry[NewsAnalysis]] = []
    reliability_by_news_id: dict[str, float | None] = {}
    for analysis in analyses:
        raw = news_raw_repo.get_by_external_id(analysis.news_id)
        if raw is None:
            reliability_by_news_id[analysis.news_id] = None
            entries.append(
                DedupEntry(
                    asset=analysis.asset,
                    event_id=analysis.news_id,
                    title=f"__unresolved_raw__:{analysis.news_id}",
                    published_at=analysis.created_at,
                    has_body=False,
                    payload=analysis,
                )
            )
        else:
            reliability_by_news_id[analysis.news_id] = raw.source_reliability
            entries.append(
                DedupEntry(
                    asset=analysis.asset,
                    event_id=analysis.news_id,
                    title=raw.title,
                    published_at=raw.published_at,
                    has_body=bool(raw.summary.strip()),
                    payload=analysis,
                )
            )

    clusters = cluster_by_event(entries)
    # HATA 15F bölüm 5-9: kümeler, `NewsAnalysis.created_at` (LLM işleme
    # tamamlanma anı) DEĞİL, temsilcinin `published_at`'ine (yayın
    # kronolojisi -- `EventCluster.event_recency`) göre azalan sırada
    # döndürülür. Eskiden bu fonksiyon `analyses` girdi listesinin (zaten
    # created_at azalan) sırasını KORUYORDU -- bu, gecikmiş LLM işleme
    # (ör. bir günlük backlog) eski-yayınlanmış bir haberi, aslında ondan
    # SONRA yayınlanmış başka bir habere göre "daha yeni" gösterebiliyordu
    # (bölüm 9, "delayed analysis" örneği) ve "son 10 benzersiz olay"
    # penceresini işleme gecikmesiyle çarpıtıyordu. Toplama FORMÜLÜ
    # DEĞİŞMEDİ (bölüm 25) -- yalnızca hangi 10 olayın pencereye gireceğini
    # belirleyen sıralama anahtarı düzeltildi.
    by_news_id = {a.news_id: a for a in analyses}
    ordered_clusters = sorted(clusters, key=lambda c: c.event_recency, reverse=True)
    return [
        _WeightedNewsAnalysis(
            analysis=by_news_id[cluster.representative.event_id],
            source_reliability=reliability_by_news_id[cluster.representative.event_id],
        )
        for cluster in ordered_clusters
    ]


def _received_before_or_at(analysis: NewsAnalysis, raw_repo: NewsRawRepository, as_of: datetime) -> bool:
    """HATA 17C: HATA 15F `received_at` (sistemin bu makaleyi İLK gözlemlediği
    an -- causality/eligibility alanı, `published_at`/yayın kronolojisiyle
    KARIŞTIRILMAZ) `as_of`'tan SONRA mı diye bakar. Ham kaydı çözümlenemeyen
    (savunma amaçlı, olağan akışta olmamalı) bir analiz için `received_at`
    bilinmez -- bu durumda ELENMEZ (True döner): `as_of` canlı kullanımda
    pratik olarak her zaman "şimdi"dir ve zaten var olan bir kayıt axiomatik
    olarak geçmişte alınmıştır; belirsizliği dışlama yönünde çözmek, bu
    fonksiyon eklenmeden ÖNCEki güvenli fallback davranışını (crash yok,
    sessizce yanlış bir kümeye eklenmiyor, tek başına kalıyor) BOZAR ve
    kanıtlanmamış bir varsayıma dayanırdı."""
    raw = raw_repo.get_by_external_id(analysis.news_id)
    if raw is None:
        return True
    return raw.received_at <= as_of


def select_recent_unique_news_analyses(
    asset: str,
    news_repo: NewsAnalysisRepository,
    news_raw_repo: NewsRawRepository | None,
    limit: int = NEWS_SCORE_LIMIT,
    as_of: datetime | None = None,
) -> list[_WeightedNewsAnalysis]:
    """HATA 15E: `DecisionEngine` ve `ExplanationEngine`'in PAYLAŞTIĞI TEK
    seçim yolu -- "son `limit` BENZERSİZ mantıksal olay".

    `news_repo.list_for_asset(asset, limit=None)` ile bu asset için TÜM
    geçmiş okunur (HATA 15B FINAL -- limit dedup'tan ÖNCE uygulanırsa
    çoklu-sağlayıcı tekrarı en yeni ham slot'ları işgal edip ondan eskiye
    giden BAĞIMSIZ olayları pencereden dışarı itebilir), TAMAMI
    `_deduplicate_news_analyses` ile kümelenir, ve `limit` yalnızca SONUÇTA
    uygulanır. `_deduplicate_news_analyses`'ın döndürdüğü liste artık
    `EventCluster.event_recency` (temsilcinin `published_at`'i -- yayın
    kronolojisi) azalan sırasındadır (HATA 15F, bölüm 5-9) -- GİRDİ
    listesinin `created_at` sırası DEĞİL, çünkü işleme (LLM analiz)
    gecikmesi yayın kronolojisiyle karışırsa "son N benzersiz olay"
    penceresini çarpıtırdı. Bu yüzden sondaki `[:limit]` dilimi "en yeni N
    benzersiz olay" anlamına -- yayın zamanına göre -- doğru şekilde gelir.

    Analiz listesi boşsa `news_raw_repo` HİÇ çağrılmaz/inşa edilmez
    (gereksiz Firestore okuması/inşası yok -- `news_raw_repo=None` iken
    varsayılan `NewsRawRepository()` de yalnızca gerçekten gerekince
    inşa edilir, bu yüzden çağıran taraf onu önden inşa etmek ZORUNDA
    DEĞİLDİR).

    SEÇİM ile TOPLAMA/SKORLAMA bilinçli olarak ayrıdır -- bu fonksiyon
    skorlama matematiğine karışmaz (bkz. `_aggregate_news_score`).

    HATA 17C: opsiyonel `as_of` -- verilirse, `received_at`'i `as_of`'tan
    SONRA olan kayıtlar dedup'tan/backfill'den ÖNCE elenir (bkz.
    `_received_before_or_at`). Bu sıralama BİLİNÇLİDİR: filtre kümelemeden
    SONRA uygulansaydı, HATA 15B FINAL'in düzelttiği "limit dedup'tan önce
    uygulanırsa çoklu-sağlayıcı tekrarı bağımsız eski olayları pencereden
    dışarı itebilir" hatası farklı bir yüzeyde (limit yerine as_of) YENİDEN
    ortaya çıkardı. `as_of=None` (varsayılan) davranışı TAMAMEN KORUR --
    mevcut hiçbir çağıran/test etkilenmez. Bu, bir historical/backtest
    çerçevesi KURMAZ: canlı kullanımda `as_of` pratik olarak her zaman
    "şimdi"dir (bkz. `decide_for_asset`), yalnızca tek bir `now()` çağrısının
    macro/news arasında tutarlı paylaşılmasını ve causality'nin (HATA 15F)
    sentetik fixture'larla test edilebilir olmasını sağlar.
    """
    news_analyses = news_repo.list_for_asset(asset, limit=None)
    if not news_analyses:
        return []
    raw_repo = news_raw_repo or NewsRawRepository()
    if as_of is not None:
        news_analyses = [a for a in news_analyses if _received_before_or_at(a, raw_repo, as_of)]
        if not news_analyses:
            return []
    return _deduplicate_news_analyses(news_analyses, raw_repo)[:limit]
