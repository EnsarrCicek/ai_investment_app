from datetime import datetime, timedelta, timezone

import pytest

from app.engines.macro.engine import (
    DEFAULT_SCALES,
    DEFAULT_WEIGHTS,
    MAX_OBSERVATION_AGE_DAYS,
    MacroAnalysisEngine,
    _is_fresh_observation,
    resolve_macro_scales,
    resolve_macro_weights,
)

NAN = float("nan")
INF = float("inf")
NEG_INF = float("-inf")

_NOW = datetime.now(timezone.utc)
_FRESH = _NOW  # bu run'daki tüm sabit fixture'lar için "şu an" -- freshness penceresi
# (5 gün) test çalışma süresine göre son derece geniş, flaky olma riski yok.


# ---------------------------------------------------------------------------
# resolve_macro_weights()
# ---------------------------------------------------------------------------


def test_resolve_macro_weights_missing_document_fails_fast():
    with pytest.raises(ValueError):
        resolve_macro_weights(None)


def test_resolve_macro_weights_partial_fails_fast():
    with pytest.raises(ValueError):
        resolve_macro_weights({"dxy": 0.2, "vix": 0.2})  # diğer 4 anahtar eksik


def test_resolve_macro_weights_extra_key_fails_fast():
    raw = dict(DEFAULT_WEIGHTS)
    raw["extra_indicator"] = 0.1
    with pytest.raises(ValueError):
        resolve_macro_weights(raw)


@pytest.mark.parametrize("bad_value", [True, False])
def test_resolve_macro_weights_bool_fails_fast(bad_value):
    raw = dict(DEFAULT_WEIGHTS)
    raw["dxy"] = bad_value
    with pytest.raises(ValueError):
        resolve_macro_weights(raw)


def test_resolve_macro_weights_string_fails_fast():
    raw = dict(DEFAULT_WEIGHTS)
    raw["dxy"] = "0.2"
    with pytest.raises(ValueError):
        resolve_macro_weights(raw)


@pytest.mark.parametrize("bad_value", [NAN, INF, NEG_INF])
def test_resolve_macro_weights_non_finite_fails_fast(bad_value):
    raw = dict(DEFAULT_WEIGHTS)
    raw["dxy"] = bad_value
    with pytest.raises(ValueError):
        resolve_macro_weights(raw)


def test_resolve_macro_weights_negative_fails_fast():
    raw = dict(DEFAULT_WEIGHTS)
    raw["dxy"] = -0.1
    with pytest.raises(ValueError):
        resolve_macro_weights(raw)


def test_resolve_macro_weights_all_zero_fails_fast():
    raw = {k: 0.0 for k in DEFAULT_WEIGHTS}
    with pytest.raises(ValueError):
        resolve_macro_weights(raw)


def test_resolve_macro_weights_individual_zero_with_total_positive_accepted():
    raw = dict(DEFAULT_WEIGHTS)
    raw["dxy"] = 0.0
    resolved = resolve_macro_weights(raw)
    assert resolved["dxy"] == 0.0
    assert resolved["vix"] == DEFAULT_WEIGHTS["vix"]


def test_resolve_macro_weights_valid_production_style_config_accepted():
    resolved = resolve_macro_weights(dict(DEFAULT_WEIGHTS))
    assert resolved == DEFAULT_WEIGHTS


# ---------------------------------------------------------------------------
# resolve_macro_scales()
# ---------------------------------------------------------------------------


def test_resolve_macro_scales_missing_document_fails_fast():
    with pytest.raises(ValueError):
        resolve_macro_scales(None)


def test_resolve_macro_scales_partial_fails_fast():
    with pytest.raises(ValueError):
        resolve_macro_scales({"dxy": 15.0, "vix": 2.0})


def test_resolve_macro_scales_extra_key_fails_fast():
    raw = dict(DEFAULT_SCALES)
    raw["extra_indicator"] = 5.0
    with pytest.raises(ValueError):
        resolve_macro_scales(raw)


@pytest.mark.parametrize("bad_value", [True, False])
def test_resolve_macro_scales_bool_fails_fast(bad_value):
    raw = dict(DEFAULT_SCALES)
    raw["dxy"] = bad_value
    with pytest.raises(ValueError):
        resolve_macro_scales(raw)


def test_resolve_macro_scales_string_fails_fast():
    raw = dict(DEFAULT_SCALES)
    raw["dxy"] = "15.0"
    with pytest.raises(ValueError):
        resolve_macro_scales(raw)


