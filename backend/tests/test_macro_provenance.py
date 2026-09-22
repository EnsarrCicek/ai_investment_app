"""HATA 16D — MacroSnapshot reproducibility/provenance tests.

Bu dosya, `MacroAnalysisEngine.analyze()`'in ürettiği `MacroSnapshot`'ın
yalnızca PERSISTED alanlarından (ne Yahoo'ya yeniden sorgu atmadan, ne de
GÜNCEL Firestore config'i okumadan) `macro_score`'un yeniden üretilebildiğini
kilitler -- HATA 16A bulgu #4'ü (provenance gap) kapatır.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.services.macro import yahoo_macro_provider as provider_module
from app.engines.macro.engine import (
    DEFAULT_SCALES,
    DEFAULT_WEIGHTS,
    ENGINE_VERSION,
    MAX_OBSERVATION_AGE_DAYS,
    MacroAnalysisEngine,
    _clamp,
    compute_macro_config_sha256,
    compute_macro_input_sha256,
)
from app.services.macro.yahoo_macro_provider import YahooMacroProvider
from tests.test_macro_analysis_engine import (
    _FULL_CHANGES,
    _FakeConfigRepo,
    _FakeProvider,
    _FakeSnapshotRepo,
    _engine,
)

_NOW = datetime.now(timezone.utc)


def _reproduce_score(snapshot):
    """Yalnızca persisted provenance alanlarından `macro_score`'u yeniden
    hesaplar -- provider/config repository'ye HİÇ dokunmaz."""
    components = {}
    for key, data in snapshot.indicators.items():
        components[key] = _clamp(-data["pct_change"] * snapshot.resolved_scales[key])
    available_weight = sum(snapshot.resolved_weights[k] for k in components)
    return round(sum(components[k] * snapshot.resolved_weights[k] for k in components) / available_weight, 2)


# ---------------------------------------------------------------------------
# Persisted fields exist and are self-contained
# ---------------------------------------------------------------------------


class _YahooLikeProvider(_FakeProvider):
    """`_FakeProvider` ile aynı arayüz + gerçek `YahooMacroProvider`'ınkiyle
    AYNI `PROVIDER_ID`/`WINDOW` sınıf attribute'ları -- gerçek provider'ın
    provenance'a NASIL bağlandığını, yfinance mock'lamadan doğrular."""

    PROVIDER_ID = YahooMacroProvider.PROVIDER_ID
    WINDOW = YahooMacroProvider.WINDOW


def test_analyze_persists_provider_identity_and_window():
    snapshot, _doc_id = _engine(provider=_YahooLikeProvider(_FULL_CHANGES)).analyze()
    assert snapshot.provider_id == YahooMacroProvider.PROVIDER_ID == "yahoo_macro_v1"
    assert snapshot.window == YahooMacroProvider.WINDOW == 20
    assert snapshot.max_observation_age_days == MAX_OBSERVATION_AGE_DAYS


def test_analyze_persists_full_resolved_weights_and_scales():
    snapshot, _doc_id = _engine().analyze()
    assert snapshot.resolved_weights == DEFAULT_WEIGHTS
    assert snapshot.resolved_scales == DEFAULT_SCALES


def test_analyze_persists_both_hashes_as_sha256_hex():
    snapshot, _doc_id = _engine().analyze()
    for value in (snapshot.macro_config_sha256, snapshot.macro_input_sha256):
        assert isinstance(value, str)
        assert len(value) == 64
        int(value, 16)  # geçerli hex


# ---------------------------------------------------------------------------
# Normal-case reproduction — the locked -13.75 example
# ---------------------------------------------------------------------------


def test_normal_case_score_reproducible_from_snapshot_only():
    snapshot, _doc_id = _engine().analyze()
    assert snapshot.macro_score == -13.75
    assert _reproduce_score(snapshot) == snapshot.macro_score == -13.75


# ---------------------------------------------------------------------------
# Partial-indicator reproduction — proves HATA 16C state is genuinely captured
# ---------------------------------------------------------------------------


