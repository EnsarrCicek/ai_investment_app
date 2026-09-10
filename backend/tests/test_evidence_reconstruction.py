"""HATA 12M-R — kanonik evidence deserileştirme/yeniden-kurma testleri.

Kapsam: `app/research/evidence_serialization.py`'nin `deserialize_*`
fonksiyonlarının (1) tam ikili (bit-seviyesi) doğruluğu, (2) şema/tip
fail-fast'leri, (3) gerçek serialize->deserialize->serialize round-trip'i
(ad-hoc bir tanılama DEĞİL, committed bir test), ve (4) EN KRİTİK olarak --
saklanmış kanonik evidence'tan yeniden kurulan girdilerin, `compute_
technical_analysis()`'i orijinal girdilerle BİREBİR AYNI (created_at hariç)
sonuca ULAŞTIRDIĞININ kanıtı (yalnızca kendi kendine hash tutarlılığı değil,
GERÇEK Technical V1 yeniden-üretimi).
"""

import math
import struct
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.data_quality import check_data_quality, check_raw_ohlcv_integrity, check_trading_day_continuity
from app.engines.technical.engine import DEFAULT_WEIGHTS, MIN_HISTORY_DAYS, compute_technical_analysis
from app.engines.technical.history_window import compute_history_window, resolve_expected_start
from app.engines.technical.scoring import compute_scoring_config_hash, resolve_family_weights, resolve_indicator_weights
from app.research.evidence_serialization import (
    asset_input_sha256,
    benchmark_input_sha256,
    deserialize_asset_snapshot,
    deserialize_benchmark_snapshot,
    deserialize_float64,
    deserialize_int64,
    deserialize_optional_float64,
    input_snapshot_sha256,
    serialize_asset_snapshot,
    serialize_benchmark_snapshot,
    serialize_float64,
    serialize_int64,
    technical_output_sha256,
)
from app.services.market_data.completed_bars import filter_completed_daily_bars
from app.services.market_data.trading_calendar import (
    expected_trading_sessions,
    normalize_bist_daily_sessions,
    session_normalization_to_dict,
)

TZ = ZoneInfo("Europe/Istanbul")


# ---------------------------------------------------------------------------
# float64 / int64 decode -- bit-seviyesi dogruluk
# ---------------------------------------------------------------------------


def test_deserialize_float64_normal_value():
    assert deserialize_float64(serialize_float64(3.14)) == 3.14


def test_deserialize_float64_positive_and_negative_zero_bits_preserved():
    pos = deserialize_float64(serialize_float64(0.0))
    neg = deserialize_float64(serialize_float64(-0.0))
    assert math.copysign(1.0, pos) == 1.0
    assert math.copysign(1.0, neg) == -1.0
    assert pos == 0.0 and neg == 0.0  # sayisal olarak esit ama isaret biti farkli


def test_deserialize_float64_nextafter_adjacent_values_distinct():
    base = 100.5
    adjacent = math.nextafter(base, math.inf)
    assert base != adjacent
    decoded_base = deserialize_float64(serialize_float64(base))
    decoded_adjacent = deserialize_float64(serialize_float64(adjacent))
    assert decoded_base == base
    assert decoded_adjacent == adjacent
    assert decoded_base != decoded_adjacent


def test_deserialize_float64_nan_bit_pattern_preserved_exactly():
    raw_bits = 0x7FF8000000000001
    original = struct.unpack(">d", raw_bits.to_bytes(8, "big"))[0]
    decoded = deserialize_float64(serialize_float64(original))
    assert struct.pack(">d", decoded).hex() == format(raw_bits, "016x")


def test_deserialize_float64_positive_and_negative_infinity():
    pos_inf = deserialize_float64(serialize_float64(float("inf")))
    neg_inf = deserialize_float64(serialize_float64(float("-inf")))
    assert pos_inf == float("inf")
    assert neg_inf == float("-inf")


