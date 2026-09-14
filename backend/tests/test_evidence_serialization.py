"""HATA 12K/12L/12M — deterministik evidence serileştirme/hashleme testleri.

Kapsam: `app/research/evidence_serialization.py`'nin kilitli sözleşmeleri --
binary64/int64 kodlama, None/NaN ayrımı, şema fail-fast'leri, hash-stability
(aynı girdi -> aynı hash) ve hash-sensitivity (herhangi bir değişiklik ->
farklı hash), ve çıktı hash'inin `created_at`'e duyarsız/diğer alanlara
duyarlı olması.
"""

import hashlib
import math
import struct
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.models.technical_analysis import TechnicalAnalysis
from app.research.evidence_serialization import (
    asset_input_sha256,
    asset_snapshot_bytes,
    benchmark_input_sha256,
    benchmark_snapshot_bytes,
    input_snapshot_sha256,
    input_snapshot_sha256_from_hashes,
    serialize_asset_snapshot,
    serialize_benchmark_snapshot,
    serialize_float64,
    serialize_int64,
    serialize_optional_float64,
    technical_output_bytes,
    technical_output_sha256,
)


# ---------------------------------------------------------------------------
# Sayısal kodlayıcılar
# ---------------------------------------------------------------------------


def test_serialize_float64_normal_value_round_trips():
    encoded = serialize_float64(3.14)
    assert encoded == {"dtype": "float64", "bits": struct.pack(">d", 3.14).hex()}
    assert struct.unpack(">d", bytes.fromhex(encoded["bits"]))[0] == 3.14


def test_serialize_float64_distinguishes_positive_and_negative_zero():
    positive = serialize_float64(0.0)
    negative = serialize_float64(-0.0)
    assert positive["bits"] != negative["bits"]


def test_serialize_float64_distinguishes_nan_and_infinities():
    nan_bits = serialize_float64(float("nan"))["bits"]
    pos_inf_bits = serialize_float64(float("inf"))["bits"]
    neg_inf_bits = serialize_float64(float("-inf"))["bits"]
    assert len({nan_bits, pos_inf_bits, neg_inf_bits}) == 3
    assert len(nan_bits) == 16


def test_serialize_int64_exact_large_value_never_loses_precision_to_float():
    # 2**53 + 1 float64'te tam temsil edilemez (float precision siniri) --
    # string encoding bunu KAYIPSIZ tasimalidir.
    exact_value = (2**53) + 1
    encoded = serialize_int64(exact_value)
    assert encoded == {"dtype": "int64", "value": "9007199254740993"}
    assert int(encoded["value"]) == exact_value
    assert float(exact_value) != exact_value - 0  # sanity: gercekten float53 sinirini asiyor mu (yorum amacli)


def test_serialize_optional_float64_none_is_json_null_not_a_bit_pattern():
    assert serialize_optional_float64(None) is None
    assert serialize_optional_float64(0.0) == serialize_float64(0.0)


def test_serialize_optional_float64_does_not_confuse_none_with_nan():
    none_encoded = serialize_optional_float64(None)
    nan_encoded = serialize_optional_float64(float("nan"))
    assert none_encoded is None
    assert nan_encoded is not None
    assert nan_encoded["dtype"] == "float64"


# ---------------------------------------------------------------------------
# Asset (OHLCV) anlik-goruntusu
# ---------------------------------------------------------------------------


def _valid_asset_df(rows: int = 5) -> pd.DataFrame:
    idx = pd.DatetimeIndex(
        [datetime(2026, 9, 1, tzinfo=timezone(timedelta(hours=3))) + timedelta(days=i) for i in range(rows)]
    )
    return pd.DataFrame(
        {
            "Open": np.array([100.0 + i for i in range(rows)], dtype=np.float64),
            "High": np.array([101.0 + i for i in range(rows)], dtype=np.float64),
            "Low": np.array([99.0 + i for i in range(rows)], dtype=np.float64),
            "Close": np.array([100.5 + i for i in range(rows)], dtype=np.float64),
            "Volume": np.array([1000 + i for i in range(rows)], dtype=np.int64),
        },
        index=idx,
    )


