from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import get_firestore_client
from app.models.intraday_bar import IntradayBar

COLLECTION = "intraday_bars"


class IntradayBarRepository:
    def __init__(self):
        self._db = get_firestore_client()

    def add_batch(self, bars: list[IntradayBar]) -> int:
        """Firestore batch write — aynı asset_id + session_date + timestamp
        ile daha önce yazılmış barları ATLAR (script'in yanlışlıkla tekrar
        çalıştırılması durumunda VWAP'ı bozacak yinelenen hacim kayıtlarını
        önlemek için). Yazılan yeni bar sayısını döner.
        """
        if not bars:
            return 0

        by_session: dict[tuple[str, str], list[IntradayBar]] = {}
        for bar in bars:
            by_session.setdefault((bar.asset_id, bar.session_date), []).append(bar)

        new_bars: list[IntradayBar] = []
        for (asset_id, session_date), session_bars in by_session.items():
            existing_timestamps = {b.timestamp for b in self.list_for_session(asset_id, session_date)}
            new_bars.extend(b for b in session_bars if b.timestamp not in existing_timestamps)

        written = 0
        for chunk_start in range(0, len(new_bars), 450):
            chunk = new_bars[chunk_start : chunk_start + 450]
            batch = self._db.batch()
            for bar in chunk:
                ref = self._db.collection(COLLECTION).document()
                batch.set(ref, bar.model_dump())
            batch.commit()
            written += len(chunk)
        return written

    def list_for_session(self, asset_id: str, session_date: str) -> list[IntradayBar]:
        docs = (
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("asset_id", "==", asset_id))
            .where(filter=FieldFilter("session_date", "==", session_date))
            .stream()
        )
        bars = [IntradayBar(**doc.to_dict()) for doc in docs]
        bars.sort(key=lambda b: b.timestamp)
        return bars