def test_deserialize_float64_rejects_malformed_encoding():
    with pytest.raises(ValueError):
        deserialize_float64({"dtype": "float32", "bits": "3ff0000000000000"})
    with pytest.raises(ValueError):
        deserialize_float64({"dtype": "float64", "bits": "3ff000000000000"})  # 15 hex chars
    with pytest.raises(ValueError):
        deserialize_float64({"dtype": "float64", "bits": "3FF0000000000000"})  # uppercase
    with pytest.raises(ValueError):
        deserialize_float64({"dtype": "float64", "bits": "zzzzzzzzzzzzzzzz"})  # invalid hex
    with pytest.raises(ValueError):
        deserialize_float64({"dtype": "float64", "bits": "3ff0000000000000", "extra": 1})  # fazla anahtar


def test_deserialize_optional_float64_none_round_trips():
    assert deserialize_optional_float64(None) is None
    assert deserialize_optional_float64(serialize_float64(1.5)) == 1.5


def test_deserialize_int64_zero_normal_and_boundary_values():
    assert deserialize_int64(serialize_int64(0)) == 0
    assert deserialize_int64(serialize_int64(4321)) == 4321
    assert deserialize_int64(serialize_int64((2**53) + 1)) == (2**53) + 1
    assert deserialize_int64(serialize_int64(2**63 - 1)) == 2**63 - 1  # int64 max
    assert deserialize_int64(serialize_int64(-(2**63))) == -(2**63)  # int64 min


def test_deserialize_int64_no_float_intermediary_for_large_values():
    huge = (2**53) + 1  # float64'te tam temsil edilemez
    encoded = serialize_int64(huge)
    assert isinstance(encoded["value"], str)
    decoded = deserialize_int64(encoded)
    assert decoded == huge
    assert isinstance(decoded, int)


def test_deserialize_int64_rejects_malformed_encoding():
    with pytest.raises(ValueError):
        deserialize_int64({"dtype": "int32", "value": "5"})
    with pytest.raises(ValueError):
        deserialize_int64({"dtype": "int64", "value": "007"})  # onde sifir
    with pytest.raises(ValueError):
        deserialize_int64({"dtype": "int64", "value": "+5"})  # artı isareti
    with pytest.raises(ValueError):
        deserialize_int64({"dtype": "int64", "value": "5.0"})  # float-benzeri string
    with pytest.raises(ValueError):
        deserialize_int64({"dtype": "int64", "value": str(2**63)})  # max'in 1 fazlasi
    with pytest.raises(ValueError):
        deserialize_int64({"dtype": "int64", "value": str(-(2**63) - 1)})  # min'in 1 eksigi


# ---------------------------------------------------------------------------
# Asset index yeniden kurma
# ---------------------------------------------------------------------------


def _valid_asset_snapshot(rows: int = 5) -> dict:
    idx = pd.DatetimeIndex(
        [datetime(2026, 9, 1, tzinfo=timezone(timedelta(hours=3))) + timedelta(days=i) for i in range(rows)]
    )
    df = pd.DataFrame(
        {
            "Open": np.array([100.0 + i for i in range(rows)], dtype=np.float64),
            "High": np.array([101.0 + i for i in range(rows)], dtype=np.float64),
            "Low": np.array([99.0 + i for i in range(rows)], dtype=np.float64),
            "Close": np.array([100.5 + i for i in range(rows)], dtype=np.float64),
            "Volume": np.array([1000 + i for i in range(rows)], dtype=np.int64),
        },
        index=idx,
    )
    return serialize_asset_snapshot(df, "TEST"), df


def test_deserialize_asset_snapshot_index_is_tz_aware_datetime_index():
    snapshot, _original_df = _valid_asset_snapshot()
    df, symbol = deserialize_asset_snapshot(snapshot)
    assert symbol == "TEST"
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is not None


def test_deserialize_asset_snapshot_timezone_is_europe_istanbul_not_machine_local():
    snapshot, _original_df = _valid_asset_snapshot()
    df, _symbol = deserialize_asset_snapshot(snapshot)
    assert str(df.index.tz) == "Europe/Istanbul"
    # utcoffset +03:00 sabit (DST yok) her satirda dogrulanir
    for ts in df.index:
        assert ts.utcoffset() == timedelta(hours=3)


