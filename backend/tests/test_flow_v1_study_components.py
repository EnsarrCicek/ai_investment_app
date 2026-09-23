"""FLOW 1B — istatistik ilkelleri, dondurulmuş veri doğrulaması, segmentasyon
ve Technical-kör koruması. Ağ yok."""

import math
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from app.research.canonical_hash import content_sha256
from app.research.flow_v1 import statistics as st
from app.research.flow_v1.dataset import (
    DatasetIntegrityError,
    integrity_invalid_mask,
    preprocess_symbol,
    rows_to_frame,
    split_into_segments,
    symbol_payload,
    verify_frozen,
)
from app.research.flow_v1.study import (
    TechnicalBlindViolation,
    assert_technical_blind,
    daily_ic,
    daily_partial_ic,
)


# ---------------------------------------------------------------- statistics


def test_spearman_is_rank_based_and_handles_ties():
    x = pd.Series([1, 2, 3, 4, 5], dtype=float)
    assert st.spearman(x, x**3) == pytest.approx(1.0)
    assert st.spearman(x, -x) == pytest.approx(-1.0)
    assert math.isnan(st.spearman(x, pd.Series([1.0] * 5)))


def test_partial_ic_removes_information_explained_by_control():
    rng = np.random.default_rng(0)
    control = pd.Series(rng.normal(size=500))
    target = control + 0.01 * rng.normal(size=500)
    # feature == control -> artık yalnızca kayan-nokta gürültüsü -> tanımsız (NaN), sahte korelasyon değil
    assert math.isnan(st.partial_rank_ic(control.copy(), control.to_frame("c"), target))
    # feature = control + hedefle ilgisiz gürültü -> ek bilgi ~0
    noisy = control + 0.5 * pd.Series(rng.normal(size=500))
    assert abs(st.partial_rank_ic(noisy, control.to_frame("c"), target)) < 0.1
    independent = pd.Series(rng.normal(size=500))
    target2 = control + independent
    assert st.partial_rank_ic(independent, control.to_frame("c"), target2) > 0.4


def test_block_bootstrap_is_deterministic_and_centered():
    x = np.random.default_rng(5).normal(0.1, 1.0, 400)
    a = st.block_bootstrap_means(x, replicates=2000)
    b = st.block_bootstrap_means(x, replicates=2000)
    np.testing.assert_array_equal(a, b)
    assert abs(a.mean() - x.mean()) < 0.02


def test_block_bootstrap_constant_series_and_short_series():
    assert np.allclose(st.block_bootstrap_means(np.full(50, 3.0), replicates=100), 3.0)
    assert np.allclose(st.block_bootstrap_means(np.array([1.0, 1.0, 1.0]), replicates=10), 1.0)


def test_newey_west_wider_than_iid_for_autocorrelated_series():
    rng = np.random.default_rng(2)
    e = rng.normal(size=2000)
    x = 0.05 + np.convolve(e, np.ones(10) / 10, mode="same")
    iid_t = x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))
    assert abs(st.newey_west_t(x, 10)) < abs(iid_t)


def test_labels_and_holm():
    assert st.label_positive({"ci_low": 0.01, "ci_high": 0.02}) == "SUPPORTED"
    assert st.label_positive({"ci_low": -0.01, "ci_high": 0.02}) == "NOT_ESTABLISHED"
    assert st.label_positive({"ci_low": -0.03, "ci_high": -0.02}) == "EVIDENCE_OPPOSITE_DIRECTION"
    assert st.label_negative({"ci_low": -0.03, "ci_high": -0.02}) == "SUPPORTED"
    adj = st.holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj == {"a": 0.03, "c": 0.06, "b": 0.06}


def test_quintiles_equal_count_and_monotonicity():
    q = st.assign_quintiles(pd.Series(np.arange(50, dtype=float)))
    assert q.value_counts().tolist() == [10] * 5
    assert st.monotonicity([1, 2, 3, 4, 5])["increasing_steps_of_4"] == 4
    assert st.monotonicity([1, 2, None, 4, 5])["spearman_vs_rank"] is None


# ---------------------------------------------------------------- frozen data


