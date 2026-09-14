"""HATA 12N2A — Technical V1 kanonik `evaluation_id`/`attempt_id` kimlik
hesaplayıcıları.

İki kimlik de HATA 12O/12Q'da kilitlenen kontratı izler: fiziksel kimlik
(Firestore doküman ID'si) mantıksal kimlik nesnesinin (dict) kanonik JSON
SHA-256'sıdır -- string concatenation ("|" ile birleştirme) ASLA
KULLANILMAZ (ayrım belirsizliği riski taşır, bkz. HATA 12O section 6).

`evaluation_id`'in mantıksal kimliği TAM OLARAK üç alandır:
    {protocol_version, T_session_date, symbol}
`attempt_number`/kullanıcı/runtime/zaman damgası bu kimliğe KATILMAZ --
aynı sembol-seans-protokol için EN FAZLA bir formal evaluation olmasını
GARANTİ ETMEK içindir (HATA 12O section 6).

`attempt_id`'in mantıksal kimliği:
    {evaluation_id, attempt_number}
"""

from __future__ import annotations

import re
from datetime import date

from app.research.canonical_hash import content_sha256
from app.research.evidence_models import validate_sha256_hex

_CANONICAL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ALLOWED_ATTEMPT_NUMBERS: tuple[int, ...] = (1, 2)


def _validate_canonical_date(t_session_date: str) -> None:
    """HATA 12M-R2'de kilitlenen AYNI iki-katmanlı sıkı doğrulama deseni
    (regex tam-eşleşme + self-round-trip) -- `date.fromisoformat()`'ın tek
    başına kabul ettiği daha geniş lehçeleri (kompakt "YYYYMMDD", ISO
    hafta-tarihi vb.) reddeder."""
    if not isinstance(t_session_date, str) or not _CANONICAL_DATE_RE.match(t_session_date):
        raise ValueError(f"T_session_date kanonik lehçede değil (YYYY-MM-DD bekleniyor): {t_session_date!r}")
    try:
        parsed = date.fromisoformat(t_session_date)
    except ValueError as exc:
        raise ValueError(f"T_session_date geçersiz takvim tarihi: {t_session_date!r}") from exc
    if parsed.isoformat() != t_session_date:
        raise ValueError(f"T_session_date kanonik round-trip'i sağlamıyor: {t_session_date!r}")


def _validate_non_empty_str(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} boş olmayan bir string olmalı: {value!r}")


def compute_evaluation_id(protocol_version: str, t_session_date: str, symbol: str) -> str:
    """Fiziksel `evaluation_id` -- `{protocol_version, T_session_date,
    symbol}` kanonik kimlik nesnesinin SHA-256'sı, 64 küçük-harf hex
    karakter. Girdiler hash'lenmeden ÖNCE doğrulanır -- kanonik olmayan bir
    tarih/boş bir string sessizce hash'lenmez, `ValueError` fırlatılır."""
    _validate_non_empty_str(protocol_version, "protocol_version")
    _validate_canonical_date(t_session_date)
    _validate_non_empty_str(symbol, "symbol")

    identity = {
        "protocol_version": protocol_version,
        "T_session_date": t_session_date,
        "symbol": symbol,
    }
    return content_sha256(identity)


def compute_session_id(protocol_version: str, t_session_date: str) -> str:
    """HATA 12N3A — fiziksel `session_id` -- `{protocol_version,
    T_session_date}` kanonik kimlik nesnesinin SHA-256'sı, 64 küçük-harf
    hex karakter. `evaluation_id`'in AYNI iki alanını paylaşır ama
    KASITLI OLARAK `symbol`'ü İÇERMEZ -- bir seans, frozen evrendeki
    TÜM sembolleri kapsar, tek bir sembole ait DEĞİLDİR. `attempt_number`/
    kullanıcı/runtime/zaman damgası/scheduler execution ID de KATILMAZ --
    fiziksel kimlik yalnızca mantıksal kimlikten türer (HATA 12O/12Q)."""
    _validate_non_empty_str(protocol_version, "protocol_version")
    _validate_canonical_date(t_session_date)

    identity = {
        "protocol_version": protocol_version,
        "T_session_date": t_session_date,
    }
    return content_sha256(identity)


def compute_attempt_id(evaluation_id: str, attempt_number: int) -> str:
    """Fiziksel `attempt_id` -- `{evaluation_id, attempt_number}` kanonik
    kimlik nesnesinin SHA-256'sı. `attempt_number` yalnızca 1 veya 2
    olabilir (HATA 12L'nin kilitlenen iki-yuvalı deneme çizelgesi) --
    string concatenation KULLANILMAZ."""
    validate_sha256_hex(evaluation_id)
    # `bool`, Python'da `int`'in bir alt sınıfıdır (`isinstance(True, int)
    # is True`) -- `attempt_number` KASITLI OLARAK tam bir `int` (bool
    # DEĞİL) olmalı; `1.0` gibi bir float da `1 == 1.0` sayısal eşitliği
    # yüzünden `in` kontrolünden SESSİZCE geçebilirdi -- kimlik girdisi
    # kesin TİP eşleşmesi ister, yalnızca sayısal değer eşitliği YETERSİZ.
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int) or attempt_number not in ALLOWED_ATTEMPT_NUMBERS:
        raise ValueError(f"attempt_number yalnızca {ALLOWED_ATTEMPT_NUMBERS} (int) olabilir: {attempt_number!r}")

    identity = {
        "evaluation_id": evaluation_id,
        "attempt_number": attempt_number,
    }
    return content_sha256(identity)
