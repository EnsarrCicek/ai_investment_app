"""Bütçe mutabakat düzeltmesi CLI'ı — sahte Firestore ile (gerçek Firestore
eşzamanlılığının kanıtı DEĞİLDİR)."""

import copy
import io
import json

import pytest
from google.api_core.exceptions import AlreadyExists

from app.engines.event_intelligence.budget import BudgetExhaustedError, EventIntelligenceBudget
from app.engines.event_intelligence.budget_adjustment import _run_cli
from app.repositories.event_intelligence_budget_repository import (
    ADJUSTMENTS_COLLECTION,
    LEDGER_COLLECTION,
    RESERVATIONS_COLLECTION,
    FirestoreBudgetLedgerRepository,
)
from tests.event_budget_fakes import FakeFirestore, fake_transactional

PROJECT = "ai-investment-app-2026"
REQUEST = {"messages": [{"role": "user", "content": "x"}], "response_format": None, "max_completion_tokens": 100}
SECRET_REASON = "gizli-gerekce-metni"
SECRET_REF = "saglayici-rapor-ref-12345"


@pytest.fixture(autouse=True)
def _project_env(monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)


def _db(logs_usd=()):
    db = FakeFirestore()
    db.project = PROJECT
    for i, cost in enumerate(logs_usd):
        db.docs[("token_usage_logs", f"legacy-{i}")] = {"cost_usd": cost}
    return db


def _repo(db, transactional=fake_transactional):
    return FirestoreBudgetLedgerRepository(db=db, transactional=transactional)


def _cli(db, *extra, adjustment_id="opening-1", amount="0.5", budget_usd=5.0, scope="openai proj, luna", factory=None):
    out = io.StringIO()
    argv = [
        "--project", PROJECT, "--adjustment-id", adjustment_id, f"--amount-usd={amount}",
        "--reason", SECRET_REASON, "--provider-report-ref", SECRET_REF,
        "--period-start", "2026-08-01T00:00:00Z", "--period-end", "2026-10-01T00:00:00Z", "--scope", scope, *extra,
    ]
    code = _run_cli(argv, firestore_client_factory=factory or (lambda: db), repository_factory=lambda db: _repo(db),
                    budget_usd=budget_usd, out=out)
    return code, json.loads(out.getvalue()), out.getvalue()


def _ledger(db):
    return db.collection_docs(LEDGER_COLLECTION).get("ledger")


def _reserve(db, amount_budget=100.0):
    return EventIntelligenceBudget(_repo(db), amount_budget).reserve(model="gpt-5.6-luna", request=REQUEST, news_id="n", asset="A")


# ------------------------------------------------------------------ dry-run + apply


def test_dry_run_is_default_and_writes_nothing():
    db = _db(logs_usd=[1.0])
    before = copy.deepcopy(db.docs)
    code, payload, raw = _cli(db)
    assert code == 0 and payload["status"] == "DRY_RUN" and payload["would"] == "WOULD_APPLY"
    assert payload["committed_usd_before"] == pytest.approx(1.0) and payload["committed_usd_after"] == pytest.approx(1.5)
    assert db.docs == before
    assert SECRET_REASON not in raw and SECRET_REF not in raw


def test_apply_adds_positive_amount_and_preserves_reservations_and_usage_logs():
    db = _db(logs_usd=[1.0])
    reservation = _reserve(db)
    db.docs[(RESERVATIONS_COLLECTION, "uncertain-1")] = {"status": "UNCERTAIN", "amount_usd": 0.2}
    ledger_before = dict(_ledger(db))
    reservations_before = copy.deepcopy(db.collection_docs(RESERVATIONS_COLLECTION))
    logs_before = copy.deepcopy(db.collection_docs("token_usage_logs"))

    code, payload, _ = _cli(db, "--apply", amount="0.123456")

    assert code == 0 and payload["status"] == "APPLIED"
    ledger = _ledger(db)
    assert ledger["committed_usd"] == pytest.approx(ledger_before["committed_usd"] + 0.123456)
    assert ledger["reserved_usd"] == pytest.approx(reservation.amount_usd)
    assert db.collection_docs(RESERVATIONS_COLLECTION) == reservations_before
    assert db.collection_docs("token_usage_logs") == logs_before
    [record] = db.collection_docs(ADJUSTMENTS_COLLECTION).values()
    assert record["amount_micro_usd"] == 123456 and record["ledger_seeded_by_this_adjustment"] is False