def test_deserialize_asset_snapshot_preserves_ordering_and_timestamp_equality():
    snapshot, original_df = _valid_asset_snapshot(5)
    df, _symbol = deserialize_asset_snapshot(snapshot)
    assert df.index.is_monotonic_increasing
    assert list(original_df.index) == list(df.index)


def test_deserialize_asset_snapshot_does_not_return_strings_or_plain_dates():
    snapshot, _ = _valid_asset_snapshot()
    df, _symbol = deserialize_asset_snapshot(snapshot)
    assert not isinstance(df.index[0], str)
    assert not (type(df.index[0]) is date)  # Timestamp da date'in alt sinifi olabilir, tam tip kontrolu


def test_deserialize_asset_snapshot_column_order_and_dtypes():
    snapshot, original_df = _valid_asset_snapshot()
    df, _symbol = deserialize_asset_snapshot(snapshot)
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert df["Open"].dtype == np.float64
    assert df["High"].dtype == np.float64
    assert df["Low"].dtype == np.float64
    assert df["Close"].dtype == np.float64
    assert df["Volume"].dtype == np.int64
    assert list(df.dtypes) == list(original_df.dtypes)


def test_deserialize_asset_snapshot_rejects_malformed_top_level():
    with pytest.raises(ValueError):
        deserialize_asset_snapshot({"rows": []})  # symbol eksik
    with pytest.raises(ValueError):
        deserialize_asset_snapshot({"symbol": "TEST", "rows": []})  # bos rows
    with pytest.raises(ValueError):
        deserialize_asset_snapshot({"symbol": "", "rows": [{}]})  # bos symbol
    with pytest.raises(ValueError):
        deserialize_asset_snapshot({"symbol": "TEST", "rows": [], "extra": 1})  # fazla anahtar


def test_deserialize_asset_snapshot_rejects_missing_or_extra_row_keys():
    snapshot, _ = _valid_asset_snapshot(1)
    incomplete_row = dict(snapshot["rows"][0])
    del incomplete_row["Volume"]
    with pytest.raises(ValueError):
        deserialize_asset_snapshot({"symbol": "TEST", "rows": [incomplete_row]})

    extra_row = dict(snapshot["rows"][0])
    extra_row["Extra"] = 1
    with pytest.raises(ValueError):
        deserialize_asset_snapshot({"symbol": "TEST", "rows": [extra_row]})


def test_deserialize_asset_snapshot_rejects_naive_timestamp():
    snapshot, _ = _valid_asset_snapshot(1)
    row = dict(snapshot["rows"][0])
    row["session_timestamp"] = "2026-09-01T00:00:00"  # tz yok
    with pytest.raises(ValueError):
        deserialize_asset_snapshot({"symbol": "TEST", "rows": [row]})


def test_deserialize_asset_snapshot_rejects_duplicate_and_non_monotonic_index():
    snapshot, _ = _valid_asset_snapshot(3)
    duplicated_rows = [snapshot["rows"][0], snapshot["rows"][0], snapshot["rows"][1]]
    with pytest.raises(ValueError):
        deserialize_asset_snapshot({"symbol": "TEST", "rows": duplicated_rows})

    reversed_rows = list(reversed(snapshot["rows"]))
    with pytest.raises(ValueError):
        deserialize_asset_snapshot({"symbol": "TEST", "rows": reversed_rows})


# ---------------------------------------------------------------------------
# Benchmark index yeniden kurma
# ---------------------------------------------------------------------------


def _valid_benchmark_snapshot(rows: int = 5) -> tuple[dict, pd.Series]:
    dates = [date(2026, 9, 1) + timedelta(days=i) for i in range(rows)]
    series = pd.Series([9000.0 + i for i in range(rows)], index=dates, dtype=np.float64)
    return serialize_benchmark_snapshot(series), series


