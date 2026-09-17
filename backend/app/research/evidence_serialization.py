"""Deterministik evidence serileştirme/hashleme çekirdeği — HATA 12K/12L/12M.

Bu modül, Technical V1 prospective validation protokolünün (bkz.
`app/research/resources/technical_v1_protocol_v1.json`) kanıt-doğruluğu sözleşmesini
uygular: bir değerlendirmenin (evaluation) kullandığı GİRDİ (asset OHLCV +
benchmark kapanış serisi) ve ürettiği ÇIKTI (`TechnicalAnalysis`), ileride
BAĞIMSIZ olarak yeniden hesaplanıp bire bir doğrulanabilsin diye
kayıp-sız, deterministik bir biçimde parmak izine (SHA-256) dönüştürülür.

Kilitli sözleşmeler (HATA 12K'de önerilip HATA 12L'de kesinleşti):
  - float64 alanlar (Open/High/Low/Close, benchmark close) ->
    `{"dtype": "float64", "bits": struct.pack(">d", value).hex()}` --
    IEEE-754 binary64 ham bit-paterni (16 küçük-harf hex karakter),
    +0.0/-0.0/NaN/+Inf/-Inf'i AYRIM KAYBI OLMADAN temsil eder.
  - int64 alanlar (Volume) -> `{"dtype": "int64", "value": "<taban-10
    string>"}` -- ASLA float'a cast edilmez.
  - `None`/eksik metodoloji değerleri -> JSON `null` -- ASLA bir float
    bit-paternine dönüştürülmez (None, "hesaplanmadı" demektir; NaN ise
    GERÇEK, ölçülmüş bir float64 sonucudur -- HATA 5B1/12K, ikisi
    KARIŞTIRILMAZ).

Bu modül HİÇBİR ağ isteği / Firestore okuma-yazma / dosya-sistemi yan
etkisi yapmaz -- yalnızca zaten materyalize edilmiş, çağıran tarafından
verilen veri yapılarını (DataFrame/Series/Pydantic model) işler.
"""

from __future__ import annotations

import hashlib
import re
import struct
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.models.technical_analysis import TechnicalAnalysis
from app.research.canonical_hash import canonical_document_bytes, content_sha256
from app.research.evidence_models import validate_sha256_hex

REQUIRED_ASSET_COLUMNS: tuple[str, ...] = ("Open", "High", "Low", "Close", "Volume")
_FLOAT_ASSET_COLUMNS: tuple[str, ...] = ("Open", "High", "Low", "Close")
_INT_ASSET_COLUMNS: tuple[str, ...] = ("Volume",)

_ASSET_CANONICAL_TZ = "Europe/Istanbul"
_ASSET_CANONICAL_UTCOFFSET = timedelta(hours=3)
_HEX16_RE = re.compile(r"^[0-9a-f]{16}$")
_INT64_STRING_RE = re.compile(r"^-?(0|[1-9][0-9]*)$")
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
# HATA 12M-R2: `date.fromisoformat()`/`datetime.fromisoformat()` (Python
# 3.11+) KASITLI OLARAK cok daha genis bir ISO-8601 lehcesi kabul eder
# (kompakt "YYYYMMDD", ISO hafta-tarihi "YYYY-Www-D", offset'siz virgul/
# saniyeli varyantlar, vb.) -- bunlar `serialize_*_snapshot()`'ın ÜRETTİĞİ
# TEK kanonik lehçe DEĞİLDİR. Bu yüzden çözümleme İKİ katmanlıdır: (1) HAM
# string, `serialize_*_snapshot()`'ın kendi ürettiği TAM lehçeyle eşleşen
# bir regex'ten GEÇMELİ, (2) çözümlenen değerin `.isoformat()`'ı HAM string'e
# TAM olarak GERİ dönmeli (self-round-trip) -- bu, regex'in kaçırabileceği
# (ör. offset saniyeleri, boşluk yerine "T") artık lehçeleri de yakalar.
# Asset tarafında AYRICA `utcoffset() == +03:00` zorunludur -- aksi halde
# "2026-09-07T21:00:00+00:00" gibi GEÇERLİ ama YANLIŞ-OFSETLİ bir string,
# kendi kendine round-trip eder (kendi offset'iyle tutarlıdır) ve bu ikinci
# kontrol OLMADAN sessizce `tz_convert()` ile Europe/Istanbul'a "onarılırdı"
# -- bozuk/kanonik-olmayan evidence SESSİZCE NORMALİZE EDİLMEZ, FAIL FAST olur.
_BENCHMARK_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ASSET_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?[+-]\d{2}:\d{2}$")


