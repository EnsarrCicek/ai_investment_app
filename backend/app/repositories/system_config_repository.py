from app.core.firebase import get_firestore_client

COLLECTION = "system_config"


class SystemConfigRepository:
    """Ana doküman kural 13: skor ağırlıkları hard-code edilmez, Firestore system_config üzerinden yönetilir."""

    def __init__(self):
        self._db = get_firestore_client()

    def get(self, config_id: str, defaults: dict) -> dict:
        ref = self._db.collection(COLLECTION).document(config_id)
        doc = ref.get()
        if not doc.exists:
            ref.set(defaults)
            return defaults
        return {**defaults, **doc.to_dict()}

    def get_raw(self, config_id: str) -> dict | None:
        """HATA 5B2D: `get()`'in aksine auto-seed YAPMAZ ve default'larla
        SESSİZCE birleştirmez -- doküman yoksa `None` döner (Firestore'a
        HİÇBİR ŞEY YAZMAZ), varsa TAM OLARAK Firestore'da ne varsa onu döner.
        HATA 5B2C'de kanıtlanan config-drift kök nedeni (`get()`'in eksik/
        partial bir dokümanı sessizce default'larla tamamlaması, ör.
        `ema_slope` anahtarının aylarca fark edilmeden eksik kalması) tekrar
        ETMESİN diye -- çağıran (bkz. `technical/scoring.py`,
        `resolve_family_weights`) eksik/fazla anahtarı KENDİSİ fail-fast
        şekilde ele almalıdır, bu metod hiçbir tamamlama/doğrulama yapmaz.
        """
        doc = self._db.collection(COLLECTION).document(config_id).get()
        return doc.to_dict() if doc.exists else None