@pytest.mark.parametrize("bad_value", [NAN, INF, NEG_INF])
def test_resolve_macro_scales_non_finite_fails_fast(bad_value):
    raw = dict(DEFAULT_SCALES)
    raw["dxy"] = bad_value
    with pytest.raises(ValueError):
        resolve_macro_scales(raw)


def test_resolve_macro_scales_zero_fails_fast():
    # HATA 16B: weight'in aksine (tek tek 0 serbest), bir scale = 0 o göstergeyi
    # SESSİZCE devre dışı bırakır -- bu invalid'dir, tek tek dahi serbest DEĞİLDİR.
    raw = dict(DEFAULT_SCALES)
    raw["dxy"] = 0.0
    with pytest.raises(ValueError):
        resolve_macro_scales(raw)


def test_resolve_macro_scales_negative_fails_fast():
    raw = dict(DEFAULT_SCALES)
    raw["dxy"] = -15.0
    with pytest.raises(ValueError):
        resolve_macro_scales(raw)


def test_resolve_macro_scales_valid_production_style_config_accepted():
    resolved = resolve_macro_scales(dict(DEFAULT_SCALES))
    assert resolved == DEFAULT_SCALES


# ---------------------------------------------------------------------------
# MacroAnalysisEngine.analyze() — fakes
# ---------------------------------------------------------------------------


class _FakeConfigRepo:
    """HATA 16B: production path artık `get()` (auto-seed + sessiz partial-
    merge, HATA 5B2C'nin kök nedeni) DEĞİL `get_raw()` kullanıyor -- gerçek
    production'ı simüle etmek için geçerli/tam config'ler döner."""

    def __init__(self, weights=DEFAULT_WEIGHTS, scales=DEFAULT_SCALES):
        self._weights = weights
        self._scales = scales

    def get_raw(self, key):
        if key == "macro_indicator_weights":
            return dict(self._weights) if self._weights is not None else None
        if key == "macro_indicator_scales":
            return dict(self._scales) if self._scales is not None else None
        return None

    def get(self, key, defaults):
        raise AssertionError(
            f"get({key!r}, ...) çağrıldı -- production path artık get_raw() kullanmalı "
            "(HATA 16B: auto-seed/sessiz partial-merge YASAK)"
        )


class _FakeProvider:
    def __init__(self, changes):
        self._changes = changes
        self.called = False

    def get_indicator_changes(self):
        self.called = True
        return dict(self._changes)


class _AssertNotCalledProvider:
    """HATA 16B madde 10/22: config resolver'lar provider fetch'ten ÖNCE
    çalışmalı -- geçersiz config varsa hiçbir Yahoo çağrısı yapılmamalı."""

    def get_indicator_changes(self):
        raise AssertionError(
            "get_indicator_changes() çağrıldı -- config resolver'lar provider "
            "fetch'ten ÖNCE fail-fast etmeliydi"
        )


class _FakeSnapshotRepo:
    def __init__(self):
        self.added = []

    def add(self, snapshot):
        self.added.append(snapshot)
        return f"doc-{len(self.added)}"


_FULL_CHANGES = {
    "dxy": {"value": 100.0, "pct_change": 1.0, "observed_at": _FRESH},
    "us_10y_yield": {"value": 4.0, "pct_change": 2.0, "observed_at": _FRESH},
    "vix": {"value": 15.0, "pct_change": 10.0, "observed_at": _FRESH},
    "oil": {"value": 70.0, "pct_change": -3.0, "observed_at": _FRESH},
    "gold": {"value": 2000.0, "pct_change": 4.0, "observed_at": _FRESH},
    "usdtry": {"value": 32.0, "pct_change": 1.5, "observed_at": _FRESH},
}


def _engine(weights=DEFAULT_WEIGHTS, scales=DEFAULT_SCALES, changes=_FULL_CHANGES, provider=None, snapshot_repo=None):
    return MacroAnalysisEngine(
        provider=provider if provider is not None else _FakeProvider(changes),
        config_repo=_FakeConfigRepo(weights=weights, scales=scales),
        snapshot_repo=snapshot_repo if snapshot_repo is not None else _FakeSnapshotRepo(),
    )


# ---------------------------------------------------------------------------
# Config fail-fast happens BEFORE provider fetch, no write side-effect
# ---------------------------------------------------------------------------


def test_analyze_missing_weights_config_fails_fast_before_provider_call():
    config_repo = _FakeConfigRepo(weights=None, scales=DEFAULT_SCALES)
    engine = MacroAnalysisEngine(
        provider=_AssertNotCalledProvider(), config_repo=config_repo, snapshot_repo=_FakeSnapshotRepo()
    )
    with pytest.raises(ValueError):
        engine.analyze()


