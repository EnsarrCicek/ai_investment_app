"""Technical V1 CONFIG kimlik-kapısı -- beklenen (expected) ve gözlemlenen
(observed) `scoring_config_hash` değerlerini üreten I/O adaptörleri.
HATA 12N3C2-B2-D / B2-D1 / B2-D2 / B2-D3.

Bu modül, `identity_gates.evaluate_config_gate()`'in SAF karşılaştırma
katmanından AYRI tutulan iki adaptörü içerir (section 6/20: repository/
dosya I/O'su, saf kapı karşılaştırmasından her zaman ayrı tutulur):

  - `load_verified_scoring_config_hash()`: dondurulmuş `app/research/
    resources/technical_v1_freeze_manifest.json`'daki `methodology_
    identity.scoring_config_hash`'i okur -- AMA ÖNCE paketlenmiş
    dosyanın KENDİ kimliğini (`content_sha256(parsed_object)`) çağıranın
    verdiği `expected_freeze_manifest_sha256` ile doğrular (HATA
    12N3C2-B2-D2'de kilitlenen tam güven zinciri, B2-D3'te implemente
    edildi). Bu TEK, güvenilen genel API'dir -- doğrulamayı ATLAYAN
    başka bir genel fonksiyon YOKTUR (`_read_manifest_json()` özel/dahili
    bir yardımcıdır, kimlik doğrulaması YAPMAZ, dışa export edilmez).
  - `compute_observed_scoring_config_hash()`: `app/engines/technical/
    engine.py::analyze_with_id()`'nin KENDİSİNİN kullandığı TAM AYNI
    kalıbı yeniden kullanır (`resolve_indicator_weights`/`resolve_family_
    weights`/`compute_scoring_config_hash` -- ikinci bir config-çözümleme
    algoritması İCAT EDİLMEDİ, B2-D2/B2-D3 kapsamında DEĞİŞMEDİ).

KİLİTLİ güven zinciri (HATA 12N3C2-B2-D2, section 13/17 -- kısayol YOK):

    doğrulanmış TechnicalV1ActivationLock
    -> expected_freeze_manifest_sha256 = activation_lock.freeze_manifest_sha256
    -> paketlenmiş kanonik JSON dosyası (bu modülün okuduğu)
    -> content_sha256(parsed JSON)  [HATA 12N3C2-B2-D2'de doğrulanan TARİHSEL algoritma]
    -> eşitlik kontrolü (BAŞARISIZSA: scoring_config_hash HİÇ okunmaz)
    -> methodology_identity.scoring_config_hash çıkarımı
    -> scoring_config_hash format doğrulaması
    -> CONFIG beklenen (expected) değeri.

Bu modül `TechnicalV1ActivationLockRepository`'yi HİÇ import/çağırmaz --
`expected_freeze_manifest_sha256` çağıran tarafından (gelecekteki
controller/servis) ZATEN doğrulanmış olarak sağlanır (section 12/16).

ÖNEMLİ SINIR (HATA 12N3C2-B2-D2 section 19/21, dürüstçe belgelendi): bir
saldırgan/bozuk bir release süreci paketlenmiş manifest'i DEĞİŞTİRİP
KENDİ değiştirdiği içerikten DOĞRU şekilde yeniden hesaplanmış bir hash'i
"expected" olarak sağlarsa, bu fonksiyon TEK BAŞINA bunu tespit EDEMEZ --
yalnızca paketlenmiş baytlar ile ÇAĞIRANIN sağladığı hash arasındaki İÇSEL
tutarlılığı kanıtlayabilir. Gerçek yetkilendirme, `expected_freeze_
manifest_sha256`'nın BAĞIMSIZ OLARAK doğrulanmış bir `TechnicalV1
ActivationLock`'tan gelmesinden kaynaklanır -- manifest'in kendi baytları
ASLA kendi kendini yetkilendirmez. Bu, loader sözleşmesinde bir GÜVENLİK
AÇIĞI DEĞİLDİR -- tasarımın kasıtlı, belgelenmiş bir sınırıdır.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engines.technical.scoring import (
    compute_scoring_config_hash,
    resolve_family_weights,
    resolve_indicator_weights,
)
from app.repositories.system_config_repository import SystemConfigRepository
from app.research.canonical_hash import content_sha256
from app.research.evidence_models import ProvenanceConflictError, validate_sha256_hex

# HATA 12N3C2-B2-D3: kanonik paketlenmiş dosya artık `backend/app/` AĞACININ
# İÇİNDE -- bu modülün KENDİ dizininin ("research/") bir alt dizini
# ("resources/") olarak. `backend/` KÖKÜNE ya da repo köküne HİÇ ÇIKILMAZ
# (Dockerfile'ın `COPY app ./app` adımı zaten `research/` KLASÖRÜNÜN
# TAMAMINI kapsıyor, ekstra bir COPY/build-context değişikliği GEREKMEZ).
# `__file__` kullanıldığından, çağıranın güncel çalışma dizininden (CWD)
# TAMAMEN BAĞIMSIZDIR (methodology_fingerprint.py'nin AYNI deseni).
_DEFAULT_FREEZE_MANIFEST_PATH = Path(__file__).resolve().parent / "resources" / "technical_v1_freeze_manifest.json"


def _read_manifest_json(path: Path) -> dict:
    """ÖZEL/dahili yardımcı -- YALNIZCA dosyayı okur/JSON parse eder,
    HİÇBİR kimlik doğrulaması YAPMAZ. Bu modülün DIŞINA hiç export
    edilmez -- doğrulamayı atlayan bir "hızlı yol" olarak KULLANILAMAZ,
    çünkü tek genel API (`load_verified_scoring_config_hash()`) BUNU
    çağırdıktan HEMEN SONRA, herhangi bir alan okumadan ÖNCE, kimlik
    kontrolünü zorunlu kılar."""
    with path.open(encoding="utf-8") as f:
        raw_text = f.read()
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ProvenanceConflictError(
            f"Paketlenmiş freeze manifest ({path}) geçerli JSON değil: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ProvenanceConflictError(
            f"Paketlenmiş freeze manifest ({path}) üst-düzeyde bir JSON nesnesi (object) değil: "
            f"{type(parsed).__name__}"
        )
    return parsed


class TechnicalV1MethodologySupersededError(ProvenanceConflictError):
    """TECH-VOL 1B: paketlenmiş Technical V1 freeze manifest'inin dondurduğu
    `engine_version`, ŞU AN çalışan `TechnicalAnalysisEngine.ENGINE_VERSION`
    ile eşleşmiyor -- V1 metodolojisi SUPERSEDED. Bu durumda V1 evidence
    capture/aktivasyonu yapılamaz: aksi halde V1 kimliğiyle (c1f0d43 /
    1.14.0) etiketlenmiş kayıtlar FARKLI bir sınıflandırıcıyla üretilirdi.
    Düzeltilmiş metodoloji `technical_v2_freeze_manifest.json`'da; V2 protokol
    ve evidence pipeline bağlantısı aktivasyondan önce AYRI bir bilettir."""


def assert_v1_methodology_matches_running_engine(parsed_manifest: dict | None = None) -> None:
    """Fail-fast guard. `parsed_manifest` verilmezse paketlenmiş V1 manifest okunur."""
    from app.engines.technical.engine import ENGINE_VERSION

    manifest = parsed_manifest if parsed_manifest is not None else _read_manifest_json(_DEFAULT_FREEZE_MANIFEST_PATH)
    identity = manifest.get("methodology_identity")
    frozen = identity.get("engine_version") if isinstance(identity, dict) else None
    if frozen != ENGINE_VERSION:
        raise TechnicalV1MethodologySupersededError(
            f"Technical V1 freeze manifest engine_version={frozen!r} ama çalışan engine={ENGINE_VERSION!r}: "
            "V1 metodolojisi SUPERSEDED (TECH-VOL 1B). V1 aktivasyonu/evidence capture reddedildi; "
            "bkz. app/research/resources/technical_v2_freeze_manifest.json."
        )


def load_verified_scoring_config_hash(
    expected_freeze_manifest_sha256: str, manifest_path: Path | None = None
) -> str:
    """Paketlenmiş freeze manifest'in KENDİ kimliğini doğrulamadan
    `scoring_config_hash`'i ASLA döndürmeyen, TEK güvenilen genel API.

    Kesin sıra (HATA 12N3C2-B2-D2 section 10/13, atlanamaz):
      1. `expected_freeze_manifest_sha256` kanonik (64 küçük-harf hex) mi?
         (çağıranın kendi hatası -- hiçbir I/O yapılmadan, yerel olarak
         `EvidenceIntegrityError` fırlatılır.)
      2. dosya okunur/JSON parse edilir (`_read_manifest_json`).
      3. `content_sha256(parsed)` (HATA 12N3C2-B2-D2'de doğrulanan TARİHSEL
         algoritma) `expected_freeze_manifest_sha256` ile TAM eşleşiyor mu?
         EŞLEŞMİYORSA: `ProvenanceConflictError` -- `scoring_config_hash`
         HİÇ OKUNMAZ/DÖNDÜRÜLMEZ.
      4. YALNIZCA kimlik doğrulaması geçtikten SONRA `methodology_identity.
         scoring_config_hash` çıkarılır ve kanonik (64 küçük-harf hex)
         format için doğrulanır -- eksik/yanlış tip/malformed: `Provenance
         ConflictError`.

    Format/girinti/anahtar sırası/satır-sonu farkları SONUCU DEĞİŞTİRMEZ --
    `content_sha256` HER ZAMAN parse edilmiş Python nesnesi üzerinden,
    kanonik olarak yeniden hesaplar (ham dosya baytları ÜZERİNDEN DEĞİL)."""
    validate_sha256_hex(expected_freeze_manifest_sha256)

    path = manifest_path if manifest_path is not None else _DEFAULT_FREEZE_MANIFEST_PATH
    parsed = _read_manifest_json(path)

    actual_freeze_manifest_sha256 = content_sha256(parsed)
    if actual_freeze_manifest_sha256 != expected_freeze_manifest_sha256:
        raise ProvenanceConflictError(
            f"Paketlenmiş freeze manifest ({path}) kimliği beklenenle eşleşmiyor -- "
            f"actual={actual_freeze_manifest_sha256}, expected={expected_freeze_manifest_sha256}. "
            f"Bu artefakt GÜVENİLMEDİ -- scoring_config_hash HİÇ okunmadı."
        )

    methodology_identity = parsed.get("methodology_identity")
    if not isinstance(methodology_identity, dict):
        raise ProvenanceConflictError(
            f"Paketlenmiş freeze manifest ({path}): 'methodology_identity' eksik ya da bir JSON "
            f"nesnesi değil: {methodology_identity!r}"
        )

    scoring_config_hash = methodology_identity.get("scoring_config_hash")
    try:
        validate_sha256_hex(scoring_config_hash)
    except Exception as exc:
        raise ProvenanceConflictError(
            f"Paketlenmiş freeze manifest ({path}): 'methodology_identity.scoring_config_hash' "
            f"kanonik (64 küçük-harf hex) formatında değil: {scoring_config_hash!r}"
        ) from exc

    # TECH-VOL 1B: kimliği doğrulanmış V1 manifest'i çalışan motorla eşleşmiyorsa
    # (metodoloji superseded) hiçbir V1 attempt'i bu beklenen değerle ilerleyemez.
    assert_v1_methodology_matches_running_engine(parsed)
    return scoring_config_hash


def compute_observed_scoring_config_hash(config_repo: SystemConfigRepository) -> str:
    """`TechnicalAnalysisEngine.analyze_with_id()`'nin KENDİSİNİN kullandığı
    TAM AYNI çözümleme kalıbını (`app/engines/technical/engine.py`)
    yeniden kullanarak, ŞU AN Firestore'da GEÇERLİ olan skor config'inden
    deterministik hash'i üretir. `config_repo`, `SystemConfigRepository`
    ile aynı `get_raw(config_id) -> dict | None` sözleşmesine uyan HERHANGİ
    bir nesne olabilir (testlerde sahte/fake bir nesne enjekte edilir --
    bu fonksiyonun kendisi gerçek Firestore'a hiç dokunmaz, yalnızca
    verilen `config_repo`'yu çağırır). HATA 12N3C2-B2-D2/B2-D3 kapsamında
    DEĞİŞMEDİ."""
    weights = resolve_indicator_weights(config_repo.get_raw("technical_indicator_weights"))
    family_weights = resolve_family_weights(config_repo.get_raw("technical_family_weights"))
    return compute_scoring_config_hash(weights, family_weights)