def test_deserialize_benchmark_snapshot_index_is_plain_date_not_timestamp():
    snapshot, _original = _valid_benchmark_snapshot()
    series = deserialize_benchmark_snapshot(snapshot)
    for key in series.index:
        assert type(key) is date  # tam olarak plain date, datetime/Timestamp DEGIL
    assert series.dtype == np.float64


def test_deserialize_benchmark_snapshot_rejects_datetime_with_offset_string():
    snapshot, _ = _valid_benchmark_snapshot(1)
    row = dict(snapshot["rows"][0])
    row["session_date"] = "2026-09-01T00:00:00+03:00"  # zaman bileseni/tz -- yalnizca YYYY-MM-DD kabul edilir
    with pytest.raises(ValueError):
        deserialize_benchmark_snapshot({"rows": [row]})


def test_deserialize_benchmark_snapshot_rejects_malformed_top_level_and_rows():
    with pytest.raises(ValueError):
        deserialize_benchmark_snapshot({"rows": []})
    with pytest.raises(ValueError):
        deserialize_benchmark_snapshot({})
    with pytest.raises(ValueError):
        deserialize_benchmark_snapshot({"rows": [{"session_date": "2026-09-01"}]})  # close eksik


def test_deserialize_benchmark_snapshot_rejects_duplicate_and_non_ascending_dates():
    snapshot, _ = _valid_benchmark_snapshot(3)
    duplicated_rows = [snapshot["rows"][0], snapshot["rows"][0], snapshot["rows"][1]]
    with pytest.raises(ValueError):
        deserialize_benchmark_snapshot({"rows": duplicated_rows})

    reversed_rows = list(reversed(snapshot["rows"]))
    with pytest.raises(ValueError):
        deserialize_benchmark_snapshot({"rows": reversed_rows})


# ---------------------------------------------------------------------------
# HATA 12M-R2 -- kanonik lehce sikiligi (fromisoformat asiri hosgorulu)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "malformed_date",
    [
        "20260910",  # kompakt (tire yok)
        "2026-W37-4",  # ISO hafta-tarihi
        "2026-09-10T00:00:00",  # zaman bileseni icerir
        " 2026-09-10",  # bastan bosluk
        "2026-09-10 ",  # sondan bosluk
        "2026-9-10",  # sifir-doldurulmamis
    ],
)
def test_deserialize_benchmark_snapshot_rejects_noncanonical_date_lexical_forms(malformed_date):
    close_enc = serialize_float64(9000.0)
    with pytest.raises(ValueError):
        deserialize_benchmark_snapshot({"rows": [{"session_date": malformed_date, "close": close_enc}]})


def test_deserialize_benchmark_snapshot_accepts_only_serializer_produced_form():
    series = pd.Series([9000.5], index=[date(2026, 9, 10)], dtype=np.float64)
    snapshot = serialize_benchmark_snapshot(series)
    assert snapshot["rows"][0]["session_date"] == "2026-09-10"
    reconstructed = deserialize_benchmark_snapshot(snapshot)
    assert list(reconstructed.index) == [date(2026, 9, 10)]


@pytest.mark.parametrize(
    "malformed_timestamp",
    [
        "2026-09-08T00:00:00",  # naive
        "2026-09-07T21:00:00+00:00",  # AYNI ana isaret eden ama YANLIS ofset
        "20260908T000000+0300",  # kompakt
        " 2026-09-08T00:00:00+03:00",  # bastan bosluk
        "2026-09-08T00:00:00+03:00 ",  # sondan bosluk
        "2026-09-08 00:00:00+03:00",  # "T" yerine bosluk
        "2026-09-08T00:00:00+0300",  # offset'te iki nokta yok
        "2026-09-08T00:00:00+03:00:00",  # offset'te saniye var
    ],
)
def test_deserialize_asset_snapshot_rejects_noncanonical_timestamp_lexical_forms(malformed_timestamp):
    open_enc = serialize_float64(100.0)
    volume_enc = serialize_int64(1000)
    row = {
        "session_timestamp": malformed_timestamp,
        "Open": open_enc,
        "High": open_enc,
        "Low": open_enc,
        "Close": open_enc,
        "Volume": volume_enc,
    }
    with pytest.raises(ValueError):
        deserialize_asset_snapshot({"symbol": "TEST", "rows": [row]})