def _sha256_of_bytes(raw: bytes) -> str:
    """HATA 12N2A-F: bu, `json.dumps` KANONİKLEŞTİRMESİNİN bir kopyası
    DEĞİLDİR -- yalnızca ZATEN kanonik/depolama-kimliği olan HAM baytları
    hash'ler. Kanonik JSON üretiminin TEK, paylaşılan implementasyonu
    `canonical_hash.py`'dedir (`canonical_document_bytes`/`content_sha256`)
    -- bu modül kendi ikinci bir `json.dumps(sort_keys=True, ...)`
    algoritmasını ASLA yeniden yazmaz."""
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Sayısal değer kodlayıcıları
# ---------------------------------------------------------------------------


def serialize_float64(value: float) -> dict:
    """IEEE-754 binary64 ham bit-paterni. `struct.pack` hiçbir özel float
    değerini (NaN/±Inf/±0.0 dahil) reddetmez -- hepsi ayrım kaybı olmadan
    temsil edilir."""
    return {"dtype": "float64", "bits": struct.pack(">d", float(value)).hex()}


def serialize_int64(value: int) -> dict:
    """Volume gibi tam sayı alanları için -- ASLA float'a cast edilmeden,
    tam taban-10 string olarak saklanır."""
    return {"dtype": "int64", "value": str(int(value))}


def serialize_optional_float64(value: float | None) -> dict | None:
    """`None` -> JSON `null` (ASLA bir bit-paternine dönüştürülmez);
    aksi halde `serialize_float64()`."""
    if value is None:
        return None
    return serialize_float64(value)


def deserialize_float64(encoded: dict) -> float:
    """`serialize_float64()`'ün TERSİ -- ham IEEE-754 binary64 baytlarını
    doğrudan `struct.unpack` ile çözer. ONDALIK PARSE/YUVARLAMA/NORMALİZASYON
    YOK -- bit-pattern serialize edildiği ANDAKİ gibi birebir geri döner
    (NaN/±Inf/±0.0 dahil, `struct` seviyesinde herhangi bir kanonikleştirme
    yapmaz).

    Fail-fast: `dtype` "float64" değilse, `bits` tam olarak 16 küçük-harf
    hex karakter değilse, veya geçersiz hex ise `ValueError` -- bozuk
    evidence SESSİZCE "onarılmaz", görünür şekilde reddedilir.
    """
    if not isinstance(encoded, dict) or set(encoded.keys()) != {"dtype", "bits"}:
        raise ValueError(f"Beklenmeyen float64 kodlama yapısı: {encoded!r}")
    if encoded["dtype"] != "float64":
        raise ValueError(f"Beklenmeyen dtype etiketi: {encoded['dtype']!r}, beklenen 'float64'")
    bits = encoded["bits"]
    if not isinstance(bits, str) or not _HEX16_RE.match(bits):
        raise ValueError(f"'bits' tam olarak 16 küçük-harf hex karakter değil: {bits!r}")
    return struct.unpack(">d", bytes.fromhex(bits))[0]


