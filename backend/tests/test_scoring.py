import numpy as np
import pandas as pd
import pytest

from app.engines.technical.scoring import (
    DEFAULT_TECHNICAL_FAMILY_WEIGHTS,
    FAMILY_MEMBERSHIP,
    aggregate_available_components,
    aggregate_available_components_series,
    aggregate_available_scores,
    aggregate_available_scores_series,
    clamp_component,
    clamp_components_df,
    compute_scoring_config_hash,
    is_available,
    resolve_family_weights,
    resolve_indicator_weights,
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


# ---------------------------------------------------------------------------
# HATA 5B2D permanent test plan, madde A-M: family-level (component -> family
# -> technical_score) hierarchical aggregation.
# ---------------------------------------------------------------------------

# HATA 5B2D — hand-computed fixture (madde 25): "current explicit component
# weights" (HATA 5B2C sonrası production Firestore, 27.08.2026) kullanılarak
# ELLE hesaplanmış referans değerler.
_FAMILY_FIXTURE = {
    "trend": 30.0,
    "rsi": 40.0,
    "bollinger": 20.0,
    "ema_slope": -10.0,
    "macd": 5.0,
    "momentum": 50.0,
    "roc": 60.0,
}


def test_family_membership_exact():
    # madde A: family membership -- versioned kod sabiti, taxonomy A (HATA
    # 5B2A/5B2B'de kabul edilen, 92-sembol audit'iyle doğrulanan final grouping).
    assert FAMILY_MEMBERSHIP == {
        "trend": ("trend",),
        "oscillator_position": ("rsi", "bollinger", "ema_slope"),
        "momentum_rate": ("macd", "momentum", "roc"),
    }


def test_default_family_weights_exact():
    # madde B: eşit (1/3) top-level family weight prior -- "bilimsel olarak
    # optimal" İDDİA EDİLMİYOR, minimal parametreli nötr bir prior (bkz. HATA
    # 5B2B madde 29). Yuvarlanmış `0.3333` literal'leri KULLANILMAMALI (toplamı
    # sessizce 0.9999 yapardı) -- `1.0/3.0` kullanılmalı.
    assert DEFAULT_TECHNICAL_FAMILY_WEIGHTS == {
        "trend": pytest.approx(1.0 / 3.0),
        "oscillator_position": pytest.approx(1.0 / 3.0),
        "momentum_rate": pytest.approx(1.0 / 3.0),
    }
    assert sum(DEFAULT_TECHNICAL_FAMILY_WEIGHTS.values()) == pytest.approx(1.0)


def test_resolve_family_weights_missing_document_uses_default_without_writing():
    # madde C (kısmen): doküman HİÇ yoksa (get_raw() -> None) DEFAULT
    # kullanılır -- Firestore'a hiçbir şey YAZILMAZ (bu fonksiyon salt-okunur).
    assert resolve_family_weights(None) == DEFAULT_TECHNICAL_FAMILY_WEIGHTS


def test_resolve_family_weights_valid_complete_document_is_used_as_is():
    # madde C: geçerli/tam bir doküman olduğu gibi kullanılır.
    valid = {"trend": 0.2, "oscillator_position": 0.5, "momentum_rate": 0.3}
    assert resolve_family_weights(valid) == valid


@pytest.mark.parametrize(
    "partial_doc",
    [
        {"trend": 0.5, "oscillator_position": 0.5},  # eksik: momentum_rate
        {"trend": 1.0 / 3.0, "oscillator_position": 1.0 / 3.0, "momentum_rate": 1.0 / 3.0, "extra_family": 0.1},  # fazla key
        {"unrelated_key": 1.0},  # tamamen alakasız
    ],
)
def test_resolve_family_weights_partial_or_unknown_keys_fail_fast(partial_doc):
    # madde D: eksik/fazla anahtarlı bir doküman SESSİZCE default'larla
    # birleştirilmez (HATA 5B2C'nin kök nedeni tekrarlanmıyor) -- fail-fast.
    with pytest.raises(ValueError):
        resolve_family_weights(partial_doc)


@pytest.mark.parametrize(
    "invalid_doc",
    [
        {"trend": NAN, "oscillator_position": 0.5, "momentum_rate": 0.5},
        {"trend": INF, "oscillator_position": 0.5, "momentum_rate": 0.5},
        {"trend": -0.1, "oscillator_position": 0.5, "momentum_rate": 0.6},  # negatif
        {"trend": "0.3", "oscillator_position": 0.3, "momentum_rate": 0.4},  # non-numeric
        {"trend": True, "oscillator_position": 0.3, "momentum_rate": 0.4},  # bool (isinstance(bool,int) tuzağı)
    ],
)
def test_resolve_family_weights_invalid_values_fail_fast(invalid_doc):
    with pytest.raises(ValueError):
        resolve_family_weights(invalid_doc)


def test_resolve_family_weights_all_zero_fails_fast():
    with pytest.raises(ValueError):
        resolve_family_weights({"trend": 0.0, "oscillator_position": 0.0, "momentum_rate": 0.0})


# ---------------------------------------------------------------------------
# HATA 5B2D FINAL COMMIT GATE, madde 1-4: `technical_indicator_weights` --
# `resolve_family_weights()`'ten KASITLI OLARAK FARKLI bir invariant: bu
# doküman 1.7.0 family mimarisi için REQUIRED bir production config'tir
# (HATA 5B2C ile 7/7 explicit hale getirildi, code DEFAULT_WEIGHTS'ten
# DEĞERCE FARKLIDIR) -- dokümanın TAMAMEN KAYBOLMASI "normal default case"
# DEĞİL, production config corruption/deletion'dır -- FAIL-FAST (sessiz
# DEFAULT fallback YOK, `defaults` parametresi KALDIRILDI).
# ---------------------------------------------------------------------------


def test_resolve_indicator_weights_missing_document_fails_fast():
    # madde 1/2: doküman TAMAMEN yoksa artık `DEFAULT_WEIGHTS`'e SESSİZCE
    # düşülmez -- "normal default case" değil, production config corruption/
    # deletion olarak ele alınır.
    with pytest.raises(ValueError):
        resolve_indicator_weights(None)


def test_resolve_indicator_weights_valid_complete_document_is_used_as_is():
    assert resolve_indicator_weights(WEIGHTS) == WEIGHTS


def test_resolve_indicator_weights_stale_six_key_document_fails_fast():
    # HATA 5B2C'nin kök nedeninin (`ema_slope` eksik 6-key doküman) artık
    # SESSİZCE tamamlanmadığının doğrudan regresyon kilidi -- bu, "missing
    # document" testinden AYRIDIR (madde 7): PARTIAL bir doküman, TAMAMEN
    # eksik bir doküman DEĞİL.
    stale_six_key = {"rsi": 0.1667, "macd": 0.1667, "trend": 0.1667, "bollinger": 0.1667, "momentum": 0.1667, "roc": 0.1665}
    with pytest.raises(ValueError):
        resolve_indicator_weights(stale_six_key)


def test_resolve_indicator_weights_unknown_extra_key_fails_fast():
    with_extra = dict(WEIGHTS, unknown_component=0.1)
    with pytest.raises(ValueError):
        resolve_indicator_weights(with_extra)


@pytest.mark.parametrize(
    "bad_value",
    [NAN, INF, NEG_INF, -0.1, "0.1", True],
)
def test_resolve_indicator_weights_invalid_value_fails_fast(bad_value):
    invalid = dict(WEIGHTS, rsi=bad_value)
    with pytest.raises(ValueError):
        resolve_indicator_weights(invalid)


def test_resolve_indicator_weights_family_with_all_zero_weights_fails_fast():
    # her family içinde en az bir POZİTİF weight olmalı -- macd/momentum/roc
    # (momentum_rate family) hepsi 0 ise bu family KONFİGÜRE seviyesinde HER
    # ZAMAN weight_sum=0 üretir (veri mevcudiyetinden bağımsız bir config
    # hatası, "geçici unavailable" ile karışmamalı).
    all_zero_momentum_rate = dict(WEIGHTS, macd=0.0, momentum=0.0, roc=0.0)
    with pytest.raises(ValueError):
        resolve_indicator_weights(all_zero_momentum_rate)


def test_resolve_indicator_weights_single_zero_weight_in_family_is_allowed():
    # >=0 izinlidir -- yalnızca family'nin TÜMÜ sıfır olduğunda fail-fast.
    one_zero = dict(WEIGHTS, macd=0.0)
    result = resolve_indicator_weights(one_zero)
    assert result == one_zero


# Hand-computed fixture'ın kullandığı gerçek (post-HATA 5B2C, explicit 7/7)
# production `technical_indicator_weights`.
_FAMILY_TEST_WEIGHTS = WEIGHTS


def _family_scores(components: dict, round_digits: int | None = None) -> dict:
    # FINAL PRE-COMMIT GATE (madde 4/5): production'la AYNI contract --
    # varsayılan `round_digits=None` (TAM HASSASİYET) çünkü bu fonksiyon
    # Level 1'i (component -> family) simüle ediyor; Level 2 (family ->
    # technical_score) bu TAM HASSASİYETLİ değerler üzerinden çalışmalı,
    # aksi halde "double rounding" ile final skor gerçek sonuçtan sapar.
    return {
        family: aggregate_available_scores(
            {m: components[m] for m in members if m in components},
            {m: _FAMILY_TEST_WEIGHTS[m] for m in members},
            round_digits=round_digits,
        )
        for family, members in FAMILY_MEMBERSHIP.items()
    }


def test_hand_computed_seven_component_fixture_exact():
    # madde M / FINAL PRE-COMMIT GATE madde 4/5: tüm 7 component available --
    # ELLE hesaplanmış TAM HASSASİYETLİ referans (madde 25):
    #   oscillator_position = 15.001874765654291
    #   momentum_rate       = 38.32466493298659
    #   trend               = 30.0 (tek üyeli family, yuvarlama farkı YOK)
    # Final technical_score bu TAM HASSASİYETLİ family değerlerinden
    # hesaplanır, EN SONDA BİR KEZ round(2) uygulanır -> 27.78 (double
    # rounding ile YANLIŞ üretilecek 27.77 DEĞİL).
    fam_scores = _family_scores(_FAMILY_FIXTURE)
    assert fam_scores["trend"] == 30.0
    assert fam_scores["oscillator_position"] == pytest.approx(15.001874765654291)
    assert fam_scores["momentum_rate"] == pytest.approx(38.32466493298659)

    final_score = aggregate_available_scores(fam_scores, DEFAULT_TECHNICAL_FAMILY_WEIGHTS)
    assert final_score == 27.78  # TEK, EN SON yuvarlama -- 27.77 (double-rounded) DEĞİL

    # Persisted/display `family_scores` (HATA 5B2D madde 7/8): TAM
    # HASSASİYETLİ değerlerden AYRICA round(2) ile üretilir -- bu yuvarlama
    # final_score hesabına GERİ BESLENMEZ (yukarıdaki final_score zaten
    # `fam_scores`'un TAM HASSASİYETLİ halinden hesaplandı).
    stored_family_scores = {k: round(v, 2) for k, v in fam_scores.items()}
    assert stored_family_scores == {"trend": 30.0, "oscillator_position": 15.0, "momentum_rate": 38.32}


def test_family_score_rounding_is_display_only_does_not_feed_back_into_final_score():
    # FINAL PRE-COMMIT GATE madde 7, doğrudan regresyon kilidi: `final_score`
    # ROUNDED (persisted) family_scores'tan YENİDEN HESAPLANIRSA yanlış
    # (double-rounded) bir sonuç üretir -- bu test bu ikisinin FARKLI
    # olduğunu (yani production kodun ROUNDED değil FULL-PRECISION family
    # dict'i kullandığını) doğrudan kanıtlar.
    fam_scores_full_precision = _family_scores(_FAMILY_FIXTURE)
    fam_scores_rounded_for_display = {k: round(v, 2) for k, v in fam_scores_full_precision.items()}

    correct_final = aggregate_available_scores(fam_scores_full_precision, DEFAULT_TECHNICAL_FAMILY_WEIGHTS)
    incorrect_double_rounded_final = aggregate_available_scores(
        fam_scores_rounded_for_display, DEFAULT_TECHNICAL_FAMILY_WEIGHTS
    )

    assert correct_final == 27.78
    assert incorrect_double_rounded_final == 27.77
    assert correct_final != incorrect_double_rounded_final  # fark GERÇEK, production DOĞRU tarafı kullanmalı


def test_rounding_contract_does_not_flip_classification_at_threshold_boundary():
    # FINAL PRE-COMMIT GATE madde 6: gerçek bir sınır-durumu fixture'ı (brute
    # search ile bulundu) -- tam-hassasiyetli final skor (15.01) ve HATALI
    # double-rounded final skor (15.00) ±15 sınırının TAM İKİ YANINA düşüyor.
    # Production'ın (round_digits=None Level 1 -> tek round(2) Level 2)
    # DOĞRU tarafta kaldığını, `technical/engine.py`'nin KENDİ ±15 "trend"
    # sınıflandırma kuralının (`>15`) buna göre DOĞRU (BULLISH, NEUTRAL
    # DEĞİL) sonucu ürettiğini kilitler.
    boundary_fixture = {
        "trend": 28.6224,
        "rsi": 35.9455,
        "bollinger": 49.2159,
        "ema_slope": 32.0236,
        "macd": -35.3556,
        "momentum": 11.8698,
        "roc": -43.2212,
    }
    raw_family_scores = _family_scores(boundary_fixture)
    correct_final = aggregate_available_scores(raw_family_scores, DEFAULT_TECHNICAL_FAMILY_WEIGHTS)
    assert correct_final == 15.01

    # Karşıt (HATALI) double-rounded hesap -- yalnızca bu farkın GERÇEK
    # olduğunu göstermek için, production KULLANMIYOR.
    rounded_for_display = {k: round(v, 2) for k, v in raw_family_scores.items()}
    double_rounded_final = aggregate_available_scores(rounded_for_display, DEFAULT_TECHNICAL_FAMILY_WEIGHTS)
    assert double_rounded_final == 15.00
    assert correct_final != double_rounded_final  # sınırın TAM İKİ YANI -- fark PRATİKTE önemli

    # `technical/engine.py`'nin KENDİ ±15 trend sınıflandırma kuralı (kod
    # DEĞİŞTİRİLMEDİ, threshold sabit) -- DOĞRU (tam hassasiyetli) final
    # skorla BULLISH, double-rounded (yanlış) skorla NEUTRAL olurdu.
    correct_trend = "BULLISH" if correct_final > 15 else ("BEARISH" if correct_final < -15 else "NEUTRAL")
    wrong_trend_if_double_rounded = (
        "BULLISH" if double_rounded_final > 15 else ("BEARISH" if double_rounded_final < -15 else "NEUTRAL")
    )
    assert correct_trend == "BULLISH"
    assert wrong_trend_if_double_rounded == "NEUTRAL"
    assert correct_trend != wrong_trend_if_double_rounded  # tam da önlenmesi gereken sınır kayması


def test_missing_member_renormalizes_within_family_not_across_families():
    # madde 26/G: bollinger NaN -> oscillator_position yalnız rsi+ema_slope
    # üzerinden (TAM HASSASİYETLE) renormalize edilir, ama family'nin
    # KENDİSİ hâlâ available olduğundan top-level family weight 1/3 olarak
    # KALIR.
    fixture = dict(_FAMILY_FIXTURE)
    fixture["bollinger"] = NAN
    fam_scores = _family_scores(fixture)
    assert fam_scores["trend"] == 30.0
    assert fam_scores["oscillator_position"] == pytest.approx(12.729751840741748)
    assert fam_scores["momentum_rate"] == pytest.approx(38.32466493298659)
    assert round(fam_scores["oscillator_position"], 2) == 12.73  # display/provenance yuvarlaması
    final_score = aggregate_available_scores(fam_scores, DEFAULT_TECHNICAL_FAMILY_WEIGHTS)
    assert final_score == 27.02


def test_whole_family_missing_renormalizes_across_remaining_families():
    # madde 27/H: macd/momentum/roc TAMAMI unavailable -> momentum_rate
    # family = None (0.0 UYDURULMAZ) -- kalan trend+oscillator_position
    # (TAM HASSASİYETLE) eşit ağırlıkla renormalize edilir.
    fixture = dict(_FAMILY_FIXTURE)
    fixture["macd"] = NAN
    fixture["momentum"] = NAN
    fixture["roc"] = NAN
    fam_scores = _family_scores(fixture)
    assert fam_scores["momentum_rate"] is None
    assert fam_scores["trend"] == 30.0
    assert fam_scores["oscillator_position"] == pytest.approx(15.001874765654291)
    final_score = aggregate_available_scores(fam_scores, DEFAULT_TECHNICAL_FAMILY_WEIGHTS)
    assert final_score == 22.5


def test_all_families_unavailable_returns_none_not_zero():
    # madde 28/I: 7 component'in TAMAMI unavailable -> 3 family de None ->
    # technical_score None (0.0/100.0 UYDURULMAZ, HATA 5B1 contract'ı
    # RECURSIVE olarak family seviyesinde de korunuyor).
    all_missing = {k: NAN for k in _FAMILY_FIXTURE}
    fam_scores = _family_scores(all_missing)
    assert fam_scores == {"trend": None, "oscillator_position": None, "momentum_rate": None}
    final_score = aggregate_available_scores(fam_scores, DEFAULT_TECHNICAL_FAMILY_WEIGHTS)
    assert final_score is None


def test_all_zero_components_produce_zero_not_none():
    # madde 29: 7 component'in TAMAMI finite 0.0 (valid zero, unavailable
    # DEĞİL) -> 3 family de 0.0 -> technical_score=0.0, None İLE KARIŞMAZ.
    all_zero = {k: 0.0 for k in _FAMILY_FIXTURE}
    fam_scores = _family_scores(all_zero)
    assert fam_scores == {"trend": 0.0, "oscillator_position": 0.0, "momentum_rate": 0.0}
    final_score = aggregate_available_scores(fam_scores, DEFAULT_TECHNICAL_FAMILY_WEIGHTS)
    assert final_score == 0.0
    assert final_score is not None


def test_within_family_configured_relative_weight_matches_hand_fixture():
    # madde E: `technical_indicator_weights`'in relative oranları (eşit
    # DEĞİL, ör. ema_slope=0.2000 > rsi/bollinger=0.1667) family içi
    # ağırlıklandırmada KULLANILIYOR -- eşit ağırlıkla aynı fixture FARKLI
    # bir sonuç üretir, bu da "configured-relative" contract'ının GERÇEKTEN
    # etkili olduğunu kanıtlar.
    fam_scores_configured = _family_scores(_FAMILY_FIXTURE)
    equal_weights = {m: 1.0 for members in FAMILY_MEMBERSHIP.values() for m in members}
    fam_scores_equal = {
        family: aggregate_available_scores(
            {m: _FAMILY_FIXTURE[m] for m in members}, {m: equal_weights[m] for m in members}, round_digits=None
        )
        for family, members in FAMILY_MEMBERSHIP.items()
    }
    assert fam_scores_configured["oscillator_position"] == pytest.approx(15.001874765654291)
    assert fam_scores_equal["oscillator_position"] == pytest.approx((40.0 + 20.0 - 10.0) / 3)
    assert fam_scores_configured["oscillator_position"] != fam_scores_equal["oscillator_position"]


# ---------------------------------------------------------------------------
# HATA 5B2D permanent test plan, madde J/K/L: scalar (aggregate_available_
# scores) == vectorized (aggregate_available_scores_series) family aggregation
# parity -- generic aliases HATA 5B1'in AYNI fonksiyonlarını yeniden kullanır.
# ---------------------------------------------------------------------------


def _vectorized_family_scores(components: dict) -> pd.DataFrame:
    # Production'la AYNI contract: `round_digits=None` (TAM HASSASİYET) --
    # bkz. `_family_scores()` yorumu.
    df = pd.DataFrame([components])
    return pd.DataFrame(
        {
            family: aggregate_available_scores_series(
                df[[m for m in members if m in df.columns]],
                {m: _FAMILY_TEST_WEIGHTS[m] for m in members},
                round_digits=None,
            )
            for family, members in FAMILY_MEMBERSHIP.items()
        }
    )


@pytest.mark.parametrize(
    "case_name, components",
    [
        ("all_available", _FAMILY_FIXTURE),
        ("finite_zero", {**_FAMILY_FIXTURE, "trend": 0.0, "rsi": 0.0}),
        ("missing_component_inside_family", {**_FAMILY_FIXTURE, "bollinger": NAN}),
        ("whole_family_missing", {**_FAMILY_FIXTURE, "macd": NAN, "momentum": NAN, "roc": NAN}),
        ("plus_inf", {**_FAMILY_FIXTURE, "roc": INF}),
        ("neg_inf", {**_FAMILY_FIXTURE, "momentum": NEG_INF}),
        ("all_families_unavailable", {k: NAN for k in _FAMILY_FIXTURE}),
    ],
)
def test_scalar_vectorized_family_aggregation_parity(case_name, components):
    # NOT: `round_digits=None` (TAM HASSASİYET) modunda scalar (saf Python
    # float) ve vectorized (pandas/numpy) hesaplama yolları son bitte (ULP
    # seviyesinde) farklı yuvarlama üretebilir (ör. toplama SIRASI farklı) --
    # bu bir contract ihlali DEĞİL, `pytest.approx` ile karşılaştırılır.
    # `round_digits=2` (varsayılan, final skor) modunda bu fark zaten
    # yuvarlamayla MASKELENİR (bkz. final parity assertion, tam eşitlik).
    scalar_fam = _family_scores(components)
    vector_fam_df = _vectorized_family_scores(components)
    for family in FAMILY_MEMBERSHIP:
        vector_value = vector_fam_df[family].iloc[0]
        scalar_value = scalar_fam[family]
        if scalar_value is None:
            assert vector_value != vector_value  # NaN
        else:
            assert vector_value == pytest.approx(scalar_value)

    scalar_final = aggregate_available_scores(scalar_fam, DEFAULT_TECHNICAL_FAMILY_WEIGHTS)
    vector_final = aggregate_available_scores_series(vector_fam_df, DEFAULT_TECHNICAL_FAMILY_WEIGHTS).iloc[0]
    if scalar_final is None:
        assert vector_final != vector_final  # NaN
    else:
        assert vector_final == scalar_final  # round(2) -- ULP farkı burada MASKELENİR, tam eşitlik beklenir


# ---------------------------------------------------------------------------
# HATA 5B2D TRUE FINAL COMMIT GATE, madde 9: `compute_scoring_config_hash`
# determinism -- cache'in yeni `scoring_config_hash` karşılaştırmasının
# temelini oluşturur.
# ---------------------------------------------------------------------------


def test_scoring_config_hash_is_deterministic_regardless_of_dict_insertion_order():
    indicator_a = {"rsi": 0.1, "macd": 0.1, "trend": 0.15, "ema_slope": 0.2, "bollinger": 0.1, "momentum": 0.15, "roc": 0.2}
    # AYNI key/value'lar, TAMAMEN FARKLI insertion sırasıyla.
    indicator_b = {"roc": 0.2, "momentum": 0.15, "bollinger": 0.1, "ema_slope": 0.2, "trend": 0.15, "macd": 0.1, "rsi": 0.1}
    family_a = {"trend": 1 / 3, "oscillator_position": 1 / 3, "momentum_rate": 1 / 3}
    family_b = {"momentum_rate": 1 / 3, "trend": 1 / 3, "oscillator_position": 1 / 3}

    assert compute_scoring_config_hash(indicator_a, family_a) == compute_scoring_config_hash(indicator_b, family_b)


def test_scoring_config_hash_changes_when_a_weight_value_changes():
    indicator = dict(WEIGHTS)
    family = dict(DEFAULT_TECHNICAL_FAMILY_WEIGHTS)
    baseline = compute_scoring_config_hash(indicator, family)

    changed_indicator = dict(indicator, rsi=indicator["rsi"] + 0.0001)
    assert compute_scoring_config_hash(changed_indicator, family) != baseline

    changed_family = dict(family, trend=family["trend"] + 0.0001)
    assert compute_scoring_config_hash(indicator, changed_family) != baseline


def test_scoring_config_hash_does_not_confuse_indicator_and_family_namespaces():
    # `indicator_weights`/`family_weights` iki ayrı namespace altında
    # serileştirilir -- aralarında değer TAŞINMASI (toplam "içerik" aynı
    # kalsa bile) farklı bir hash üretmeli.
    indicator = {"a": 0.5, "b": 0.5}
    family = {"c": 0.3, "d": 0.7}
    original = compute_scoring_config_hash(indicator, family)

    swapped = compute_scoring_config_hash(family, indicator)  # namespace'ler TERS
    assert swapped != original


def test_scoring_config_hash_missing_family_default_equals_explicit_equal_document():
    # madde 7/F: `technical_family_weights` dokümanı HENÜZ production'da yok
    # -> `resolve_family_weights(None)` eşit-1/3 default döner. Pre-deploy
    # gate'te bu AYNI değerlerle explicit bir doküman oluşturulduğunda,
    # RESOLVED config (dolayısıyla hash) DEĞİŞMEMELİ -- dokümanın fiziksel
    # var/yok oluşu değil, RESOLVED scoring semantics hash'e girer.
    indicator = dict(WEIGHTS)
    missing_family_resolved = resolve_family_weights(None)
    explicit_equal_doc = {"trend": 1.0 / 3.0, "oscillator_position": 1.0 / 3.0, "momentum_rate": 1.0 / 3.0}
    explicit_family_resolved = resolve_family_weights(explicit_equal_doc)

    assert missing_family_resolved == explicit_family_resolved
    assert compute_scoring_config_hash(indicator, missing_family_resolved) == compute_scoring_config_hash(
        indicator, explicit_family_resolved
    )