def test_deserialize_asset_snapshot_accepts_only_serializer_produced_timestamp_form():
    idx = pd.DatetimeIndex([datetime(2026, 9, 8, tzinfo=timezone(timedelta(hours=3)))])
    df = pd.DataFrame(
        {
            "Open": np.array([100.0], dtype=np.float64),
            "High": np.array([101.0], dtype=np.float64),
            "Low": np.array([99.0], dtype=np.float64),
            "Close": np.array([100.5], dtype=np.float64),
            "Volume": np.array([1000], dtype=np.int64),
        },
        index=idx,
    )
    snapshot = serialize_asset_snapshot(df, "TEST")
    assert snapshot["rows"][0]["session_timestamp"] == "2026-09-08T00:00:00+03:00"
    reconstructed_df, _symbol = deserialize_asset_snapshot(snapshot)
    assert str(reconstructed_df.index[0].tz) == "Europe/Istanbul"
    assert reconstructed_df.index[0].utcoffset() == timedelta(hours=3)


def test_deserialize_asset_snapshot_does_not_silently_normalize_wrong_offset_instant():
    """HATA 12M-R2 kilit-madde: '+00:00' ile ifade edilen, sayisal olarak
    dogru bir ana isaret eden ama KANONIK OLMAYAN bir zaman damgasi,
    tz_convert() ile SESSIZCE +03:00'e "onarilmamali" -- FAIL FAST olmali."""
    open_enc = serialize_float64(100.0)
    volume_enc = serialize_int64(1000)
    # "2026-09-07T21:00:00+00:00" tam olarak "2026-09-08T00:00:00+03:00" ile
    # AYNI ana isaret eder (yalnizca farkli lehcede yazilmis) -- yine de
    # kanonik-olmayan oldugu icin REDDEDILMELI.
    row = {
        "session_timestamp": "2026-09-07T21:00:00+00:00",
        "Open": open_enc,
        "High": open_enc,
        "Low": open_enc,
        "Close": open_enc,
        "Volume": volume_enc,
    }
    with pytest.raises(ValueError, match="ofsetinde değil|kanonik"):
        deserialize_asset_snapshot({"symbol": "TEST", "rows": [row]})


# ---------------------------------------------------------------------------
# TRUE round-trip (committed, ad-hoc DEGIL) + binary-esitlik
# ---------------------------------------------------------------------------


def test_asset_true_round_trip_serialize_deserialize_serialize():
    idx = pd.DatetimeIndex(
        [datetime(2026, 9, 1, tzinfo=timezone(timedelta(hours=3))) + timedelta(days=i) for i in range(10)]
    )
    rng = np.random.default_rng(777)
    closes = 100 + np.cumsum(rng.normal(0, 1, 10))
    original_df = pd.DataFrame(
        {
            "Open": closes,
            "High": closes + 1,
            "Low": closes - 1,
            "Close": closes,
            "Volume": rng.integers(1000, 5000, 10).astype(np.int64),
        },
        index=idx,
    )

    snapshot_1 = serialize_asset_snapshot(original_df, "AKBNK")
    reconstructed_df, reconstructed_symbol = deserialize_asset_snapshot(snapshot_1)
    snapshot_2 = serialize_asset_snapshot(reconstructed_df, reconstructed_symbol)

    assert snapshot_1 == snapshot_2  # kanonik serialize edilmis nesne esitligi
    assert asset_input_sha256(original_df, "AKBNK") == asset_input_sha256(reconstructed_df, reconstructed_symbol)
    assert list(original_df.dtypes) == list(reconstructed_df.dtypes)
    assert list(original_df.index) == list(reconstructed_df.index)

    # Her float64 hucre icin bit-seviyesi esitlik (adi `==` karsilastirmasindan
    # daha guclu -- +0.0/-0.0/NaN gibi degerlerde adi `==` yanlis pozitif/
    # negatif verebilir, bit karsilastirmasi VERMEZ).
    for col in ("Open", "High", "Low", "Close"):
        original_bits = [struct.pack(">d", v).hex() for v in original_df[col].to_numpy()]
        reconstructed_bits = [struct.pack(">d", v).hex() for v in reconstructed_df[col].to_numpy()]
        assert original_bits == reconstructed_bits

    assert list(original_df["Volume"].to_numpy()) == list(reconstructed_df["Volume"].to_numpy())
    assert reconstructed_df["Volume"].dtype == np.int64