def test_analyze_missing_scales_config_fails_fast_before_provider_call():
    config_repo = _FakeConfigRepo(weights=DEFAULT_WEIGHTS, scales=None)
    engine = MacroAnalysisEngine(
        provider=_AssertNotCalledProvider(), config_repo=config_repo, snapshot_repo=_FakeSnapshotRepo()
    )
    with pytest.raises(ValueError):
        engine.analyze()


def test_analyze_all_weights_zero_config_fails_before_provider_call():
    all_zero = {k: 0.0 for k in DEFAULT_WEIGHTS}
    config_repo = _FakeConfigRepo(weights=all_zero, scales=DEFAULT_SCALES)
    engine = MacroAnalysisEngine(
        provider=_AssertNotCalledProvider(), config_repo=config_repo, snapshot_repo=_FakeSnapshotRepo()
    )
    with pytest.raises(ValueError):
        engine.analyze()


def test_analyze_no_config_write_side_effect_on_missing_config():
    # `_FakeConfigRepo.get()` çağrılırsa AssertionError fırlatır -- production
    # path'in `get_raw()` DIŞINDA hiçbir şey kullanmadığını, dolayısıyla hiçbir
    # auto-seed/write yapmadığını structurally kilitler.
    config_repo = _FakeConfigRepo(weights=None, scales=None)
    engine = MacroAnalysisEngine(
        provider=_AssertNotCalledProvider(), config_repo=config_repo, snapshot_repo=_FakeSnapshotRepo()
    )
    with pytest.raises(ValueError):
        engine.analyze()


# ---------------------------------------------------------------------------
# Zero available weight for THIS RUN -> explicit failure, no fake 0.0
# ---------------------------------------------------------------------------


def test_analyze_available_weight_zero_for_run_raises_no_snapshot_persisted():
    # Config toplamda geçerli (dxy=0, diğerleri pozitif) ama bu run'da SADECE
    # dxy verisi mevcut -- HATA 16A'nın confirmed production bug'ını (fake
    # macro_score=0.0) birebir yeniden üretir.
    weights = dict(DEFAULT_WEIGHTS)
    weights["dxy"] = 0.0
    snapshot_repo = _FakeSnapshotRepo()
    engine = _engine(
        weights=weights,
        changes={"dxy": {"value": 100.0, "pct_change": 1.0, "observed_at": _FRESH}},
        snapshot_repo=snapshot_repo,
    )

    with pytest.raises(ValueError):
        engine.analyze()

    assert snapshot_repo.added == []


def test_analyze_all_providers_missing_still_raises_unchanged():
    engine = _engine(changes={})
    with pytest.raises(ValueError):
        engine.analyze()


# ---------------------------------------------------------------------------
# Genuine neutral (0.0) must still persist as a real result
# ---------------------------------------------------------------------------


def test_analyze_genuine_zero_score_persists_successfully():
    # dxy component = +15.0 (pct_change=-1.0, scale=15.0), vix component = -15.0
    # (pct_change=+7.5, scale=2.0) -- eşit ağırlıklarla (0.5/0.5) tam olarak
    # birbirini götürür: gerçek/hesaplanmış nötr sonuç.
    weights = {
        "dxy": 0.5,
        "vix": 0.5,
        "us_10y_yield": 0.0,
        "oil": 0.0,
        "gold": 0.0,
        "usdtry": 0.0,
    }
    changes = {
        "dxy": {"value": 100.0, "pct_change": -1.0, "observed_at": _FRESH},
        "vix": {"value": 15.0, "pct_change": 7.5, "observed_at": _FRESH},
    }
    snapshot_repo = _FakeSnapshotRepo()
    engine = _engine(weights=weights, changes=changes, snapshot_repo=snapshot_repo)

    snapshot, doc_id = engine.analyze()

    assert snapshot.macro_score == 0.0
    assert doc_id is not None
    assert len(snapshot_repo.added) == 1


# ---------------------------------------------------------------------------
# Partial-data renormalization — exact numeric assertion
# ---------------------------------------------------------------------------


def test_analyze_partial_indicator_renormalization_exact_score():
    changes = {
        "dxy": {"value": 100.0, "pct_change": 1.0, "observed_at": _FRESH},
        "vix": {"value": 15.0, "pct_change": 10.0, "observed_at": _FRESH},
        "oil": {"value": 70.0, "pct_change": -3.0, "observed_at": _FRESH},
    }
    snapshot, _doc_id = _engine(changes=changes).analyze()

    # components: dxy=-15.0, vix=-20.0, oil=+15.0
    # available_weight = .20+.20+.15 = 0.55
    # weighted sum = -15*.20 + -20*.20 + 15*.15 = -3 -4 +2.25 = -4.75
    # macro_score = round(-4.75/0.55, 2) = -8.64
    assert snapshot.macro_score == -8.64