def test_serialize_asset_snapshot_valid_df_produces_one_row_per_bar():
    df = _valid_asset_df(3)
    snapshot = serialize_asset_snapshot(df, "TEST")
    assert snapshot["symbol"] == "TEST"
    assert len(snapshot["rows"]) == 3
    assert snapshot["rows"][0]["Volume"] == {"dtype": "int64", "value": "1000"}
    assert snapshot["rows"][0]["Close"]["dtype"] == "float64"


def test_serialize_asset_snapshot_rejects_wrong_column_set_or_order():
    df = _valid_asset_df().rename(columns={"Volume": "Vol"})
    with pytest.raises(ValueError):
        serialize_asset_snapshot(df, "TEST")


def test_serialize_asset_snapshot_rejects_non_float64_price_column():
    df = _valid_asset_df()
    df["Close"] = df["Close"].astype(np.float32)
    with pytest.raises(ValueError):
        serialize_asset_snapshot(df, "TEST")


def test_serialize_asset_snapshot_rejects_volume_cast_to_float():
    df = _valid_asset_df()
    df["Volume"] = df["Volume"].astype(np.float64)
    with pytest.raises(ValueError):
        serialize_asset_snapshot(df, "TEST")


def test_serialize_asset_snapshot_rejects_non_ascending_index():
    df = _valid_asset_df(3).iloc[::-1]
    with pytest.raises(ValueError):
        serialize_asset_snapshot(df, "TEST")


def test_serialize_asset_snapshot_rejects_duplicate_index():
    df = _valid_asset_df(3)
    df.index = [df.index[0]] * 3
    with pytest.raises(ValueError):
        serialize_asset_snapshot(df, "TEST")


def test_asset_input_sha256_stable_across_repeated_calls():
    df = _valid_asset_df()
    assert asset_input_sha256(df, "TEST") == asset_input_sha256(df.copy(deep=True), "TEST")


def test_asset_input_sha256_changes_on_single_close_value_bump():
    df_a = _valid_asset_df()
    df_b = df_a.copy(deep=True)
    df_b.loc[df_b.index[-1], "Close"] = math.nextafter(df_b.loc[df_b.index[-1], "Close"], math.inf)
    assert asset_input_sha256(df_a, "TEST") != asset_input_sha256(df_b, "TEST")


def test_asset_input_sha256_changes_on_symbol_change():
    df = _valid_asset_df()
    assert asset_input_sha256(df, "AKBNK") != asset_input_sha256(df, "GARAN")


# ---------------------------------------------------------------------------
# Benchmark anlik-goruntusu
# ---------------------------------------------------------------------------


def _valid_benchmark_series(rows: int = 5) -> pd.Series:
    dates = [date(2026, 9, 1) + timedelta(days=i) for i in range(rows)]
    return pd.Series([9000.0 + i for i in range(rows)], index=dates, dtype=np.float64)


def test_serialize_benchmark_snapshot_valid_series():
    series = _valid_benchmark_series(3)
    snapshot = serialize_benchmark_snapshot(series)
    assert len(snapshot["rows"]) == 3
    assert snapshot["rows"][0]["session_date"] == "2026-09-01"
    assert snapshot["rows"][0]["close"]["dtype"] == "float64"


def test_serialize_benchmark_snapshot_rejects_non_float64_dtype():
    series = _valid_benchmark_series().astype(np.float32)
    with pytest.raises(ValueError):
        serialize_benchmark_snapshot(series)


def test_serialize_benchmark_snapshot_rejects_datetime_index_elements():
    series = _valid_benchmark_series(2)
    series.index = [datetime(2026, 9, 1), datetime(2026, 9, 2)]
    with pytest.raises(ValueError):
        serialize_benchmark_snapshot(series)


def test_serialize_benchmark_snapshot_rejects_non_ascending_index():
    series = _valid_benchmark_series(3).iloc[::-1]
    with pytest.raises(ValueError):
        serialize_benchmark_snapshot(series)


def test_benchmark_input_sha256_stable_and_sensitive():
    series_a = _valid_benchmark_series()
    series_b = series_a.copy(deep=True)
    assert benchmark_input_sha256(series_a) == benchmark_input_sha256(series_b)

    series_b.iloc[-1] = math.nextafter(series_b.iloc[-1], math.inf)
    assert benchmark_input_sha256(series_a) != benchmark_input_sha256(series_b)


