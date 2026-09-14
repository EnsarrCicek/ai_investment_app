"""HATA 12N3A — Technical V1 saf oturum (session) muhasebe/manifest
alan modeli.

Bu modül HİÇBİR I/O yapmaz -- dosya sistemi erişimi (protokol JSON'unu
okumak dahil), Firestore/GCS erişimi, ağ isteği YOKTUR. `research/
technical_v1_protocol_v1.json`'daki frozen 100 sembollük evreni OKUMAK
daha sonraki bir adapter/wiring katmanının (N3C/N3D) sorumluluğudur --
bu modül yalnızca ZATEN YÜKLENMİŞ, güvenilen `frozen_symbols`/
`protocol_version`/hash'ler gibi düz veriyi girdi olarak kabul eder.

GÜVEN SINIRI (HATA 12N3-A5'te kilitlendi, burada AÇIKÇA tekrarlanır):
bu modül Firestore depolama-provenance'ını DOĞRULAMAZ. `build_session_
manifest()`'e verilen `FinalEvaluation` nesnelerinin GERÇEKTEN Firestore'a
persist edilmiş, N2B2'nin `TechnicalV1EvaluationRepository.get_verified()`
metodundan geçmiş GÜVENİLİR nesneler olması ÜRETİM ÇAĞIRANININ
sorumluluğudur -- bu modül yalnızca o GÜVENİLEN nesneler üzerinde
oturum-seviyesi KÜME/kimlik/sayım/kanonik-hash TUTARLILIĞINI kurar.
Bireysel bir dokümanın Firestore'daki ham hash'inin/şemasının doğruluğu
SADECE N2B2'nin sorumluluğundadır (bkz. `technical_v1_evaluation_
repository.py`); burada TEKRAR DOĞRULANMAZ (yapısal olarak da mümkün
değildir -- `FinalEvaluation.record_content_sha256` türetilmiş bir
property'dir, saklanan ham Firestore hash'i bu nesneye hiç taşınmaz).

Kilitli tasarım kararları (HATA 12N3-A/A2/A3/A4/A5'te kilitlendi):
  - `session_id`'in mantıksal kimliği TAM OLARAK `{protocol_version,
    T_session_date}`'dir -- sembol/attempt/runtime/zaman damgası KATILMAZ.
  - `expected_evaluation_ids_sha256`, "hangi 100 kimlik gerekliydi?"
    sorusuna cevap verir -- frozen evrenden BAĞIMSIZ olarak yeniden
    türetilebilir, ham 100 ID saklanmaz.
  - `final_evaluation_records_sha256`, "bu 100 kimliği HANGİ tam
    içerikler karşıladı?" sorusuna cevap verir -- `{evaluation_id,
    record_content_sha256}` ÇİFTLERİ üzerinden hash'lenir (yalnızca
    ID'ler veya yalnızca hash'ler AYRI AYRI DEĞİL) ki ID<->içerik
    bağı korunsun.
  - `TechnicalV1SessionManifest` HİÇBİR `session_status`/retry/
    completion-flag alanı İÇERMEZ -- dokümanın var olması, tanımı
    gereği bilimsel oturum TAMLIĞINI temsil eder (yaratım ön-koşulu:
    frozen 100 kimliğin TÜMÜ güvenilir final kayıtlara sahip).
  - `SessionAccountingStatus`/`ExpectedEvaluationState`, retry-pending
    gibi MUTABLE orkestrasyon durumlarını KESİNLİKLE İÇERMEZ -- bunlar
    yalnızca N3C'nin mutable `technical_v1_session_runs` durumuna aittir.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum

from app.research.canonical_hash import content_sha256
from app.research.evidence_identity import compute_evaluation_id, compute_session_id
from app.research.evidence_models import validate_sha256_hex
from app.research.final_evaluation_models import CaptureStatus, EvaluationIntegrityStatus, FinalEvaluation

EXPECTED_FROZEN_SYMBOL_COUNT = 100

TECHNICAL_V1_SESSION_MANIFEST_SCHEMA_VERSION = "technical_v1_session_manifest_v1"

_CANONICAL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_non_empty_str(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} boş olmayan bir string olmalı: {value!r}")


def _validate_canonical_date_str(value: str, field_name: str) -> None:
    """`evidence_identity.py`'nin AYNI iki-katmanlı sıkı doğrulama deseni
    (regex tam-eşleşme + self-round-trip) -- `final_evaluation_models.py`
    da bu KÜÇÜK format kontrolünü PAYLAŞILAN bir public API üzerinden
    içe aktarmak yerine kendi private kopyası olarak tutar (paylaşılan
    tek ilkel olan `canonical_hash.content_sha256()`'ın aksine)."""
    if not isinstance(value, str) or not _CANONICAL_DATE_RE.match(value):
        raise ValueError(f"{field_name} kanonik lehçede değil (YYYY-MM-DD bekleniyor): {value!r}")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} geçersiz takvim tarihi: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} kanonik round-trip'i sağlamıyor: {value!r}")


