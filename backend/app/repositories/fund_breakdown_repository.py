from app.core.firebase import get_firestore_client

COLLECTION = "fund_breakdown_snapshots"


class FundBreakdownRepository:
    """fund_snapshot_repository.py ile AYNI prensip (doküman ID = tarih,
    KALICI önbellek, boş sonuç asla yazılmaz) — ayrı bir koleksiyonda, çünkü
    içeriği farklı (fiyat değil, portföy varlık dağılımı yüzdeleri)."""

    def __init__(self):
        self._db = get_firestore_client()

    def get_or_fetch(self, date: str, provider, kind: str = "YAT") -> list[dict]:
        doc_id = f"{kind}_{date}"
        ref = self._db.collection(COLLECTION).document(doc_id)
        doc = ref.get()
        if doc.exists:
            return doc.to_dict()["funds"]

        funds = provider.get_breakdown_snapshot(date, kind=kind)
        if funds:
            ref.set({"date": date, "kind": kind, "funds": funds})
        return funds