def test_same_id_same_content_is_idempotent():
    db = _db(logs_usd=[1.0])
    _cli(db, "--apply")
    committed = _ledger(db)["committed_usd"]
    code, payload, _ = _cli(db, "--apply")
    assert code == 0 and payload["status"] == "ALREADY_APPLIED"
    assert _ledger(db)["committed_usd"] == committed
    assert len(db.collection_docs(ADJUSTMENTS_COLLECTION)) == 1


@pytest.mark.parametrize("flag", [[], ["--apply"]])
def test_same_id_different_content_is_rejected(flag):
    db = _db(logs_usd=[1.0])
    _cli(db, "--apply", amount="0.5")
    before = copy.deepcopy(db.docs)
    code, payload, _ = _cli(db, *flag, amount="0.6")
    assert code == 2 and payload["status"] == "CONFLICT"
    assert db.docs == before


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "inf", "-inf", "abc", "0.0000001", ""])
def test_invalid_amounts_are_rejected_before_any_firestore_access(amount):
    def no_client():
        raise AssertionError("Firestore'a erişilmemeli")

    code, payload, _ = _cli(None, "--apply", amount=amount, factory=no_client)
    assert code == 2 and payload["status"] == "INVALID_INPUT"


def test_adjustment_beyond_limit_blocks_later_paid_calls_via_existing_gate():
    db = _db(logs_usd=[4.0])
    code, payload, _ = _cli(db, "--apply", amount="1.5", budget_usd=5.0)
    assert code == 0 and payload["remaining_usd_after"] < 0
    with pytest.raises(BudgetExhaustedError):
        EventIntelligenceBudget(_repo(db), 5.0).reserve(model="gpt-5.6-luna", request=REQUEST, news_id="n", asset="A")


# ------------------------------------------------------------------ first ledger creation


def test_first_adjustment_seeds_history_once():
    db = _db(logs_usd=[1.0, 0.25])
    _cli(db, "--apply", amount="0.5")
    ledger = _ledger(db)
    assert ledger["seeded_from_token_usage_logs_usd"] == pytest.approx(1.25)
    assert ledger["committed_usd"] == pytest.approx(1.75)
    assert ledger["reserved_usd"] == 0.0
    _reserve(db)  # sonraki ücretli çağrı geçmişi yeniden eklemez
    assert _ledger(db)["committed_usd"] == pytest.approx(1.75)


def test_race_with_first_paid_call_loses_nothing_and_counts_history_once():
    db = _db(logs_usd=[1.0])
    deferred = []

    def read_now_commit_later(fn):
        def run(transaction):
            result = fn(transaction)
            deferred.append(transaction)
            return result
        return run

    # Düzeltme defter yokken okur; ilk ücretli çağrı defteri ondan önce oluşturur.
    _repo(db, read_now_commit_later).apply_adjustment("opening-1", 0.5, {"x": 1}, "sha")
    reservation = _reserve(db)
    with pytest.raises(AlreadyExists):
        deferred[0].commit()  # kaybeden düzeltme hiçbir şey yazmadı
    assert db.collection_docs(ADJUSTMENTS_COLLECTION) == {}
    assert _ledger(db)["committed_usd"] == pytest.approx(1.0)

    # Operatör aynı komutu yeniden çalıştırır (gerçek Firestore'da transaction yeniden denemesi).
    code, payload, _ = _cli(db, "--apply", amount="0.5")
    assert payload["status"] == "APPLIED"
    ledger = _ledger(db)
    assert ledger["seeded_from_token_usage_logs_usd"] == pytest.approx(1.0)
    assert ledger["committed_usd"] == pytest.approx(1.5)
    assert ledger["reserved_usd"] == pytest.approx(reservation.amount_usd)


# ------------------------------------------------------------------ project identity


@pytest.mark.parametrize("env, client_project", [(None, PROJECT), ("other", PROJECT), (PROJECT, "other")])
def test_project_mismatch_blocks_before_reads(monkeypatch, env, client_project):
    if env is None:
        monkeypatch.delenv("FIREBASE_PROJECT_ID")
    else:
        monkeypatch.setenv("FIREBASE_PROJECT_ID", env)
    db = _db()
    db.project = client_project
    db.fail_reads = True  # okuma denenirse test patlar
    code, payload, _ = _cli(db, "--apply")
    assert code == 2 and payload["status"] == "PROJECT_MISMATCH"