def deserialize_int64(encoded: dict) -> int:
    """`serialize_int64()`'ün TERSİ -- taban-10 string'i doğrudan `int()`
    ile çözer, HİÇBİR float ara adımı YOK. Fail-fast: `dtype` "int64"
    değilse, `value` kanonik taban-10 tam sayı formatında değilse (önde
    sıfır/`+` işareti YOK -- `serialize_int64()`'ün ÜRETTİĞİ TEK format),
    veya int64 aralığının ([-2**63, 2**63-1]) dışındaysa `ValueError`.
    """
    if not isinstance(encoded, dict) or set(encoded.keys()) != {"dtype", "value"}:
        raise ValueError(f"Beklenmeyen int64 kodlama yapısı: {encoded!r}")
    if encoded["dtype"] != "int64":
        raise ValueError(f"Beklenmeyen dtype etiketi: {encoded['dtype']!r}, beklenen 'int64'")
    value_str = encoded["value"]
    if not isinstance(value_str, str) or not _INT64_STRING_RE.match(value_str):
        raise ValueError(f"'value' kanonik taban-10 tam sayı string'i değil: {value_str!r}")
    parsed = int(value_str)
    if not (_INT64_MIN <= parsed <= _INT64_MAX):
        raise ValueError(f"int64 aralığı dışında: {parsed}")
    return parsed


def deserialize_optional_float64(encoded: dict | None) -> float | None:
    """`None`/JSON `null` -> `None`; aksi halde `deserialize_float64()`."""
    if encoded is None:
        return None
    return deserialize_float64(encoded)


# ---------------------------------------------------------------------------
# Asset (OHLCV) girdi anlık-görüntüsü
# ---------------------------------------------------------------------------


def serialize_asset_snapshot(df: pd.DataFrame, symbol: str) -> dict:
    """Zaten materyalize edilmiş kanonik bir OHLCV dataframe'ini (HATA 12L
    ile ampirik doğrulanmış şema: kolonlar TAM OLARAK ["Open","High","Low",
    "Close","Volume"], Open/High/Low/Close=float64, Volume=int64, tz-aware
    Europe/Istanbul index, kesin artan/benzersiz satır sırası) evidence
    kaydı için deterministik, JSON-serileştirilebilir bir sözlüğe çevirir.

    Fail-fast: şema beklenenden SAPARSA (eksik/fazla/yanlış sıralı kolon,
    yanlış dtype, artan olmayan/yinelenen index) evidence YANLIŞ bir girdi
    kanıtı taşımasın diye burada `ValueError` fırlatılır -- sessizce
    coerce/cast YAPILMAZ.

    Not: `DataFrame.iterrows()`/`to_dict(orient="records")` KASITLI OLARAK
    kullanılmaz -- karışık dtype'lı (float64 + int64) bir satırı bir
    `Series`'e paketlemek pandas'ta örtük upcast riski taşır (Volume'un
    sessizce float'a dönmesi). Bunun yerine her kolon KENDİ dtype'ıyla
    ayrı ayrı numpy dizisine çevrilip pozisyona göre eşlenir.
    """
    if list(df.columns) != list(REQUIRED_ASSET_COLUMNS):
        raise ValueError(
            f"Beklenmeyen asset dataframe kolon seti/sırası: {list(df.columns)!r}, "
            f"beklenen {list(REQUIRED_ASSET_COLUMNS)!r}"
        )
    if len(df) == 0:
        raise ValueError("Asset dataframe boş -- evidence anlık-görüntüsü üretilemez")
    if not df.index.is_monotonic_increasing or not df.index.is_unique:
        raise ValueError("Asset dataframe index'i kesin artan sırada/benzersiz değil")
    for col in _FLOAT_ASSET_COLUMNS:
        if df[col].dtype != np.float64:
            raise ValueError(f"Asset kolonu {col!r} float64 değil: {df[col].dtype}")
    for col in _INT_ASSET_COLUMNS:
        if df[col].dtype != np.int64:
            raise ValueError(f"Asset kolonu {col!r} int64 değil: {df[col].dtype}")

    index_values = df.index.to_pydatetime()
    open_vals = df["Open"].to_numpy(dtype=np.float64)
    high_vals = df["High"].to_numpy(dtype=np.float64)
    low_vals = df["Low"].to_numpy(dtype=np.float64)
    close_vals = df["Close"].to_numpy(dtype=np.float64)
    volume_vals = df["Volume"].to_numpy(dtype=np.int64)

    rows = [
        {
            "session_timestamp": index_values[i].isoformat(),
            "Open": serialize_float64(open_vals[i]),
            "High": serialize_float64(high_vals[i]),
            "Low": serialize_float64(low_vals[i]),
            "Close": serialize_float64(close_vals[i]),
            "Volume": serialize_int64(volume_vals[i]),
        }
        for i in range(len(df))
    ]
    return {"symbol": symbol, "rows": rows}


