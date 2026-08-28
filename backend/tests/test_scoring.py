import numpy as np
import pandas as pd
import pytest

from app.engines.technical.scoring import (
    aggregate_available_components,
    aggregate_available_components_series,
    clamp_component,
    clamp_components_df,
    is_available,
    safe_ratio,
)

NAN = float("nan")
INF = float("inf")
NEG_INF = float("-inf")

# Real Firestore weights (bkz. HATA 5B/5B1 audit'leri) -- gerçek production
# ağırlıklarıyla test etmek, testin gerçek contract'ı doğrulamasını sağlar.
WEIGHTS = {
    "rsi": 0.1667,
    "macd": 0.1667,
    "trend": 0.1667,
    "ema_slope": 0.2,
    "bollinger": 0.1667,
    "momentum": 0.1667,
    "roc": 0.1665,
}


# ---------------------------------------------------------------------------
# HATA 5B1 permanent test plan, madde A-F: is_available / clamp_component /
# safe_ratio -- temel non-finite semantics.
# ---------------------------------------------------------------------------


def test_finite_positive_is_available():
    assert is_available(42.5) is True


def test_finite_negative_is_available():
    assert is_available(-42.5) is True


def test_finite_zero_is_available():
    # HATA 5B1 kesin invariant: finite 0.0 MISSING DEĞİLDİR.
    assert is_available(0.0) is True


def test_none_is_unavailable():
    assert is_available(None) is False


def test_nan_is_unavailable():
    assert is_available(NAN) is False


def test_positive_inf_is_unavailable():
    assert is_available(INF) is False


def test_negative_inf_is_unavailable():
    assert is_available(NEG_INF) is False


def test_is_available_none_does_not_raise_typeerror():
    # math.isfinite(None) TypeError fırlatır -- is_available None'ı ÖNCE
    # ayırt etmeli, isfinite'a hiç ULAŞMAMALI.
    assert is_available(None) is False  # exception atmamalı


def test_clamp_component_preserves_nan_not_fabricate_100():
    # HATA 5B1 KÖK BULGU: eski canlı `_clamp` (max(low,min(high,value)))
    # NaN'ı DETERMİNİSTİK olarak +100.0'a çeviriyordu. Düzeltilmiş
    # `clamp_component` NaN'ı NaN olarak KORUR.
    result = clamp_component(NAN)
    assert result != result  # NaN != NaN -- tek güvenilir NaN testi


def test_clamp_component_excludes_positive_inf_not_100():
    # FINAL CONTRACT AUDIT düzeltmesi: +inf artık +100'e CLAMP EDİLMEZ --
    # unavailable (NaN) sayılır.
    result = clamp_component(INF)
    assert result != result


def test_clamp_component_excludes_negative_inf_not_neg_100():
    result = clamp_component(NEG_INF)
    assert result != result


def test_clamp_component_clamps_finite_out_of_range_values():
    assert clamp_component(150.0) == 100.0
    assert clamp_component(-150.0) == -100.0


def test_clamp_component_passes_through_finite_zero():
    assert clamp_component(0.0) == 0.0


def test_safe_ratio_zero_denominator_is_unavailable():
    result = safe_ratio(5.0, 0.0)
    assert result != result


def test_safe_ratio_zero_over_zero_is_unavailable():
    result = safe_ratio(0.0, 0.0)
    assert result != result


def test_safe_ratio_nan_numerator_is_unavailable():
    result = safe_ratio(NAN, 5.0)
    assert result != result


def test_safe_ratio_nan_denominator_is_unavailable():
    result = safe_ratio(5.0, NAN)
    assert result != result


def test_safe_ratio_normal_division():
    assert safe_ratio(10.0, 2.0) == 5.0


# ---------------------------------------------------------------------------
# HATA 5B1 permanent test plan, madde G/H/I: partial/renormalization exact
# reference -- HATA 5B1 final contract audit'inde hesaplanan gerçek sayılar.
# ---------------------------------------------------------------------------

# Sabit fixture: HATA 5B1 raporundaki "exact partial-component example".
_FIXTURE = {"rsi": 40.0, "macd": 20.0, "trend": 0.0, "ema_slope": 30.0, "bollinger": NAN, "momentum": -10.0, "roc": 20.0}


def test_one_missing_component_exact_renormalization():
    # HATA 5B1 raporu: Bollinger NaN -> correct score = 17.10.
    assert aggregate_available_components(_FIXTURE, WEIGHTS) == 17.1


@pytest.mark.parametrize(
    "missing_key, expected",
    [
        ("rsi", 6.61),
        ("macd", 9.84),
        ("trend", 13.06),
        ("ema_slope", 7.5),
        ("bollinger", 17.1),
        ("momentum", 14.68),
        ("roc", 9.84),
    ],
)
def test_each_of_seven_components_missing_exact_reference(missing_key, expected):
    # HATA 5B1 raporunun "7 missing-component matrix" tablosundaki CORRECT
    # (renormalized) sütunu -- her bileşenin AYRI AYRI eksik olduğu senaryo.
    fixture = dict(_FIXTURE)
    fixture["bollinger"] = -25.0  # taban değeri finite yap (yalnız test edilen key missing)
    fixture[missing_key] = NAN
    assert aggregate_available_components(fixture, WEIGHTS) == pytest.approx(expected, abs=0.01)


