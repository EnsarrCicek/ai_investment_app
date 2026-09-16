"""HATA 12N3C2-B2-D — `app/research/technical_v1_scoring_config_values.py`
testleri. Gerçek Firestore erişimi olmadan -- sahte bir `config_repo`
(`get_raw()` sözleşmesine uyan) enjekte edilir; freeze manifest için
geçici bir fixture dosyası kullanılır."""

import json

import pytest

from app.engines.technical.scoring import compute_scoring_config_hash
from app.research.technical_v1_scoring_config_values import (
    compute_observed_scoring_config_hash,
    load_expected_scoring_config_hash,
)

_VALID_INDICATOR_WEIGHTS = {
    "trend": 1.0,
    "rsi": 1.0,
    "bollinger": 1.0,
    "ema_slope": 1.0,
    "macd": 1.0,
    "momentum": 1.0,
    "roc": 1.0,
}
_VALID_FAMILY_WEIGHTS = {"trend": 1.0, "oscillator_position": 1.0, "momentum_rate": 1.0}


class _FakeConfigRepo:
    def __init__(self, indicator_weights=None, family_weights=None):
        self._indicator_weights = indicator_weights
        self._family_weights = family_weights

    def get_raw(self, config_id: str):
        if config_id == "technical_indicator_weights":
            return self._indicator_weights
        if config_id == "technical_family_weights":
            return self._family_weights
        raise AssertionError(f"beklenmeyen config_id: {config_id}")


# ---------------------------------------------------------------------------
# load_expected_scoring_config_hash (section 7)
# ---------------------------------------------------------------------------


def test_load_expected_scoring_config_hash_from_real_freeze_manifest():
    value = load_expected_scoring_config_hash()
    assert isinstance(value, str)
    assert len(value) == 64
    assert all(c in "0123456789abcdef" for c in value)


def test_load_expected_scoring_config_hash_from_fixture_file(tmp_path):
    fixture = tmp_path / "fake_freeze_manifest.json"
    fixture.write_text(
        json.dumps({"methodology_identity": {"scoring_config_hash": "c" * 64}}),
        encoding="utf-8",
    )
    assert load_expected_scoring_config_hash(fixture) == "c" * 64


def test_load_expected_scoring_config_hash_does_not_modify_file(tmp_path):
    fixture = tmp_path / "fake_freeze_manifest.json"
    original_content = json.dumps({"methodology_identity": {"scoring_config_hash": "d" * 64}})
    fixture.write_text(original_content, encoding="utf-8")

    load_expected_scoring_config_hash(fixture)

    assert fixture.read_text(encoding="utf-8") == original_content


# ---------------------------------------------------------------------------
# compute_observed_scoring_config_hash (section 8/32)
# ---------------------------------------------------------------------------


def test_observed_hash_matches_direct_compute_scoring_config_hash_call():
    repo = _FakeConfigRepo(indicator_weights=dict(_VALID_INDICATOR_WEIGHTS), family_weights=dict(_VALID_FAMILY_WEIGHTS))
    observed = compute_observed_scoring_config_hash(repo)

    expected = compute_scoring_config_hash(_VALID_INDICATOR_WEIGHTS, _VALID_FAMILY_WEIGHTS)
    assert observed == expected


def test_observed_hash_changes_when_weights_change():
    repo_a = _FakeConfigRepo(indicator_weights=dict(_VALID_INDICATOR_WEIGHTS), family_weights=dict(_VALID_FAMILY_WEIGHTS))
    changed_weights = dict(_VALID_INDICATOR_WEIGHTS)
    changed_weights["rsi"] = 2.0
    repo_b = _FakeConfigRepo(indicator_weights=changed_weights, family_weights=dict(_VALID_FAMILY_WEIGHTS))

    assert compute_observed_scoring_config_hash(repo_a) != compute_observed_scoring_config_hash(repo_b)


def test_observed_hash_propagates_resolver_fail_fast_on_missing_config():
    """`resolve_indicator_weights(None)` -- config hiç yoksa/eksikse fail-
    fast davranışı (mevcut, ikinci kez YAZILMAYAN mantık) doğrudan
    yansıtılmalı, sessizce bir varsayılana düşülmemeli."""
    repo = _FakeConfigRepo(indicator_weights=None, family_weights=dict(_VALID_FAMILY_WEIGHTS))
    with pytest.raises(Exception):
        compute_observed_scoring_config_hash(repo)


def test_observed_hash_does_not_duplicate_hash_canonicalization():
    """Section 32: gözlemlenen adaptör `compute_scoring_config_hash()`'i
    DOĞRUDAN çağırır -- ikinci bir kanonikleştirme/hash uygulaması YOKTUR."""
    import inspect

    from app.research import technical_v1_scoring_config_values as module

    source = inspect.getsource(module)
    assert "hashlib" not in source
    assert "compute_scoring_config_hash(" in source
