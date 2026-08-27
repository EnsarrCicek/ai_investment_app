"""HATA 4B: `NewOpportunityNotificationRepository`'nin KENDİ (production)
metodlarını, gerçek Firestore/ağ olmadan, doğrudan çalıştıran testler.

`test_fcm_sender.py`'deki `_FakeNewOpportunityLogRepo` bu sınıfın davranışını
TAKLİT EDEN bağımsız bir sahte — burada onun yerine gerçek `Firestore`
istemcisini (`get_firestore_client`) minimal, sözleşme-uyumlu bir sahteyle
değiştirip PRODUCTION SINIFININ KENDİSİNİ (`_doc_id`, `claim_new_opportunity`,
`mark_new_opportunity_sent`, `release_new_opportunity_claim`) çağırıyoruz --
token karşılaştırması, PENDING kontrolü, SENT koruması, update/delete kararı
hep gerçek repository kodundan geliyor. `firestore.transactional` yalnızca
identity-wrapper'a monkeypatch'lenir (gerçek Firestore transaction protokolü
network gerektirir) -- decorator'ın SARDIĞI fonksiyonun GÖVDESİ (iş mantığı)
değişmeden çalışır.
"""

import pytest
from google.api_core.exceptions import AlreadyExists

from app.repositories import new_opportunity_notification_repository as repo_module


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

    def get(self, transaction=None):
        return _FakeDocSnapshot(self._store.get(self._key))

    def create(self, data):
        if self._key in self._store:
            raise AlreadyExists(f"document already exists: {self._key}")
        self._store[self._key] = dict(data)


class _FakeTransaction:
    """Gerçek `google.cloud.firestore.Transaction`'ın yalnız repository'nin
    kullandığı iki metodunu (`update`/`delete`) taklit eder -- retry/commit
    protokolü olmadan, doğrudan store üzerinde çalışır."""

    def update(self, doc_ref, data):
        if doc_ref._key in doc_ref._store:
            doc_ref._store[doc_ref._key].update(data)

    def delete(self, doc_ref):
        doc_ref._store.pop(doc_ref._key, None)


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

    def transaction(self):
        return _FakeTransaction()

    def raw_store(self, name):
        return self._collections.setdefault(name, {})


@pytest.fixture
def fake_db():
    return _FakeFirestoreClient()


@pytest.fixture
def repo(monkeypatch, fake_db):
    monkeypatch.setattr(repo_module, "get_firestore_client", lambda: fake_db)
    # Gerçek Firestore transaction protokolü ağ/backend gerektirir --
    # decorator'ı identity-wrapper'a indirgiyoruz, ama SARDIĞI production
    # fonksiyonunun gövdesi (token karşılaştırması, PENDING/SENT kararları)
    # AYNEN çalışır.
    monkeypatch.setattr(repo_module.firestore, "transactional", lambda f: f)
    return repo_module.NewOpportunityNotificationRepository()


def _raw_doc(fake_db, doc_id):
    return fake_db.raw_store(repo_module.COLLECTION).get(doc_id)


# ---------------------------------------------------------------------------
# 1. Doc-id contract
# ---------------------------------------------------------------------------


def test_doc_id_is_deterministic_64_char_lowercase_sha256(repo):
    doc_id = repo._doc_id("u1", "THYAO", "THYAO:BULLISH:2026-08-20")

    assert len(doc_id) == 64
    assert doc_id == doc_id.lower()
    int(doc_id, 16)  # geçerli hex mi -- değilse ValueError fırlatır


def test_doc_id_same_triple_produces_same_hash(repo):
    a = repo._doc_id("u1", "THYAO", "THYAO:BULLISH:2026-08-20")
    b = repo._doc_id("u1", "THYAO", "THYAO:BULLISH:2026-08-20")
    assert a == b


def test_doc_id_asset_case_insensitive(repo):
    lower = repo._doc_id("u1", "thyao", "THYAO:BULLISH:2026-08-20")
    upper = repo._doc_id("u1", "THYAO", "THYAO:BULLISH:2026-08-20")
    assert lower == upper