def _validate_strict_int(value: int, field_name: str) -> None:
    """`bool`, Python'da `int`'in bir alt sınıfıdır -- sayım alanları
    KASITLI OLARAK tam bir `int` (bool DEĞİL) olmalı (aynı disiplin
    `evidence_identity.compute_attempt_id`'de de uygulanır)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} tam bir int olmalı (bool değil): {value!r}")


# ---------------------------------------------------------------------------
# Frozen evren doğrulaması (HATA 12N3A section 5/6/9) -- SAF, dosya sistemi
# erişimi YOK. Girdi ZATEN YÜKLENMİŞ bir semboller dizisidir.
# ---------------------------------------------------------------------------


def validate_frozen_universe(symbols: Sequence[str]) -> tuple[str, ...]:
    """Zaten yüklenmiş bir frozen sembol listesini doğrular -- HİÇBİR
    normalizasyon (strip/uppercase/sort/dedupe/geçersiz-olanı-düşürme)
    YAPMAZ; herhangi bir ihlal SESSİZCE onarılmaz, `ValueError` fırlatılır.
    Sağlanan SIRA korunur (`tuple` olarak döner) -- frozen protokol
    dokümanındaki sıra kanıt/denetim değeri taşır, keyfi olarak
    yeniden sıralanmaz."""
    if not isinstance(symbols, Sequence) or isinstance(symbols, (str, bytes)):
        raise ValueError(f"symbols sıralı bir koleksiyon (liste/tuple) olmalı, çıplak str/bytes DEĞİL: {symbols!r}")

    validated: list[str] = []
    for index, symbol in enumerate(symbols):
        if not isinstance(symbol, str):
            raise ValueError(f"symbols[{index}] bir string olmalı: {symbol!r}")
        if symbol == "":
            raise ValueError(f"symbols[{index}] boş bir string olamaz")
        if symbol != symbol.strip():
            raise ValueError(f"symbols[{index}] baştaki/sondaki boşluk içeriyor -- SESSİZCE strip edilmez: {symbol!r}")
        validated.append(symbol)

    if len(validated) != EXPECTED_FROZEN_SYMBOL_COUNT:
        raise ValueError(
            f"frozen universe tam olarak {EXPECTED_FROZEN_SYMBOL_COUNT} sembol içermeli, "
            f"{len(validated)} bulundu -- denominator SESSİZCE küçültülemez/büyütülemez."
        )
    if len(set(validated)) != len(validated):
        raise ValueError("frozen universe içinde tekrar eden sembol(ler) var -- her sembol TEKİL olmalı.")

    return tuple(validated)


# ---------------------------------------------------------------------------
# Beklenen evaluation_id kümesi (HATA 12N3A section 7/8)
# ---------------------------------------------------------------------------


def derive_expected_evaluation_ids(
    protocol_version: str, t_session_date: str, frozen_symbols: Sequence[str]
) -> tuple[str, ...]:
    """Her doğrulanmış sembol için `compute_evaluation_id(...)` çağırır --
    dinamik keşif/Firestore sorgusu YOK, TAMAMEN önceden hesaplanabilir.
    Dönen tuple, `frozen_symbols`'un SIRASINI korur."""
    validated_symbols = validate_frozen_universe(frozen_symbols)
    expected_ids = tuple(
        compute_evaluation_id(protocol_version, t_session_date, symbol) for symbol in validated_symbols
    )
    if len(set(expected_ids)) != len(expected_ids):
        raise ValueError(
            "türetilen evaluation_id kümesinde tekrar eden değer(ler) var -- "
            "bu, pratikte olanaksız bir SHA-256 çakışmasına işaret eder."
        )
    return expected_ids