def test_partial_indicator_score_reproducible_from_snapshot_only():
    stale_at = _NOW - timedelta(days=MAX_OBSERVATION_AGE_DAYS + 5)
    changes = {k: dict(v) for k, v in _FULL_CHANGES.items()}
    changes["oil"]["observed_at"] = stale_at

    snapshot, _doc_id = _engine(changes=changes).analyze()

    assert "oil" not in snapshot.indicators
    assert set(snapshot.indicators) == {"dxy", "us_10y_yield", "vix", "gold", "usdtry"}
    assert _reproduce_score(snapshot) == snapshot.macro_score == -18.82


# ---------------------------------------------------------------------------
# Hash sensitivity
# ---------------------------------------------------------------------------


def test_weight_change_changes_hashes_and_score():
    snapshot_a, _ = _engine().analyze()

    weights_b = dict(DEFAULT_WEIGHTS)
    weights_b["dxy"] = 0.40
    snapshot_b, _ = _engine(weights=weights_b).analyze()

    assert snapshot_a.macro_config_sha256 != snapshot_b.macro_config_sha256
    assert snapshot_a.macro_input_sha256 != snapshot_b.macro_input_sha256
    assert snapshot_a.macro_score != snapshot_b.macro_score
    assert snapshot_b.macro_score == -13.96


def test_scale_change_changes_hashes_and_component_and_score():
    snapshot_a, _ = _engine().analyze()

    scales_b = dict(DEFAULT_SCALES)
    scales_b["dxy"] = 30.0
    snapshot_b, _ = _engine(scales=scales_b).analyze()

    assert snapshot_a.macro_config_sha256 != snapshot_b.macro_config_sha256
    assert snapshot_a.macro_input_sha256 != snapshot_b.macro_input_sha256
    assert snapshot_b.components["dxy"] == -30.0
    assert snapshot_b.macro_score == -16.75
    assert _reproduce_score(snapshot_b) == snapshot_b.macro_score


# ---------------------------------------------------------------------------
# Freshness / window methodology parameters are bound into BOTH hashes
# ---------------------------------------------------------------------------


def test_freshness_threshold_change_changes_hash():
    base = compute_macro_config_sha256(DEFAULT_WEIGHTS, DEFAULT_SCALES, 20, 5)
    changed = compute_macro_config_sha256(DEFAULT_WEIGHTS, DEFAULT_SCALES, 20, 9)  # test fixture only
    assert base != changed


def test_window_change_changes_hash():
    base = compute_macro_config_sha256(DEFAULT_WEIGHTS, DEFAULT_SCALES, 20, 5)
    changed = compute_macro_config_sha256(DEFAULT_WEIGHTS, DEFAULT_SCALES, 10, 5)  # test fixture only
    assert base != changed


# ---------------------------------------------------------------------------
# Hash order/timezone stability
# ---------------------------------------------------------------------------


def test_hash_stable_across_dict_insertion_order():
    w1 = {"dxy": 0.2, "vix": 0.2, "us_10y_yield": 0.2, "oil": 0.15, "gold": 0.1, "usdtry": 0.15}
    w2 = {k: w1[k] for k in reversed(list(w1))}  # aynı içerik, TERS ekleme sırası
    s = DEFAULT_SCALES
    assert compute_macro_config_sha256(w1, s, 20, 5) == compute_macro_config_sha256(w2, s, 20, 5)

    w3 = dict(w1)
    w3["dxy"] = 0.21  # gerçekten farklı değer
    assert compute_macro_config_sha256(w1, s, 20, 5) != compute_macro_config_sha256(w3, s, 20, 5)


