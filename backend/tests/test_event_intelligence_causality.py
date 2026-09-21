"""HATA 15F — news timestamp causality/ordering testleri.

Kapsam: `NewsRawRepository.upsert` (`received_at` immutability) +
`app.services.news.news_selection` (son-N-benzersiz-olay penceresinin
sıralama anahtarının `NewsAnalysis.created_at` yerine temsilcinin
`published_at`'ine dayanması, HATA 15F bölüm 5-9).
"""

from datetime import datetime, timedelta, timezone

from app.models.news_analysis import NewsAnalysis
from app.models.news_raw import NewsRawItem
from app.repositories.news_raw_repository import NewsRawRepository
from app.services.news import news_selection as selection_module
from app.services.news.news_selection import select_recent_unique_news_analyses

T0 = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)


def _news(external_id, title, published_at=T0, received_at=None, summary="özet", asset="THYAO"):
    return NewsRawItem(
        external_id=external_id,
        title=title,
        summary=summary,
        url=f"https://example.com/{external_id}",
        publisher="Test",
        source="test",
        source_reliability=0.8,
        related_assets=[asset],
        published_at=published_at,
        received_at=received_at or published_at,
    )


def _analysis(news_id, asset="THYAO", sentiment_score=0.0, confidence=1.0, created_at=T0):
    return NewsAnalysis(
        news_id=news_id,
        asset=asset,
        sentiment_score=sentiment_score,
        confidence=confidence,
        importance=0.5,
        event_type="other",
        reasoning="r",
        model_used="gpt-5.6-luna",
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# 1. `NewsRawRepository.upsert` — `received_at` immutability (bölüm 12/21).
# ---------------------------------------------------------------------------


class _FakeDocSnapshot:
    def __init__(self, data):
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _FakeDocRef:
    def __init__(self, store, key):
        self._store = store
        self._key = key

    def get(self):
        return _FakeDocSnapshot(self._store.get(self._key))

    def set(self, data):
        self._store[self._key] = dict(data)


class _FakeCollection:
    def __init__(self, store):
        self._store = store

    def document(self, doc_id):
        return _FakeDocRef(self._store, doc_id)


class _FakeFirestoreClient:
    def __init__(self):
        self._collections: dict[str, dict] = {}

    def collection(self, name):
        return _FakeCollection(self._collections.setdefault(name, {}))


def _repo(monkeypatch):
    import app.repositories.news_raw_repository as repo_module

    fake_db = _FakeFirestoreClient()
    monkeypatch.setattr(repo_module, "get_firestore_client", lambda: fake_db)
    return repo_module.NewsRawRepository()


def test_received_at_is_immutable_across_reingestion(monkeypatch):
    repo = _repo(monkeypatch)
    first_seen = T0
    second_fetch = T0 + timedelta(hours=3)

    repo.upsert(_news("yahoo:1", "THY hisseleri yükseldi", published_at=T0, received_at=first_seen))
    # Aynı external_id ikinci kez upsert edilir -- provider'lar her cron
    # çalışmasında `received_at = datetime.now(...)` üretir (bkz.
    # yahoo/google/foreks_news_provider.py), bu yüzden burada BİLEREK
    # farklı (daha yeni) bir `received_at` gönderiliyor.
    repo.upsert(
        _news(
            "yahoo:1",
            "THY hisseleri yükseldi (güncellendi)",
            published_at=T0,
            received_at=second_fetch,
        )
    )

    stored = repo.get_by_external_id("yahoo:1")
    assert stored.received_at == first_seen  # İLK gözlem zamanı SABİT kaldı
    assert stored.title == "THY hisseleri yükseldi (güncellendi)"  # diğer alanlar normal güncellendi


def test_first_upsert_sets_received_at_normally(monkeypatch):
    repo = _repo(monkeypatch)
    repo.upsert(_news("yahoo:2", "Yeni haber", published_at=T0, received_at=T0))
    stored = repo.get_by_external_id("yahoo:2")
    assert stored.received_at == T0


# ---------------------------------------------------------------------------
# 2. Seçim penceresi sıralama anahtarı — `published_at`, `created_at` DEĞİL
#    (bölüm 5-9, "delayed analysis" -- kritik test).
# ---------------------------------------------------------------------------


class _FakeAnalysisListRepo:
    def __init__(self, analyses):
        self._analyses = analyses

    def list_for_asset(self, asset, limit=None):
        assert limit is None  # HATA 15B FINAL sözleşmesi korunmalı
        return list(self._analyses)


class _FakeNewsRawRepoWithData:
    def __init__(self, raw_by_id):
        self._raw_by_id = raw_by_id

    def get_by_external_id(self, external_id):
        return self._raw_by_id.get(external_id)


def test_processing_delay_does_not_distort_recency_ordering():
    # Ticket bölüm 9: A daha ERKEN yayınlandı (09:00) ama analiz İŞLEME
    # (created_at) GEÇ tamamlandı (12:00) -- ör. bir günlük backlog. B daha
    # SONRA yayınlandı (10:00) ama HEMEN analiz edildi (10:05). Doğru
    # causality sözleşmesi: B, A'dan daha "yeni olay" sayılmalı (published_at
    # esas), created_at'e göre sıralarsa (eski hatalı davranış) A "daha yeni"
    # görünürdü.
    raw_a = _news("prov:A", "THY bağımsız olay A", published_at=T0)  # 09:00
    raw_b = _news("prov:B", "GARAN bağımsız olay B", published_at=T0 + timedelta(hours=1))  # 10:00
    analysis_a = _analysis("prov:A", sentiment_score=-50.0, created_at=T0 + timedelta(hours=3))  # 12:00
    analysis_b = _analysis("prov:B", sentiment_score=50.0, created_at=T0 + timedelta(minutes=65))  # 10:05

    news_repo = _FakeAnalysisListRepo([analysis_a, analysis_b])  # created_at azalan: A önce, B sonra
    raw_repo = _FakeNewsRawRepoWithData({"prov:A": raw_a, "prov:B": raw_b})

    selected = select_recent_unique_news_analyses("THYAO", news_repo, raw_repo, limit=10)

    assert [w.analysis.news_id for w in selected] == ["prov:B", "prov:A"]  # B (yayın-yeni) önce


def test_limit_one_selects_most_recently_published_event_not_most_recently_processed():
    raw_a = _news("prov:A", "THY bağımsız olay A", published_at=T0)
    raw_b = _news("prov:B", "GARAN bağımsız olay B", published_at=T0 + timedelta(hours=1))
    analysis_a = _analysis("prov:A", sentiment_score=-50.0, created_at=T0 + timedelta(hours=3))
    analysis_b = _analysis("prov:B", sentiment_score=50.0, created_at=T0 + timedelta(minutes=65))

    news_repo = _FakeAnalysisListRepo([analysis_a, analysis_b])
    raw_repo = _FakeNewsRawRepoWithData({"prov:A": raw_a, "prov:B": raw_b})

    selected = select_recent_unique_news_analyses("THYAO", news_repo, raw_repo, limit=1)

    assert [w.analysis.news_id for w in selected] == ["prov:B"]


# ---------------------------------------------------------------------------
# 3. Son-10-benzersiz-olay backfill semantiği, published_at sıralamasında
#    da (created_at'ten TAMAMEN bağımsız/karışık olsa bile) doğru çalışmalı.
# ---------------------------------------------------------------------------


def _independent(label, published_at, created_at, score):
    raw = _news(f"prov:{label}", f"Bağımsız olay {label}", published_at=published_at)
    analysis = _analysis(f"prov:{label}", sentiment_score=score, created_at=created_at)
    return raw, analysis


def test_last_10_unique_holds_when_created_at_order_is_scrambled_relative_to_published_at():
    # 10 bağımsız olay; published_at TUTARLI şekilde azalan (A en yeni yayın,
    # J en eski), ama created_at (işleme sırası) BİLEREK karıştırılmış --
    # gerçek dünyada işleme sırası (retry/backlog/farklı asset zamanlaması
    # yüzünden) yayın sırasını izlemek ZORUNDA değildir.
    labels = "ABCDEFGHIJ"
    raws, analyses = {}, []
    for i, label in enumerate(labels):
        published_at = T0 + timedelta(hours=(9 - i))  # A=+9h ... J=+0h (A en yeni yayın)
        # created_at kasıtlı olarak TERS sırada (J en önce işlenmiş, A en son)
        created_at = T0 + timedelta(hours=i)
        raw, analysis = _independent(label, published_at, created_at, score=10.0 * (i + 1))
        raws[analysis.news_id] = raw
        analyses.append(analysis)

    news_repo = _FakeAnalysisListRepo(analyses)
    raw_repo = _FakeNewsRawRepoWithData(raws)

    selected = select_recent_unique_news_analyses("THYAO", news_repo, raw_repo, limit=10)

    assert len(selected) == 10
    # published_at'e göre azalan sırada olmalı: A (en yeni yayın) ilk.
    assert [w.analysis.news_id for w in selected] == [f"prov:{c}" for c in labels]


# ---------------------------------------------------------------------------
# 4. Aynı mantıksal olay, çoklu-sağlayıcı published_at -- temsilci kimliği
#    DEĞİŞMEMELİ (bölüm 10/16), yalnızca pencere sıralaması etkilenir.
# ---------------------------------------------------------------------------


def test_duplicate_event_representative_identity_unaffected_by_ordering_fix():
    # A 10:00, B 10:07, C 10:15 -- aynı olay, aynı asset. Temsilci hâlâ
    # (gövde var + en ERKEN published_at) kuralıyla A olmalı (DEĞİŞMEDİ).
    a = _news("yahoo:dup", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0)
    b = _news(
        "google:dup", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0 + timedelta(minutes=7)
    )
    c = _news(
        "foreks:dup", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0 + timedelta(minutes=15)
    )
    analysis_a = _analysis("yahoo:dup", sentiment_score=70.0, created_at=T0)
    news_repo = _FakeAnalysisListRepo([analysis_a])
    raw_repo = _FakeNewsRawRepoWithData({"yahoo:dup": a, "google:dup": b, "foreks:dup": c})

    selected = select_recent_unique_news_analyses("THYAO", news_repo, raw_repo, limit=10)

    assert [w.analysis.news_id for w in selected] == ["yahoo:dup"]


def test_decision_and_explanation_still_receive_identical_ordering_after_causality_fix():
    # HATA 15E parity garantisi HATA 15F'ten SONRA da geçerli olmalı --
    # DecisionEngine ve ExplanationEngine ikisi de AYNI paylaşımlı
    # `select_recent_unique_news_analyses`'i çağırıyor (kod düzeyinde tek
    # kaynak), bu yüzden burada aynı fixture'ı iki kez çağırmak yeterli
    # kanıttır (ayrı bir "explanation" yolu YOK, HATA 15E bkz.).
    raw_a = _news("prov:A", "THY bağımsız olay A", published_at=T0)
    raw_b = _news("prov:B", "GARAN bağımsız olay B", published_at=T0 + timedelta(hours=1))
    analysis_a = _analysis("prov:A", created_at=T0 + timedelta(hours=3))
    analysis_b = _analysis("prov:B", created_at=T0 + timedelta(minutes=65))
    news_repo = _FakeAnalysisListRepo([analysis_a, analysis_b])
    raw_repo = _FakeNewsRawRepoWithData({"prov:A": raw_a, "prov:B": raw_b})

    decision_side = select_recent_unique_news_analyses("THYAO", news_repo, raw_repo, limit=10)
    explanation_side = select_recent_unique_news_analyses("THYAO", news_repo, raw_repo, limit=10)

    assert [w.analysis.news_id for w in decision_side] == [w.analysis.news_id for w in explanation_side]


# ---------------------------------------------------------------------------
# 5. Timezone normalizasyonu — farklı UTC offset'li ama karşılaştırılabilir
#    zaman damgaları hatasız/doğru sıralanmalı (naive/aware karışıklığı yok).
# ---------------------------------------------------------------------------


def test_timezone_aware_timestamps_at_different_offsets_order_correctly():
    tr_tz = timezone(timedelta(hours=3))  # Türkiye saati (UTC+3)
    # 12:00 UTC+3 == 09:00 UTC -- yani B (10:00 UTC) gerçekte A'dan (09:00
    # UTC eşdeğeri) daha SONRA yayınlanmış.
    published_a = datetime(2026, 1, 10, 12, 0, tzinfo=tr_tz)
    published_b = T0 + timedelta(hours=1)  # 10:00 UTC

    raw_a = _news("prov:tzA", "THY olay A", published_at=published_a)
    raw_b = _news("prov:tzB", "GARAN olay B", published_at=published_b)
    analysis_a = _analysis("prov:tzA", created_at=T0)
    analysis_b = _analysis("prov:tzB", created_at=T0)
    news_repo = _FakeAnalysisListRepo([analysis_a, analysis_b])
    raw_repo = _FakeNewsRawRepoWithData({"prov:tzA": raw_a, "prov:tzB": raw_b})

    selected = select_recent_unique_news_analyses("THYAO", news_repo, raw_repo, limit=10)

    assert [w.analysis.news_id for w in selected] == ["prov:tzB", "prov:tzA"]  # B gerçekten daha yeni


# ---------------------------------------------------------------------------
# 6. Ham provenance bulunamayan (legacy/savunma) analizler -- crash yok,
#    `analysis.created_at` en iyi mevcut sinyal olarak kullanılmaya devam
#    ediyor (bölüm 26 -- geriye dönük uyumluluk, yeni alan gerektirmez).
# ---------------------------------------------------------------------------


def test_missing_raw_provenance_falls_back_to_created_at_without_crash():
    analysis = _analysis("orphan:1", created_at=T0)
    news_repo = _FakeAnalysisListRepo([analysis])
    raw_repo = _FakeNewsRawRepoWithData({})  # ham kayıt yok

    selected = select_recent_unique_news_analyses("THYAO", news_repo, raw_repo, limit=10)

    assert [w.analysis.news_id for w in selected] == ["orphan:1"]
    assert selected[0].source_reliability is None


# ---------------------------------------------------------------------------
# 7. Rigor check A yardımcı fonksiyonu (eski davranışı doğrudan test etmek
#    için, bkz. bölüm 27 -- test dosyası içinde monkeypatch ile TEK bir yerde
#    uygulanır, production kodu kalıcı olarak DEĞİŞTİRİLMEZ).
# ---------------------------------------------------------------------------


def test_rigor_check_old_created_at_ordering_fails_processing_delay_test(monkeypatch):
    """Eski (hatalı) `created_at`-sıralı davranışı GEÇİCİ olarak geri
    yükleyip `test_processing_delay_does_not_distort_recency_ordering`'in
    beklediği sonucu üretMEDİĞİNİ kanıtlar -- düzeltmenin gerçekten bir şey
    değiştirdiğinin kanıtı (bölüm 27)."""

    def _old_broken_dedup(analyses, news_raw_repo):
        # HATA 15F ÖNCESİ production kodunun birebir kopyası: kümele, ama
        # `analyses` girdi sırasını (created_at azalan) KORU.
        entries = []
        reliability_by_news_id = {}
        for analysis in analyses:
            raw = news_raw_repo.get_by_external_id(analysis.news_id)
            if raw is None:
                reliability_by_news_id[analysis.news_id] = None
                entries.append(
                    selection_module.DedupEntry(
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
                    selection_module.DedupEntry(
                        asset=analysis.asset,
                        event_id=analysis.news_id,
                        title=raw.title,
                        published_at=raw.published_at,
                        has_body=bool(raw.summary.strip()),
                        payload=analysis,
                    )
                )
        clusters = selection_module.cluster_by_event(entries)
        kept_ids = {c.representative.event_id for c in clusters}
        return [
            selection_module._WeightedNewsAnalysis(
                analysis=a, source_reliability=reliability_by_news_id[a.news_id]
            )
            for a in analyses
            if a.news_id in kept_ids
        ]

    monkeypatch.setattr(selection_module, "_deduplicate_news_analyses", _old_broken_dedup)

    raw_a = _news("prov:A", "THY bağımsız olay A", published_at=T0)
    raw_b = _news("prov:B", "GARAN bağımsız olay B", published_at=T0 + timedelta(hours=1))
    analysis_a = _analysis("prov:A", created_at=T0 + timedelta(hours=3))
    analysis_b = _analysis("prov:B", created_at=T0 + timedelta(minutes=65))
    news_repo = _FakeAnalysisListRepo([analysis_a, analysis_b])
    raw_repo = _FakeNewsRawRepoWithData({"prov:A": raw_a, "prov:B": raw_b})

    selected = select_recent_unique_news_analyses("THYAO", news_repo, raw_repo, limit=10)

    # Eski davranış created_at azalan sırayı korur: analysis_a (12:00) önce
    # gelir -- doğru (published_at-esaslı) sıralamanın TERSİ.
    assert [w.analysis.news_id for w in selected] == ["prov:A", "prov:B"]


def test_rigor_check_received_at_overwrite_fails_immutability_test(monkeypatch):
    """Eski (hatalı) `.set()`-tabanlı upsert davranışını GEÇİCİ olarak simüle
    edip `received_at`'in gerçekten korunmadığını -- düzeltmenin bir şey
    değiştirdiğinin kanıtı olarak -- gösterir (bölüm 27)."""
    import app.repositories.news_raw_repository as repo_module

    fake_db = _FakeFirestoreClient()
    monkeypatch.setattr(repo_module, "get_firestore_client", lambda: fake_db)
    repo = repo_module.NewsRawRepository()

    def _old_broken_upsert(item):
        # HATA 15F ÖNCESİ production kodunun birebir kopyası: `existing`
        # okuma/koruma YOK.
        fake_db.collection(repo_module.COLLECTION).document(item.external_id).set(item.model_dump())

    monkeypatch.setattr(repo, "upsert", _old_broken_upsert)

    first_seen = T0
    second_fetch = T0 + timedelta(hours=3)
    repo.upsert(_news("yahoo:old", "Haber", published_at=T0, received_at=first_seen))
    repo.upsert(_news("yahoo:old", "Haber (güncellendi)", published_at=T0, received_at=second_fetch))

    stored = repo.get_by_external_id("yahoo:old")
    assert stored.received_at == second_fetch  # eski davranış: SESSİZCE ilerledi (hatalı)
