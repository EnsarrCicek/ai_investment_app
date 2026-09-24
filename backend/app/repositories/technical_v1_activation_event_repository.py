"""HATA 13B — Technical V1 immutable activation-event repository'si.

Koleksiyon: `technical_v1_activation_events/{activation_event_id}` -- create-only,
KALICI yetkilendirme kaydı olarak. Bu repository:

  - `TechnicalV1ActivationLockRepository`'yi hiç import/çağırmaz -- bir
    kilit oluşturmak ile o kilidi yetkilendirmek AYRI, açık işlemlerdir
    (HATA 13B section 19/47). Bu repository, verilen bir
    `TechnicalV1ActivationEvent`'in kendi başına yapısal olarak geçerli
    olduğunu varsayar/doğrular -- çağıranın önce gerçekten var olan bir
    kilit ile tutarlı bir olay inşa etmiş olması (bkz. `app.research.
    preclaim_authorization`) BU repository'nin sorumluluğu DEĞİLDİR.
  - `AttemptClaim`/`AttemptResult`/`TechnicalV1AttemptRepository`'ye hiç
    dokunmaz -- HATA 13B, `claim_attempt()`'e HİÇBİR guard TAKMAZ (section
    46), bu yalnızca HATA 13C'nin işidir.
  - `TechnicalV1ActivationEvent.to_document_fields()`'i TEK, kanonik
    doküman temsili olarak kullanır -- final şemayı BURADA BAĞIMSIZ OLARAK
    YENİDEN İNŞA ETMEZ; kimlik/hash/format doğrulama mantığını KOPYALAMAZ,
    `app.research.activation_event`'ten import eder.

Kilitli create-only sözleşme (`TechnicalV1ActivationLockRepository`/
`TechnicalV1EvaluationRepository`/`TechnicalV1SessionManifestRepository`
İLE AYNI desen, `AlreadyExists` precondition'ı):
  - `.create()` yalnız BİR KEZ, ilk yaratımda kullanılır.
  - `set()`/`update()`/`add()`/`delete()` normal akışta HİÇ KULLANILMAZ.
  - Var olan bir doküman bulunursa: KÖRÜKÖRÜNE idempotent başarı İLAN
    EDİLMEZ -- ÖNCE var olan dokümanın HAM içerik-hash'i yeniden hesaplanıp
    doğrulanır, SONRA adayla karşılaştırılır. Aynıysa `IDEMPOTENT_REUSE`,
    farklıysa `ProvenanceConflictError` (sert hata, ASLA en-son-kazanır).

    KİLİTLİ SENARYO (HATA 13B section 6/30): `INITIAL` olayının kimliği
    (`activation_event_id`) YALNIZCA `protocol_version`'a bağlıdır --
    `activation_lock_id` İÇERİĞE girer ama KİMLİĞE GİRMEZ. Bu yüzden aynı
    `protocol_version` için FARKLI bir `activation_lock_id` ile ikinci bir
    `INITIAL` yaratma girişimi, TAM OLARAK bu mekanizma ile -- AYNI
    doküman ID'si, FARKLI içerik-hash'i -- bir `ProvenanceConflictError`
    olarak YAKALANIR. Bu KASITLIDIR, özel bir ek kod dalı GEREKMEZ.

`TechnicalV1ActivationEvent`, KENDİ `__post_init__` metodunda
`activation_event_id`'yi ZATEN bağımsız olarak yeniden hesaplayıp doğrular
(bkz. `app/research/activation_event.py`) -- bu yüzden bu repository, diğer
repository'lerin "adayın kendi kimliği tutarlı mı" ön-kontrolünü
TEKRARLAMAZ: geçerli bir `TechnicalV1ActivationEvent` örneği zaten yapısal
olarak kendi-kendine-tutarlıdır, aksi halde HİÇ İNŞA EDİLEMEZDİ.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from google.api_core.exceptions import AlreadyExists

from app.core.firebase import get_firestore_client
from app.research.activation_event import TechnicalV1ActivationEvent
from app.research.canonical_hash import content_sha256
from app.research.evidence_models import ProvenanceConflictError, validate_sha256_hex

COLLECTION = "technical_v1_activation_events"


class ActivationEventOutcome(str, Enum):
    CREATED = "CREATED"
    IDEMPOTENT_REUSE = "IDEMPOTENT_REUSE"


@dataclass(frozen=True)
class PersistedTechnicalV1ActivationEvent:
    """Firestore sunucu metadata'sını (`create_time`), olay İÇERİĞİNE hiç
    kopyalamadan taşıyan salt-okunur zarf (HATA 13B section 16). `create_time`
    ASLA `TechnicalV1ActivationEvent.to_document_fields()`'e veya
    `record_content_sha256`'ya/`activation_event_id`'ye girmez -- bu SADECE
    bir okuma-zamanı gözlem değeridir, timezone-aware'dır ve çağıran
    tarafından değiştirilemez. `INITIAL` olayı için bu değer, ileride
    `effective_holdout_start` hesabının kullanacağı ham girdilerden biri
    olacaktır (bu hesap BU HATA'nın kapsamı DIŞINDADIR)."""

    event: TechnicalV1ActivationEvent
    create_time: datetime


def _verify_and_reconstruct(expected_activation_event_id: str, raw_fields: dict) -> TechnicalV1ActivationEvent:
    """HATA 13B section 15: `TechnicalV1ActivationLockRepository._verify_and_
    reconstruct()` İLE AYNI çok-adımlı doğrulama boru hattı, activation-event
    şemasına uygulanmış hali -- hem `create()`'in var-olan-doküman
    karşılaştırma yolu HEM DE `get_verified()` BUNU çağırır.

    Sıra (hiçbiri atlanmaz):
      1. saklanan `record_content_sha256` kanonik (64 küçük-harf hex) mi?
      2. TÜM diğer alanlardan (kendisi HARİÇ -- `activation_event_id` DAHİL)
         yeniden hesaplanan hash, saklanan değerle EŞLEŞİYOR mu? (nesne
         ADI/saklanan string TEK BAŞINA ASLA güvenilmez -- bu, dolaylı
         olarak da alan-SETİNİN tam olarak beklenen olduğunu doğrular:
         eksik/fazla bir alan içerik-hash'ini DEĞİŞTİRİR, bu adım onu
         yakalar.)
      3. semantik yeniden kuruluş (`TechnicalV1ActivationEvent.
         from_document_fields()`) başarılı mı? (şema/format açısından
         imkânsız bir doküman -- ör. tamperlenmiş `activation_event_id`,
         bilinmeyen `event_type`, bozuk şema versiyonu -- BURADA
         YAKALANIR; bu adım AYRICA `from_document_fields()`'in KENDİ,
         BAĞIMSIZ alan-seti/hash kontrolünü de çalıştırarak adım 1-2'yi
         tekrar, bağımsız bir yoldan doğrular.)
      4. TAM HAM ŞEMA ROUNDTRIP KONTROLÜ: yeniden kurulan modelin KENDİ
         `to_document_fields()` çıktısı, ham dokümanla (`raw_fields`,
         `record_content_sha256` dahil) TAM OLARAK (Python yapısal `==`)
         aynı mı?
      5. yeniden kurulan kaydın KENDİ `activation_event_id`'si, BEKLENEN
         (istenen/doküman referansı) ID İLE eşleşiyor mu? (doc-ref-ID /
         içerik-ID wrong-wiring kontrolü.)

    Herhangi bir adım başarısız olursa `ProvenanceConflictError` -- ham
    bir `ValueError`/`KeyError`/`TypeError` normal uygulama akışına SIZMAZ.
    """
    stored_hash = raw_fields.get("record_content_sha256")
    try:
        validate_sha256_hex(stored_hash)
    except Exception as exc:
        raise ProvenanceConflictError(
            f"technical_v1_activation_events/{expected_activation_event_id}: saklanan "
            f"record_content_sha256 kanonik (64 küçük-harf hex) formatında değil: {stored_hash!r}"
        ) from exc

    content_fields = {key: value for key, value in raw_fields.items() if key != "record_content_sha256"}

    try:
        recomputed_hash = content_sha256(content_fields)
    except (TypeError, ValueError) as exc:
        raise ProvenanceConflictError(
            f"technical_v1_activation_events/{expected_activation_event_id}: içerik alanları kanonik "
            f"olarak hash'lenemedi (JSON-güvenli olmayan bir değer içeriyor olabilir): {exc}"
        ) from exc
    if recomputed_hash != stored_hash:
        raise ProvenanceConflictError(
            f"technical_v1_activation_events/{expected_activation_event_id}: yeniden hesaplanan içerik "
            f"hash'i ({recomputed_hash}) saklanan değerle ({stored_hash}) eşleşmiyor -- doküman "
            f"içeriği kendi saklanan hash'iyle TUTARSIZ (tamper/bozulma şüphesi)."
        )

    try:
        event = TechnicalV1ActivationEvent.from_document_fields(raw_fields)
    except (KeyError, ValueError, TypeError) as exc:
        raise ProvenanceConflictError(
            f"technical_v1_activation_events/{expected_activation_event_id}: içerik hash'i geçerli ama "
            f"doküman semantik olarak TechnicalV1ActivationEvent şemasıyla tutarsız (ör. tamperlenmiş "
            f"activation_event_id, bilinmeyen event_type, bozuk şema versiyonu, geçersiz format): {exc}"
        ) from exc

    canonical_reconstructed = event.to_document_fields()
    if canonical_reconstructed != raw_fields:
        raise ProvenanceConflictError(
            f"technical_v1_activation_events/{expected_activation_event_id}: ham doküman içerik-hash "
            f"açısından içsel olarak tutarlı olsa da, yeniden kurulan modelin kanonik "
            f"`to_document_fields()` çıktısı ham dokümanla TAM OLARAK eşleşmiyor -- bilinmeyen/eksik/"
            f"normalize edilmiş bir alan şüphesi. Sessiz şema normalizasyonu ASLA kabul edilmez."
        )

    if event.activation_event_id != expected_activation_event_id:
        raise ProvenanceConflictError(
            f"technical_v1_activation_events/{expected_activation_event_id}: dokümanın KENDİ "
            f"içeriğindeki activation_event_id ({event.activation_event_id}) doküman ID'sinden "
            f"({expected_activation_event_id}) FARKLI -- yanlış/wrong-wiring bir kayıt."
        )

    return event


class TechnicalV1ActivationEventRepository:
    def __init__(self, db=None):
        # HATA 12N2B2/12N3B/12N3C2-B2-B ile AYNI desen: `db` enjekte
        # EDİLMEZSE gerçek Firestore client'ı yalnızca BU ANDA (modül
        # import anında DEĞİL) kurulur -- testler `db` için minimal,
        # sözleşme-uyumlu bir sahte vererek gerçek ağ/ADC/proje erişimi
        # OLMADAN bu sınıfı egzersiz eder.
        self._db = db if db is not None else get_firestore_client()

    def create(self, event: TechnicalV1ActivationEvent) -> ActivationEventOutcome:
        """HATA 13B section 14: `DocumentReference.create()` ile create-only
        yazma denenir, doküman ID'si HER ZAMAN `event.activation_event_id`'dir
        (auto-ID/UUID/alternatif anahtar YOK). `AlreadyExists` durumunda var
        olan doküman KÖRÜKÖRÜNE idempotent SAYILMAZ -- `_verify_and_
        reconstruct()` ile TAM doğrulanıp candidate'in KENDİ (her zaman
        doğru, çünkü türetilmiş bir property olan) hash'iyle karşılaştırılır."""
        # TECHNICAL V2-R1: kilit repository'sindeki guard ile AYNI sözleşme --
        # olayın sürümü protocol_version'ından çözülür ve çalışan motor o
        # sürümün engine_version'ıyla eşleşmeli (engine 1.15.0 altında YENİ V1
        # olayı reddedilir); bilinmeyen/karışık protocol_version da reddedilir.
        # Firestore'a hiçbir erişim olmadan fail-fast.
        from app.research.technical_versions import (
            assert_identity_matches_running_engine,
            identity_for_protocol_version,
        )

        assert_identity_matches_running_engine(identity_for_protocol_version(event.protocol_version))
        doc_ref = self._db.collection(COLLECTION).document(event.activation_event_id)
        candidate_fields = event.to_document_fields()
        candidate_hash = candidate_fields["record_content_sha256"]

        try:
            doc_ref.create(candidate_fields)
            return ActivationEventOutcome.CREATED
        except AlreadyExists:
            existing_snapshot = doc_ref.get()
            if not existing_snapshot.exists:
                raise ProvenanceConflictError(
                    f"technical_v1_activation_events/{event.activation_event_id}: create() AlreadyExists "
                    f"fırlattı ama hemen ardından yapılan okuma dokümanı bulamadı -- beklenmeyen "
                    f"depolama-katmanı tutarsızlığı."
                )
            existing_event = _verify_and_reconstruct(event.activation_event_id, existing_snapshot.to_dict())
            existing_hash = existing_event.record_content_sha256
            if existing_hash == candidate_hash:
                return ActivationEventOutcome.IDEMPOTENT_REUSE
            raise ProvenanceConflictError(
                f"technical_v1_activation_events/{event.activation_event_id}: VAR OLAN kayıt FARKLI "
                f"içerikle tekrar persist edilmeye çalışıldı (existing={existing_hash}, candidate="
                f"{candidate_hash}) -- en-son-kazanır UYGULANMAZ, sert hata. `INITIAL` için bu, AYNI "
                f"protocol_version altında FARKLI bir activation_lock_id'yi yetkilendirme girişiminin "
                f"YAKALANDIĞININ kanıtıdır (HATA 13B section 6)."
            )

    def get_verified(self, activation_event_id: str) -> PersistedTechnicalV1ActivationEvent | None:
        """HATA 13B section 15: istenen `activation_event_id` ÖNCE (herhangi
        bir Firestore erişiminden ÖNCE) kanonik (64 küçük-harf hex) formatı
        için doğrulanır -- format hatası burada, yerel olarak, I/O YAPILMADAN
        fırlatılır. Doküman yoksa `None`. Varsa, ham doküman ÖNCE tam olarak
        doğrulanır (bkz. `_verify_and_reconstruct`), yalnızca ONDAN SONRA
        güvenilen bir `TechnicalV1ActivationEvent` + Firestore `create_time`
        metadata'sı içeren bir zarf döner. Doğrulanmamış/güvenilmeyen bir
        olay ASLA doğrudan DÖNDÜRÜLMEZ."""
        validate_sha256_hex(activation_event_id)
        doc = self._db.collection(COLLECTION).document(activation_event_id).get()
        if not doc.exists:
            return None
        event = _verify_and_reconstruct(activation_event_id, doc.to_dict())
        return PersistedTechnicalV1ActivationEvent(event=event, create_time=doc.create_time)
