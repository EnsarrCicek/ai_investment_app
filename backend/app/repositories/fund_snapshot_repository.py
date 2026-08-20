from app.core.firebase import get_firestore_client

COLLECTION = "fund_snapshots"


class FundSnapshotRepository:
    """Her tarih için TEFAS'tan çekilen fon anlık görüntüsünü KALICI olarak
    önbelleğe alır (doküman ID = tarih, ör. "2026-08-19") — geçmiş bir
    tarihin fon fiyatları asla değişmez, bu yüzden TTL yok (bkz.
    benchmark_service.py'deki 15 dakikalık TTL'in AKSİNE — o "şu an geçerli"
    bir seriydi, bu KALICI geçmiş veridir).

    Boş bir sonuç (o tarihte veri yok — hafta sonu/tatil/henüz yayınlanmamış)
    ASLA önbelleğe yazılmaz: aksi halde "bugün" gibi henüz yayınlanmamış bir
    tarih sonsuza kadar boş kalırmış gibi görünürdü.
    """

    def __init__(self):
        self._db = get_firestore_client()

    def get_or_fetch(self, date: str, provider, kind: str = "YAT") -> list[dict]:
        doc_id = f"{kind}_{date}"
        ref = self._db.collection(COLLECTION).document(doc_id)
        doc = ref.get()
        if doc.exists:
            return doc.to_dict()["funds"]

        funds = provider.get_snapshot(date, kind=kind)
        if funds:
            ref.set({"date": date, "kind": kind, "funds": funds})
        return funds
