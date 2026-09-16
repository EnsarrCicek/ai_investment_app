"""HATA 12N3C2-B2-B — Technical V1 immutable activation-lock repository'si.

Koleksiyon: `technical_v1_activation_locks/{activation_lock_id}` -- create-only,
KALICI yetkilendirme kaydı olarak. Bu repository:

  - Aktivasyon OLAYI (activation event) mantığı/koleksiyonu HİÇ İÇERMEZ --
    `technical_v1_activation_events`'e hiç dokunmaz/sorgulamaz (B3-R3
    tasarımı vardır ama implementasyonu bu HATA'nın kapsamı DIŞINDADIR).
  - `AttemptClaim`/`AttemptResult`'a hiç dokunmaz -- `activation_lock_id`
    bağlama (B2-C) bu HATA'nın kapsamı DIŞINDADIR.
  - `TechnicalV1ActivationLock.to_document_fields()`'i TEK, kanonik doküman
    temsili olarak kullanır -- final şemayı BURADA BAĞIMSIZ OLARAK YENİDEN
    İNŞA ETMEZ; `compute_activation_lock_id`/hash/format doğrulama mantığını
    KOPYALAMAZ, `app.research.activation_lock`'tan import eder.

Kilitli create-only sözleşme (HATA 12N2B2/12N3B'deki `TechnicalV1Evaluation
Repository`/`TechnicalV1SessionManifestRepository` İLE AYNI desen,
`AlreadyExists` precondition'ı):
  - `.create()` yalnız BİR KEZ, ilk yaratımda kullanılır.
  - `set()`/`update()`/`add()`/`delete()` normal akışta HİÇ KULLANILMAZ.
  - Var olan bir doküman bulunursa: KÖRÜKÖRÜNE idempotent başarı İLAN
    EDİLMEZ -- ÖNCE var olan dokümanın HAM içerik-hash'i yeniden hesaplanıp
    doğrulanır, SONRA adayla karşılaştırılır. Aynıysa `IDEMPOTENT_REUSE`,
    farklıysa `ProvenanceConflictError` (sert hata, ASLA en-son-kazanır).

`TechnicalV1ActivationLock`, `FinalEvaluation`'ın aksine, KENDİ `__post_init__`
metodunda `activation_lock_id`'yi ZATEN bağımsız olarak yeniden hesaplayıp
doğrular (bkz. HATA 12N3C2-B2-A) -- bu yüzden bu repository, diğer iki
repository'nin "adayın kendi kimliği tutarlı mı" ön-kontrolünü TEKRARLAMAZ:
geçerli bir `TechnicalV1ActivationLock` örneği zaten yapısal olarak
kendi-kendine-tutarlıdır (self-consistent), aksi halde HİÇ İNŞA EDİLEMEZDİ.

`TechnicalV1ActivationLock.from_document_fields()` (B2-A'da kilitlendi),
`FinalEvaluation`/`TechnicalV1SessionManifest`'in aksine, saklanan
`record_content_sha256`'yı KENDİ İÇİNDE ZATEN bağımsız olarak yeniden
hesaplayıp doğrular. Ticket'ın section 14 talimatı gereği bu repository
YİNE DE kendi ham-hash kontrolünü (`_verify_and_reconstruct` adım 1-2)
BAĞIMSIZ OLARAK, `from_document_fields()`'i çağırmadan ÖNCE yapar --
"yalnızca modelin kendi kontrolüne güven" ASLA yapılmaz (defense-in-depth,
section 14/16'da açıkça istenen bir kasıtlı çakışma/tekrar)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from google.api_core.exceptions import AlreadyExists

from app.core.firebase import get_firestore_client
from app.research.activation_lock import TechnicalV1ActivationLock
from app.research.canonical_hash import content_sha256
from app.research.evidence_models import ProvenanceConflictError, validate_sha256_hex

COLLECTION = "technical_v1_activation_locks"


class ActivationLockOutcome(str, Enum):
    CREATED = "CREATED"
    IDEMPOTENT_REUSE = "IDEMPOTENT_REUSE"


@dataclass(frozen=True)
class PersistedTechnicalV1ActivationLock:
    """Firestore sunucu metadata'sını (`create_time`), kilit İÇERİĞİNE hiç
    kopyalamadan taşıyan salt-okunur zarf. `create_time` ASLA
    `TechnicalV1ActivationLock.to_document_fields()`'e veya
    `record_content_sha256`'ya/`activation_lock_id`'ye girmez -- bu SADECE
    bir okuma-zamanı gözlem değeridir. `update_time` KASITLI OLARAK
    dışarı verilmez -- bu kayıt create-only'dir, tek anlamlı sunucu
    metadata'sı `create_time`'dır."""

    lock: TechnicalV1ActivationLock
    create_time: datetime


def _verify_and_reconstruct(expected_activation_lock_id: str, raw_fields: dict) -> TechnicalV1ActivationLock:
    """HATA 12N3C2-B2-B section 14-18: N2B2/N3B'deki İLE AYNI çok-adımlı
    doğrulama boru hattı, activation-lock şemasına uygulanmış hali -- hem
    `create()`'in var-olan-doküman karşılaştırma yolu HEM DE `get_verified()`
    BUNU çağırır, aynı mantık İKİ AYRI yerde YAZILMAZ.

    Sıra (hiçbiri atlanmaz):
      1. saklanan `record_content_sha256` kanonik (64 küçük-harf hex) mi?
      2. TÜM diğer alanlardan (kendisi HARİÇ -- `activation_lock_id` DAHİL,
         HATA 12N3C2-B2-A'da kilitlenen düzeltme) yeniden hesaplanan hash,
         saklanan değerle EŞLEŞİYOR mu? (nesne ADI/saklanan string TEK
         BAŞINA ASLA güvenilmez -- bu kontrol `from_document_fields()`'in
         KENDİ iç kontrolünden BAĞIMSIZ olarak, repository katmanında
         AYRICA yapılır, section 14.)
      3. semantik yeniden kuruluş (`TechnicalV1ActivationLock.
         from_document_fields()`) başarılı mı? (şema/format açısından
         imkânsız bir doküman -- ör. tamperlenmiş `activation_lock_id` +
         doğru yeniden hesaplanmış `record_content_sha256` -- BURADA
         YAKALANIR, çünkü bu modelin KENDİ `__post_init__`'i kimlik-taşıyan
         alanlardan `activation_lock_id`'yi bağımsız olarak yeniden türetip
         doğrular.)
      4. TAM HAM ŞEMA ROUNDTRIP KONTROLÜ: yeniden kurulan modelin KENDİ
         `to_document_fields()` çıktısı, ham dokümanla (`raw_fields`,
         `record_content_sha256` dahil) TAM OLARAK (Python yapısal `==`)
         aynı mı?
      5. yeniden kurulan kaydın KENDİ `activation_lock_id`'si, BEKLENEN
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
            f"technical_v1_activation_locks/{expected_activation_lock_id}: saklanan "
            f"record_content_sha256 kanonik (64 küçük-harf hex) formatında değil: {stored_hash!r}"
        ) from exc

    content_fields = {key: value for key, value in raw_fields.items() if key != "record_content_sha256"}

    try:
        recomputed_hash = content_sha256(content_fields)
    except (TypeError, ValueError) as exc:
        raise ProvenanceConflictError(
            f"technical_v1_activation_locks/{expected_activation_lock_id}: içerik alanları kanonik "
            f"olarak hash'lenemedi (JSON-güvenli olmayan bir değer içeriyor olabilir): {exc}"
        ) from exc
    if recomputed_hash != stored_hash:
        raise ProvenanceConflictError(
            f"technical_v1_activation_locks/{expected_activation_lock_id}: yeniden hesaplanan içerik "
            f"hash'i ({recomputed_hash}) saklanan değerle ({stored_hash}) eşleşmiyor -- doküman "
            f"içeriği kendi saklanan hash'iyle TUTARSIZ (tamper/bozulma şüphesi)."
        )

    try:
        lock = TechnicalV1ActivationLock.from_document_fields(raw_fields)
    except (KeyError, ValueError, TypeError) as exc:
        raise ProvenanceConflictError(
            f"technical_v1_activation_locks/{expected_activation_lock_id}: içerik hash'i geçerli ama "
            f"doküman semantik olarak TechnicalV1ActivationLock şemasıyla tutarsız (ör. tamperlenmiş "
            f"activation_lock_id, bozuk şema versiyonu, geçersiz format): {exc}"
        ) from exc

    canonical_reconstructed = lock.to_document_fields()
    if canonical_reconstructed != raw_fields:
        raise ProvenanceConflictError(
            f"technical_v1_activation_locks/{expected_activation_lock_id}: ham doküman içerik-hash "
            f"açısından içsel olarak tutarlı olsa da, yeniden kurulan modelin kanonik "
            f"`to_document_fields()` çıktısı ham dokümanla TAM OLARAK eşleşmiyor -- bilinmeyen/eksik/"
            f"normalize edilmiş bir alan şüphesi. Sessiz şema normalizasyonu ASLA kabul edilmez."
        )

    if lock.activation_lock_id != expected_activation_lock_id:
        raise ProvenanceConflictError(
            f"technical_v1_activation_locks/{expected_activation_lock_id}: dokümanın KENDİ "
            f"içeriğindeki activation_lock_id ({lock.activation_lock_id}) doküman ID'sinden "
            f"({expected_activation_lock_id}) FARKLI -- yanlış/wrong-wiring bir kayıt."
        )

    return lock


