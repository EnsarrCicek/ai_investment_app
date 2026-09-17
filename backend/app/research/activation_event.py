"""Technical V1 aktivasyon OLAYI (activation event) -- saf domain modeli.

HATA 13B. `app.research.activation_lock`'taki aktivasyon KİLİDİNDEN (protokol
× onaylı metodoloji parmak-izi × belirli Cloud Run deployment kimliği
üçlüsünü TANIMLAYAN kayıt) TAMAMEN AYRI, değişmez bir YETKİLENDİRME kaydı:
"şu protokol altında şu aktivasyon kilidi, prospektif evidence-capture
yapmaya GERÇEKTEN yetkilidir" beyanı.

Aktivasyon KİLİDİ ile aktivasyon OLAYI arasındaki ayrım (bkz.
`activation_lock.py` modül docstring'i, HATA 12N3C2-B2-A): kilit "şu
deployment şu metodoloji ile evidence-capture yapmaya YETKİLİDİR" der;
olay ise bu yetkinin GERÇEKTEN, belirli bir anda YÜRÜRLÜĞE GİRDİĞİNİN
kanıtıdır. `INITIAL` olayının Firestore `create_time`'ı, ileride
`effective_holdout_start`'ın hesaplanacağı ham girdilerden BİRİDİR --
ama bu hesaplama BU MODÜLÜN KAPSAMI DIŞINDADIR (HATA 13B section 16/17).

Bu modül KESİNLİKLE şunları YAPMAZ:
  - Firestore/GCS/ağ erişimi (firebase_admin, google.cloud.firestore yok).
  - Ortam değişkeni okuma (os.environ yok).
  - Zaman damgası üretimi (datetime.now() yok) -- create_time HER ZAMAN
    repository katmanının (`technical_v1_activation_event_repository.py`)
    sorumluluğundadır, bu saf modelde YOKTUR.
  - `effective_holdout_start` hesaplaması YAPMAZ (HATA 13B section 16).
  - `TechnicalV1ActivationLockRepository`'yi/`claim_attempt()`'i/herhangi
    bir attempt modelini import/çağırmaz.
  - Kullanıcı kimliği/email/aktör adı/serbest metin not TAŞIMAZ.

İKİ kapalı olay türü (section 5, ÜÇÜNCÜSÜ YOK):
  - `INITIAL`: bir `protocol_version` için İLK aktivasyon kilidini
    yetkilendirir. Kimliği YALNIZCA `protocol_version`'a bağlıdır --
    `activation_lock_id` kimliğe GİRMEZ (bu yüzden aynı `protocol_version`
    için `INITIAL` bir SINGLETON'dur), ama olayın İÇERİĞİ yetkilendirdiği
    TAM `activation_lock_id`'yi BAĞLAR. Sonuç: aynı `protocol_version` +
    FARKLI bir `activation_lock_id` ile ikinci bir `INITIAL` YARATILAMAZ --
    aynı ID altında farklı içerik = repository katmanında bir
    `ProvenanceConflictError` (KASITLI, section 6/30).
  - `LOCK_AUTHORIZED`: aynı protokol altında SONRAKİ/yerine-geçen bir
    aktivasyon kilidini yetkilendirir. Kimliği HEM `protocol_version` HEM
    `activation_lock_id`'ye bağlıdır -- her yeni yetkilendirilen kilidin
    KENDİ, ayrı bir deterministik olay ID'si vardır.

KİLİTLİ SINIR (HATA 13B section 3): bu modülün var olması, "aktivasyon
olayı olmadan claim yok" kuralını SİSTEM GENELİNDE UYGULAMAZ -- henüz
hiçbir attempt worker/controller yoktur. Bu kuralı GERÇEKTEN uygulayacak
olan, `claim_attempt()`'ten HEMEN ÖNCE `app.research.preclaim_
authorization.authorize_pre_claim()`'i çağıracak olan HATA 13C'dir.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.research.canonical_hash import content_sha256
from app.research.evidence_models import validate_sha256_hex

TECHNICAL_V1_ACTIVATION_EVENT_SCHEMA_VERSION = "technical_v1_activation_event_v1"

# to_document_fields() ile BİREBİR aynı 6 anahtar -- from_document_fields()'in
# katı alan-seti doğrulaması bu kümeye karşı yapılır (bkz. activation_lock.py
# ile AYNI desen).
_DOCUMENT_FIELD_KEYS = frozenset(
    {
        "activation_event_schema_version",
        "activation_event_id",
        "event_type",
        "protocol_version",
        "activation_lock_id",
        "record_content_sha256",
    }
)


class ActivationEventType(str, Enum):
    """Kapalı (closed) küme -- HATA 13B kapsamı YALNIZCA bu iki türle
    sınırlıdır (section 5). Üçüncü bir tür İCAT EDİLMEZ."""

    INITIAL = "INITIAL"
    LOCK_AUTHORIZED = "LOCK_AUTHORIZED"


def _validate_non_empty_str(value: object, field_name: str) -> None:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field_name} boş olmayan bir string olmalı: {value!r}")


def _validate_no_surrounding_whitespace(value: str, field_name: str) -> None:
    if value != value.strip():
        raise ValueError(f"{field_name} baştaki/sondaki boşluk içeremez: {value!r}")


def compute_initial_activation_event_id(*, protocol_version: str) -> str:
    """HATA 13B section 6: `INITIAL` kimliği YALNIZCA `protocol_version`'a
    bağlıdır -- `activation_lock_id` KASITLI OLARAK kimliğe GİRMEZ (bu
    yüzden bir `protocol_version` için tek bir `INITIAL` ID'si vardır,
    hangi kilit yetkilendirilmeye çalışılırsa çalışılsın)."""
    payload = {
        "activation_event_identity": {
            "activation_event_schema_version": TECHNICAL_V1_ACTIVATION_EVENT_SCHEMA_VERSION,
            "event_type": ActivationEventType.INITIAL.value,
            "protocol_version": protocol_version,
        }
    }
    return content_sha256(payload)


def compute_lock_authorized_activation_event_id(*, protocol_version: str, activation_lock_id: str) -> str:
    """HATA 13B section 7: `LOCK_AUTHORIZED` kimliği HEM `protocol_version`
    HEM `activation_lock_id`'ye bağlıdır -- her ayrı yetkilendirilen kilit
    KENDİ, deterministik olay ID'sine sahiptir."""
    payload = {
        "activation_event_identity": {
            "activation_event_schema_version": TECHNICAL_V1_ACTIVATION_EVENT_SCHEMA_VERSION,
            "event_type": ActivationEventType.LOCK_AUTHORIZED.value,
            "protocol_version": protocol_version,
            "activation_lock_id": activation_lock_id,
        }
    }
    return content_sha256(payload)