def compute_expected_evaluation_ids_sha256(expected_evaluation_ids: Sequence[str]) -> str:
    """HATA 12N3-A3/A4'te kilitlenen tam kanonik payload: `{"evaluation_
    ids": sorted(...)}` -- çıplak/etiketsiz bir liste ASLA hash'lenmez
    (domain-separation, HATA 12O section 6'nın aynı gerekçesi)."""
    ids = list(expected_evaluation_ids)
    if len(ids) != EXPECTED_FROZEN_SYMBOL_COUNT:
        raise ValueError(
            f"expected_evaluation_ids tam olarak {EXPECTED_FROZEN_SYMBOL_COUNT} kimlik içermeli, {len(ids)} bulundu."
        )
    if len(set(ids)) != len(ids):
        raise ValueError("expected_evaluation_ids içinde tekrar eden kimlik(ler) var.")
    for evaluation_id in ids:
        validate_sha256_hex(evaluation_id)

    return content_sha256({"evaluation_ids": sorted(ids)})


def compute_final_evaluation_records_sha256(pairs: Sequence[tuple[str, str]]) -> str:
    """HATA 12N3-A4 section 2/3/9/10'da kilitlenen tam kanonik payload:
    `evaluation_id` <-> `record_content_sha256` ÇİFTLERİ, `evaluation_id`'ye
    göre sıralanmış bir liste olarak hash'lenir -- yalnızca `record_
    content_sha256` değerlerinin sıralı listesi ASLA hash'lenmez (bu,
    kimlik<->içerik bağını yok ederdi; ör. iki kaydın hash'leri
    KENDİ evaluation_id'leri arasında YER DEĞİŞTİRSE bile digest AYNI
    kalırdı -- section 3'ün açıkça reddettiği durum)."""
    pair_list = list(pairs)
    if len(pair_list) != EXPECTED_FROZEN_SYMBOL_COUNT:
        raise ValueError(
            f"final evaluation record seti tam olarak {EXPECTED_FROZEN_SYMBOL_COUNT} çift içermeli, "
            f"{len(pair_list)} bulundu."
        )
    evaluation_ids = [evaluation_id for evaluation_id, _ in pair_list]
    if len(set(evaluation_ids)) != len(evaluation_ids):
        raise ValueError("final evaluation record setinde tekrar eden evaluation_id var.")
    for evaluation_id, record_content_sha256 in pair_list:
        validate_sha256_hex(evaluation_id)
        validate_sha256_hex(record_content_sha256)

    sorted_pairs = sorted(pair_list, key=lambda pair: pair[0])
    return content_sha256(
        {
            "evaluations": [
                {"evaluation_id": evaluation_id, "record_content_sha256": record_content_sha256}
                for evaluation_id, record_content_sha256 in sorted_pairs
            ]
        }
    )


# ---------------------------------------------------------------------------
# Saf oturum muhasebesi (HATA 12N3-A3/A5'te kilitlenen ayrım: BU katman
# SADECE 100 beklenen kimliğin doğrulama SONUÇLARINDAN türetilir --
# retry-pending gibi mutable orkestrasyon durumu KESİNLİKLE burada
# TEMSİL EDİLMEZ, bkz. modül docstring'i).
# ---------------------------------------------------------------------------


class ExpectedEvaluationState(str, Enum):
    """Beklenen tek bir evaluation_id için doğrulama GİRDİ durumu --
    `EvaluationIntegrityStatus`/`VerificationState`/`ResultState` (final
    kaydın KENDİ İÇERİĞİNDEKİ domain-sonuç durumları) İLE KARIŞTIRILMAZ;
    bu, N2B2'nin `get_verified(id)` çağrısının KENDİ SONUCUNU temsil eder."""

    VERIFIED = "VERIFIED"
    ABSENT = "ABSENT"
    CONFLICT = "CONFLICT"


class SessionAccountingStatus(str, Enum):
    COMPLETE = "COMPLETE"
    MISSING_FINAL_RECORDS = "MISSING_FINAL_RECORDS"
    REPOSITORY_PROVENANCE_CONFLICT = "REPOSITORY_PROVENANCE_CONFLICT"


