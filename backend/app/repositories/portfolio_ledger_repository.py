from typing import Callable

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import get_firestore_client
from app.models.portfolio_position import PortfolioPosition
from app.models.portfolio_transaction import PortfolioTransaction

POSITIONS = "portfolio_positions"
TRANSACTIONS = "portfolio_transactions"
# Pozisyon başına sıralama belgesi: her satış işlemi bu belgeyi okuyup yazar; böylece aynı pozisyondaki eşzamanlı iki
# satış Firestore işlem çakışmasıyla sıralanır (biri yeniden denenir ve güncel lot/satış durumunu görür).
LEDGER_HEADS = "portfolio_ledger_heads"


class PortfolioLedgerRepository:
    """Satış defteri: alış lotları + değişmez satış kayıtları. Satış tek bir Firestore işlemi içinde yürür:
    (1) sıralama belgesi, lotlar ve satışlar okunur, (2) `plan_fn` sürümü doğrular ve muhasebeyi hesaplar,
    (3) satış kaydı yazılır; tam satışta lotlar silinir (mevcut `/close` sözleşmesi). Hata -> hiçbir şey yazılmaz.

    user_id her zaman backend'de doğrulanmış kimliktir (bkz. app/core/auth.py)."""

    def __init__(self):
        self._db = get_firestore_client()

    def _lots_query(self, user_id: str, asset: str):
        return (self._db.collection(POSITIONS).where(filter=FieldFilter("user_id", "==", user_id))
                .where(filter=FieldFilter("asset", "==", asset)))

    def _sales_query(self, user_id: str, asset: str):
        return (self._db.collection(TRANSACTIONS).where(filter=FieldFilter("user_id", "==", user_id))
                .where(filter=FieldFilter("asset", "==", asset)))

    def load(self, user_id: str, asset: str, transaction=None):
        lots = [(d.id, PortfolioPosition(**d.to_dict())) for d in self._lots_query(user_id, asset).stream(transaction=transaction)]
        sales = [(d.id, PortfolioTransaction(**d.to_dict())) for d in self._sales_query(user_id, asset).stream(transaction=transaction)]
        return lots, sales

    def execute_sale(self, user_id: str, asset: str, plan_fn: Callable) -> tuple[str, object]:
        """plan_fn(lots, sales) -> SalePlan (veya SaleError fırlatır). Döner: (satış kaydı kimliği, plan)."""
        head_ref = self._db.collection(LEDGER_HEADS).document(f"{user_id}_{asset}")

        @firestore.transactional
        def run(tx):
            head_ref.get(transaction=tx)  # sıralama kilidi (okunan belge yazılınca çakışma algılanır)
            lots, sales = self.load(user_id, asset, transaction=tx)
            plan = plan_fn(lots, sales)
            sale_ref = self._db.collection(TRANSACTIONS).document()
            tx.set(sale_ref, plan.transaction.model_dump())
            if plan.full:
                for lot_id in plan.lot_ids:
                    tx.delete(self._db.collection(POSITIONS).document(lot_id))
            tx.set(head_ref, {"user_id": user_id, "asset": asset, "last_sale_id": sale_ref.id,
                              "last_version_before": plan.transaction.position_version_before,
                              "updated_at": plan.transaction.created_at})
            return sale_ref.id, plan

        return run(self._db.transaction())

    def sales_for_user(self, user_id: str) -> list[tuple[str, PortfolioTransaction]]:
        docs = self._db.collection(TRANSACTIONS).where(filter=FieldFilter("user_id", "==", user_id)).stream()
        return [(d.id, PortfolioTransaction(**d.to_dict())) for d in docs]
