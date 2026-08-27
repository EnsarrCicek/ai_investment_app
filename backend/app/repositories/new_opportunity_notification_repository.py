import hashlib
import uuid
from datetime import datetime, timezone

from firebase_admin import firestore
from google.api_core.exceptions import AlreadyExists

from app.core.firebase import get_firestore_client

COLLECTION = "new_opportunity_notification_log"


class NewOpportunityNotificationRepository:
    """HATA 4B (27.08.2026): `notify_if_new_opportunity()` için EVENT-SPECIFIC,
    atomic-claim tabanlı dedupe.

    HATA 4B pre-commit audit'inde iki gerçek bug kanıtlandı ve bu sürümle
    düzeltildi:

    1. LAST-ONLY DEDUPE BUG: önceki sürüm `(user_id, asset) -> son bildirilen
       event_id` tutuyordu (`get_last_notified_event_id`/
       `set_last_notified_event_id`, TEK doküman, her yeni event'te
       OVERWRITE edilir). Gerçek repository sınıfıyla kanıtlandı: event1
       bildirildikten sonra event2 bildirilirse event1'in kaydı SİLİNMİŞ
       olur (event2 ile overwrite edildiği için); `select_live_breakout_
       event()` daha sonra (event2 INVALIDATED olup canlı seçimden düştüğü
       için) event1'e GERİ DÖNERSE, event1 zaten bir kez bildirilmiş olmasına
       RAĞMEN "bildirilmemiş" görünüp TEKRAR gönderilir. Bu sürüm her
       breakout event'i için AYRI bir doküman tutarak bunu yapısal olarak
       imkânsız kılar — event2'nin dokümanı event1'inkini asla etkilemez.

    2. CONCURRENCY RACE BUG: önceki "check sonra write" deseni (`get()` sonra
       ayrı bir `set()`) atomik değildi — `GET /decisions/{symbol}` route'u
       ile günlük `run_daily_analysis()` job'ı aynı (user,asset,event) için
       yakın zamanda çalışırsa, ikisi de "henüz bildirilmedi" görüp İKİSİ DE
       gönderebilirdi. Bu sürüm Firestore'un `DocumentReference.create()`'ının
       (doküman zaten varsa `AlreadyExists` fırlatan) ATOMİK precondition'ını
       kullanarak "kontrol et VE claim et"i TEK bir Firestore işlemine
       indirger — iki eşzamanlı çağrıdan yalnız BİRİ claim'i kazanabilir.

    DELIVERY SEMANTİĞİ — DÜRÜST CONTRACT (v1, bilinçli tercih):
    Firestore transaction'ı ile FCM (harici bir servis) çağrısı TEK bir
    atomik işleme ALINAMAZ — dolayısıyla "FCM exactly-once garantili" gibi
    bir iddia YOKTUR. İki gerçek crash penceresi var:
      A) claim yazıldı ama FCM çağrılmadan önce process öldü.
      B) FCM'e GÖNDERİLDİ ama `mark_new_opportunity_sent()` çağrılmadan önce
         process öldü (belirsiz/"stuck" PENDING).
    v1'in BİLİNÇLİ tercihi: **DUPLICATE-AVERSE / AT-MOST-ONCE**. Yalnızca
    FCM'in AÇIKÇA (senkron olarak, `messaging.send()` bir hata fırlatarak)
    başarısız olduğu durumda claim RELEASE edilir ve gelecekte tekrar
    denenebilir hale gelir. Belirsiz/"stuck" bir PENDING (B senaryosu) bu
    sürümde OTOMATİK OLARAK yeniden claim edilebilir hale GETİRİLMEZ — yani
    çok nadir bir process-crash durumunda bir bildirim tamamen kaybolabilir,
    ama AYNI event için asla duplicate gönderilmez. Stale-PENDING recovery
    (ör. bir TTL sonrası otomatik reclaim) ayrı, ileride ele alınabilecek bir
    reliability konusudur — bu görevin kapsamı DIŞINDADIR.

    Mevcut `NotificationLogRepository`/`notification_log` koleksiyonuna ve
    `notify_if_strong_decision()`'ın kendi (BUY/SELL karar bazlı) dedupe
    contract'ına HİÇ DOKUNULMADI.
    """

    STATUS_PENDING = "PENDING"
    STATUS_SENT = "SENT"

    def __init__(self):
        self._db = get_firestore_client()

    def _doc_id(self, user_id: str, asset: str, event_id: str) -> str:
        """Ham `f"{user_id}_{asset}_{event_id}"` concat YERİNE deterministic
        bir hash: delimiter collision riski taşımaz (`event_id`'nin kendisi
        `:` içerir, ham concat'te bileşenler arası sınır teorik olarak
        belirsizleşebilirdi), path-safety sorumluluğunu bileşenlerin kendi
        formatına bağlamaz, ve formatları ileride değişse bile stabil kalır.
        """
        canonical = f"{user_id}\0{asset.upper()}\0{event_id}".encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def claim_new_opportunity(self, user_id: str, asset: str, event_id: str) -> str | None:
        """Atomic "kontrol et VE claim et": doküman zaten varsa (bu event daha
        önce claim edilmiş/gönderilmiş) `None` döner (`AlreadyExists`) — FCM
        HİÇ ÇAĞRILMAMALI. Yoksa yeni bir `claim_token` (UUID4) ile `PENDING`
        durumunda oluşturur ve token'ı döner — çağıran bu token'ı
        `mark_new_opportunity_sent`/`release_new_opportunity_claim`'e
        AYNEN geçirmelidir (bkz. o metodların docstring'i — yalnız aynı
        token'ı taşıyan claimant bu dokümanı güncelleyebilir/silebilir).
        """
        claim_token = uuid.uuid4().hex
        doc_ref = self._db.collection(COLLECTION).document(self._doc_id(user_id, asset, event_id))
        try:
            doc_ref.create(
                {
                    "user_id": user_id,
                    "asset": asset,
                    "event_id": event_id,
                    "status": self.STATUS_PENDING,
                    "claim_token": claim_token,
                    "claimed_at": datetime.now(timezone.utc),
                    "sent_at": None,
                }
            )
            return claim_token
        except AlreadyExists:
            return None

    def mark_new_opportunity_sent(self, user_id: str, asset: str, event_id: str, claim_token: str) -> None:
        """FCM başarıyla gönderildikten SONRA çağrılır. Transaction içinde
        okur, yalnızca doküman hâlâ `PENDING` VE `claim_token` eşleşiyorsa
        `SENT`'e günceller — eski/yavaş bir çağrının (yanlış/eski token)
        başka bir claimant'ın dokümanını güncellemesini engeller."""
        doc_ref = self._db.collection(COLLECTION).document(self._doc_id(user_id, asset, event_id))
        transaction = self._db.transaction()

        @firestore.transactional
        def _update(transaction):
            snapshot = doc_ref.get(transaction=transaction)
            data = snapshot.to_dict() if snapshot.exists else None
            if data is not None and data.get("status") == self.STATUS_PENDING and data.get("claim_token") == claim_token:
                transaction.update(doc_ref, {"status": self.STATUS_SENT, "sent_at": datetime.now(timezone.utc)})

        _update(transaction)

    def release_new_opportunity_claim(self, user_id: str, asset: str, event_id: str, claim_token: str) -> None:
        """FCM AÇIKÇA (senkron) başarısız olduğunda çağrılır — claim'i geri
        alır (event hâlâ canlıysa gelecekte gerçek bir retry mümkün olsun
        diye). Transaction içinde okur, yalnızca doküman hâlâ `PENDING` VE
        `claim_token` eşleşiyorsa SİLER — bu sayede zaten `SENT` olmuş bir
        doküman (ör. eski/gecikmiş bir çağrının aynı/eski token'la release
        çağırması) YANLIŞLIKLA SİLİNEMEZ; `SENT` bir event asla release
        edilemez."""
        doc_ref = self._db.collection(COLLECTION).document(self._doc_id(user_id, asset, event_id))
        transaction = self._db.transaction()

        @firestore.transactional
        def _release(transaction):
            snapshot = doc_ref.get(transaction=transaction)
            data = snapshot.to_dict() if snapshot.exists else None
            if data is not None and data.get("status") == self.STATUS_PENDING and data.get("claim_token") == claim_token:
                transaction.delete(doc_ref)

        _release(transaction)