def asset_snapshot_bytes(df: pd.DataFrame, symbol: str) -> bytes:
    """HATA 12N1: bu asset anlık-görüntüsü için GCS'e yüklenecek TEK,
    kanonik bayt dizisi -- `asset_input_sha256()` BUNUN ÜZERİNDEN
    hesaplanır (bkz. aşağı), ayrı bir "depolama temsili" YOKTUR."""
    return canonical_document_bytes(serialize_asset_snapshot(df, symbol))


def asset_input_sha256(df: pd.DataFrame, symbol: str) -> str:
    return _sha256_of_bytes(asset_snapshot_bytes(df, symbol))


def deserialize_asset_snapshot(snapshot: dict) -> tuple[pd.DataFrame, str]:
    """`serialize_asset_snapshot()`'ın TERSİ -- saklanmış kanonik evidence'tan
    motorun (`compute_technical_analysis()`) doğrudan tükettiği ŞEMAYI
    (kolonlar TAM OLARAK Open/High/Low/Close/Volume, Open/High/Low/Close=
    float64, Volume=int64 -- ASLA float üzerinden değil) ve `symbol`'ü
    yeniden kurar.

    Zaman damgası semantiği: her `session_timestamp` tz-aware bir ISO-8601
    string olarak çözülür (naive/timezone'suz bir değer KABUL EDİLMEZ), sonra
    `Europe/Istanbul` isimli IANA bölgesine `tz_convert` edilir -- Türkiye'nin
    2016'dan beri DST uygulamadığı sabit +03:00 kaymasını KORUYARAK, motorun
    ürettiği index'le AYNI isimlendirilmiş bölge kimliğine döner (yalnızca
    ham bir `datetime.timezone(timedelta(hours=3))` sabit-ofset nesnesinde
    KALMAZ). Bu bir "saatlik dilim düşürme"/"yerel makine saatine çevirme"
    DEĞİLDİR -- AYNI ana (instant) işaret eden, isimlendirilmiş bir bölge
    kimliğine normalize etmektir; `.isoformat()` çıktısı (dolayısıyla
    yeniden serialize edilen bit-pattern) DEĞİŞMEZ.

    Fail-fast: şema/sıra/dtype/sıralama beklenenden SAPARSA `ValueError` --
    bozuk evidence sessizce "onarılmaz".
    """
    if not isinstance(snapshot, dict) or set(snapshot.keys()) != {"symbol", "rows"}:
        bad = snapshot if not isinstance(snapshot, dict) else set(snapshot.keys())
        raise ValueError(f"Beklenmeyen asset snapshot yapısı (üst seviye anahtarlar): {bad!r}")
    symbol = snapshot["symbol"]
    if not isinstance(symbol, str) or not symbol:
        raise ValueError(f"'symbol' boş olmayan bir string değil: {symbol!r}")
    rows = snapshot["rows"]
    if not isinstance(rows, list) or len(rows) == 0:
        raise ValueError("'rows' boş veya liste değil -- asset dataframe boş olamaz")

    required_row_keys = {"session_timestamp", "Open", "High", "Low", "Close", "Volume"}
    timestamps: list[datetime] = []
    open_vals: list[float] = []
    high_vals: list[float] = []
    low_vals: list[float] = []
    close_vals: list[float] = []
    volume_vals: list[int] = []

    for i, row in enumerate(rows):
        if not isinstance(row, dict) or set(row.keys()) != required_row_keys:
            bad_row = row if not isinstance(row, dict) else set(row.keys())
            raise ValueError(f"Satır {i}: beklenmeyen anahtar seti: {bad_row!r}")
        ts_raw = row["session_timestamp"]
        if not isinstance(ts_raw, str):
            raise ValueError(f"Satır {i}: 'session_timestamp' bir string değil: {ts_raw!r}")
        if not _ASSET_TIMESTAMP_RE.match(ts_raw):
            raise ValueError(
                f"Satır {i}: 'session_timestamp' kanonik lehçede değil (YYYY-MM-DDTHH:MM:SS[+-]HH:MM bekleniyor): {ts_raw!r}"
            )
        try:
            ts = datetime.fromisoformat(ts_raw)
        except ValueError as exc:
            raise ValueError(f"Satır {i}: 'session_timestamp' geçersiz ISO-8601: {ts_raw!r}") from exc
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise ValueError(f"Satır {i}: 'session_timestamp' tz-aware değil (naive): {ts_raw!r}")
        if ts.isoformat() != ts_raw:
            # HATA 12M-R2: regex'in kaçırabileceği (offset saniyeleri, "T"
            # yerine boşluk gibi) kalan lehçe farklarını yakalayan self-
            # round-trip guard'ı.
            raise ValueError(f"Satır {i}: 'session_timestamp' kanonik round-trip'i sağlamıyor: {ts_raw!r}")
        if ts.utcoffset() != _ASSET_CANONICAL_UTCOFFSET:
            # GEÇERLİ ama YANLIŞ-OFSETLİ bir zaman damgası (ör. aynı ana
            # işaret eden "+00:00" varyantı) kendi kendine round-trip
            # EDEBİLİR -- bu satır, böyle bir değerin `tz_convert()` ile
            # SESSİZCE Europe/Istanbul'a "onarılmasını" önler.
            raise ValueError(
                f"Satır {i}: 'session_timestamp' beklenen +03:00 (Europe/Istanbul) ofsetinde değil: {ts_raw!r}"
            )
        timestamps.append(ts)
        open_vals.append(deserialize_float64(row["Open"]))
        high_vals.append(deserialize_float64(row["High"]))
        low_vals.append(deserialize_float64(row["Low"]))
        close_vals.append(deserialize_float64(row["Close"]))
        volume_vals.append(deserialize_int64(row["Volume"]))

    index = pd.DatetimeIndex(timestamps).tz_convert(_ASSET_CANONICAL_TZ)
    df = pd.DataFrame(
        {
            "Open": np.array(open_vals, dtype=np.float64),
            "High": np.array(high_vals, dtype=np.float64),
            "Low": np.array(low_vals, dtype=np.float64),
            "Close": np.array(close_vals, dtype=np.float64),
            "Volume": np.array(volume_vals, dtype=np.int64),
        },
        index=index,
    )
    if not df.index.is_monotonic_increasing or not df.index.is_unique:
        raise ValueError("Yeniden kurulan asset dataframe index'i kesin artan sırada/benzersiz değil")
    if list(df.columns) != list(REQUIRED_ASSET_COLUMNS):
        raise ValueError(f"Yeniden kurulan asset dataframe kolon sırası bozuk: {list(df.columns)!r}")

    return df, symbol