def _compute_expected_activation_event_id(
    *, event_type: ActivationEventType, protocol_version: str, activation_lock_id: str
) -> str:
    """`event_type`'a göre HANGİ kimlik formülünün uygulanacağını seçen TEK
    yer -- `__post_init__`/`from_document_fields()` İKİ AYRI yerde bu
    seçimi TEKRARLAMAZ, buraya delege eder."""
    if event_type == ActivationEventType.INITIAL:
        return compute_initial_activation_event_id(protocol_version=protocol_version)
    if event_type == ActivationEventType.LOCK_AUTHORIZED:
        return compute_lock_authorized_activation_event_id(
            protocol_version=protocol_version, activation_lock_id=activation_lock_id
        )
    raise ValueError(f"Bilinmeyen event_type, kimlik hesaplanamıyor: {event_type!r}")


@dataclass(frozen=True)
class TechnicalV1ActivationEvent:
    """Belirli bir `protocol_version` altında belirli bir
    `activation_lock_id`'yi prospektif evidence-capture yapmaya
    YETKİLENDİREN, değişmez (immutable), ekle-yalnızca (append-only) kayıt.

    Zaman damgası TAŞIMAZ -- `create_time` her zaman repository katmanının
    (`technical_v1_activation_event_repository.py`) sorumluluğundadır.
    """

    activation_event_schema_version: str
    activation_event_id: str
    event_type: ActivationEventType
    protocol_version: str
    activation_lock_id: str

    def __post_init__(self) -> None:
        if self.activation_event_schema_version != TECHNICAL_V1_ACTIVATION_EVENT_SCHEMA_VERSION:
            raise ValueError(
                "activation_event_schema_version beklenen sabitle eşleşmiyor "
                f"(forward-compat desteklenmiyor): {self.activation_event_schema_version!r} != "
                f"{TECHNICAL_V1_ACTIVATION_EVENT_SCHEMA_VERSION!r}"
            )

        if not isinstance(self.event_type, ActivationEventType):
            raise ValueError(
                f"event_type tam olarak bir ActivationEventType üyesi olmalı (normalizasyon/coerce YOK): "
                f"{self.event_type!r}"
            )

        _validate_non_empty_str(self.protocol_version, "protocol_version")
        _validate_no_surrounding_whitespace(self.protocol_version, "protocol_version")

        validate_sha256_hex(self.activation_lock_id)
        validate_sha256_hex(self.activation_event_id)

        # activation_event_id ASLA çağırandan körü körüne güvenilmez --
        # event_type'ın KENDİ kimlik formülünden bağımsız olarak yeniden
        # türetilir ve eşitlik zorunlu kılınır (bkz. activation_lock.py
        # ile AYNI desen, HATA 12N3C2-B2-A section 11).
        expected_activation_event_id = _compute_expected_activation_event_id(
            event_type=self.event_type,
            protocol_version=self.protocol_version,
            activation_lock_id=self.activation_lock_id,
        )
        if self.activation_event_id != expected_activation_event_id:
            raise ValueError(
                "activation_event_id, event_type'ın kimlik formülünden bağımsız olarak yeniden "
                f"hesaplanan değerle eşleşmiyor -- verilen={self.activation_event_id!r}, "
                f"beklenen={expected_activation_event_id!r}"
            )

    def to_content_fields(self) -> dict:
        """Depolanan TÜM 5 içerik alanı (activation_event_id DAHİL).

        `record_content_sha256`'nın payload'ı budur -- `activation_lock.py`
        ile AYNI kilitlenen düzeltme: record_content_sha256,
        activation_event_id'yi de kapsar (yalnızca kendi kendisini hariç
        tutar), çünkü aksi halde activation_event_id'nin kendisindeki bir
        bozulma (tampering) record_content_sha256 tarafından hiç
        yakalanmazdı."""
        return {
            "activation_event_schema_version": self.activation_event_schema_version,
            "activation_event_id": self.activation_event_id,
            "event_type": self.event_type.value,
            "protocol_version": self.protocol_version,
            "activation_lock_id": self.activation_lock_id,
        }

    @property
    def record_content_sha256(self) -> str:
        """Depolanan bir alan DEĞİL -- her zaman türetilen bir @property."""
        return content_sha256(self.to_content_fields())

    def to_document_fields(self) -> dict:
        """5 içerik alanı + record_content_sha256 = tam olarak 6 alan.
        create_time YOKTUR (bu saf modelin kapsamı dışında)."""
        return {**self.to_content_fields(), "record_content_sha256": self.record_content_sha256}

    @classmethod
    def from_document_fields(cls, data: dict) -> "TechnicalV1ActivationEvent":
        """Katı yeniden kuruluş: eksik/bilinmeyen alan reddedilir, şema
        onarımı/normalizasyon YAPILMAZ. `activation_lock.py`'nin
        `from_document_fields()`'i İLE AYNI desen: saklanan
        `record_content_sha256`'yı DA doğrudan burada, bağımsız olarak
        yeniden hesaplayıp karşılaştırır."""
        actual_keys = set(data.keys())
        if actual_keys != _DOCUMENT_FIELD_KEYS:
            missing = _DOCUMENT_FIELD_KEYS - actual_keys
            unexpected = actual_keys - _DOCUMENT_FIELD_KEYS
            raise ValueError(
                "from_document_fields: alan seti beklenen şemayla eşleşmiyor "
                f"(eksik={sorted(missing)}, beklenmeyen={sorted(unexpected)})"
            )

        stored_record_content_sha256 = data["record_content_sha256"]
        validate_sha256_hex(stored_record_content_sha256)

        try:
            event_type = ActivationEventType(data["event_type"])
        except ValueError as exc:
            raise ValueError(f"Bilinmeyen/geçersiz event_type: {data['event_type']!r}") from exc

        reconstructed = cls(
            activation_event_schema_version=data["activation_event_schema_version"],
            activation_event_id=data["activation_event_id"],
            event_type=event_type,
            protocol_version=data["protocol_version"],
            activation_lock_id=data["activation_lock_id"],
        )

        if reconstructed.record_content_sha256 != stored_record_content_sha256:
            raise ValueError(
                "from_document_fields: stored record_content_sha256, içerik alanlarından "
                f"bağımsız olarak yeniden hesaplanan değerle eşleşmiyor -- stored="
                f"{stored_record_content_sha256!r}, recomputed={reconstructed.record_content_sha256!r}"
            )

        return reconstructed