def test_benchmark_true_round_trip_serialize_deserialize_serialize():
    dates = [date(2026, 9, 1) + timedelta(days=i) for i in range(10)]
    rng = np.random.default_rng(888)
    original_series = pd.Series(9000 + np.cumsum(rng.normal(0, 10, 10)), index=dates, dtype=np.float64)

    snapshot_1 = serialize_benchmark_snapshot(original_series)
    reconstructed_series = deserialize_benchmark_snapshot(snapshot_1)
    snapshot_2 = serialize_benchmark_snapshot(reconstructed_series)

    assert snapshot_1 == snapshot_2
    assert benchmark_input_sha256(original_series) == benchmark_input_sha256(reconstructed_series)
    assert list(original_series.index) == list(reconstructed_series.index)

    original_bits = [struct.pack(">d", v).hex() for v in original_series.to_numpy()]
    reconstructed_bits = [struct.pack(">d", v).hex() for v in reconstructed_series.to_numpy()]
    assert original_bits == reconstructed_bits


# ---------------------------------------------------------------------------
# Yeniden-uretim testi: reconstructed girdilerden compute_technical_analysis()
# ---------------------------------------------------------------------------


def _bist_trading_days(end: date, n: int) -> list[date]:
    search_start = end - timedelta(days=n * 2 + 20)
    sessions = expected_trading_sessions(search_start, end)
    assert sessions is not None and len(sessions) >= n
    return sessions[-n:]


def _asset_history_df(rows: int = 150, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100 + np.cumsum(rng.normal(0, 1, rows))
    end = (pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)).date()
    trading_days = _bist_trading_days(end, rows)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes + 1,
            "Low": closes - 1,
            "Close": closes,
            "Volume": rng.integers(1000, 5000, rows),
        },
        index=pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in trading_days]),
    )


def _benchmark_history_series(rows: int = 150, seed: int = 900) -> pd.Series:
    end = (pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)).date()
    trading_days = _bist_trading_days(end, rows)
    rng = np.random.default_rng(seed)
    closes = 9000 + np.cumsum(rng.normal(0, 20, rows))
    return pd.Series(closes, index=trading_days, dtype=np.float64).sort_index()


class _FakeConfigRepo:
    def get_raw(self, key):
        if key == "technical_indicator_weights":
            return dict(DEFAULT_WEIGHTS)
        return None


def _resolve_head(df_raw: pd.DataFrame, symbol: str, config_repo, now=None):
    weights = resolve_indicator_weights(config_repo.get_raw("technical_indicator_weights"))
    family_weights = resolve_family_weights(config_repo.get_raw("technical_family_weights"))
    scoring_config_hash = compute_scoring_config_hash(weights, family_weights)

    history_window = compute_history_window(now)
    provider_history = filter_completed_daily_bars(df_raw, now=now)
    provider_history, session_normalization_result = normalize_bist_daily_sessions(
        provider_history, symbol=symbol, provider="yahoo_finance"
    )
    expected_start, validation_status = resolve_expected_start(provider_history, history_window.analysis_start)
    check_trading_day_continuity(provider_history, symbol, now=now, expected_start=expected_start)
    df = provider_history[provider_history.index.date >= expected_start]
    check_raw_ohlcv_integrity(df, symbol)
    check_data_quality(df, symbol, min_history_days=MIN_HISTORY_DAYS, now=now)

    return (
        df,
        weights,
        family_weights,
        scoring_config_hash,
        validation_status.value,
        session_normalization_to_dict(session_normalization_result),
    )