# ---------------------------------------------------------------------------
# Birlesik girdi anlik-goruntusu
# ---------------------------------------------------------------------------


def test_input_snapshot_sha256_changes_if_either_side_changes():
    asset_df = _valid_asset_df()
    benchmark_series = _valid_benchmark_series()
    baseline = input_snapshot_sha256(asset_df, "TEST", benchmark_series)

    mutated_asset = asset_df.copy(deep=True)
    mutated_asset.loc[mutated_asset.index[-1], "Close"] = math.nextafter(
        mutated_asset.loc[mutated_asset.index[-1], "Close"], math.inf
    )
    assert input_snapshot_sha256(mutated_asset, "TEST", benchmark_series) != baseline

    mutated_benchmark = benchmark_series.copy(deep=True)
    mutated_benchmark.iloc[-1] = math.nextafter(mutated_benchmark.iloc[-1], math.inf)
    assert input_snapshot_sha256(asset_df, "TEST", mutated_benchmark) != baseline


# ---------------------------------------------------------------------------
# Cikti (TechnicalAnalysis) parmak izi
# ---------------------------------------------------------------------------


def _sample_analysis(created_at: datetime, technical_score: float = 42.0) -> TechnicalAnalysis:
    return TechnicalAnalysis(
        asset="TEST",
        technical_score=technical_score,
        trend="BULLISH",
        confidence=0.9,
        components={"rsi": 42.0},
        indicators={"rsi": 55.0},
        created_at=created_at,
        engine_version="1.14.0",
        scoring_config_hash="deadbeef",
    )


def test_technical_output_sha256_is_insensitive_to_created_at():
    analysis_a = _sample_analysis(datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc))
    analysis_b = _sample_analysis(datetime(2026, 9, 10, 9, 45, tzinfo=timezone.utc))
    assert technical_output_sha256(analysis_a) == technical_output_sha256(analysis_b)


def test_technical_output_sha256_is_sensitive_to_other_field_changes():
    fixed_created_at = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)
    analysis_a = _sample_analysis(fixed_created_at, technical_score=42.0)
    analysis_b = _sample_analysis(fixed_created_at, technical_score=42.01)
    assert technical_output_sha256(analysis_a) != technical_output_sha256(analysis_b)


# ---------------------------------------------------------------------------
# HATA 12N1 -- kanonik GCS bayt yardimcilari + golden-hash regresyonu
#
# Bu golden degerler, `asset_snapshot_bytes`/`benchmark_snapshot_bytes`/
# `technical_output_bytes` eklenmeden ONCE (HATA 12N1'in kendi bu turdaki
# refactor'unden hemen once), su ANDA cagirilan AYNI fixture'lardan
# (_valid_asset_df(), _valid_benchmark_series(), _sample_analysis(...))
# uretilerek kaydedilmisti -- byte-ureten yardimci fonksiyonlarin eklenmesi
# Technical V1 evidence kimligini SESSIZCE DEGISTIRMEDIGINI kanitlar.
# ---------------------------------------------------------------------------

_GOLDEN_ASSET_SHA256 = "d47fafa069eb433ae36dd2beb6bc1b1d22383e0b2d4124003fcb7757943bff75"
_GOLDEN_BENCHMARK_SHA256 = "d86fef8c332d0b5400203f231f01c056433b865ae31edfae2ae0a2703f4e6130"
_GOLDEN_OUTPUT_SHA256 = "7a15eee425dfdd04b0881cf0656d322bb191a95a2f3ee4bec5cd8b9e8e39b1b9"
# HATA 12N2A: `input_snapshot_sha256()` bu golden'dan HEMEN ONCE (yeni
# `input_snapshot_sha256_from_hashes()` combinator'una delege edilecek
# sekilde refactor edilmeden ONCE), su anda kullanilan AYNI fixture'lardan
# uretilerek kaydedildi.
_GOLDEN_INPUT_SNAPSHOT_SHA256 = "6ed8904eb19f3d4e6c112c9bcb59f2062ce41f6fbb6bd97d8b6885d3a0256d8f"


def test_golden_asset_input_sha256_unchanged_after_byte_helper_refactor():
    df = _valid_asset_df()
    assert asset_input_sha256(df, "TEST") == _GOLDEN_ASSET_SHA256


