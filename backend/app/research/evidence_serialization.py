"""Deterministik evidence serileştirme/hashleme çekirdeği — HATA 12K/12L/12M.

Bu modül, Technical V1 prospective validation protokolünün (bkz.
`research/technical_v1_protocol_v1.json`) kanıt-doğruluğu sözleşmesini
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
import json
import struct
from datetime import date, datetime

import numpy as np
import pandas as pd

from app.models.technical_analysis import TechnicalAnalysis

REQUIRED_ASSET_COLUMNS: tuple[str, ...] = ("Open", "High", "Low", "Close", "Volume")
_FLOAT_ASSET_COLUMNS: tuple[str, ...] = ("Open", "High", "Low", "Close")
_INT_ASSET_COLUMNS: tuple[str, ...] = ("Volume",)


def _canonical_json(payload: object) -> str:
    """`compute_scoring_config_hash()`'teki (scoring.py) AYNI kanonikleştirme
    deseni -- dict insertion sırasından bağımsız, tek/sabit bir string."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _sha256_of(canonical: str) -> str:
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def asset_input_sha256(df: pd.DataFrame, symbol: str) -> str:
    return _sha256_of(_canonical_json(serialize_asset_snapshot(df, symbol)))


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


def benchmark_input_sha256(series: pd.Series) -> str:
    return _sha256_of(_canonical_json(serialize_benchmark_snapshot(series)))


def input_snapshot_sha256(asset_df: pd.DataFrame, symbol: str, benchmark_series: pd.Series) -> str:
    """Tek bir değerlendirmenin (evaluation) TÜM girdi kanıtını (asset +
    benchmark) TEK bir parmak izinde birleştirir -- ikisinden HERHANGİ
    BİRİ, tek bir bit bile değişse, bu hash değişir."""
    payload = {
        "asset_input_sha256": asset_input_sha256(asset_df, symbol),
        "benchmark_input_sha256": benchmark_input_sha256(benchmark_series),
    }
    return _sha256_of(_canonical_json(payload))


# ---------------------------------------------------------------------------
# Çıktı (TechnicalAnalysis) parmak izi
# ---------------------------------------------------------------------------


def technical_output_sha256(analysis: TechnicalAnalysis) -> str:
    """`TechnicalAnalysis.model_dump()`'ın `created_at` HARİÇ TÜM alanlarının
    SHA-256'sı. `created_at`, modeldeki TEK deterministik olmayan alandır
    (HATA 12K/12L tam alan-listesi denetimi: ne `analysis_id` ne
    `updated_at`/`generated_at`/`provider_fetch_timestamp` diye bir alan
    mevcut değil; Firestore doküman ID'si zaten ayrı bir `analyze_with_id()`
    dönüş değeridir, model alanı DEĞİLDİR).

    `compute_scoring_config_hash()` (scoring.py) ile AYNI basit
    `json.dumps(sort_keys=True)` deseni kullanılır -- Python'ın
    deterministik float repr'ine güvenilir. Bu, girdi tarafında kullanılan
    açık binary64/int64 bit-paterni kodlamasından BİLİNÇLİ OLARAK farklıdır:
    bu ticket girdi-provenance'ının TAM ikili doğruluğunu, çıktının ise
    YENİDEN ÜRETİLEBİLİRLİĞİNİ (aynı girdi -> aynı çıktı) doğrulamayı
    hedefler.
    """
    payload = analysis.model_dump(mode="json", exclude={"created_at"})
    return _sha256_of(_canonical_json(payload))