def test_input_hash_timezone_equivalent_instants_produce_same_hash():
    instant_utc = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    instant_plus5 = instant_utc.astimezone(timezone(timedelta(hours=5)))

    used_a = {"dxy": {"pct_change": 1.0, "observed_at": instant_utc}}
    used_b = {"dxy": {"pct_change": 1.0, "observed_at": instant_plus5}}

    hash_a = compute_macro_input_sha256(
        "yahoo_macro_v1", 20, 5, {"dxy": 0.2}, {"dxy": 15.0}, ENGINE_VERSION, used_a
    )
    hash_b = compute_macro_input_sha256(
        "yahoo_macro_v1", 20, 5, {"dxy": 0.2}, {"dxy": 15.0}, ENGINE_VERSION, used_b
    )
    assert hash_a == hash_b


# ---------------------------------------------------------------------------
# Regression: no snapshot ever exists for an invalid/unavailable run
# (HATA 16B/16C already lock this at the engine level; this just confirms
# no provenance record can accidentally be created for those paths.)
# ---------------------------------------------------------------------------


def test_no_snapshot_no_provenance_when_available_weight_zero():
    weights = dict(DEFAULT_WEIGHTS)
    weights["dxy"] = 0.0
    snapshot_repo = _FakeSnapshotRepo()
    engine = _engine(
        weights=weights,
        changes={"dxy": {"value": 100.0, "pct_change": 1.0, "observed_at": _NOW}},
        snapshot_repo=snapshot_repo,
    )
    with pytest.raises(ValueError):
        engine.analyze()
    assert snapshot_repo.added == []


# ---------------------------------------------------------------------------
# Legacy compatibility — old MacroSnapshot records lack provenance fields
# ---------------------------------------------------------------------------


def test_legacy_snapshot_without_provenance_fields_deserializes_safely():
    from app.models.macro_snapshot import MacroSnapshot

    legacy = MacroSnapshot(
        macro_score=-13.75,
        confidence=0.93,
        components={"dxy": -15.0},
        indicators={"dxy": {"value": 100.0, "pct_change": 1.0}},
        created_at=_NOW,
        engine_version="1.0.0",
    )
    assert legacy.provider_id is None
    assert legacy.window is None
    assert legacy.max_observation_age_days is None
    assert legacy.resolved_weights is None
    assert legacy.resolved_scales is None
    assert legacy.macro_config_sha256 is None
    assert legacy.macro_input_sha256 is None


# ---------------------------------------------------------------------------
# Provider fallback — a provider without PROVIDER_ID/WINDOW attributes
# (existing _FakeProvider) must not crash provenance binding.
# ---------------------------------------------------------------------------


def test_provenance_binding_falls_back_gracefully_for_provider_without_attrs():
    snapshot, _doc_id = _engine(provider=_FakeProvider(_FULL_CHANGES)).analyze()
    assert snapshot.provider_id == "_FakeProvider"
    assert snapshot.window == 20  # DEFAULT_PROVIDER_WINDOW fallback


# ---------------------------------------------------------------------------
# End-to-end with the REAL YahooMacroProvider (mocked yfinance) — proves
# production binding, not just the fake-provider shortcut above.
# ---------------------------------------------------------------------------


class _FakeTicker:
    def __init__(self, closes):
        self._closes = closes

    def history(self, period):
        end = pd.Timestamp.now(tz="UTC").normalize()
        index = pd.date_range(end=end, periods=len(self._closes), freq="D", tz="UTC")
        return pd.DataFrame({"Close": self._closes}, index=index)


def test_real_yahoo_provider_end_to_end_provenance(monkeypatch):
    closes = [100.0] * 20 + [110.0]
    monkeypatch.setattr(provider_module.yf, "Ticker", lambda _symbol: _FakeTicker(closes))

    engine = MacroAnalysisEngine(
        provider=YahooMacroProvider(),
        config_repo=_FakeConfigRepo(),
        snapshot_repo=_FakeSnapshotRepo(),
    )
    snapshot, doc_id = engine.analyze()

    assert doc_id is not None
    assert snapshot.provider_id == "yahoo_macro_v1"
    assert snapshot.window == 20
    assert snapshot.resolved_weights == DEFAULT_WEIGHTS
    assert snapshot.resolved_scales == DEFAULT_SCALES
    assert _reproduce_score(snapshot) == snapshot.macro_score