def test_golden_benchmark_input_sha256_unchanged_after_byte_helper_refactor():
    series = _valid_benchmark_series()
    assert benchmark_input_sha256(series) == _GOLDEN_BENCHMARK_SHA256


def test_golden_technical_output_sha256_unchanged_after_byte_helper_refactor():
    analysis = _sample_analysis(datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc))
    assert technical_output_sha256(analysis) == _GOLDEN_OUTPUT_SHA256


def test_golden_input_snapshot_sha256_unchanged_after_combinator_refactor():
    df = _valid_asset_df()
    series = _valid_benchmark_series()
    assert input_snapshot_sha256(df, "TEST", series) == _GOLDEN_INPUT_SNAPSHOT_SHA256


def test_input_snapshot_sha256_from_hashes_matches_direct_computation():
    df = _valid_asset_df()
    series = _valid_benchmark_series()
    direct = input_snapshot_sha256(df, "TEST", series)
    from_hashes = input_snapshot_sha256_from_hashes(asset_input_sha256(df, "TEST"), benchmark_input_sha256(series))
    assert direct == from_hashes


def test_input_snapshot_sha256_from_hashes_rejects_malformed_hash():
    with pytest.raises(Exception):
        input_snapshot_sha256_from_hashes("not-a-hash", "b" * 64)
    with pytest.raises(Exception):
        input_snapshot_sha256_from_hashes("a" * 64, "not-a-hash")


def test_asset_snapshot_bytes_sha256_matches_asset_input_sha256():
    df = _valid_asset_df()
    raw = asset_snapshot_bytes(df, "TEST")
    assert isinstance(raw, bytes)
    assert hashlib.sha256(raw).hexdigest() == asset_input_sha256(df, "TEST")


def test_benchmark_snapshot_bytes_sha256_matches_benchmark_input_sha256():
    series = _valid_benchmark_series()
    raw = benchmark_snapshot_bytes(series)
    assert isinstance(raw, bytes)
    assert hashlib.sha256(raw).hexdigest() == benchmark_input_sha256(series)


def test_technical_output_bytes_sha256_matches_technical_output_sha256():
    analysis = _sample_analysis(datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc))
    raw = technical_output_bytes(analysis)
    assert isinstance(raw, bytes)
    assert hashlib.sha256(raw).hexdigest() == technical_output_sha256(analysis)


def test_byte_helpers_are_deterministic_across_repeated_calls():
    df = _valid_asset_df()
    series = _valid_benchmark_series()
    analysis = _sample_analysis(datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc))

    assert asset_snapshot_bytes(df, "TEST") == asset_snapshot_bytes(df.copy(deep=True), "TEST")
    assert benchmark_snapshot_bytes(series) == benchmark_snapshot_bytes(series.copy(deep=True))
    assert technical_output_bytes(analysis) == technical_output_bytes(analysis.model_copy())


def test_asset_snapshot_bytes_are_utf8_compact_json_no_pretty_print():
    df = _valid_asset_df(1)
    raw = asset_snapshot_bytes(df, "TEST")
    text = raw.decode("utf-8")
    assert "\n" not in text
    assert ", " not in text  # kompakt separators=(",", ":") -- bosluklu degil
    assert ": " not in text


def test_technical_output_bytes_insensitive_to_created_at_sensitive_to_other_fields():
    analysis_a = _sample_analysis(datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc))
    analysis_b = _sample_analysis(datetime(2026, 9, 10, 9, 45, tzinfo=timezone.utc))
    assert technical_output_bytes(analysis_a) == technical_output_bytes(analysis_b)

    analysis_c = _sample_analysis(datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc), technical_score=42.01)
    assert technical_output_bytes(analysis_a) != technical_output_bytes(analysis_c)
    assert hashlib.sha256(technical_output_bytes(analysis_a)).hexdigest() != hashlib.sha256(
        technical_output_bytes(analysis_c)
    ).hexdigest()


def test_technical_output_bytes_does_not_contain_created_at_key():
    analysis = _sample_analysis(datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc))
    text = technical_output_bytes(analysis).decode("utf-8")
    assert '"created_at"' not in text
