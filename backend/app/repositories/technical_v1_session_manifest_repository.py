"""HATA 12N3B — Technical V1 immutable session manifest repository'si.

Koleksiyon: `technical_v1_sessions/{session_id}` -- create-only, KALICI
bilimsel kanıt olarak. Bu repository:

  - Session muhasebesi/manifest İNŞA ETME mantığını ÇALIŞTIRMAZ
    (`build_session_manifest()`'i hiç import/çağırmaz) -- yalnızca ZATEN
    ÜRETİLMİŞ bir `TechnicalV1SessionManifest` nesnesini KALICI HALE
    GETİRİR.
  - `TechnicalV1EvaluationRepository`'yi hiç import/çağırmaz --
    `technical_v1_evaluations` koleksiyonuna HİÇ DOKUNMAZ/SORGULAMAZ.
    Bu, persistence katmanının ikinci bir session-builder'a
    DÖNÜŞMESİNİ önler (HATA 12N3B section 30).
  - `TechnicalV1SessionManifest.to_document_fields()`'i TEK, kanonik
    doküman temsili olarak kullanır -- final şemayı BURADA BAĞIMSIZ
    OLARAK YENİDEN İNŞA ETMEZ.

Kilitli create-only sözleşme (HATA 12N2B2/12N2B2-F'deki
`TechnicalV1EvaluationRepository` ile AYNI desen, `AlreadyExists`
precondition'ı):
  - `.create()` yalnız BİR KEZ, ilk yaratımda kullanılır.
  - `set()`/`update()`/`add()`/`delete()` normal akışta HİÇ KULLANILMAZ.
  - Var olan bir doküman bulunursa: KÖRÜKÖRÜNE idempotent başarı
    İLAN EDİLMEZ -- ÖNCE var olan dokümanın HAM içerik-hash'i yeniden
    hesaplanıp doğrulanır (nesne ADI/saklanan hash string'i TEK BAŞINA
    ASLA güvenilmez), SONRA adayla karşılaştırılır. Aynıysa
    `IDEMPOTENT_REUSE`, farklıysa `ProvenanceConflictError` (sert hata,
    ASLA en-son-kazanır).
  - `get_verified()` YALNIZCA manifest dokümanının KENDİSİNİ doğrular --
    bağlı 100 `FinalEvaluation` kaydını YENİDEN OKUMAZ/DOĞRULAMAZ (HATA
    12N3B section 40); bu daha üst-seviye bir doğrulama/orkestrasyon
    katmanının (N3C ve sonrası) sorumluluğudur.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from google.api_core.exceptions import AlreadyExists

from app.core.firebase import get_firestore_client
from app.research.canonical_hash import content_sha256
from app.research.evidence_identity import compute_session_id
from app.research.evidence_models import ProvenanceConflictError, validate_sha256_hex
from app.research.session_manifest import TechnicalV1SessionManifest

COLLECTION = "technical_v1_sessions"


class SessionManifestOutcome(str, Enum):
    CREATED = "CREATED"
    IDEMPOTENT_REUSE = "IDEMPOTENT_REUSE"


@dataclass(frozen=True)
class PersistedTechnicalV1SessionManifest:
    """HATA 12N3B section 26: Firestore sunucu metadata'sını (`create_
    time`), manifest İÇERİĞİNE hiç kopyalamadan taşıyan salt-okunur zarf.
    `create_time` ASLA `TechnicalV1SessionManifest.to_document_fields()`'e
    veya `record_content_sha256`'ya girmez -- bu SADECE bir okuma-zamanı
    gözlem değeridir."""

    manifest: TechnicalV1SessionManifest
    create_time: datetime


def _verify_and_reconstruct(expected_session_id: str, raw_fields: dict) -> TechnicalV1SessionManifest:
    """HATA 12N3B section 9/10/13: `technical_v1_evaluation_repository.
    _verify_and_reconstruct()` İLE AYNI beş-adımlı boru hattı, manifest
    şemasına uygulanmış hali -- hem `create()`'in var-olan-doküman
    karşılaştırma yolu HEM DE `get_verified()` BUNU çağırır, aynı mantık
    İKİ AYRI yerde YAZILMAZ.

    Sıra (hiçbiri atlanmaz):
      1. saklanan `record_content_sha256` kanonik (64 küçük-harf hex) mi?
      2. TÜM diğer alanlardan (kendisi HARİÇ) yeniden hesaplanan hash,
         saklanan değerle EŞLEŞİYOR mu?
      3. semantik yeniden kuruluş (`TechnicalV1SessionManifest.
         from_document_fields()`) başarılı mı? (hash-tutarlı ama şema
         açısından imkânsız -- ör. `expected_symbol_count=99`, eksik bir
         sayım anahtarı, ya da `technical_observation_eligible_count`
         tutarsızlığı -- burada YAKALANIR, çünkü bunların hepsi
         dataclass'ın KENDİ `__post_init__` doğrulamalarıdır.)
      4. TAM HAM ŞEMA ROUNDTRIP KONTROLÜ: yeniden kurulan modelin KENDİ
         `to_document_fields()` çıktısı, ham dokümanla (`raw_fields`,
         `record_content_sha256` dahil) TAM OLARAK (Python yapısal `==`)
         aynı mı? Bu adım şunları yakalar: beklenmeyen bir üst-düzey
         FAZLA alan, `capture_status_counts`/`evaluation_integrity_
         status_counts` içinde beklenmeyen bir FAZLA anahtar, sıfır-
         sayılı bir enum anahtarının TAMAMEN EKSİK olması (açık `0` ile
         "anahtar hiç yok" AYNI KANONİK ŞEMA DEĞİLDİR).
      5. yeniden kurulan kaydın KENDİ kimlik alanları (session_id/
         protocol_version/T_session_date), hem bağımsız olarak yeniden
         hesaplanan `compute_session_id(...)` İLE hem de BEKLENEN
         (istenen) doküman ID'si İLE eşleşiyor mu?

    Herhangi bir adım başarısız olursa `ProvenanceConflictError` -- ham
    bir `ValueError`/`KeyError` normal uygulama akışına SIZMAZ.
    """
    stored_hash = raw_fields.get("record_content_sha256")
    try:
        validate_sha256_hex(stored_hash)
    except Exception as exc:
        raise ProvenanceConflictError(
            f"technical_v1_sessions/{expected_session_id}: saklanan record_content_sha256 kanonik "
            f"(64 küçük-harf hex) formatında değil: {stored_hash!r}"
        ) from exc

    content_fields = {key: value for key, value in raw_fields.items() if key != "record_content_sha256"}

    try:
        recomputed_hash = content_sha256(content_fields)
    except (TypeError, ValueError) as exc:
        raise ProvenanceConflictError(
            f"technical_v1_sessions/{expected_session_id}: içerik alanları kanonik olarak "
            f"hash'lenemedi (JSON-güvenli olmayan bir değer içeriyor olabilir): {exc}"
        ) from exc
    if recomputed_hash != stored_hash:
        raise ProvenanceConflictError(
            f"technical_v1_sessions/{expected_session_id}: yeniden hesaplanan içerik hash'i "
            f"({recomputed_hash}) saklanan değerle ({stored_hash}) eşleşmiyor -- doküman içeriği "
            f"kendi saklanan hash'iyle TUTARSIZ (tamper/bozulma şüphesi)."
        )

    try:
        manifest = TechnicalV1SessionManifest.from_document_fields(content_fields)
    except (KeyError, ValueError, TypeError) as exc:
        raise ProvenanceConflictError(
            f"technical_v1_sessions/{expected_session_id}: içerik hash'i geçerli ama doküman "
            f"semantik olarak TechnicalV1SessionManifest şemasıyla tutarsız: {exc}"
        ) from exc

    canonical_reconstructed = manifest.to_document_fields()
    if canonical_reconstructed != raw_fields:
        raise ProvenanceConflictError(
            f"technical_v1_sessions/{expected_session_id}: ham doküman içerik-hash açısından içsel "
            f"olarak tutarlı olsa da, yeniden kurulan modelin kanonik `to_document_fields()` çıktısı "
            f"ham dokümanla TAM OLARAK eşleşmiyor -- bilinmeyen/eksik/normalize edilmiş bir alan "
            f"şüphesi (üst-düzey veya sayım-eşlemesi anahtarları dahil). Sessiz şema normalizasyonu "
            f"ASLA kabul edilmez."
        )

    recomputed_session_id = compute_session_id(manifest.protocol_version, manifest.T_session_date)
    if manifest.session_id != recomputed_session_id:
        raise ProvenanceConflictError(
            f"technical_v1_sessions/{expected_session_id}: saklanan session_id ({manifest.session_id}) "
            f"kendi protocol_version/T_session_date alanlarından bağımsız olarak yeniden hesaplanan "
            f"({recomputed_session_id}) ile eşleşmiyor."
        )
    if manifest.session_id != expected_session_id:
        raise ProvenanceConflictError(
            f"technical_v1_sessions/{expected_session_id}: dokümanın KENDİ içeriğindeki session_id "
            f"({manifest.session_id}) doküman ID'sinden ({expected_session_id}) FARKLI -- yanlış/"
            f"wrong-wiring bir kayıt."
        )

    return manifest


class TechnicalV1SessionManifestRepository:
    def __init__(self, db=None):
        # HATA 12N2B2 ile AYNI desen: `db` enjekte EDİLMEZSE gerçek
        # Firestore client'ı yalnızca BU ANDA (modül import anında DEĞİL)
        # kurulur -- testler `db` için minimal, sözleşme-uyumlu bir sahte
        # vererek gerçek ağ/ADC/proje erişimi OLMADAN bu sınıfı egzersiz eder.
        self._db = db if db is not None else get_firestore_client()

    def create(self, manifest: TechnicalV1SessionManifest) -> SessionManifestOutcome:
        """HATA 12N3B section 3/4/5/6: adayın KENDİ kimliği önce bağımsız
        olarak doğrulanır, sonra `DocumentReference.create()` ile
        create-only yazma denenir. `AlreadyExists` durumunda var olan
        doküman KÖRÜKÖRÜNE idempotent SAYILMAZ -- `_verify_and_
        reconstruct()` ile TAM doğrulanıp candidate'in KENDİ (her zaman
        doğru, çünkü türetilmiş bir property olan) hash'iyle karşılaştırılır.
        """
        expected_session_id = compute_session_id(manifest.protocol_version, manifest.T_session_date)
        if manifest.session_id != expected_session_id:
            raise ProvenanceConflictError(
                f"Sağlanan TechnicalV1SessionManifest.session_id ({manifest.session_id}) kendi "
                f"protocol_version/T_session_date alanlarından bağımsız olarak yeniden hesaplanan "
                f"({expected_session_id}) ile eşleşmiyor -- persist edilmedi."
            )

        doc_ref = self._db.collection(COLLECTION).document(manifest.session_id)
        candidate_fields = manifest.to_document_fields()
        # `record_content_sha256` her zaman türetilmiş bir property'dir --
        # adayın KENDİ hash'i ayrıca "doğrulanmaya" gerek duymaz, tanım
        # gereği doğrudur.
        candidate_hash = candidate_fields["record_content_sha256"]

        try:
            doc_ref.create(candidate_fields)
            return SessionManifestOutcome.CREATED
        except AlreadyExists:
            existing_snapshot = doc_ref.get()
            if not existing_snapshot.exists:
                raise ProvenanceConflictError(
                    f"technical_v1_sessions/{manifest.session_id}: create() AlreadyExists fırlattı "
                    f"ama hemen ardından yapılan okuma dokümanı bulamadı -- beklenmeyen depolama-"
                    f"katmanı tutarsızlığı."
                )
            existing_manifest = _verify_and_reconstruct(manifest.session_id, existing_snapshot.to_dict())
            existing_hash = existing_manifest.record_content_sha256
            if existing_hash == candidate_hash:
                return SessionManifestOutcome.IDEMPOTENT_REUSE
            raise ProvenanceConflictError(
                f"technical_v1_sessions/{manifest.session_id}: VAR OLAN kayıt FARKLI içerikle "
                f"tekrar persist edilmeye çalışıldı (existing={existing_hash}, candidate="
                f"{candidate_hash}) -- en-son-kazanır UYGULANMAZ, sert hata."
            )

    def get_verified(self, session_id: str) -> PersistedTechnicalV1SessionManifest | None:
        """HATA 12N3B section 27/40: ham doküman ÖNCE tam olarak
        doğrulanır (bkz. `_verify_and_reconstruct`), yalnızca ONDAN SONRA
        güvenilen bir `TechnicalV1SessionManifest` + Firestore `create_
        time` metadata'sı içeren bir zarf döner. Doğrulanmamış/güvenilmeyen
        bir manifest ASLA doğrudan DÖNDÜRÜLMEZ. Bağlı 100 `FinalEvaluation`
        kaydını YENİDEN OKUMAZ/DOĞRULAMAZ -- yalnızca manifest dokümanının
        KENDİSİNİ doğrular (bu, daha üst bir katmanın sorumluluğudur)."""
        doc = self._db.collection(COLLECTION).document(session_id).get()
        if not doc.exists:
            return None
        manifest = _verify_and_reconstruct(session_id, doc.to_dict())
        return PersistedTechnicalV1SessionManifest(manifest=manifest, create_time=doc.create_time)