# ---------------------------------------------------------------------------
# Benchmark (XU100) girdi anlık-görüntüsü
# ---------------------------------------------------------------------------


def serialize_benchmark_snapshot(series: pd.Series) -> dict:
    """Zaten materyalize edilmiş benchmark kapanış serisini (index=plain
    `datetime.date`, no tz; value=float64 -- bkz. `benchmark_service.py`
    `_to_date_indexed_series()`) deterministik bir sözlüğe çevirir.

    Fail-fast aynı şekilde geçerlidir: yanlış dtype, artan olmayan/yinelenen
    index, veya `datetime.date` yerine tz-aware/`datetime.datetime` bir
    index elemanı (`datetime`, `date`'in alt sınıfıdır -- bu yüzden
    `isinstance(x, date)` tek başına YETERSİZ, `datetime` örnekleri açıkça
    reddedilir) `ValueError` ile durur.
    """
    if series.dtype != np.float64:
        raise ValueError(f"Benchmark serisi float64 değil: {series.dtype}")
    if len(series) == 0:
        raise ValueError("Benchmark serisi boş -- evidence anlık-görüntüsü üretilemez")

    index_list = list(series.index)
    if index_list != sorted(index_list):
        raise ValueError("Benchmark serisi index'i artan sırada değil")
    if len(set(index_list)) != len(index_list):
        raise ValueError("Benchmark serisi index'inde yinelenen tarih var")

    rows = []
    for date_key in index_list:
        if not isinstance(date_key, date) or isinstance(date_key, datetime):
            raise ValueError(f"Benchmark index elemanı plain datetime.date değil: {type(date_key)!r}")
        rows.append(
            {
                "session_date": date_key.isoformat(),
                "close": serialize_float64(series[date_key]),
            }
        )
    return {"rows": rows}