def test_all_components_unavailable_returns_none_not_zero_not_hundred():
    all_missing = {k: NAN for k in WEIGHTS}
    assert aggregate_available_components(all_missing, WEIGHTS) is None


def test_all_available_matches_legacy_exact_score():
    # HATA 5A/5B tarihinde ölçülen gerçek THYAO 1y son gün skoru ile aynı
    # formülün (hiçbir component missing değilken) birebir aynı sonucu
    # üretmesi -- non-regression.
    all_available = {"rsi": 40.0, "macd": 20.0, "trend": 0.0, "ema_slope": 30.0, "bollinger": -25.0, "momentum": -10.0, "roc": 20.0}
    weight_sum = sum(WEIGHTS.values())
    expected_raw = sum(all_available[k] * WEIGHTS[k] for k in all_available)
    expected = round(max(-100.0, min(100.0, expected_raw / weight_sum)), 2)
    assert aggregate_available_components(all_available, WEIGHTS) == expected


# ---------------------------------------------------------------------------
# HATA 5B1 permanent test plan, madde K/L/M/N: RSI flat valid-zero vs
# ATR/Bollinger zero-denominator unavailable -- indicator-by-indicator.
# ---------------------------------------------------------------------------


def test_flat_rsi_component_is_available_valid_zero():
    # indicators.rsi()'ın KENDİ kasıtlı tanımı: düz seride RSI=50 ->
    # component=(50-50)*2=0.0 -- GERÇEK geçerli sıfır, unavailable DEĞİL.
    rsi_component = (50.0 - 50) * 2
    assert is_available(rsi_component) is True
    assert rsi_component == 0.0


def test_atr_zero_makes_macd_unavailable():
    # Düz fiyatta ATR=0 VE macd_hist de 0 -> 0/0 belirsizlik, "geçerli sıfır"
    # DEĞİL.
    macd_component = safe_ratio(0.0, 0.0) * 25
    assert is_available(macd_component) is False


def test_atr_zero_makes_momentum_unavailable():
    momentum_component = safe_ratio(0.0, 0.0) * 20
    assert is_available(momentum_component) is False


def test_bollinger_width_zero_makes_bollinger_unavailable():
    # Düz fiyatta close==middle VE band_width==0 -> 0/0.
    bollinger_component = safe_ratio(0.0, 0.0) * 100
    assert is_available(bollinger_component) is False


# ---------------------------------------------------------------------------
# HATA 5B1 permanent test plan, madde O/P/Q: live scalar == backtest
# vectorized parity -- PAYLAŞILAN aggregator fonksiyonlarının KENDİSİ
# üzerinden (gerçek live/backtest engine'lerini çalıştırmadan) doğrudan kilit.
# ---------------------------------------------------------------------------


def test_scalar_and_vectorized_aggregation_agree_with_one_missing_component():
    scalar_result = aggregate_available_components(_FIXTURE, WEIGHTS)
    df = pd.DataFrame([_FIXTURE])
    vectorized_result = aggregate_available_components_series(df, WEIGHTS).iloc[0]
    assert scalar_result == vectorized_result


def test_scalar_and_vectorized_aggregation_agree_with_finite_zero():
    fixture = {"rsi": 0.0, "macd": 20.0, "trend": 0.0, "ema_slope": 30.0, "bollinger": -25.0, "momentum": -10.0, "roc": 20.0}
    scalar_result = aggregate_available_components(fixture, WEIGHTS)
    df = pd.DataFrame([fixture])
    vectorized_result = aggregate_available_components_series(df, WEIGHTS).iloc[0]
    assert scalar_result == vectorized_result


@pytest.mark.parametrize("bad_value", [NAN, INF, NEG_INF])
def test_scalar_and_vectorized_aggregation_agree_on_non_finite_cases(bad_value):
    fixture = dict(_FIXTURE)
    fixture["bollinger"] = bad_value
    scalar_result = aggregate_available_components(fixture, WEIGHTS)
    df = pd.DataFrame([fixture])
    vectorized_result = aggregate_available_components_series(df, WEIGHTS).iloc[0]
    assert scalar_result == vectorized_result


def test_vectorized_all_missing_returns_nan_not_zero_not_hundred():
    all_missing = {k: NAN for k in WEIGHTS}
    df = pd.DataFrame([all_missing])
    result = aggregate_available_components_series(df, WEIGHTS).iloc[0]
    assert result != result  # NaN


# ---------------------------------------------------------------------------
# clamp_components_df: availability must be derived from the RAW (unclamped)
# value, never from the post-clip value (an inf ratio must not look
# "available" just because .clip() turned it into a finite 100.0).
# ---------------------------------------------------------------------------


def test_clamp_components_df_excludes_inf_even_though_clip_would_make_it_finite():
    raw = pd.DataFrame({"a": [INF, 5.0], "b": [NAN, -300.0]})
    result = clamp_components_df(raw)
    assert result["a"].iloc[0] != result["a"].iloc[0]  # NaN, NOT clipped to 100
    assert result["a"].iloc[1] == 5.0
    assert result["b"].iloc[0] != result["b"].iloc[0]  # NaN stays NaN
    assert result["b"].iloc[1] == -100.0  # finite out-of-range value IS clamped
