"""Technical V1 aktivasyon kilidi (activation lock) -- saf domain modeli.

HATA 12N3C2-B2-A. Bu modül, prospektif evidence-capture'ı belirli bir
(protokol × onaylı metodoloji parmak-izi × belirli Cloud Run deployment
kimliği) üçlüsüne bağlayacak olan "aktivasyon kilidi" kaydının SAF veri
şemasını ve kimlik (activation_lock_id) hesaplama mantığını tanımlar.

Bu modül KESİNLİKLE şunları YAPMAZ (HATA 12N3C2-B2-A section 3-4):
  - Firestore/GCS/ağ erişimi (firebase_admin, google.cloud.firestore yok).
  - Ortam değişkeni okuma (os.environ yok).
  - Dosya sistemi / git / subprocess erişimi.
  - Zaman damgası üretimi (datetime.now() yok) -- create_time HER ZAMAN
    repository katmanının (henüz yazılmamış, ayrı bir HATA'nın konusu)
    sorumluluğundadır, bu saf modelde YOKTUR.
  - Bir aktivasyon OLAYI (activation event) ya da scheduler/dispatch mantığı
    üretmez -- bu SADECE "kilit" kaydının kimlik/şema katmanıdır.

Aktivasyon KİLİDİ, aktivasyon OLAYI değildir: kilit, "şu deployment şu
metodoloji ile evidence-capture yapmaya YETKİLİDİR" beyanıdır; capture'ın
GERÇEKTEN mümkün olduğu an (`effective_holdout_start`), ayrı ve daha sonraki
bir HATA'da tanımlanacak aktivasyon OLAYININ create_time'ıdır (bkz. HATA
12N3C2-B3-R2/B3-R3 -- Model A, bu modülün kapsamı dışında).

Kimlik-taşıyan alanlar (activation_lock_id'ye girer, HATA 12N3C2-B3-R2'de
kilitlendi) TAM OLARAK: activation_lock_schema_version, protocol_version,
authorized_methodology_source_fingerprint, authorized_project_id,
authorized_runtime_service, authorized_runtime_revision -- kendini-tanımlayan
bir sarmalayıcı ({"activation_lock_identity": {...}}) altında hash'lenir
(compute_evaluation_id/compute_session_id'nin düz-dict biçiminden KASITLI bir
sapma, çünkü bu YENİ bir kimlik alanı ve şema-versiyonları arası çakışma
riski gerçek -- bkz. B3-R2).

İçerik-yalnızca alanlar (activation_lock_id'ye GİRMEZ ama record_content_
sha256'ya girer): protocol_sha256, freeze_manifest_sha256,
methodology_git_commit, methodology_approval_reference -- bu ayrım,
FinalEvaluation.evaluation_id'nin AYNI üç alanı (protocol_sha256,
methodology_git_commit, freeze_manifest_sha256) kendi kimlik hash'inden
hariç tutmasıyla BİREBİR aynı, doğrudan emsal alınan desendir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.research.canonical_hash import content_sha256
from app.research.evidence_models import validate_sha256_hex

TECHNICAL_V1_ACTIVATION_LOCK_SCHEMA_VERSION = "technical_v1_activation_lock_v1"

_GIT_SHA_HEX_RE = re.compile(r"^[0-9a-f]{40}$")

# to_document_fields() ile BİREBİR aynı 12 anahtar -- from_document_fields()'in
# katı alan-seti doğrulaması bu kümeye karşı yapılır (HATA 12N3C2-B2-A section 14/15).
_DOCUMENT_FIELD_KEYS = frozenset(
    {
        "activation_lock_schema_version",
        "activation_lock_id",
        "protocol_version",
        "protocol_sha256",
        "freeze_manifest_sha256",
        "methodology_git_commit",
        "authorized_methodology_source_fingerprint",
        "authorized_project_id",
        "authorized_runtime_service",
        "authorized_runtime_revision",
        "methodology_approval_reference",
        "record_content_sha256",
    }
)


def _validate_non_empty_str(value: object, field_name: str) -> None:
    """`evidence_identity.py`/`session_manifest.py`/`final_evaluation_models.py`'de
    zaten kurulu, kasıtlı olarak paylaşılmayan (her modülün kendi özel
    kopyasını tuttuğu) minimal format-doğrulama konvansiyonunun devamı."""
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field_name} boş olmayan bir string olmalı: {value!r}")


def _validate_no_surrounding_whitespace(value: str, field_name: str) -> None:
    if value != value.strip():
        raise ValueError(f"{field_name} baştaki/sondaki boşluk içeremez: {value!r}")


def _validate_git_sha_hex(value: object, field_name: str) -> None:
    """Tam olarak 40 küçük-harf hex karakter mi -- fail-fast, coerce yok.

    Bu, `evidence_models.validate_sha256_hex`'in 64-hex kardeşidir ancak GIT
    commit SHA'ları için; kod tabanında hiçbir yerde önceden mevcut değildi
    (bu HATA'da doğrulandı: `grep`, mevcut bir git-SHA doğrulayıcı bulamadı).
    Yalnızca FORMAT doğrular -- belirli bir commit'in gerçekten var olduğunu
    ya da onaylandığını KANITLAMAZ (bu doğrulama saf şema katmanının kapsamı
    dışındadır, bkz. modül docstring'i)."""
    if not isinstance(value, str) or not _GIT_SHA_HEX_RE.match(value):
        raise ValueError(
            f"{field_name} tam olarak 40 küçük-harf hex karakter (git commit SHA formatı) değil: {value!r}"
        )


def _validate_runtime_identity_component(value: object, field_name: str) -> None:
    """`compute_runtime_fingerprint()`'in "/" ayracıyla birleştirdiği üç
    bileşenden (project_id/service/revision) her biri için: boş olamaz,
    baştaki/sondaki boşluk içeremez, ve "/" İÇEREMEZ (aksi halde
    runtime_fingerprint string'i tersine-çevrilemez/belirsiz hale gelir)."""
    _validate_non_empty_str(value, field_name)
    _validate_no_surrounding_whitespace(value, field_name)  # type: ignore[arg-type]
    if "/" in value:  # type: ignore[operator]
        raise ValueError(f"{field_name} '/' karakteri içeremez: {value!r}")


def compute_activation_lock_id(
    *,
    protocol_version: str,
    authorized_methodology_source_fingerprint: str,
    authorized_project_id: str,
    authorized_runtime_service: str,
    authorized_runtime_revision: str,
) -> str:
    """Kimlik-taşıyan 6 alanın (şema versiyonu sabit olarak dahil) kendini-
    tanımlayan sarmalayıcı altında kanonik SHA-256'sı (HATA 12N3C2-B3-R2).

    `activation_lock_schema_version` burada bir PARAMETRE DEĞİL, sabittir --
    çünkü bu fonksiyon her zaman TEK bir şema versiyonu (bu modülün kendi
    versiyonu) için kimlik üretir; farklı bir şema versiyonu farklı bir
    modül/fonksiyon gerektirir (HATA 12N3C2-B2-A section 10: "forward-compat
    yok, farklı şema versiyonu reddedilir")."""
    payload = {
        "activation_lock_identity": {
            "activation_lock_schema_version": TECHNICAL_V1_ACTIVATION_LOCK_SCHEMA_VERSION,
            "protocol_version": protocol_version,
            "authorized_methodology_source_fingerprint": authorized_methodology_source_fingerprint,
            "authorized_project_id": authorized_project_id,
            "authorized_runtime_service": authorized_runtime_service,
            "authorized_runtime_revision": authorized_runtime_revision,
        }
    }
    return content_sha256(payload)


def compute_runtime_fingerprint(project_id: str, service: str, revision: str) -> str:
    """`project_id + "/" + service + "/" + revision`.

    GCP proje kimlikleri, Cloud Run servis adları ve revizyon adları DNS-
    label benzeri kısıtlara tabidir ve "/" içeremez (HATA 12N3C2-B3-R2'de
    doğrulandı) -- bu yüzden "/" ayracı tersine-çevrilemez biçimde güvenlidir.
    Bu fonksiyon `TechnicalV1ActivationLock`'un kendi iç durumuna bağlı
    DEĞİLDİR (üç ham string alır, bir string döner) -- kasıtlı olarak bu
    modülde tutuluyor çünkü aktivasyon kilidinin `authorized_project_id`/
    `authorized_runtime_service`/`authorized_runtime_revision` alanlarıyla
    AYNI üç bileşenin AYNI birleştirme kuralını paylaşır; ayrı bir modüle
    taşımak gereksiz bir dolaylama (indirection) olurdu."""
    _validate_runtime_identity_component(project_id, "project_id")
    _validate_runtime_identity_component(service, "service")
    _validate_runtime_identity_component(revision, "revision")
    return f"{project_id}/{service}/{revision}"


@dataclass(frozen=True)
class TechnicalV1ActivationLock:
    """Belirli bir (protokol × onaylı metodoloji parmak-izi × belirli Cloud
    Run deployment kimliği) üçlüsünü prospektif evidence-capture yapmaya
    YETKİLENDİREN, değişmez (immutable), ekle-yalnızca (append-only) kayıt.

    Zaman damgası TAŞIMAZ -- `create_time` her zaman repository katmanının
    (bu HATA'nın kapsamı dışında, henüz yazılmadı) sorumluluğundadır.
    """

    activation_lock_schema_version: str
    activation_lock_id: str
    protocol_version: str
    protocol_sha256: str
    freeze_manifest_sha256: str
    methodology_git_commit: str
    authorized_methodology_source_fingerprint: str
    authorized_project_id: str
    authorized_runtime_service: str
    authorized_runtime_revision: str
    methodology_approval_reference: str

    def __post_init__(self) -> None:
        if self.activation_lock_schema_version != TECHNICAL_V1_ACTIVATION_LOCK_SCHEMA_VERSION:
            raise ValueError(
                "activation_lock_schema_version beklenen sabitle eşleşmiyor "
                f"(forward-compat desteklenmiyor): {self.activation_lock_schema_version!r} != "
                f"{TECHNICAL_V1_ACTIVATION_LOCK_SCHEMA_VERSION!r}"
            )

        _validate_non_empty_str(self.protocol_version, "protocol_version")
        _validate_no_surrounding_whitespace(self.protocol_version, "protocol_version")

        validate_sha256_hex(self.protocol_sha256)
        validate_sha256_hex(self.freeze_manifest_sha256)
        validate_sha256_hex(self.authorized_methodology_source_fingerprint)

        _validate_git_sha_hex(self.methodology_git_commit, "methodology_git_commit")
        _validate_git_sha_hex(self.methodology_approval_reference, "methodology_approval_reference")

        _validate_runtime_identity_component(self.authorized_project_id, "authorized_project_id")
        _validate_runtime_identity_component(self.authorized_runtime_service, "authorized_runtime_service")
        _validate_runtime_identity_component(self.authorized_runtime_revision, "authorized_runtime_revision")

        # activation_lock_id ASLA çağırandan körü körüne güvenilmez -- kimlik-
        # taşıyan 6 alandan bağımsız olarak yeniden türetilir ve eşitlik
        # zorunlu kılınır (HATA 12N3C2-B2-A section 11).
        validate_sha256_hex(self.activation_lock_id)
        expected_activation_lock_id = compute_activation_lock_id(
            protocol_version=self.protocol_version,
            authorized_methodology_source_fingerprint=self.authorized_methodology_source_fingerprint,
            authorized_project_id=self.authorized_project_id,
            authorized_runtime_service=self.authorized_runtime_service,
            authorized_runtime_revision=self.authorized_runtime_revision,
        )
        if self.activation_lock_id != expected_activation_lock_id:
            raise ValueError(
                "activation_lock_id, kimlik-taşıyan alanlardan bağımsız olarak yeniden "
                f"hesaplanan değerle eşleşmiyor -- verilen={self.activation_lock_id!r}, "
                f"beklenen={expected_activation_lock_id!r}"
            )

    def to_content_fields(self) -> dict:
        """Depolanan TÜM 11 içerik alanı (activation_lock_id DAHİL).

        `record_content_sha256`'nın payload'ı budur -- HATA 12N3C2-B2-A
        section 13'te KİLİTLENEN düzeltme: record_content_sha256,
        activation_lock_id'yi de kapsar (yalnızca kendi kendisini hariç
        tutar), çünkü aksi halde activation_lock_id'nin kendisindeki bir
        bozulma (tampering) record_content_sha256 tarafından hiç
        yakalanmazdı."""
        return {
            "activation_lock_schema_version": self.activation_lock_schema_version,
            "activation_lock_id": self.activation_lock_id,
            "protocol_version": self.protocol_version,
            "protocol_sha256": self.protocol_sha256,
            "freeze_manifest_sha256": self.freeze_manifest_sha256,
            "methodology_git_commit": self.methodology_git_commit,
            "authorized_methodology_source_fingerprint": self.authorized_methodology_source_fingerprint,
            "authorized_project_id": self.authorized_project_id,
            "authorized_runtime_service": self.authorized_runtime_service,
            "authorized_runtime_revision": self.authorized_runtime_revision,
            "methodology_approval_reference": self.methodology_approval_reference,
        }

    @property
    def record_content_sha256(self) -> str:
        """Depolanan bir alan DEĞİL -- her zaman türetilen bir @property
        (bu oturumda tekrar tekrar kilitlenen, ASLA sapılmayan kural)."""
        return content_sha256(self.to_content_fields())

    def to_document_fields(self) -> dict:
        """11 içerik alanı + record_content_sha256 = tam olarak 12 alan.
        create_time/updated_at/scoring_config_hash YOKTUR (bu saf modelin
        kapsamı dışında)."""
        return {**self.to_content_fields(), "record_content_sha256": self.record_content_sha256}

    @classmethod
    def from_document_fields(cls, data: dict) -> "TechnicalV1ActivationLock":
        """Katı yeniden kuruluş: eksik/bilinmeyen alan reddedilir, şema
        onarımı/normalizasyon YAPILMAZ.

        `FinalEvaluation`/`TechnicalV1SessionManifest`'in aksine (onlarda
        ham-hash doğrulaması KASITLI olarak repository katmanına bırakılır),
        bu metod STORED `record_content_sha256`'yı DA doğrudan burada,
        bağımsız olarak yeniden hesaplayıp karşılaştırır -- çünkü bu HATA
        için henüz bir repository katmanı YOK (o, ayrı bir sonraki HATA'nın
        -- "B2-B" -- konusu) ve ticket'ın kendi section 15 talimatı bunu
        açıkça istiyor: "recompute and verify: activation_lock_id,
        record_content_sha256. Do not trust either stored hash blindly."
        Bu, saf modelin BUGÜN, herhangi bir repository'ye ihtiyaç duymadan
        tamamen kendi kendini doğrulayan (self-contained) bir yeniden-
        kuruluş sağlamasını mümkün kılar."""
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

        reconstructed = cls(
            activation_lock_schema_version=data["activation_lock_schema_version"],
            activation_lock_id=data["activation_lock_id"],
            protocol_version=data["protocol_version"],
            protocol_sha256=data["protocol_sha256"],
            freeze_manifest_sha256=data["freeze_manifest_sha256"],
            methodology_git_commit=data["methodology_git_commit"],
            authorized_methodology_source_fingerprint=data["authorized_methodology_source_fingerprint"],
            authorized_project_id=data["authorized_project_id"],
            authorized_runtime_service=data["authorized_runtime_service"],
            authorized_runtime_revision=data["authorized_runtime_revision"],
            methodology_approval_reference=data["methodology_approval_reference"],
        )

        if reconstructed.record_content_sha256 != stored_record_content_sha256:
            raise ValueError(
                "from_document_fields: stored record_content_sha256, içerik alanlarından "
                f"bağımsız olarak yeniden hesaplanan değerle eşleşmiyor -- stored="
                f"{stored_record_content_sha256!r}, recomputed={reconstructed.record_content_sha256!r}"
            )

        return reconstructed