def benchmark_snapshot_bytes(series: pd.Series) -> bytes:
    """HATA 12N1: bu benchmark anlık-görüntüsü için GCS'e yüklenecek TEK,
    kanonik bayt dizisi -- `benchmark_input_sha256()` BUNUN ÜZERİNDEN
    hesaplanır."""
    return canonical_document_bytes(serialize_benchmark_snapshot(series))


def benchmark_input_sha256(series: pd.Series) -> str:
    return _sha256_of_bytes(benchmark_snapshot_bytes(series))


def deserialize_benchmark_snapshot(snapshot: dict) -> pd.Series:
    """`serialize_benchmark_snapshot()`'ın TERSİ -- `compute_technical_
    analysis()`'in `benchmark_close_series` parametresinin beklediği TAM
    nesneyi (index=plain `datetime.date`, TZ-AWARE Timestamp DEĞİL; value=
    float64) yeniden kurar. `date.fromisoformat()` YALNIZCA "YYYY-MM-DD"
    kabul eder -- bir zaman bileşeni/tz-offset içeren bir string burada
    otomatik olarak REDDEDİLİR (bozuk/yanlış-şema bir "benchmark tarihi").

    Fail-fast aynı şekilde geçerlidir: şema/sıra/dtype/sıralama beklenenden
    SAPARSA `ValueError`.
    """
    if not isinstance(snapshot, dict) or set(snapshot.keys()) != {"rows"}:
        bad = snapshot if not isinstance(snapshot, dict) else set(snapshot.keys())
        raise ValueError(f"Beklenmeyen benchmark snapshot yapısı (üst seviye anahtarlar): {bad!r}")
    rows = snapshot["rows"]
    if not isinstance(rows, list) or len(rows) == 0:
        raise ValueError("'rows' boş veya liste değil -- benchmark serisi boş olamaz")

    required_row_keys = {"session_date", "close"}
    dates: list[date] = []
    closes: list[float] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or set(row.keys()) != required_row_keys:
            bad_row = row if not isinstance(row, dict) else set(row.keys())
            raise ValueError(f"Satır {i}: beklenmeyen anahtar seti: {bad_row!r}")
        date_raw = row["session_date"]
        if not isinstance(date_raw, str):
            raise ValueError(f"Satır {i}: 'session_date' bir string değil: {date_raw!r}")
        if not _BENCHMARK_DATE_RE.match(date_raw):
            # `date.fromisoformat()` (Python 3.11+) KOMPAKT "YYYYMMDD" ve ISO
            # hafta-tarihi "YYYY-Www-D" formlarını da kabul eder -- bunlar
            # `serialize_benchmark_snapshot()`'ın ÜRETMEDİĞİ lehçelerdir,
            # burada erken ve AÇIKÇA reddedilir (fromisoformat'a hiç ulaşmaz).
            raise ValueError(f"Satır {i}: 'session_date' kanonik lehçede değil (YYYY-MM-DD bekleniyor): {date_raw!r}")
        try:
            session_date = date.fromisoformat(date_raw)
        except ValueError as exc:
            raise ValueError(f"Satır {i}: 'session_date' geçersiz (yalnızca YYYY-MM-DD kabul edilir): {date_raw!r}") from exc
        if session_date.isoformat() != date_raw:
            raise ValueError(f"Satır {i}: 'session_date' kanonik round-trip'i sağlamıyor: {date_raw!r}")
        dates.append(session_date)
        closes.append(deserialize_float64(row["close"]))

    series = pd.Series(closes, index=dates, dtype=np.float64)
    index_list = list(series.index)
    if index_list != sorted(index_list):
        raise ValueError("Yeniden kurulan benchmark serisi index'i artan sırada değil")
    if len(set(index_list)) != len(index_list):
        raise ValueError("Yeniden kurulan benchmark serisi index'inde yinelenen tarih var")

    return series