@dataclass(frozen=True)
class SessionAccountingResult:
    """KASITLI OLARAK YOK: retry sayaçları/son hata/zaman damgası/worker
    durumu -- bunlar N3C'nin mutable operasyonel durumuna aittir, bu saf
    modelin KAPSAMI DIŞINDADIR."""

    session_id: str
    expected_symbol_count: int
    verified_count: int
    absent_count: int
    conflict_count: int
    status: SessionAccountingStatus

    def __post_init__(self) -> None:
        _validate_non_empty_str(self.session_id, "session_id")
        for field_name in ("expected_symbol_count", "verified_count", "absent_count", "conflict_count"):
            _validate_strict_int(getattr(self, field_name), field_name)
        if self.verified_count + self.absent_count + self.conflict_count != self.expected_symbol_count:
            raise ValueError(
                "verified_count + absent_count + conflict_count, expected_symbol_count'a EŞİT olmalı "
                f"({self.verified_count}+{self.absent_count}+{self.conflict_count} != {self.expected_symbol_count})"
            )


def derive_session_accounting(
    session_id: str,
    expected_evaluation_ids: Sequence[str],
    states: Mapping[str, ExpectedEvaluationState],
) -> SessionAccountingResult:
    """HATA 12N3A section 13: girdi SADECE toplam sayılar DEĞİL, TAM
    `evaluation_id -> ExpectedEvaluationState` eşlemesidir -- bu, eksik
    beklenen bir kimliği, yabancı/beklenmeyen bir kimliği ve yanlış kayıt
    sayısını AYRI AYRI tespit edebilmek içindir (yalnızca toplam sayılarla
    bu üçü birbirinden ayırt edilemezdi)."""
    expected_set = set(expected_evaluation_ids)
    if len(expected_set) != len(expected_evaluation_ids):
        raise ValueError("expected_evaluation_ids içinde tekrar eden kimlik(ler) var.")

    actual_set = set(states.keys())
    if actual_set != expected_set:
        missing = expected_set - actual_set
        foreign = actual_set - expected_set
        raise ValueError(
            "states eşlemesi, beklenen evaluation_id kümesiyle TAM OLARAK eşleşmiyor -- "
            f"eksik={sorted(missing)!r} yabancı={sorted(foreign)!r}"
        )

    verified_count = sum(1 for state in states.values() if state == ExpectedEvaluationState.VERIFIED)
    absent_count = sum(1 for state in states.values() if state == ExpectedEvaluationState.ABSENT)
    conflict_count = sum(1 for state in states.values() if state == ExpectedEvaluationState.CONFLICT)

    if conflict_count > 0:
        status = SessionAccountingStatus.REPOSITORY_PROVENANCE_CONFLICT
    elif absent_count > 0:
        status = SessionAccountingStatus.MISSING_FINAL_RECORDS
    else:
        status = SessionAccountingStatus.COMPLETE

    return SessionAccountingResult(
        session_id=session_id,
        expected_symbol_count=len(expected_evaluation_ids),
        verified_count=verified_count,
        absent_count=absent_count,
        conflict_count=conflict_count,
        status=status,
    )


# ---------------------------------------------------------------------------
# Değişmez oturum manifestosu (HATA 12N3-A4/A5'te kilitlenen tam şema)
# ---------------------------------------------------------------------------

_CAPTURE_STATUS_KEYS: tuple[str, ...] = tuple(status.value for status in CaptureStatus)
_EVALUATION_INTEGRITY_STATUS_KEYS: tuple[str, ...] = tuple(status.value for status in EvaluationIntegrityStatus)


def _validate_count_map(value: Mapping[str, int], expected_keys: tuple[str, ...], field_name: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} bir mapping (dict) olmalı: {value!r}")
    if set(value.keys()) != set(expected_keys):
        raise ValueError(
            f"{field_name} TAM OLARAK şu anahtarları içermeli (eksik/fazla anahtar YOK): "
            f"{sorted(expected_keys)!r}, bulunan: {sorted(value.keys())!r}"
        )
    for key, count in value.items():
        _validate_strict_int(count, f"{field_name}[{key}]")
        if count < 0:
            raise ValueError(f"{field_name}[{key}] negatif olamaz: {count!r}")