def _payload(symbol, n=3):
    rows = [[f"2024-01-0{i + 2}", 10.0, 11.0, 9.0, 10.5, 1000.0] for i in range(n)]
    return symbol_payload(symbol, rows)


def test_verify_frozen_accepts_matching_hashes_and_rejects_tampering():
    frozen = {"AAA": _payload("AAA"), "XU100": _payload("XU100")}
    hashes = {s: content_sha256(p) for s, p in frozen.items()}
    manifest = {
        "symbols": {s: {"status": "OK", "content_sha256": h} for s, h in hashes.items()},
        "dataset_sha256": content_sha256(hashes),
    }
    frames = verify_frozen(frozen, manifest)
    assert set(frames) == {"AAA", "XU100"}
    frozen["AAA"]["rows"][0][4] = 10.6
    with pytest.raises(DatasetIntegrityError):
        verify_frozen(frozen, manifest)


def test_verify_frozen_rejects_unlisted_symbol():
    frozen = {"AAA": _payload("AAA")}
    h = {"AAA": content_sha256(frozen["AAA"])}
    manifest = {"symbols": {"AAA": {"status": "OK", "content_sha256": h["AAA"]}}, "dataset_sha256": content_sha256(h)}
    frozen["BBB"] = _payload("BBB")
    with pytest.raises(DatasetIntegrityError):
        verify_frozen(frozen, manifest)


def _bars(days, volume=1000.0):
    rows = [[d.isoformat(), 10.0, 11.0, 9.0, 10.5, volume] for d in days]
    return rows_to_frame(rows)


def test_split_into_segments_breaks_on_missing_expected_session():
    # 2024-01-02 Salı .. 2024-01-10 Çarşamba; 2024-01-05 (Cuma) eksik
    days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 8), date(2024, 1, 9)]
    segments = split_into_segments(_bars(days))
    assert [len(s) for s in segments] == [3, 2]


def test_split_into_segments_weekend_is_not_a_gap():
    days = [date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 8)]
    assert [len(s) for s in split_into_segments(_bars(days))] == [3]


def test_preprocess_drops_holiday_phantom_and_counts_invalid_rows():
    # 2024-01-01 resmi tatil (Yılbaşı) -> hayalet bar; 2024-01-03 imkansız OHLC
    days = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    df = _bars(days)
    df.loc[df.index[2], "High"] = 5.0
    segments, q = preprocess_symbol("AAA", df, now=datetime(2024, 2, 1, tzinfo=timezone.utc))
    assert q.dropped_non_session_bars == 1
    assert q.invalid_integrity_bars == 1
    assert q.missing_expected_sessions == 1
    assert [len(s) for s in segments] == [1, 1]


def test_integrity_mask_flags_nan_and_nonpositive():
    df = _bars([date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)])
    df.loc[df.index[0], "Close"] = np.nan
    df.loc[df.index[1], "Low"] = 0.0
    assert integrity_invalid_mask(df).tolist() == [True, True, False]


# ---------------------------------------------------------------- technical blind


def test_technical_columns_cannot_be_evaluated_against_returns():
    panel = pd.DataFrame({"date": ["d"] * 30, "technical_score": np.arange(30.0), "ex_10": np.arange(30.0),
                          "pvfs": np.arange(30.0)})
    with pytest.raises(TechnicalBlindViolation):
        daily_ic(panel, "technical_score", "ex_10")
    with pytest.raises(TechnicalBlindViolation):
        daily_partial_ic(panel, "rsi14", ["technical_score"], "ex_10")


def test_blind_guard_scans_result_keys():
    assert_technical_blind({"P1": {"mean": 0.1}, "gate": {"decision": "DUR"}})
    with pytest.raises(TechnicalBlindViolation):
        assert_technical_blind({"x": [{"technical_ic_10": 0.05}]})


def test_circular_bootstrap_ci_contains_mean_on_short_series():
    x = np.random.default_rng(9).normal(0.0, 1.0, 30)
    x[:5] += 5.0  # uç gözlemler — düz moving-block bunları eksik örnekliyordu
    summary = st.summarize_series(pd.Series(x), 1, block_length=20)
    assert summary["ci_low"] <= summary["mean"] <= summary["ci_high"]
