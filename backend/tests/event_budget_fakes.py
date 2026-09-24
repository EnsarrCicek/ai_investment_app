"""EventIntelligence bütçe testleri için sahte Firestore.

Transaction'lar tek bir kilit altında SIRALI çalıştırılır ve yazmalar commit'te
uygulanır (istisnada atılır). Bu, gerçek repository kodunu çalıştırır ama gerçek
Firestore'un eşzamanlılık/çakışma davranışının KANITI DEĞİLDİR.
"""

from __future__ import annotations

import threading

from google.api_core.exceptions import AlreadyExists, NotFound

from app.engines.event_intelligence.budget import EventIntelligenceBudget
from app.engines.event_intelligence.usage import MODEL_PRICING_PER_1M
from app.repositories.event_intelligence_budget_repository import FirestoreBudgetLedgerRepository


class _Snap:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _DocRef:
    def __init__(self, db, collection, doc_id):
        self._db, self.collection, self.id = db, collection, doc_id

    def get(self, transaction=None):
        self._db.check_read()
        return _Snap(self.id, self._db.docs.get((self.collection, self.id)))


class _Collection:
    def __init__(self, db, name):
        self._db, self._name = db, name

    def document(self, doc_id):
        return _DocRef(self._db, self._name, doc_id)

    def stream(self, transaction=None):
        self._db.check_read()
        return [_Snap(i, d) for (c, i), d in list(self._db.docs.items()) if c == self._name]


class _Transaction:
    def __init__(self, db):
        self.db = db
        self._writes = []

    def create(self, ref, data):
        self._writes.append(("create", ref, dict(data)))

    def update(self, ref, data):
        self._writes.append(("update", ref, dict(data)))

    def commit(self):
        if self.db.fail_commits:
            raise RuntimeError("simulated commit failure")
        staged = dict(self.db.docs)
        for op, ref, data in self._writes:
            key = (ref.collection, ref.id)
            if op == "create":
                if key in staged:
                    raise AlreadyExists(f"{key}")
                staged[key] = data
            else:
                if key not in staged:
                    raise NotFound(f"{key}")
                staged[key] = {**staged[key], **data}
        self.db.docs = staged


class FakeFirestore:
    def __init__(self):
        self.docs: dict[tuple[str, str], dict] = {}
        self.lock = threading.Lock()
        self.fail_reads = False
        self.fail_commits = False

    def check_read(self):
        if self.fail_reads:
            raise RuntimeError("simulated Firestore read failure")

    def collection(self, name):
        return _Collection(self, name)

    def transaction(self):
        return _Transaction(self)

    def collection_docs(self, name) -> dict[str, dict]:
        return {i: d for (c, i), d in self.docs.items() if c == name}


def fake_transactional(fn):
    def run(transaction):
        with transaction.db.lock:
            result = fn(transaction)
            transaction.commit()
            return result

    return run


class AnyModelLunaPricing(dict):
    """Yalnızca model adı keyfi olan eski motor testleri için: her ada Luna fiyatı."""

    def get(self, key, default=None):
        return MODEL_PRICING_PER_1M.get(key, MODEL_PRICING_PER_1M["gpt-5.6-luna"])


def make_test_budget(
    budget_usd: float = 100.0, db: FakeFirestore | None = None, pricing=MODEL_PRICING_PER_1M
) -> EventIntelligenceBudget:
    db = db or FakeFirestore()
    return EventIntelligenceBudget(
        FirestoreBudgetLedgerRepository(db=db, transactional=fake_transactional), budget_usd, pricing
    )


def any_model_test_budget() -> EventIntelligenceBudget:
    return make_test_budget(pricing=AnyModelLunaPricing())
