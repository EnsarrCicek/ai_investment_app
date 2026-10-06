"""Portföy testleri için bellek içi depo + satış defteri sahteleri (Firestore yok, ağ yok).

`FakeLedgerRepository.execute_sale`, gerçek depodaki tek Firestore işlemi sözleşmesini taklit eder: kilit altında
oku -> planla -> yaz; plan hata verirse hiçbir şey yazılmaz. Gerçek Firestore işlem/çakışma davranışını DEĞİL,
depo düzeyindeki atomiklik sözleşmesini sınar.
"""

import itertools
import threading

from app.models.portfolio_position import PortfolioPosition, merged_currency
from app.models.portfolio_transaction import PortfolioTransaction
from app.services.portfolio.sale_ledger import ledger_totals


class InMemoryPortfolio:
    def __init__(self, docs=()):
        self.lots: dict[str, dict] = {}
        self.sales: dict[str, dict] = {}
        self._ids = itertools.count()
        self.lock = threading.Lock()
        for d in docs:
            self.add_lot(d)

    def add_lot(self, doc: dict) -> str:
        lot_id = f"lot{next(self._ids)}"
        self.lots[lot_id] = dict(doc)
        return lot_id

    def new_sale_id(self) -> str:
        return f"sale{next(self._ids)}"


class FakePortfolioRepository:
    def __init__(self, store: InMemoryPortfolio):
        self.s = store

    def add(self, position: PortfolioPosition) -> str:
        return self.s.add_lot(position.model_dump())

    def list_for_user(self, user_id):
        return [(i, PortfolioPosition(**d)) for i, d in self.s.lots.items() if d["user_id"] == user_id]

    def get_position_for_asset(self, user_id, asset):
        lots = [(i, PortfolioPosition(**d)) for i, d in self.s.lots.items() if d["user_id"] == user_id and d["asset"] == asset]
        if not lots:
            return None
        sales = [(i, PortfolioTransaction(**d)) for i, d in self.s.sales.items() if d["user_id"] == user_id and d["asset"] == asset]
        qty, cost, _ = ledger_totals(lots, sales)
        return PortfolioPosition(user_id=user_id, asset=asset, buy_price=round(float(cost / qty), 2),
                                 buy_date=min(p.buy_date for _, p in lots), quantity=float(qty),
                                 created_at=max(p.created_at for _, p in lots), currency=merged_currency([p for _, p in lots]))

    def delete_for_asset(self, user_id, asset):
        for i in [i for i, d in self.s.lots.items() if d["user_id"] == user_id and d["asset"] == asset]:
            del self.s.lots[i]

    def replace_for_asset(self, user_id, asset, position):
        self.delete_for_asset(user_id, asset)
        return self.add(position)


class FakeLedgerRepository:
    def __init__(self, store: InMemoryPortfolio):
        self.s = store

    def sales_for_user(self, user_id):
        return [(i, PortfolioTransaction(**d)) for i, d in self.s.sales.items() if d["user_id"] == user_id]

    def load(self, user_id, asset, transaction=None):
        lots = [(i, PortfolioPosition(**d)) for i, d in self.s.lots.items() if d["user_id"] == user_id and d["asset"] == asset]
        sales = [(i, PortfolioTransaction(**d)) for i, d in self.s.sales.items() if d["user_id"] == user_id and d["asset"] == asset]
        return lots, sales

    def execute_sale(self, user_id, asset, plan_fn):
        with self.s.lock:
            lots, sales = self.load(user_id, asset)
            plan = plan_fn(lots, sales)  # hata -> hiçbir şey yazılmaz
            sale_id = self.s.new_sale_id()
            self.s.sales[sale_id] = plan.transaction.model_dump()
            if plan.full:
                for lot_id in plan.lot_ids:
                    del self.s.lots[lot_id]
            return sale_id, plan