# ---------------------------------------------------------------------------
# Full normal case — locks the HATA 16A synthetic example, no regression
# ---------------------------------------------------------------------------


def test_analyze_full_normal_case_matches_audit_example():
    snapshot, doc_id = _engine().analyze()

    assert snapshot.macro_score == -13.75
    assert snapshot.confidence == 0.93
    assert doc_id is not None
    assert snapshot.components["dxy"] == -15.0
    assert snapshot.components["us_10y_yield"] == -20.0
    assert snapshot.components["vix"] == -20.0
    assert snapshot.components["oil"] == 15.0
    assert snapshot.components["gold"] == -32.0
    assert snapshot.components["usdtry"] == -12.0


# ---------------------------------------------------------------------------
# Config source sensitivity — proves resolved raw config is actually used
# ---------------------------------------------------------------------------


def test_analyze_config_weight_source_sensitivity():
    weights = dict(DEFAULT_WEIGHTS)
    weights["dxy"] = 0.40
    snapshot, _doc_id = _engine(weights=weights).analyze()

    # weighted sum = -15*.40 + -20*.20 + -20*.20 + 15*.15 + -32*.10 + -12*.15
    #              = -6.0 -4.0 -4.0 +2.25 -3.2 -1.8 = -16.75
    # available_weight = .40+.20+.20+.15+.10+.15 = 1.20
    # macro_score = round(-16.75/1.20, 2) = -13.96
    assert snapshot.macro_score == -13.96
    assert snapshot.macro_score != -13.75


def test_analyze_config_scale_source_sensitivity():
    scales = dict(DEFAULT_SCALES)
    scales["dxy"] = 30.0
    snapshot, _doc_id = _engine(scales=scales).analyze()

    # dxy component değişir: -1.0*30.0 -> clamp(-30.0) = -30.0 (öncekinden farklı: -15.0)
    # weighted sum = -30*.20 + -20*.20 + -20*.20 + 15*.15 + -32*.10 + -12*.15
    #              = -6.0 -4.0 -4.0 +2.25 -3.2 -1.8 = -16.75
    # available_weight = 1.00 (weights değişmedi)
    # macro_score = round(-16.75/1.00, 2) = -16.75
    assert snapshot.components["dxy"] == -30.0
    assert snapshot.macro_score == -16.75
    assert snapshot.macro_score != -13.75


# ---------------------------------------------------------------------------
# HATA 16C — _is_fresh_observation() unit-level freshness rule
# ---------------------------------------------------------------------------


def test_is_fresh_observation_exact_boundary_inclusive():
    observed_at = _NOW - timedelta(days=MAX_OBSERVATION_AGE_DAYS)
    assert _is_fresh_observation(observed_at, _NOW) is True


def test_is_fresh_observation_one_day_past_boundary_is_stale():
    observed_at = _NOW - timedelta(days=MAX_OBSERVATION_AGE_DAYS + 1)
    assert _is_fresh_observation(observed_at, _NOW) is False


def test_is_fresh_observation_two_day_weekend_style_gap_not_stale():
    # Örnek: Cuma kapanışı + 2 takvim günü sonra (Cumartesi/Pazar tarzı borsa
    # kapalı aralığı) analiz -- eşiğin (5 gün) çok altında, stale OLMAMALI.
    # Kural takvim-günü SAYISINA dayanır, gerçek haftanın günü kurala etki
    # etmez -- bu yüzden burada gerçek bir Cuma tarihi gerekmez.
    observed_at = datetime(2000, 1, 1, 21, 0, tzinfo=timezone.utc)
    now = observed_at + timedelta(days=2)
    assert _is_fresh_observation(observed_at, now) is True


def test_is_fresh_observation_three_day_monday_style_gap_not_stale():
    # Cuma kapanışı hâlâ en son bar, Pazartesi (yeni günlük bar henüz
    # oluşmadan önce) analiz -- 3 takvim günü fark, stale OLMAMALI; yeni bir
    # Pazartesi kapanışı BEKLENMEZ.
    observed_at = datetime(2000, 1, 1, 21, 0, tzinfo=timezone.utc)
    now = observed_at + timedelta(days=3)
    assert _is_fresh_observation(observed_at, now) is True