class TechnicalV1ActivationLockRepository:
    def __init__(self, db=None):
        # HATA 12N2B2/12N3B ile AYNI desen: `db` enjekte EDİLMEZSE gerçek
        # Firestore client'ı yalnızca BU ANDA (modül import anında DEĞİL)
        # kurulur -- testler `db` için minimal, sözleşme-uyumlu bir sahte
        # vererek gerçek ağ/ADC/proje erişimi OLMADAN bu sınıfı egzersiz eder.
        self._db = db if db is not None else get_firestore_client()

    def create(self, lock: TechnicalV1ActivationLock) -> ActivationLockOutcome:
        """HATA 12N3C2-B2-B section 6/7/9/10: `DocumentReference.create()`
        ile create-only yazma denenir, doküman ID'si HER ZAMAN
        `lock.activation_lock_id`'dir (auto-ID/UUID/alternatif anahtar YOK).
        `AlreadyExists` durumunda var olan doküman KÖRÜKÖRÜNE idempotent
        SAYILMAZ -- `_verify_and_reconstruct()` ile TAM doğrulanıp
        candidate'in KENDİ (her zaman doğru, çünkü türetilmiş bir property
        olan) hash'iyle karşılaştırılır. `TechnicalV1ActivationLock`
        yapısal olarak zaten kendi-kendine-tutarlı olduğundan (kendi
        `__post_init__`'i garanti eder), burada AYRICA bir "adayın kendi
        kimliği tutarlı mı" ön-kontrolü YOKTUR -- section 8."""
        doc_ref = self._db.collection(COLLECTION).document(lock.activation_lock_id)
        candidate_fields = lock.to_document_fields()
        # `record_content_sha256` her zaman türetilmiş bir property'dir --
        # adayın KENDİ hash'i ayrıca "doğrulanmaya" gerek duymaz, tanım
        # gereği doğrudur.
        candidate_hash = candidate_fields["record_content_sha256"]

        try:
            doc_ref.create(candidate_fields)
            return ActivationLockOutcome.CREATED
        except AlreadyExists:
            existing_snapshot = doc_ref.get()
            if not existing_snapshot.exists:
                raise ProvenanceConflictError(
                    f"technical_v1_activation_locks/{lock.activation_lock_id}: create() AlreadyExists "
                    f"fırlattı ama hemen ardından yapılan okuma dokümanı bulamadı -- beklenmeyen "
                    f"depolama-katmanı tutarsızlığı."
                )
            existing_lock = _verify_and_reconstruct(lock.activation_lock_id, existing_snapshot.to_dict())
            existing_hash = existing_lock.record_content_sha256
            if existing_hash == candidate_hash:
                return ActivationLockOutcome.IDEMPOTENT_REUSE
            raise ProvenanceConflictError(
                f"technical_v1_activation_locks/{lock.activation_lock_id}: VAR OLAN kayıt FARKLI "
                f"içerikle tekrar persist edilmeye çalışıldı (existing={existing_hash}, candidate="
                f"{candidate_hash}) -- en-son-kazanır UYGULANMAZ, sert hata. Bu, protocol_sha256/"
                f"freeze_manifest_sha256/methodology_git_commit/methodology_approval_reference gibi "
                f"İÇERİK-YALNIZCA alanların (activation_lock_id'yi ETKİLEMEYEN) B3'te kilitlenen "
                f"ayrımının depolama katmanında da ZORLANDIĞININ kanıtıdır."
            )

    def get_verified(self, activation_lock_id: str) -> PersistedTechnicalV1ActivationLock | None:
        """HATA 12N3C2-B2-B section 11/12: istenen `activation_lock_id`
        ÖNCE (herhangi bir Firestore erişiminden ÖNCE) kanonik (64
        küçük-harf hex) formatı için doğrulanır -- format hatası burada,
        yerel olarak, I/O YAPILMADAN `EvidenceIntegrityError` olarak
        fırlatılır (çağıranın kendi hatası, saklanan içerikle bir çatışma
        DEĞİL -- taksonomi ayrımı korunur). Doküman yoksa `None`. Varsa,
        ham doküman ÖNCE tam olarak doğrulanır (bkz. `_verify_and_
        reconstruct`), yalnızca ONDAN SONRA güvenilen bir
        `TechnicalV1ActivationLock` + Firestore `create_time` metadata'sı
        içeren bir zarf döner. Doğrulanmamış/güvenilmeyen bir kilit ASLA
        doğrudan DÖNDÜRÜLMEZ."""
        validate_sha256_hex(activation_lock_id)
        doc = self._db.collection(COLLECTION).document(activation_lock_id).get()
        if not doc.exists:
            return None
        lock = _verify_and_reconstruct(activation_lock_id, doc.to_dict())
        return PersistedTechnicalV1ActivationLock(lock=lock, create_time=doc.create_time)