@dataclass(frozen=True)
class TechnicalV1SessionManifest:
    """HATA 12N3-A4 section 10/HATA 12N3-A5 section 10: tam, kilitli
    içerik şeması. KASITLI OLARAK YOK: `session_status`/retry/completion-
    flag/operasyonel hata alanı (bkz. modül docstring'i) -- bu dokümanın
    var olması, tanımı gereği bilimsel oturum TAMLIĞINI temsil eder."""

    manifest_schema_version: str
    session_id: str
    protocol_version: str
    T_session_date: str
    protocol_sha256: str
    freeze_manifest_sha256: str
    expected_symbol_count: int
    expected_evaluation_ids_sha256: str
    final_evaluation_records_sha256: str
    capture_status_counts: Mapping[str, int]
    evaluation_integrity_status_counts: Mapping[str, int]
    technical_observation_eligible_count: int

    def __post_init__(self) -> None:
        if self.manifest_schema_version != TECHNICAL_V1_SESSION_MANIFEST_SCHEMA_VERSION:
            # HATA 12N3A section 14: schema version `protocol_version`'dan
            # ASLA türetilmez/karışmaz -- bu sınıf yalnızca TEK, bilinen
            # şema sürümünü temsil eder (ör. bir v2 şema gerekirse, bu
            # kodda mevcut olan protokol-versiyonlama disiplininin AYNISI
            # izlenir: ayrı, kendi başına doğrulanan bir sınıf).
            raise ValueError(
                f"manifest_schema_version yalnızca {TECHNICAL_V1_SESSION_MANIFEST_SCHEMA_VERSION!r} olabilir: "
                f"{self.manifest_schema_version!r}"
            )
        _validate_non_empty_str(self.protocol_version, "protocol_version")
        # T_session_date kanonik lehçe kontrolü -- evidence_identity.py'nin
        # AYNI iki-katmanlı deseni (regex tam-eşleşme + self-round-trip),
        # final_evaluation_models.py'nin ZATEN yaptığı gibi burada da
        # KENDİ private kopyası olarak tutulur (paylaşılan tek bir hashing
        # ilkelinin -- content_sha256 -- aksine, bu küçük format kontrolü
        # modüller arası paylaşılan bir public API DEĞİLDİR).
        _validate_canonical_date_str(self.T_session_date, "T_session_date")
        for field_name in (
            "protocol_sha256",
            "freeze_manifest_sha256",
            "expected_evaluation_ids_sha256",
            "final_evaluation_records_sha256",
        ):
            validate_sha256_hex(getattr(self, field_name))

        expected_session_id = compute_session_id(self.protocol_version, self.T_session_date)
        if self.session_id != expected_session_id:
            raise ValueError(
                f"session_id ({self.session_id}) protocol_version/T_session_date'ten bağımsız olarak "
                f"yeniden hesaplanan ({expected_session_id}) ile eşleşmiyor -- çağırandan geldiği gibi "
                f"KÖRÜKÖRÜNE güvenilmez."
            )

        _validate_strict_int(self.expected_symbol_count, "expected_symbol_count")
        if self.expected_symbol_count != EXPECTED_FROZEN_SYMBOL_COUNT:
            raise ValueError(
                f"expected_symbol_count şema V1 için tam olarak {EXPECTED_FROZEN_SYMBOL_COUNT} olmalı: "
                f"{self.expected_symbol_count!r} (keyfi/available-symbol-count denominator YASAK)."
            )

        _validate_count_map(self.capture_status_counts, _CAPTURE_STATUS_KEYS, "capture_status_counts")
        _validate_count_map(
            self.evaluation_integrity_status_counts, _EVALUATION_INTEGRITY_STATUS_KEYS, "evaluation_integrity_status_counts"
        )
        capture_sum = sum(self.capture_status_counts.values())
        if capture_sum != self.expected_symbol_count:
            raise ValueError(f"capture_status_counts toplamı {self.expected_symbol_count} olmalı: {capture_sum}")
        integrity_sum = sum(self.evaluation_integrity_status_counts.values())
        if integrity_sum != self.expected_symbol_count:
            raise ValueError(
                f"evaluation_integrity_status_counts toplamı {self.expected_symbol_count} olmalı: {integrity_sum}"
            )

        _validate_strict_int(self.technical_observation_eligible_count, "technical_observation_eligible_count")
        if not (0 <= self.technical_observation_eligible_count <= self.expected_symbol_count):
            raise ValueError(
                f"technical_observation_eligible_count [0, {self.expected_symbol_count}] aralığında olmalı: "
                f"{self.technical_observation_eligible_count!r}"
            )
        # HATA 12N3-A4 section 21/HATA 12N3-A5 section 21: mevcut selector
        # semantiğiyle KİLİTLİ değişmez -- `technical_observation_eligible`
        # ile `CaptureStatus.VALID_CAPTURE_AVAILABLE`, `select_final_
        # evaluation()`'da AYNI `selected is not None` koşuluyla belirlenir
        # (bkz. final_evaluation_selector.py), bu yüzden bu iki sayı HER
        # ZAMAN tam olarak eşit olmalıdır.
        valid_capture_count = self.capture_status_counts[CaptureStatus.VALID_CAPTURE_AVAILABLE.value]
        if self.technical_observation_eligible_count != valid_capture_count:
            raise ValueError(
                "technical_observation_eligible_count, capture_status_counts"
                f"[{CaptureStatus.VALID_CAPTURE_AVAILABLE.value!r}] ile TAM OLARAK eşit olmalı "
                f"({self.technical_observation_eligible_count} != {valid_capture_count})"
            )

    def to_content_fields(self) -> dict:
        """`record_content_sha256` HARİÇ tüm alanlar -- doğrudan
        `canonical_hash.content_sha256()`'a verilir. Sayım eşlemeleri
        zaten düz `dict[str, int]`'dir (Enum nesnesi YOK), bu yüzden
        ekstra bir dönüştürme adımı gerekmez."""
        return {
            "manifest_schema_version": self.manifest_schema_version,
            "session_id": self.session_id,
            "protocol_version": self.protocol_version,
            "T_session_date": self.T_session_date,
            "protocol_sha256": self.protocol_sha256,
            "freeze_manifest_sha256": self.freeze_manifest_sha256,
            "expected_symbol_count": self.expected_symbol_count,
            "expected_evaluation_ids_sha256": self.expected_evaluation_ids_sha256,
            "final_evaluation_records_sha256": self.final_evaluation_records_sha256,
            "capture_status_counts": dict(self.capture_status_counts),
            "evaluation_integrity_status_counts": dict(self.evaluation_integrity_status_counts),
            "technical_observation_eligible_count": self.technical_observation_eligible_count,
        }

    @property
    def record_content_sha256(self) -> str:
        # `FinalEvaluation.record_content_sha256` İLE AYNI desen -- bu
        # sınıfın bir ALANI DEĞİLDİR, HER ZAMAN diğer tüm alanlardan
        # TÜRETİLİR (HATA 12N3-A4 section 15/23).
        return content_sha256(self.to_content_fields())

    def to_document_fields(self) -> dict:
        return {**self.to_content_fields(), "record_content_sha256": self.record_content_sha256}