def build_initial_activation_event(*, protocol_version: str, activation_lock_id: str) -> TechnicalV1ActivationEvent:
    """HATA 13B section 12: çağıranın kimlik hesabını KENDİSİ yapmasını
    ÖNLEYEN saf builder -- `compute_initial_activation_event_id()`'i
    doğrudan çağırır, İKİNCİ bir kimlik hesaplama mantığı YAZILMAZ."""
    activation_event_id = compute_initial_activation_event_id(protocol_version=protocol_version)
    return TechnicalV1ActivationEvent(
        activation_event_schema_version=TECHNICAL_V1_ACTIVATION_EVENT_SCHEMA_VERSION,
        activation_event_id=activation_event_id,
        event_type=ActivationEventType.INITIAL,
        protocol_version=protocol_version,
        activation_lock_id=activation_lock_id,
    )


def build_lock_authorized_event(*, protocol_version: str, activation_lock_id: str) -> TechnicalV1ActivationEvent:
    """HATA 13B section 12: `LOCK_AUTHORIZED` için AYNI desen."""
    activation_event_id = compute_lock_authorized_activation_event_id(
        protocol_version=protocol_version, activation_lock_id=activation_lock_id
    )
    return TechnicalV1ActivationEvent(
        activation_event_schema_version=TECHNICAL_V1_ACTIVATION_EVENT_SCHEMA_VERSION,
        activation_event_id=activation_event_id,
        event_type=ActivationEventType.LOCK_AUTHORIZED,
        protocol_version=protocol_version,
        activation_lock_id=activation_lock_id,
    )
