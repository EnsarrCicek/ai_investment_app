"""EventIntelligence bütçe defteri — Firestore transaction'larıyla ortak kalıcı durum.

Defter dokümanı (`event_intelligence_budget/ledger`):
  committed_usd — uzlaştırılmış gerçek tahmini maliyetlerin toplamı;
  reserved_usd  — açık (RESERVED) ve belirsiz (UNCERTAIN) rezervasyonların toplamı.
İlk kullanımda committed_usd, mevcut `token_usage_logs` kayıtlarının toplamından
tohumlanır (tüm-zamanlar anlamı korunur, geçmiş silinmez).

Mutabakat düzeltmeleri (`event_intelligence_budget_adjustments/{id}`): operatörün
girdiği pozitif tutar committed_usd'ye eklenir; kayıt ve defter güncellemesi
aynı transaction'dadır (bkz. `event_intelligence/budget_adjustment.py`).

Rezervasyon dokümanları (`event_intelligence_budget_reservations/{id}`):
RESERVED -> SETTLED (gerçek kullanımla) veya RESERVED -> UNCERTAIN (tutulur).
Uzlaştırmada kullanım kaydı `token_usage_logs/{reservation_id}` olarak AYNI
transaction içinde create edilir — çift muhasebe mümkün değil.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from firebase_admin import firestore

from app.core.firebase import get_firestore_client
from app.models.token_usage import TokenUsageLog
from app.repositories.token_usage_repository import COLLECTION as TOKEN_USAGE_COLLECTION

LEDGER_COLLECTION = "event_intelligence_budget"
LEDGER_DOCUMENT = "ledger"
RESERVATIONS_COLLECTION = "event_intelligence_budget_reservations"
ADJUSTMENTS_COLLECTION = "event_intelligence_budget_adjustments"

RESERVED = "RESERVED"
SETTLED = "SETTLED"
UNCERTAIN = "UNCERTAIN"


class AdjustmentConflictError(ValueError):
    """Aynı düzeltme kimliği farklı içerikle yeniden gönderildi."""


def _amount(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"bütçe defteri alanı geçersiz: {field}")
    return float(value)


class FirestoreBudgetLedgerRepository:
    def __init__(self, db=None, transactional=None):
        self._db = db or get_firestore_client()
        self._transactional = transactional or firestore.transactional

    def _ledger_ref(self):
        return self._db.collection(LEDGER_COLLECTION).document(LEDGER_DOCUMENT)

    def _reservation_ref(self, reservation_id: str):
        return self._db.collection(RESERVATIONS_COLLECTION).document(reservation_id)

    def _run(self, fn):
        return self._transactional(fn)(self._db.transaction())

    def _read_or_seed(self, transaction, ledger_ref) -> tuple[bool, float, float]:
        """Defteri okur; yoksa `token_usage_logs` toplamını AYNI transaction
        içinde hesaplar (tohum). Dönüş: (defter var mı, committed, reserved).
        Tohumlanan defteri yazmak çağıranın işidir (`_ledger_create_fields`)."""
        snapshot = ledger_ref.get(transaction=transaction)
        if snapshot.exists:
            data = snapshot.to_dict()
            return True, _amount(data.get("committed_usd"), "committed_usd"), _amount(data.get("reserved_usd"), "reserved_usd")
        seed = sum(
            _amount(doc.to_dict().get("cost_usd"), "cost_usd")
            for doc in self._db.collection(TOKEN_USAGE_COLLECTION).stream(transaction=transaction)
        )
        return False, seed, 0.0

    @staticmethod
    def _ledger_create_fields(seed: float, committed: float, reserved: float) -> dict:
        return {
            "budget_semantics": "ALL_TIME_TOTAL_ESTIMATED_USD",
            "committed_usd": committed,
            "reserved_usd": reserved,
            "seeded_from_token_usage_logs_usd": seed,
            "seeded_at": datetime.now(timezone.utc),
        }

    def reserve(
        self, *, reservation_id: str, amount_usd: float, budget_usd: float, model: str, news_id: str, asset: str
    ) -> bool:
        ledger_ref = self._ledger_ref()
        reservation_ref = self._reservation_ref(reservation_id)

        def _reserve(transaction) -> bool:
            exists, committed, reserved = self._read_or_seed(transaction, ledger_ref)
            if committed + reserved + amount_usd > budget_usd:
                return False
            if exists:
                transaction.update(ledger_ref, {"reserved_usd": reserved + amount_usd})
            else:
                transaction.create(ledger_ref, self._ledger_create_fields(committed, committed, amount_usd))
            transaction.create(
                reservation_ref,
                {
                    "status": RESERVED,
                    "amount_usd": amount_usd,
                    "model": model,
                    "news_id": news_id,
                    "asset": asset,
                    "created_at": datetime.now(timezone.utc),
                },
            )
            return True

        return self._run(_reserve)

    def settle(self, reservation_id: str, log: TokenUsageLog) -> None:
        ledger_ref = self._ledger_ref()
        reservation_ref = self._reservation_ref(reservation_id)
        usage_ref = self._db.collection(TOKEN_USAGE_COLLECTION).document(reservation_id)

        def _settle(transaction) -> None:
            reservation = reservation_ref.get(transaction=transaction)
            ledger = ledger_ref.get(transaction=transaction)
            if not reservation.exists or not ledger.exists:
                raise ValueError("rezervasyon veya bütçe defteri bulunamadı")
            data = reservation.to_dict()
            if data.get("status") == SETTLED:
                return  # aynı rezervasyonun tekrar uzlaştırılması: no-op
            if data.get("status") != RESERVED:
                raise ValueError(f"rezervasyon uzlaştırılamaz durumda: {data.get('status')!r}")
            amount = _amount(data.get("amount_usd"), "amount_usd")
            ledger_data = ledger.to_dict()
            committed = _amount(ledger_data.get("committed_usd"), "committed_usd")
            reserved = _amount(ledger_data.get("reserved_usd"), "reserved_usd")
            transaction.update(
                ledger_ref,
                {"committed_usd": committed + log.cost_usd, "reserved_usd": max(reserved - amount, 0.0)},
            )
            transaction.update(
                reservation_ref,
                {"status": SETTLED, "settled_cost_usd": log.cost_usd, "settled_at": datetime.now(timezone.utc)},
            )
            transaction.create(usage_ref, log.model_dump())

        self._run(_settle)

    def apply_adjustment(self, adjustment_id: str, amount_usd: float, record: dict, content_sha256: str) -> str:
        """Pozitif düzeltmeyi committed_usd'ye ekler. Aynı kimlik + aynı içerik
        -> "ALREADY_APPLIED" (yazma yok); aynı kimlik + farklı içerik ->
        ValueError. reserved_usd, rezervasyonlar ve kullanım kayıtlarına dokunulmaz."""
        ledger_ref = self._ledger_ref()
        adjustment_ref = self._db.collection(ADJUSTMENTS_COLLECTION).document(adjustment_id)

        def _apply(transaction) -> str:
            existing = adjustment_ref.get(transaction=transaction)
            exists, committed, reserved = self._read_or_seed(transaction, ledger_ref)
            if existing.exists:
                if existing.to_dict().get("content_sha256") != content_sha256:
                    raise AdjustmentConflictError(f"'{adjustment_id}' farklı içerikle zaten kayıtlı")
                return "ALREADY_APPLIED"
            if exists:
                transaction.update(ledger_ref, {"committed_usd": committed + amount_usd})
            else:
                transaction.create(ledger_ref, self._ledger_create_fields(committed, committed + amount_usd, reserved))
            transaction.create(
                adjustment_ref,
                {
                    **record,
                    "content_sha256": content_sha256,
                    "ledger_committed_before_usd": committed,
                    "ledger_committed_after_usd": committed + amount_usd,
                    "ledger_seeded_by_this_adjustment": not exists,
                    "applied_at": datetime.now(timezone.utc),
                },
            )
            return "APPLIED"

        return self._run(_apply)

    def preview_adjustment(self, adjustment_id: str, content_sha256: str) -> dict:
        """Dry-run: yalnızca okuma, transaction ve yazma yok."""
        existing = self._db.collection(ADJUSTMENTS_COLLECTION).document(adjustment_id).get()
        ledger = self._ledger_ref().get()
        if ledger.exists:
            data = ledger.to_dict()
            committed = _amount(data.get("committed_usd"), "committed_usd")
            reserved = _amount(data.get("reserved_usd"), "reserved_usd")
        else:
            committed = sum(
                _amount(doc.to_dict().get("cost_usd"), "cost_usd")
                for doc in self._db.collection(TOKEN_USAGE_COLLECTION).stream()
            )
            reserved = 0.0
        if not existing.exists:
            status = "WOULD_APPLY"
        elif existing.to_dict().get("content_sha256") == content_sha256:
            status = "ALREADY_APPLIED"
        else:
            status = "CONFLICT"
        return {"status": status, "ledger_exists": ledger.exists, "committed_usd": committed, "reserved_usd": reserved}

    def mark_uncertain(self, reservation_id: str) -> None:
        reservation_ref = self._reservation_ref(reservation_id)

        def _mark(transaction) -> None:
            reservation = reservation_ref.get(transaction=transaction)
            if reservation.exists and reservation.to_dict().get("status") == RESERVED:
                transaction.update(reservation_ref, {"status": UNCERTAIN, "uncertain_at": datetime.now(timezone.utc)})

        self._run(_mark)
