"""HATA 12N3C1 — Technical V1 mutable oturum-çalıştırma (session-run)
Firestore repository'si.

Koleksiyon: `technical_v1_session_runs/{session_id}` -- KASITLI OLARAK
MUTABLE, OPERASYONEL bir belgedir. Bu, N2B2/N3B'nin izlediği create-only/
içerik-hash'li bilimsel kanıt sözleşmesinin TAM TERSİDİR:

  - `record_content_sha256` YOK.
  - create-only sözleşme YOK.
  - ham hash/şema roundtrip doğrulaması YOK.
  - HER `upsert()` çağrısı TAM DEĞİŞTİRME (full replacement) yazar --
    `set()` KULLANILIR, `update()`/`arrayUnion`/`arrayRemove` ASLA
    kullanılmaz -- böylece önceki bir geçişten kalan HİÇBİR bayat alan
    hayatta KALAMAZ.

BU KOLEKSİYON BİLİMSEL KANIT DEĞİLDİR (bkz. `app/research/session_run.py`
modül docstring'i, aynı ilke burada tekrarlanır): eğer bu doküman şu
değişmez depolarla ÇELİŞİRSE -- `technical_v1_attempt_claims`/
`technical_v1_attempt_results`, `technical_v1_evaluations`,
`technical_v1_sessions` -- DAİMA o değişmez depolar KAZANIR; bu doküman
herhangi bir zaman yeniden üretilebilir/onarılabilir. HİÇBİR bilimsel
doğruluk-hassas karar bu dokümandan OKUNARAK VERİLEMEZ -- yalnızca UI/
operatör görünürlüğü/tanılama içindir.

Bu repository yalnızca SESSION CONTROLLER/SERVICE (N3C3/N3C4, henüz
yazılmadı) tarafından çağrılmalıdır -- tek-tek sembol worker'ları bu
koleksiyona ASLA DOĞRUDAN YAZMAZ (bir servis-katmanı sözleşmesi, henüz
bir IAM garantisi DEĞİLDİR).

`TechnicalV1EvaluationRepository`/`TechnicalV1SessionManifestRepository`/
`TechnicalV1AttemptRepository`/`EvidenceObjectStore`'un HİÇBİRİ burada
import/çağrı EDİLMEZ -- bu repository YALNIZCA `technical_v1_session_
runs`'a sahiptir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from firebase_admin import firestore

from app.core.firebase import get_firestore_client
from app.research.session_run import TechnicalV1SessionRunSnapshot

COLLECTION = "technical_v1_session_runs"

_STORED_DOCUMENT_FIELD_KEYS: frozenset[str] = frozenset(
    {
        "session_id",
        "protocol_version",
        "T_session_date",
        "status",
        "retry_pending_evaluation_ids",
        "provenance_blocked_evaluation_ids",
        "updated_at",
    }
)


@dataclass(frozen=True)
class PersistedTechnicalV1SessionRun:
    """HATA 12N3C-A3 section 2/15/20: mantıksal anlık-görüntüyü,
    repository-sahipli `updated_at` operasyonel metadata'sından AYRI
    tutan salt-okunur zarf. `updated_at`, dokümanın KENDİ saklanan
    `updated_at` İÇERİK alanından (Firestore'un `SERVER_TIMESTAMP`
    sentinel'ini bir commit sonrası çözdüğü değer) gelir --
    `DocumentSnapshot.update_time` metadata'sı İLE KARIŞTIRILMAZ/
    KULLANILMAZ (somut bir tüketici olmadıkça, bkz. modül docstring'i;
    şu an İÇİN böyle bir tüketici YOKTUR, bu yüzden hiç MARUZ BIRAKILMAZ).
    `updated_at` bilimsel kanıt/sinyal/deneme zaman damgası/oturum
    kimliği DEĞİLDİR -- yalnızca operasyonel gözlem metadata'sıdır."""

    snapshot: TechnicalV1SessionRunSnapshot
    updated_at: datetime


class TechnicalV1SessionRunRepository:
    def __init__(self, db=None):
        # HATA 12N2A/12N2B2/12N3B ile AYNI desen: `db` enjekte EDİLMEZSE
        # gerçek Firestore client'ı yalnızca BU ANDA (modül import anında
        # DEĞİL) kurulur -- testler `db` için minimal, sözleşme-uyumlu bir
        # sahte vererek gerçek ağ/ADC/proje erişimi OLMADAN bu sınıfı
        # egzersiz eder.
        self._db = db if db is not None else get_firestore_client()

    def upsert(self, snapshot: TechnicalV1SessionRunSnapshot) -> None:
        """HATA 12N3C-A2/A3'te kilitlenen TAM DEĞİŞTİRME (full-
        replacement) yazma sözleşmesi -- `create()`/`AlreadyExists`
        YOKTUR (bu doküman create-only DEĞİLDİR), `update()`/
        `arrayUnion` da YOKTUR. `updated_at`, `firestore.SERVER_
        TIMESTAMP` sentinel'i olarak BURADA (yalnızca repository
        kodunda) enjekte edilir -- saf domain modeli bu sentinel'i HİÇ
        GÖRMEZ."""
        payload = {**snapshot.to_document_fields(), "updated_at": firestore.SERVER_TIMESTAMP}
        self._db.collection(COLLECTION).document(snapshot.session_id).set(payload, merge=False)

    def get(self, session_id: str) -> PersistedTechnicalV1SessionRun | None:
        """HATA 12N3C-A3 section 21/22/23: doküman yoksa `None`. Varsa:
        (1) TAM OLARAK beklenen saklanan alan kümesi zorunlu (bilinmeyen/
        eksik alan reddedilir), (2) `updated_at` çıkarılıp AYRI tutulur,
        (3) kalan altı mantıksal alandan `TechnicalV1SessionRunSnapshot.
        from_document_fields()` ile yeniden kuruluş yapılır (bu, saklanan
        `status`'un iki listeden bağımsız olarak türetilenle TAM
        eşleştiğini de doğrular -- tutarsız bir operasyonel durum
        SESSİZCE onarılmaz), (4) yeniden kurulan `session_id`'nin istenen
        doküman ID'siyle eşleştiği doğrulanır."""
        doc = self._db.collection(COLLECTION).document(session_id).get()
        if not doc.exists:
            return None

        raw_fields = doc.to_dict()
        actual_keys = set(raw_fields.keys())
        if actual_keys != _STORED_DOCUMENT_FIELD_KEYS:
            missing = _STORED_DOCUMENT_FIELD_KEYS - actual_keys
            unexpected = actual_keys - _STORED_DOCUMENT_FIELD_KEYS
            raise ValueError(
                f"technical_v1_session_runs/{session_id}: beklenmeyen/eksik saklanan alan kümesi -- "
                f"eksik={sorted(missing)!r} beklenmeyen={sorted(unexpected)!r}"
            )

        updated_at = raw_fields["updated_at"]
        if not isinstance(updated_at, datetime) or updated_at.tzinfo is None or updated_at.utcoffset() is None:
            raise ValueError(
                f"technical_v1_session_runs/{session_id}: saklanan updated_at tz-aware bir datetime "
                f"değil (naive/string/int/sentinel kabul edilmez): {updated_at!r}"
            )

        logical_fields = {key: value for key, value in raw_fields.items() if key != "updated_at"}
        snapshot = TechnicalV1SessionRunSnapshot.from_document_fields(logical_fields)
        if snapshot.session_id != session_id:
            raise ValueError(
                f"technical_v1_session_runs/{session_id}: dokümanın KENDİ içeriğindeki session_id "
                f"({snapshot.session_id}) doküman ID'sinden ({session_id}) FARKLI -- yanlış/"
                f"wrong-wiring bir kayıt."
            )

        return PersistedTechnicalV1SessionRun(snapshot=snapshot, updated_at=updated_at)