# ---------------------------------------------------------------------------
# Saf manifest builder (HATA 12N3-A4 section 24-32, HATA 12N3-A5 section 28)
# ---------------------------------------------------------------------------


def build_session_manifest(
    *,
    protocol_version: str,
    T_session_date: str,
    protocol_sha256: str,
    freeze_manifest_sha256: str,
    frozen_symbols: Sequence[str],
    final_evaluations: Sequence[FinalEvaluation],
) -> TechnicalV1SessionManifest:
    """HATA 12N3A'nın saf manifest inşacısı.

    GÜVEN SINIRI (modül docstring'inde tam açıklanmıştır -- burada
    tekrarlanır): `final_evaluations`'daki her nesnenin ÜRETİM ortamında
    `TechnicalV1EvaluationRepository.get_verified()`'dan geçmiş GÜVENİLİR
    nesneler olması ÇAĞIRANIN sorumluluğudur. Bu fonksiyon Firestore'a
    HİÇ ERİŞMEZ ve saklanan ham hash'i YENİDEN DOĞRULAMAZ (yapısal olarak
    mümkün de değildir) -- yalnızca sağlanan nesneler ÜZERİNDE oturum-
    seviyesi küme/kimlik/sayım/hash tutarlılığını KURAR.
    """
    validated_symbols = validate_frozen_universe(frozen_symbols)
    expected_ids = derive_expected_evaluation_ids(protocol_version, T_session_date, validated_symbols)

    evaluations = list(final_evaluations)
    if len(evaluations) != EXPECTED_FROZEN_SYMBOL_COUNT:
        raise ValueError(
            f"final_evaluations tam olarak {EXPECTED_FROZEN_SYMBOL_COUNT} kayıt içermeli, "
            f"{len(evaluations)} bulundu -- denominator SESSİZCE küçültülemez/büyütülemez."
        )

    actual_ids = [evaluation.evaluation_id for evaluation in evaluations]
    if len(set(actual_ids)) != len(actual_ids):
        raise ValueError("final_evaluations içinde tekrar eden evaluation_id var -- SESSİZCE dedupe edilmez.")

    for evaluation in evaluations:
        if evaluation.protocol_version != protocol_version:
            raise ValueError(
                f"FinalEvaluation.protocol_version ({evaluation.protocol_version!r}) oturumun "
                f"protocol_version'ı ({protocol_version!r}) ile eşleşmiyor -- yanlış oturuma ait kayıt."
            )
        if evaluation.T_session_date != T_session_date:
            raise ValueError(
                f"FinalEvaluation.T_session_date ({evaluation.T_session_date!r}) oturumun "
                f"T_session_date'i ({T_session_date!r}) ile eşleşmiyor -- yanlış oturuma ait kayıt."
            )
        recomputed_id = compute_evaluation_id(evaluation.protocol_version, evaluation.T_session_date, evaluation.symbol)
        if recomputed_id != evaluation.evaluation_id:
            raise ValueError(
                f"FinalEvaluation.evaluation_id ({evaluation.evaluation_id}) kendi protocol_version/"
                f"T_session_date/symbol alanlarından bağımsız olarak yeniden hesaplanan "
                f"({recomputed_id}) ile eşleşmiyor."
            )

    if set(actual_ids) != set(expected_ids):
        missing = set(expected_ids) - set(actual_ids)
        foreign = set(actual_ids) - set(expected_ids)
        raise ValueError(
            "final_evaluations kümesi, frozen evrenden türetilen beklenen 100 evaluation_id kümesiyle "
            f"TAM OLARAK eşleşmiyor -- eksik={sorted(missing)!r} yabancı/beklenmeyen={sorted(foreign)!r}"
        )

    capture_status_counts = {key: 0 for key in _CAPTURE_STATUS_KEYS}
    evaluation_integrity_status_counts = {key: 0 for key in _EVALUATION_INTEGRITY_STATUS_KEYS}
    technical_observation_eligible_count = 0
    for evaluation in evaluations:
        capture_status_counts[evaluation.capture_status.value] += 1
        evaluation_integrity_status_counts[evaluation.evaluation_integrity_status.value] += 1
        if evaluation.technical_observation_eligible is True:
            technical_observation_eligible_count += 1

    valid_capture_count = capture_status_counts[CaptureStatus.VALID_CAPTURE_AVAILABLE.value]
    if technical_observation_eligible_count != valid_capture_count:
        raise ValueError(
            "sağlanan final_evaluations kendi içinde tutarsız: technical_observation_eligible=True "
            f"olan kayıt sayısı ({technical_observation_eligible_count}), "
            f"CaptureStatus.VALID_CAPTURE_AVAILABLE sayısıyla ({valid_capture_count}) eşleşmiyor -- "
            "bu ikisi mevcut selector semantiğinde HER ZAMAN eşit olmalıdır (bkz. "
            "final_evaluation_selector.py); bu, çağıranın verdiği nesnelerin bozuk/el-yapımı "
            "olduğuna işaret eder."
        )

    expected_evaluation_ids_sha256 = compute_expected_evaluation_ids_sha256(expected_ids)
    final_evaluation_records_sha256 = compute_final_evaluation_records_sha256(
        [(evaluation.evaluation_id, evaluation.record_content_sha256) for evaluation in evaluations]
    )
    session_id = compute_session_id(protocol_version, T_session_date)

    return TechnicalV1SessionManifest(
        manifest_schema_version=TECHNICAL_V1_SESSION_MANIFEST_SCHEMA_VERSION,
        session_id=session_id,
        protocol_version=protocol_version,
        T_session_date=T_session_date,
        protocol_sha256=protocol_sha256,
        freeze_manifest_sha256=freeze_manifest_sha256,
        expected_symbol_count=EXPECTED_FROZEN_SYMBOL_COUNT,
        expected_evaluation_ids_sha256=expected_evaluation_ids_sha256,
        final_evaluation_records_sha256=final_evaluation_records_sha256,
        capture_status_counts=capture_status_counts,
        evaluation_integrity_status_counts=evaluation_integrity_status_counts,
        technical_observation_eligible_count=technical_observation_eligible_count,
    )
