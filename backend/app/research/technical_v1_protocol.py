"""Technical V1 protokol belgesi -- doğrulanmış (verified) paketleme/yükleme
katmanı. HATA 12N3C2-E1-R1 / E1-R2.

`research/technical_v1_protocol_v1.json`'daki (artık `app/research/
resources/`'a taşınan) protokol, `technical_v1_freeze_manifest.json`'dan
AYRI, BAŞKA bir dondurulmuş bilimsel artefakttır -- kendi KENDİ kimlik
hash'ini (`protocol_sha256`) taşır, freeze manifest'in `freeze_manifest_
sha256`'sıyla KARIŞTIRILMAZ.

KİLİTLİ kimlik tanımı (HATA 12N3C2-E1-R1'de doğrulanan TARİHSEL algoritma):

    protocol_sha256 := content_sha256(parsed protokol JSON nesnesi)

AYNI, tek paylaşılan `app.research.canonical_hash.content_sha256`
primitive'i -- freeze manifest'in `load_verified_scoring_config_hash()`'i
İLE AYNI güven-zinciri deseni (`technical_v1_scoring_config_values.py`),
ama İKİ AYRI artefakt için İKİ AYRI, birbirinden bağımsız fonksiyon --
`protocol_sha256` `freeze_manifest_sha256`'nın YERİNE KULLANILMAZ.

ÖNEMLİ PROVENANCE SINIRI (HATA 12N3C2-E1-R1'de dürüstçe belgelendi): kilitli
`ee13afdde2a251bd86fc684e0786f01a9d0b12f7a52ebb2b7771693cb1d38f79` değeri
BU repodaki HİÇBİR commit'te/dosyada bir alan olarak YAZILI DEĞİLDİR
(kapsamlı bir `git log --all -S`/`git fsck`/tam çalışma-dizini araması BUNU
doğruladı) -- protokol dosyası `e925260e895651c9ad58b1bd4d3705747ded71ba`
commit'iyle oluşturulduktan SONRA HİÇ değiştirilmedi, ve GÜNCEL dosyanın
`content_sha256(parsed)`'i bu değeri TAM OLARAK yeniden üretir. Bu, önceki
bir konuşma turunda SÖZLÜ olarak hesaplanmış/paylaşılmış ama hiçbir zaman
bir dosyaya YAZILMAMIŞ bir değerdir -- freeze_manifest_sha256'nın aksine
(o, protokol JSON'unun KENDİ İÇİNDE `methodology_references.freeze_
manifest_sha256` olarak KAYITLIDIR).

KİLİTLİ güven zinciri (E1-R1 section 14/16/17, kısayol YOK):

    doğrulanmış TechnicalV1ActivationLock
    -> expected_protocol_sha256 = activation_lock.protocol_sha256
    -> paketlenmiş kanonik protokol JSON'u (bu modülün okuduğu)
    -> content_sha256(parsed JSON)
    -> eşitlik kontrolü (BAŞARISIZSA: HİÇBİR protokol alanı okunmaz/dönmez)
    -> protocol_version / universe.frozen_symbol_list çıkarımı + doğrulaması
    -> TrustedTechnicalV1Protocol.

Bu modül `TechnicalV1ActivationLockRepository`'yi HİÇ import/çağırmaz,
Firestore'a HİÇ dokunmaz, canlı BIST100/provider/ağ sorgusu YAPMAZ --
tek evren kaynağı, bu paketlenmiş dondurulmuş artefakttır.

ÖNEMLİ SINIR (E1-R1 section 27 ile aynı, dürüstçe tekrarlanır): bir
saldırgan/bozuk bir release süreci protokolü DEĞİŞTİRİP KENDİ değiştirdiği
içerikten DOĞRU şekilde yeniden hesaplanmış bir hash'i "expected" olarak
sağlarsa, bu fonksiyon TEK BAŞINA bunu tespit EDEMEZ. Gerçek yetkilendirme,
`expected_protocol_sha256`'nın BAĞIMSIZ OLARAK doğrulanmış bir
`TechnicalV1ActivationLock`'tan gelmesinden kaynaklanır -- bu, loader
sözleşmesinde bir GÜVENLİK AÇIĞI DEĞİLDİR, tasarımın kasıtlı sınırıdır.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.research.canonical_hash import content_sha256
from app.research.evidence_models import ProvenanceConflictError, validate_sha256_hex

# HATA 12N3C2-E1-R2: kanonik paketlenmiş dosya `backend/app/` AĞACININ
# İÇİNDE -- bu modülün KENDİ dizininin ("research/") bir alt dizini
# ("resources/") olarak (freeze manifest ile AYNI dizin, AYRI dosya).
# `__file__` kullanıldığından çağıranın CWD'sinden TAMAMEN BAĞIMSIZDIR.
_DEFAULT_PROTOCOL_PATH = Path(__file__).resolve().parent / "resources" / "technical_v1_protocol_v1.json"

_REQUIRED_FROZEN_SYMBOL_COUNT = 100


@dataclass(frozen=True)
class TrustedTechnicalV1Protocol:
    """Doğrulanmış protokol belgesinden çıkarılan, KÜÇÜK/dar, değişmez
    güvenilen sonuç. Bir `TechnicalV1ActivationLock` gibi ayrı bir kimlik
    hash'i TAŞIMAZ -- kendisi zaten `load_verified_technical_v1_protocol()`
    tarafından ÜRETİLDİĞİ an doğrulanmış olur (bkz. o fonksiyonun kendi
    kimlik-doğrulama adımı)."""

    protocol_sha256: str
    protocol_version: str
    frozen_symbol_list: tuple[str, ...]
    frozen_symbols: frozenset[str]


def _read_protocol_json(path: Path) -> dict:
    """ÖZEL/dahili yardımcı -- YALNIZCA dosyayı okur/JSON parse eder,
    HİÇBİR kimlik doğrulaması YAPMAZ. Bu modülün DIŞINA hiç export
    edilmez -- doğrulamayı atlayan bir "hızlı yol" olarak KULLANILAMAZ."""
    with path.open(encoding="utf-8") as f:
        raw_text = f.read()
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ProvenanceConflictError(f"Paketlenmiş protokol ({path}) geçerli JSON değil: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ProvenanceConflictError(
            f"Paketlenmiş protokol ({path}) üst-düzeyde bir JSON nesnesi (object) değil: "
            f"{type(parsed).__name__}"
        )
    return parsed


def _validate_non_empty_no_whitespace_str(value: object, field_name: str, path: Path) -> str:
    if not isinstance(value, str) or not value:
        raise ProvenanceConflictError(f"Paketlenmiş protokol ({path}): '{field_name}' boş olmayan bir string olmalı: {value!r}")
    if value != value.strip():
        raise ProvenanceConflictError(
            f"Paketlenmiş protokol ({path}): '{field_name}' baştaki/sondaki boşluk içeremez: {value!r}"
        )
    return value


def _validate_frozen_symbol_list(parsed: dict, path: Path) -> tuple[str, ...]:
    """Section 17/18/19/20 -- katı, ONARIMSIZ doğrulama. Geçersiz bir
    kanonik protokol yapısı YÜKSEK SESLE başarısız olur; hiçbir girdi
    strip/upper/".IS" temizleme/tekilleştirme YOLUYLA "düzeltilmez"."""
    universe = parsed.get("universe")
    if not isinstance(universe, dict):
        raise ProvenanceConflictError(
            f"Paketlenmiş protokol ({path}): 'universe' eksik ya da bir JSON nesnesi değil: {universe!r}"
        )

    frozen_symbol_list = universe.get("frozen_symbol_list")
    if not isinstance(frozen_symbol_list, list):
        raise ProvenanceConflictError(
            f"Paketlenmiş protokol ({path}): 'universe.frozen_symbol_list' eksik ya da bir JSON "
            f"listesi değil: {frozen_symbol_list!r}"
        )

    if len(frozen_symbol_list) != _REQUIRED_FROZEN_SYMBOL_COUNT:
        raise ProvenanceConflictError(
            f"Paketlenmiş protokol ({path}): 'universe.frozen_symbol_list' tam olarak "
            f"{_REQUIRED_FROZEN_SYMBOL_COUNT} eleman içermeli, {len(frozen_symbol_list)} bulundu."
        )

    for index, symbol in enumerate(frozen_symbol_list):
        if not isinstance(symbol, str) or not symbol:
            raise ProvenanceConflictError(
                f"Paketlenmiş protokol ({path}): frozen_symbol_list[{index}] boş olmayan bir string "
                f"olmalı: {symbol!r}"
            )
        if symbol != symbol.strip():
            raise ProvenanceConflictError(
                f"Paketlenmiş protokol ({path}): frozen_symbol_list[{index}] baştaki/sondaki boşluk "
                f"içeremez: {symbol!r}"
            )
        if symbol != symbol.upper():
            raise ProvenanceConflictError(
                f"Paketlenmiş protokol ({path}): frozen_symbol_list[{index}] kanonik büyük-harf "
                f"formatında değil: {symbol!r}"
            )
        if "." in symbol:
            raise ProvenanceConflictError(
                f"Paketlenmiş protokol ({path}): frozen_symbol_list[{index}] '.' karakteri içeremez "
                f"(bare BIST ticker bekleniyor, provider-suffix YOK): {symbol!r}"
            )

    if len(set(frozen_symbol_list)) != _REQUIRED_FROZEN_SYMBOL_COUNT:
        raise ProvenanceConflictError(
            f"Paketlenmiş protokol ({path}): frozen_symbol_list içinde yinelenen (duplicate) "
            f"sembol(ler) var -- {len(frozen_symbol_list)} eleman, yalnızca "
            f"{len(set(frozen_symbol_list))} benzersiz."
        )

    # Section 21: mevcutsa saklanan yapısal-kontrol alanlarıyla ek çapraz
    # kontrol -- ALANLAR YOKSA İCAT EDİLMEZ, yalnızca VARSA doğrulanır.
    constituent_count = universe.get("constituent_count")
    if isinstance(constituent_count, int) and constituent_count != len(frozen_symbol_list):
        raise ProvenanceConflictError(
            f"Paketlenmiş protokol ({path}): 'universe.constituent_count' ({constituent_count}) "
            f"gerçek frozen_symbol_list uzunluğuyla ({len(frozen_symbol_list)}) eşleşmiyor."
        )
    unique_ticker_count = universe.get("unique_ticker_count")
    if isinstance(unique_ticker_count, int) and unique_ticker_count != len(set(frozen_symbol_list)):
        raise ProvenanceConflictError(
            f"Paketlenmiş protokol ({path}): 'universe.unique_ticker_count' ({unique_ticker_count}) "
            f"gerçek benzersiz sembol sayısıyla ({len(set(frozen_symbol_list))}) eşleşmiyor."
        )

    return tuple(frozen_symbol_list)


def load_verified_technical_v1_protocol(
    expected_protocol_sha256: str, protocol_path: Path | None = None
) -> TrustedTechnicalV1Protocol:
    """Paketlenmiş protokolün KENDİ kimliğini doğrulamadan HİÇBİR alanı
    ASLA döndürmeyen, TEK güvenilen genel API.

    Kesin sıra (HATA 12N3C2-E1-R2 section 13, atlanamaz):
      1. `expected_protocol_sha256` kanonik (64 küçük-harf hex) mi?
         (çağıranın kendi hatası -- hiçbir I/O yapılmadan, yerel olarak
         `EvidenceIntegrityError` fırlatılır.)
      2. dosya okunur/JSON parse edilir (`_read_protocol_json`).
      3. `content_sha256(parsed)` `expected_protocol_sha256` ile TAM
         eşleşiyor mu? EŞLEŞMİYORSA: `ProvenanceConflictError` -- HİÇBİR
         protokol alanı OKUNMAZ/DÖNDÜRÜLMEZ.
      4. YALNIZCA kimlik doğrulaması geçtikten SONRA `protocol_version` ve
         `universe.frozen_symbol_list` çıkarılır/doğrulanır.

    Format/girinti/anahtar sırası/satır-sonu farkları SONUCU DEĞİŞTİRMEZ --
    `content_sha256` HER ZAMAN parse edilmiş Python nesnesi üzerinden,
    kanonik olarak yeniden hesaplar (ham dosya baytları ÜZERİNDEN DEĞİL)."""
    validate_sha256_hex(expected_protocol_sha256)

    path = protocol_path if protocol_path is not None else _DEFAULT_PROTOCOL_PATH
    parsed = _read_protocol_json(path)

    actual_protocol_sha256 = content_sha256(parsed)
    if actual_protocol_sha256 != expected_protocol_sha256:
        raise ProvenanceConflictError(
            f"Paketlenmiş protokol ({path}) kimliği beklenenle eşleşmiyor -- "
            f"actual={actual_protocol_sha256}, expected={expected_protocol_sha256}. "
            f"Bu artefakt GÜVENİLMEDİ -- hiçbir protokol alanı okunmadı."
        )

    protocol_version = _validate_non_empty_no_whitespace_str(
        parsed.get("protocol_version"), "protocol_version", path
    )
    frozen_symbol_list = _validate_frozen_symbol_list(parsed, path)

    return TrustedTechnicalV1Protocol(
        protocol_sha256=actual_protocol_sha256,
        protocol_version=protocol_version,
        frozen_symbol_list=frozen_symbol_list,
        frozen_symbols=frozenset(frozen_symbol_list),
    )