@pytest.mark.parametrize(
    "a,b",
    [
        (("u1", "THYAO", "e1"), ("u2", "THYAO", "e1")),  # farklı user
        (("u1", "THYAO", "e1"), ("u1", "GARAN", "e1")),  # farklı asset
        (("u1", "THYAO", "e1"), ("u1", "THYAO", "e2")),  # farklı event_id
    ],
)
def test_doc_id_differs_when_any_component_differs(repo, a, b):
    assert repo._doc_id(*a) != repo._doc_id(*b)


def test_doc_id_does_not_contain_raw_components(repo):
    doc_id = repo._doc_id("some-user-id", "THYAO", "THYAO:BULLISH:2026-08-20")
    assert "some-user-id" not in doc_id
    assert "THYAO" not in doc_id
    assert "2026-08-20" not in doc_id


# ---------------------------------------------------------------------------
# 2/3. First claim / AlreadyExists
# ---------------------------------------------------------------------------


def test_first_claim_creates_pending_document_with_expected_fields(repo, fake_db):
    token = repo.claim_new_opportunity("u1", "THYAO", "THYAO:BULLISH:2026-08-20")

    assert token is not None
    doc_id = repo._doc_id("u1", "THYAO", "THYAO:BULLISH:2026-08-20")
    data = _raw_doc(fake_db, doc_id)
    assert data == {
        "user_id": "u1",
        "asset": "THYAO",
        "event_id": "THYAO:BULLISH:2026-08-20",
        "status": "PENDING",
        "claim_token": token,
        "claimed_at": data["claimed_at"],  # varlığını doğruluyoruz, tam değeri önemsiz
        "sent_at": None,
    }
    assert data["claimed_at"] is not None


def test_second_claim_for_same_event_is_denied_via_already_exists(repo):
    # Production'ın `except AlreadyExists: return None` dalı gerçekten tetikleniyor mu --
    # fake DocumentReference.create() gerçek SDK gibi AlreadyExists fırlatıyor.
    first = repo.claim_new_opportunity("u1", "THYAO", "THYAO:BULLISH:2026-08-20")
    second = repo.claim_new_opportunity("u1", "THYAO", "THYAO:BULLISH:2026-08-20")

    assert first is not None
    assert second is None


# ---------------------------------------------------------------------------
# 4. Per-event storage / event1->event2->event1 regresyonu (repository seviyesi)
# ---------------------------------------------------------------------------


def test_two_different_events_get_separate_documents_and_do_not_overwrite(repo, fake_db):
    token1 = repo.claim_new_opportunity("u1", "THYAO", "THYAO:BULLISH:2026-08-01")
    token2 = repo.claim_new_opportunity("u1", "THYAO", "THYAO:BULLISH:2026-08-08")

    assert token1 is not None and token2 is not None
    assert token1 != token2

    doc_id1 = repo._doc_id("u1", "THYAO", "THYAO:BULLISH:2026-08-01")
    doc_id2 = repo._doc_id("u1", "THYAO", "THYAO:BULLISH:2026-08-08")
    assert doc_id1 != doc_id2
    assert _raw_doc(fake_db, doc_id1) is not None  # event2 claim'i event1'i SİLMEDİ/EZMEDİ
    assert _raw_doc(fake_db, doc_id1)["event_id"] == "THYAO:BULLISH:2026-08-01"

    repo.mark_new_opportunity_sent("u1", "THYAO", "THYAO:BULLISH:2026-08-01", token1)
    repo.mark_new_opportunity_sent("u1", "THYAO", "THYAO:BULLISH:2026-08-08", token2)

    # event1->event2->event1 regresyonu: event1 zaten SENT olduğundan tekrar claim edilemez.
    reclaim_event1 = repo.claim_new_opportunity("u1", "THYAO", "THYAO:BULLISH:2026-08-01")
    assert reclaim_event1 is None


# ---------------------------------------------------------------------------
# 5/6. mark_new_opportunity_sent -- doğru/yanlış token
# ---------------------------------------------------------------------------