@pytest.mark.parametrize("seed", [3, 21, 456])
def test_reconstructed_snapshot_reproduces_technical_v1_output_exactly(seed):
    """HATA 12M-R kritik test: saklanmis kanonik evidence'tan yeniden
    kurulan (asset_df, benchmark_series) ile compute_technical_analysis()
    cagirmak, ORIJINAL (materyalize edilmis) nesnelerle cagirmakla
    `technical_output_sha256` DUZEYINDE TAM AYNI sonucu vermeli --
    saklanan kanit yalnizca KENDI KENDINE hash tutarli degil, GERCEKTEN
    Technical V1'i yeniden uretebiliyor.
    """
    config_repo = _FakeConfigRepo()
    asset_raw = _asset_history_df(seed=seed)
    benchmark_raw = _benchmark_history_series(seed=seed + 1000)

    df, weights, family_weights, scoring_hash, validation_status, session_fields = _resolve_head(
        asset_raw, "TEST", config_repo
    )

    # Path A: orijinal (materyalize edilmis) nesnelerden dogrudan
    original_analysis = compute_technical_analysis(
        df,
        "TEST",
        weights,
        family_weights,
        scoring_hash,
        validation_status,
        session_fields,
        benchmark_close_series=benchmark_raw,
    )

    # Path B: serialize -> deserialize -> compute_technical_analysis()
    asset_snapshot = serialize_asset_snapshot(df, "TEST")
    benchmark_snapshot = serialize_benchmark_snapshot(benchmark_raw)
    reconstructed_df, reconstructed_symbol = deserialize_asset_snapshot(asset_snapshot)
    reconstructed_benchmark = deserialize_benchmark_snapshot(benchmark_snapshot)

    reconstructed_analysis = compute_technical_analysis(
        reconstructed_df,
        reconstructed_symbol,
        weights,
        family_weights,
        scoring_hash,
        validation_status,
        session_fields,
        benchmark_close_series=reconstructed_benchmark,
    )

    assert technical_output_sha256(original_analysis) == technical_output_sha256(reconstructed_analysis)
    assert original_analysis.model_dump(exclude={"created_at"}) == reconstructed_analysis.model_dump(
        exclude={"created_at"}
    )


@pytest.mark.parametrize("seed", [3, 21, 456])
def test_reconstructed_snapshot_hashes_match_originals(seed):
    """HATA 12M-R madde 12: tam girdi cifti icin asset/benchmark/birlesik
    input_snapshot_sha256 hash'lerinin orijinal ile yeniden kurulan
    arasinda BIREBIR ayni oldugunu dogrudan kanitlar."""
    config_repo = _FakeConfigRepo()
    asset_raw = _asset_history_df(seed=seed)
    benchmark_raw = _benchmark_history_series(seed=seed + 1000)

    df, _weights, _family_weights, _scoring_hash, _validation_status, _session_fields = _resolve_head(
        asset_raw, "TEST", config_repo
    )

    asset_snapshot = serialize_asset_snapshot(df, "TEST")
    benchmark_snapshot = serialize_benchmark_snapshot(benchmark_raw)
    reconstructed_df, reconstructed_symbol = deserialize_asset_snapshot(asset_snapshot)
    reconstructed_benchmark = deserialize_benchmark_snapshot(benchmark_snapshot)

    assert asset_input_sha256(df, "TEST") == asset_input_sha256(reconstructed_df, reconstructed_symbol)
    assert benchmark_input_sha256(benchmark_raw) == benchmark_input_sha256(reconstructed_benchmark)
    assert input_snapshot_sha256(df, "TEST", benchmark_raw) == input_snapshot_sha256(
        reconstructed_df, reconstructed_symbol, reconstructed_benchmark
    )