def test_is_fresh_observation_timezone_offset_equivalent_classification():
    observed_utc = _NOW - timedelta(days=2)
    observed_plus5 = observed_utc.astimezone(timezone(timedelta(hours=5)))
    observed_minus8 = observed_utc.astimezone(timezone(timedelta(hours=-8)))
    assert _is_fresh_observation(observed_utc, _NOW) is True
    assert _is_fresh_observation(observed_plus5, _NOW) is True
    assert _is_fresh_observation(observed_minus8, _NOW) is True


def test_is_fresh_observation_missing_timestamp_not_fresh():
    assert _is_fresh_observation(None, _NOW) is False


def test_is_fresh_observation_naive_datetime_not_fresh():
    naive = datetime(2026, 1, 1, 12, 0)  # tzinfo yok
    assert _is_fresh_observation(naive, _NOW) is False


def test_is_fresh_observation_wrong_type_not_fresh():
    assert _is_fresh_observation("2026-09-18", _NOW) is False


def test_is_fresh_observation_future_timestamp_not_accepted():
    observed_at = _NOW + timedelta(days=2)
    assert _is_fresh_observation(observed_at, _NOW) is False


# ---------------------------------------------------------------------------
# HATA 16C — MacroAnalysisEngine.analyze() freshness integration
# ---------------------------------------------------------------------------


def test_analyze_one_stale_indicator_excluded_and_renormalized():
    stale_at = _NOW - timedelta(days=MAX_OBSERVATION_AGE_DAYS + 5)
    changes = {k: dict(v) for k, v in _FULL_CHANGES.items()}
    changes["oil"]["observed_at"] = stale_at

    snapshot, doc_id = _engine(changes=changes).analyze()

    assert "oil" not in snapshot.components
    assert "oil" not in snapshot.indicators
    # available_weight = 1.00 - .15(oil) = 0.85
    # weighted sum without oil = -15*.20 + -20*.20 + -20*.20 + -32*.10 + -12*.15
    #                          = -3.0 -4.0 -4.0 -3.2 -1.8 = -16.0
    # macro_score = round(-16.0/0.85, 2) = -18.82
    assert snapshot.macro_score == -18.82
    assert doc_id is not None


def test_analyze_all_indicators_stale_raises_no_snapshot_persisted():
    stale_at = _NOW - timedelta(days=MAX_OBSERVATION_AGE_DAYS + 5)
    changes = {k: {**v, "observed_at": stale_at} for k, v in _FULL_CHANGES.items()}
    snapshot_repo = _FakeSnapshotRepo()
    engine = _engine(changes=changes, snapshot_repo=snapshot_repo)

    with pytest.raises(ValueError):
        engine.analyze()

    assert snapshot_repo.added == []


def test_analyze_missing_observed_at_excludes_indicator():
    changes = {k: dict(v) for k, v in _FULL_CHANGES.items()}
    del changes["gold"]["observed_at"]

    snapshot, _doc_id = _engine(changes=changes).analyze()

    assert "gold" not in snapshot.components
    assert "gold" not in snapshot.indicators


def test_analyze_future_observed_at_excludes_indicator():
    changes = {k: dict(v) for k, v in _FULL_CHANGES.items()}
    changes["usdtry"]["observed_at"] = _NOW + timedelta(days=2)

    snapshot, _doc_id = _engine(changes=changes).analyze()

    assert "usdtry" not in snapshot.components
    assert "usdtry" not in snapshot.indicators


def test_analyze_zero_weight_fresh_with_positive_weight_stale_raises_no_fake_neutral():
    # dxy ağırlığı 0 (config'te GEÇERLİ -- toplam > 0), ama bu run'da SADECE
    # dxy fresh; diğer TÜM pozitif ağırlıklı göstergeler stale. HATA 16A'nın
    # "available_weight == 0" senaryosunun (HATA 16B) HATA 16C ile birleşmiş
    # hâli: sonuç yine fake macro_score=0.0 OLMAMALI.
    weights = dict(DEFAULT_WEIGHTS)
    weights["dxy"] = 0.0
    stale_at = _NOW - timedelta(days=MAX_OBSERVATION_AGE_DAYS + 5)
    changes = {k: dict(v) for k, v in _FULL_CHANGES.items()}
    for key in changes:
        if key != "dxy":
            changes[key]["observed_at"] = stale_at
    snapshot_repo = _FakeSnapshotRepo()
    engine = _engine(weights=weights, changes=changes, snapshot_repo=snapshot_repo)

    with pytest.raises(ValueError):
        engine.analyze()

    assert snapshot_repo.added == []