def test_mark_sent_with_correct_token_updates_status_and_sent_at(repo, fake_db):
    token = repo.claim_new_opportunity("u1", "THYAO", "THYAO:BULLISH:2026-08-20")
    doc_id = repo._doc_id("u1", "THYAO", "THYAO:BULLISH:2026-08-20")

    repo.mark_new_opportunity_sent("u1", "THYAO", "THYAO:BULLISH:2026-08-20", token)

    data = _raw_doc(fake_db, doc_id)
    assert data["status"] == "SENT"
    assert data["sent_at"] is not None
    assert data is not None  # doküman hâlâ var


def test_mark_sent_with_wrong_token_leaves_document_unchanged(repo, fake_db):
    token = repo.claim_new_opportunity("u1", "THYAO", "THYAO:BULLISH:2026-08-20")
    doc_id = repo._doc_id("u1", "THYAO", "THYAO:BULLISH:2026-08-20")

    repo.mark_new_opportunity_sent("u1", "THYAO", "THYAO:BULLISH:2026-08-20", "wrong-token")

    data = _raw_doc(fake_db, doc_id)
    assert data["status"] == "PENDING"
    assert data["sent_at"] is None
    assert data["claim_token"] == token  # değişmedi


# ---------------------------------------------------------------------------
# 7/8. release_new_opportunity_claim -- doğru/yanlış token
# ---------------------------------------------------------------------------


def test_release_with_correct_token_deletes_document_and_allows_reclaim(repo, fake_db):
    token = repo.claim_new_opportunity("u1", "THYAO", "THYAO:BULLISH:2026-08-20")
    doc_id = repo._doc_id("u1", "THYAO", "THYAO:BULLISH:2026-08-20")

    repo.release_new_opportunity_claim("u1", "THYAO", "THYAO:BULLISH:2026-08-20", token)

    assert _raw_doc(fake_db, doc_id) is None
    new_token = repo.claim_new_opportunity("u1", "THYAO", "THYAO:BULLISH:2026-08-20")
    assert new_token is not None  # release sonrası tekrar claim edilebiliyor


def test_release_with_wrong_token_does_not_delete_document(repo, fake_db):
    token = repo.claim_new_opportunity("u1", "THYAO", "THYAO:BULLISH:2026-08-20")
    doc_id = repo._doc_id("u1", "THYAO", "THYAO:BULLISH:2026-08-20")

    repo.release_new_opportunity_claim("u1", "THYAO", "THYAO:BULLISH:2026-08-20", "wrong-token")

    data = _raw_doc(fake_db, doc_id)
    assert data is not None
    assert data["status"] == "PENDING"
    assert data["claim_token"] == token


# ---------------------------------------------------------------------------
# 9. SENT bir doküman ASLA release edilemez (yanlışlıkla doğru token'la bile).
# ---------------------------------------------------------------------------


def test_sent_document_is_never_released_even_with_correct_token(repo, fake_db):
    token = repo.claim_new_opportunity("u1", "THYAO", "THYAO:BULLISH:2026-08-20")
    doc_id = repo._doc_id("u1", "THYAO", "THYAO:BULLISH:2026-08-20")
    repo.mark_new_opportunity_sent("u1", "THYAO", "THYAO:BULLISH:2026-08-20", token)

    repo.release_new_opportunity_claim("u1", "THYAO", "THYAO:BULLISH:2026-08-20", token)  # yanlışlıkla çağrıldı

    data = _raw_doc(fake_db, doc_id)
    assert data is not None
    assert data["status"] == "SENT"


# ---------------------------------------------------------------------------
# 11. Claim token uniqueness.
# ---------------------------------------------------------------------------


def test_claim_tokens_are_unique_across_events(repo):
    token1 = repo.claim_new_opportunity("u1", "THYAO", "THYAO:BULLISH:2026-08-01")
    token2 = repo.claim_new_opportunity("u1", "THYAO", "THYAO:BULLISH:2026-08-08")

    assert token1
    assert token2
    assert token1 != token2