def input_snapshot_sha256_from_hashes(asset_input_sha256_value: str, benchmark_input_sha256_value: str) -> str:
    """HATA 12N2A: `input_snapshot_sha256()`'ın ZATEN HESAPLANMIŞ asset/
    benchmark hash'lerinden çalışan TEK, paylaşılan birleştirici (combinator)
    implementasyonu -- örneğin bir repository, ham `df`/`series` nesnelerini
    DEĞİL, önceden saklanmış iki hash string'ini elinde tutuyorsa (bkz.
    `attempt_models.py`, girdi-tutarlılık doğrulaması) bunu kullanır.
    `input_snapshot_sha256()` (aşağıda) da AYNI bu fonksiyonu çağırır --
    birleştirme formülü İKİ AYRI yerde YAZILMAZ.

    Fail-fast: her iki değer de kanonik (64 küçük-harf hex) SHA-256 formunda
    olmalı -- aksi halde `EvidenceIntegrityError`."""
    validate_sha256_hex(asset_input_sha256_value)
    validate_sha256_hex(benchmark_input_sha256_value)
    payload = {
        "asset_input_sha256": asset_input_sha256_value,
        "benchmark_input_sha256": benchmark_input_sha256_value,
    }
    return content_sha256(payload)


def input_snapshot_sha256(asset_df: pd.DataFrame, symbol: str, benchmark_series: pd.Series) -> str:
    """Tek bir değerlendirmenin (evaluation) TÜM girdi kanıtını (asset +
    benchmark) TEK bir parmak izinde birleştirir -- ikisinden HERHANGİ
    BİRİ, tek bir bit bile değişse, bu hash değişir."""
    return input_snapshot_sha256_from_hashes(
        asset_input_sha256(asset_df, symbol),
        benchmark_input_sha256(benchmark_series),
    )


# ---------------------------------------------------------------------------
# Çıktı (TechnicalAnalysis) parmak izi
# ---------------------------------------------------------------------------


def technical_output_bytes(analysis: TechnicalAnalysis) -> bytes:
    """HATA 12N1: bu `TechnicalAnalysis` çıktısı için GCS'e yüklenecek TEK,
    kanonik bayt dizisi -- `technical_output_sha256()` BUNUN ÜZERİNDEN
    hesaplanır. `created_at` HARİÇ TÜM alanları kapsar (HATA 12K/12L tam
    alan-listesi denetimi: ne `analysis_id` ne `updated_at`/`generated_at`/
    `provider_fetch_timestamp` diye bir alan mevcut değil; Firestore
    doküman ID'si zaten ayrı bir `analyze_with_id()` dönüş değeridir, model
    alanı DEĞİLDİR).

    `compute_scoring_config_hash()` (scoring.py) ile AYNI basit
    `json.dumps(sort_keys=True)` deseni kullanılır -- Python'ın
    deterministik float repr'ine güvenilir. Bu, girdi tarafında kullanılan
    açık binary64/int64 bit-paterni kodlamasından BİLİNÇLİ OLARAK farklıdır:
    bu ticket girdi-provenance'ının TAM ikili doğruluğunu, çıktının ise
    YENİDEN ÜRETİLEBİLİRLİĞİNİ (aynı girdi -> aynı çıktı) doğrulamayı
    hedefler.

    HATA 12N1 (10.09.2026) -- depolanacak bayt dizisi TAM OLARAK bu
    fonksiyonun döndürdüğüdür: binary64-sarmalama YOK, `created_at` EKLEME
    YOK, zarf (envelope)/operasyonel zaman damgası EKLEME YOK -- deterministik
    payload'ı DEĞİŞTİRMEDEN, hash'in hesaplandığı AYNI bayt dizisi GCS'e gider.
    """
    payload = analysis.model_dump(mode="json", exclude={"created_at"})
    return canonical_document_bytes(payload)


def technical_output_sha256(analysis: TechnicalAnalysis) -> str:
    return _sha256_of_bytes(technical_output_bytes(analysis))
